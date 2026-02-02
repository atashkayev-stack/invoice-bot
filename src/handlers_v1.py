import logging, json, base64, urllib.parse, io, os, time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from fpdf import FPDF
import io
import os
from jinja2 import Template
from datetime import datetime
from src.pdf_from_template import PDFFromTemplate

# Инициализация
pdf_gen = PDFFromTemplate(templates_dir="templates/default")

# Импорты модулей
try:
    from .database_v1 import Database
    from .ai_service_v1 import AIService
    from .config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL
except ImportError:
    from database_v1 import Database
    from ai_service_v1 import AIService
    from config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL

logger = logging.getLogger(__name__)
db, ai = Database(), AIService()

# Состояния
SETTINGS_MENU, WAITING_FOR_DOC = range(2)


def get_main_keyboard():
    return ReplyKeyboardMarkup([[
        KeyboardButton("📝 Rechnung erstellen"),
        KeyboardButton("📋 Angebot erstellen")
    ], [
        KeyboardButton("👥 Meine Kunden"),
        KeyboardButton("📊 Meine Rechnungen")
    ], [
        KeyboardButton("📄 Meine Angebote"),
        KeyboardButton("⚙️ Einstellungen")
    ], [KeyboardButton("🔙 Zurück")]],
                               resize_keyboard=True)


# --- ОБРАБОТКА ДАННЫХ ИЗ WEB APP ---


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из WebApp"""
    raw_data = update.effective_message.web_app_data.data
    data = json.loads(raw_data)
    user_id = update.effective_user.id

    # ========== СОХРАНЕНИЕ ПРОФИЛЯ ==========
    if data.get('type') == 'profile_update':
        user_id = update.effective_user.id

        # Собираем данные без старых ключей zip и address
        profile_data = {
            "company_name": data.get('company_name'),
            "street": data.get('street'),  # Новое поле из формы
            "postal_code": data.get('postal_code'),  # Новое поле из формы
            "city": data.get('city'),
            "email": data.get('email'),
            "phone": data.get('phone'),
            "tax_id": data.get('tax_id'),
            "vat_id": data.get('vat_id'),
            "bank_name": data.get('bank_name'),
            "iban": data.get('iban'),
            "bic": data.get('bic'),
            "legal_form":
            data.get('legal_form',
                     'Einzelunternehmer'),  # Поле для ZUGFeRD 2.4
            "is_kleinunternehmer": data.get('is_kleinunternehmer', False),
            "default_vat_rate": float(data.get('default_vat_rate', 19.0)),
            "payment_terms_days": int(data.get('payment_terms', 14))
        }

        if db.update_profile(user_id, profile_data):
            await update.message.reply_text("✅ Profil gespeichert!",
                                            reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("❌ Fehler beim Speichern!")

        return  # Твое оригинальное окончание — оно остается!

    # ========== СОЗДАНИЕ ДОКУМЕНТА ИЗ ШАБЛОНА ==========
    profile = db.get_profile(user_id) or {}

    is_offer = data.get('type') == "offer_creation"
    doc_type = "ANGEBOT" if is_offer else "RECHNUNG"
    format_type = data.get('format_type', 'ZUGFeRD')

    await update.message.reply_text(
        f"⌛ Generiere {doc_type} ({format_type})...")

    try:
        # 1. Генерируем PDF из шаблона
        if is_offer:
            # Оффер с XML (если выбран ZUGFeRD)
            pdf_file = pdf_gen.generate_offer_pdf(
                data, profile, with_xml=(format_type == 'ZUGFeRD'))
        else:
            # Счет с XML (если выбран ZUGFeRD)
            pdf_file = pdf_gen.generate_invoice_pdf(
                data, profile, with_xml=(format_type == 'ZUGFeRD'))

        pdf_bytes = pdf_file.getvalue()

        # 2. Отправка в зависимости от формата
        if format_type == 'ZUGFeRD':
            # PDF + встроенный XML
            filename = f"{doc_type}_{datetime.now().strftime('%Y%m%d')}.pdf"

            await update.message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename=filename,
                caption=f"📄 {doc_type} (ZUGFeRD: PDF + XML)")

        elif format_type == 'XRechnung':
            # Только XML файл
            xml_string = pdf_gen.generate_xml_only(data, profile)
            filename = f"{doc_type}_{datetime.now().strftime('%Y%m%d')}.xml"

            await update.message.reply_document(
                document=io.BytesIO(xml_string.encode('utf-8')),
                filename=filename,
                caption=f"📋 {doc_type} (XRechnung: nur XML)")

        await update.message.reply_text("✅ Erfolgreich erstellt!",
                                        reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}",
                                        reply_markup=get_main_keyboard())


# --- ОСТАЛЬНЫЕ ФУНКЦИИ (Обязательные для main_v1.py) ---


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not db.get_profile(user.id):
        db.create_profile(user.id, user.first_name, user.username)
    await update.message.reply_text(f"Hallo!",
                                    reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nutzen Sie die Buttons.")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает форму настроек сразу"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    # Формируем URL с данными профиля
    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
    url = f"{SETTINGS_FORM_URL}?data={urllib.parse.quote(encoded)}"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("📝 Ihre Kontaktdaten eingeben / prüfen",
                       web_app=WebAppInfo(url=url))
    ], [KeyboardButton("📄 Aus Dokument laden")], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

    await update.message.reply_text("⚙️ Einstellungen:", reply_markup=keyboard)
    return SETTINGS_MENU


async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bitte Foto senden.")
    return WAITING_FOR_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Dokument erhalten (Dummy)")
    return SETTINGS_MENU


async def settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await settings_command(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Abgebrochen.",
                                    reply_markup=get_main_keyboard())
    return ConversationHandler.END


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_INVOICE_FORM_URL}?data={encoded}"
    await update.message.reply_text(
        "Öffnen Sie das Formular:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📝 Rechnung", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True))


async def angebot_erstellen_start(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_OFFER_FORM_URL}?data={encoded}"
    await update.message.reply_text(
        "Öffnen Sie das Formular:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📋 Angebot", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "📝 Rechnung erstellen":
        await rechnung_erstellen_start(update, context)
    elif t == "📋 Angebot erstellen":
        await angebot_erstellen_start(update, context)
    elif t == "⚙️ Einstellungen":
        await settings_command(update, context)
    elif t == "🔙 Zurück":
        await update.message.reply_text("Hauptmenü",
                                        reply_markup=get_main_keyboard())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


# Заглушки для Callback-ов (если они есть в main_v1.py)
async def view_offer_details(update, context):
    pass


async def convert_offer_to_invoice(update, context):
    pass
