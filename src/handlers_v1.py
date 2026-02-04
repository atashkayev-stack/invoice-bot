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


# В начало файла handlers_v1.py, после импортов


def get_vat_info(profile, vat_rate=None):
    """Маппинг НДС для всех форматов (XML, PDF, HTML)"""
    is_kleinunternehmer = profile.get('is_kleinunternehmer', False)
    rate = vat_rate if vat_rate is not None else profile.get(
        'default_vat_rate', 19)

    if is_kleinunternehmer:
        return {
            'rate': 0.00,
            'category': 'E',
            'reason': 'Kleinunternehmer gemäß § 19 UStG'
        }
    elif rate == 0:
        return {'rate': 0.00, 'category': 'Z', 'reason': 'Steuerbefreit'}
    else:
        return {'rate': float(rate), 'category': 'S', 'reason': None}


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
            "id": user_id,

            # Базовые данные
            "company_name": data.get("company_name"),
            "street": data.get("street"),
            "postal_code": data.get("postal_code"),
            "city": data.get("city"),
            "country_code": data.get("country_code", "DE"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "fax": data.get("fax"),
            "website": data.get("website"),

            # Правовая информация
            "legal_form": data.get("legal_form"),
            "trade_register_number": data.get("trade_register_number"),
            "trade_register_court": data.get("trade_register_court"),
            "managing_director": data.get("managing_director"),
            "contact_person": data.get("contact_person"),
            "contact_department": data.get("contact_department"),

            # Налоги
            "tax_id": data.get("tax_id"),
            "vat_id": data.get("vat_id"),
            "tax_office": data.get("tax_office"),
            "is_kleinunternehmer": data.get("is_kleinunternehmer", False),
            "default_vat_rate": data.get("default_vat_rate", 19),
            "global_location_number": data.get("global_location_number"),
            "duns_number": data.get("duns_number"),

            # Банк
            "bank_name": data.get("bank_name"),
            "iban": data.get("iban"),
            "bic": data.get("bic"),
            "sepa_creditor_id": data.get("sepa_creditor_id"),
            "sepa_mandate_reference": data.get("sepa_mandate_reference"),
            "payment_terms_days": data.get("payment_terms_days", 14),

            # Нумерация счетов
            "invoice_number_prefix": data.get("invoice_number_prefix", "RE-"),
            "invoice_number_format": data.get("invoice_number_format", 4),
            "next_invoice_number": data.get("next_invoice_number", 1),

            # Нумерация офферов
            "offer_number_prefix": data.get("offer_number_prefix", "ANG-"),
            "offer_number_format": data.get("offer_number_format", 4),
            "next_offer_number": data.get("next_offer_number", 1),
            "offer_validity_days": data.get("offer_validity_days", 14),

            # Нумерация клиентов
            "customer_id_prefix": data.get("customer_id_prefix", "KUND-"),
            "next_customer_number": data.get("next_customer_number", 1),

            # Настройки документов
            "default_currency": data.get("default_currency", "EUR"),
            "default_language": data.get("default_language", "de"),
            "invoice_note_default": data.get("invoice_note_default"),

            #gdpr_consent
            "gdpr_consent": data.get("gdpr_consent", False),
            "gdpr_consent_date": data.get("gdpr_consent_date"),
        }

        if db.update_profile(user_id, profile_data):
            await update.message.reply_text("✅ Profil gespeichert!",
                                            reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("❌ Fehler beim Speichern!")

        return  # Твое оригинальное окончание — оно остается!

# ========== СОЗДАНИЕ СЧЕТА ==========
    if data.get('type') == 'invoice_creation':
        from src.xml_generator_v2 import XMLGeneratorV2, embed_xml_in_pdf
        from src.pdf_generator_v2 import PDFGeneratorV2

        user_id = update.effective_user.id
        profile = db.get_profile(user_id) or {}

        # Создаём/обновляем клиента
        client_data = {
            'company_name': data.get('client_name'),
            'street': data.get('client_street'),
            'postal_code': data.get('client_postal_code'),
            'city': data.get('client_city'),
            'country_code': data.get('client_country', 'DE'),
            'email': data.get('client_email'),
            'customer_id': data.get('customer_id'),
            'vat_id': data.get('client_vat_id'),
            'legal_form': data.get('client_legal_form'),
            'trade_register_number': data.get('client_trade_register'),
            'buyer_reference': data.get('buyer_reference')
        }
        client_id = db.create_or_update_client(user_id, client_data)

        # Создаём счет
        invoice_data = {
            'user_id':
            user_id,
            'client_id':
            client_id,
            'number':
            data.get('invoice_number'),
            'invoice_date':
            data.get('invoice_date'),
            'due_date':
            data.get('due_date'),
            'delivery_date':
            data.get('delivery_date') or data.get('invoice_date'),
            'client_name':
            data.get('client_name'),
            'client_address':
            f"{data.get('client_street', '')}, {data.get('client_postal_code', '')} {data.get('client_city', '')}"
            .strip(', '),
            'customer_id':
            data.get('customer_id'),
            'purchase_order_number':
            data.get('purchase_order'),
            'buyer_reference':
            data.get('buyer_reference'),
            'currency':
            data.get('currency', 'EUR'),
            'payment_days':
            data.get('payment_days', 14),
            'payment_means_code':
            data.get('payment_means', '58'),
            'vat_per_item':
            data.get('vat_per_item', False),
            'global_vat_rate':
            data.get('global_vat_rate'),
            'amount':
            data.get('total_net'),
            'vat_amount':
            data.get('total_vat'),
            'total':
            data.get('total_gross'),
            'format_type':
            data.get('format_type', 'ZUGFeRD'),
            'notes':
            data.get('notes'),
            'status':
            'draft'
        }

        invoice_id = db.create_invoice(invoice_data)

        if invoice_id:
            db.create_invoice_items(invoice_id, data.get('items', []))
            db.increment_invoice_number(user_id)

            # Генерируем PDF
            pdf_gen = PDFGeneratorV2()
            xml_gen = XMLGeneratorV2()

            pdf_buf = pdf_gen.generate_invoice_pdf(data,
                                                   profile,
                                                   with_xml=False)
            pdf_bytes = pdf_buf.getvalue()

            if data.get('format_type') == 'ZUGFeRD':
                xml_string = xml_gen.generate_zugferd_xml(data, profile)
                pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)
                filename = f"Rechnung_{data.get('invoice_number')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                await update.message.reply_document(
                    document=io.BytesIO(pdf_bytes),
                    filename=filename,
                    caption="✅ Rechnung (ZUGFeRD)")
            elif data.get('format_type') == 'XRechnung':
                xml_string = xml_gen.generate_zugferd_xml(data, profile)
                filename = f"Rechnung_{data.get('invoice_number')}_{datetime.now().strftime('%Y%m%d')}.xml"
                await update.message.reply_document(
                    document=io.BytesIO(xml_string.encode('utf-8')),
                    filename=filename,
                    caption="✅ XRechnung (XML)")

            await update.message.reply_text("✅ Rechnung gespeichert!",
                                            reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("❌ Fehler!",
                                            reply_markup=get_main_keyboard())

        return


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

    logger.error(f"data_json: {data_json}")

    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
    url = f"{SETTINGS_FORM_URL}&data={urllib.parse.quote(encoded)}"

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
