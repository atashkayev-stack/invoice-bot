import logging, json, base64, urllib.parse, io, os, time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from fpdf import FPDF
from datetime import datetime

# Импорты твоих модулей v1
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

# Состояния для диалогов
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


# --- БАЗОВЫЕ КОМАНДЫ ---


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Willkommen! Wählen Sie eine Aktion:",
                                    reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Nutzen Sie die Tasten unten, um Dokumente zu erstellen.")


# --- ОБРАБОТКА ОШИБОК (Та самая ошибка на строке 57) ---


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ein interner Fehler ist aufgetreten.")


# --- СПИСКИ И КОНВЕРТАЦИЯ (Строка 49 в main) ---


async def my_clients_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👥 Kundenliste wird geladen...")


async def my_invoices_command(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Ihre Rechnungen:")


async def my_offers_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📄 Ihre Angebote:")


async def view_offer_details(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("🔍 Details werden geladen...")


async def convert_offer_to_invoice(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offer_id = query.data.split('_')[-1]
    # Вызов метода из твоего database_v1.py
    res = db.convert_offer_to_invoice(offer_id)
    if res:
        await query.message.reply_text(
            f"✅ Успешно конвертировано в счет №{res}")
    else:
        await query.message.reply_text("❌ Ошибка конвертации.")


# --- НАСТРОЙКИ И OCR ---


async def settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    encoded = base64.urlsafe_b64encode(json.dumps(
        profile or {}).encode()).decode().strip("=")
    url = f"{SETTINGS_FORM_URL}?data={urllib.parse.quote(encoded)}"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("✍️ Manuell bearbeiten", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("📄 Aus Dokument laden")], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)
    await update.message.reply_text("⚙️ Einstellungen:", reply_markup=keyboard)
    return SETTINGS_MENU


async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bitte senden Sie ein Foto/PDF Ihres Briefkopfs.")
    return WAITING_FOR_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Анализирую...")
    try:
        file_id = update.message.photo[
            -1].file_id if update.message.photo else update.message.document.file_id
        file = await context.bot.get_file(file_id)
        data = ai.extract_client_data(bytes(await
                                            file.download_as_bytearray()))
        if data:
            db.update_profile(update.effective_user.id, data)
            await msg.edit_text("✅ Данные распознаны и сохранены!")
        else:
            await msg.edit_text("❌ Ошибка распознавания.")
    except Exception as e:
        logger.error(f"OCR: {e}")
    return SETTINGS_MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)
    return ConversationHandler.END


# --- WEBAPP И PDF ---


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    try:
        raw_data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        # ЛОГИРОВАНИЕ: смотрим, что реально пришло
        logger.info(f"ДАННЫЕ ИЗ WEBAPP: {json.dumps(raw_data, indent=2)}")

        # 1. Проверяем, это документ (Счет/Предложение) или Настройки
        if "invoice_items" in raw_data or "offer_items" in raw_data:
            # Определяем тип документа
            is_offer = "offer_items" in raw_data
            doc_type = "ANGEBOT" if is_offer else "RECHNUNG"

            # Сохраняем в базу (в базе v1 метод create_invoice универсален или адаптируй его)
            db.create_invoice(raw_data)

            profile = db.get_profile(user_id)
            if not profile:
                await update.message.reply_text(
                    "⚠️ Сначала заполни настройки профиля!")
                return

            await update.message.reply_text(f"⏳ Генерирую {doc_type}...")
            await generate_document_pdf(update, raw_data, profile, is_offer)

        else:
            # Если это настройки (ключи из settings_v1.html)
            db.update_profile(user_id, raw_data)
            await update.message.reply_text("✅ Настройки профиля сохранены!")

    except Exception as e:
        logger.error(f"Ошибка в web_app_data_handler: {e}", exc_info=True)


async def generate_document_pdf(update: Update, data: dict, profile: dict,
                                is_offer: bool):
    try:
        pdf = FPDF()
        pdf.add_page()

        # Шрифты (используем стандартный Helvetica для надежности)
        pdf.set_font("Helvetica", 'B', 16)
        title = "ANGEBOT" if is_offer else "RECHNUNG"
        pdf.cell(0, 10, title, ln=True, align='C')
        pdf.ln(10)

        # Данные отправителя (из профиля)
        pdf.set_font("Helvetica", 'B', 10)
        pdf.cell(0,
                 5,
                 f"{profile.get('company_name', 'Meine Firma')}",
                 ln=True,
                 align='R')
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0,
                 5,
                 f"{profile.get('street', '')} {profile.get('city', '')}",
                 ln=True,
                 align='R')
        pdf.ln(10)

        # Данные клиента
        client = data.get('client_data', {})
        pdf.set_font("Helvetica", 'B', 10)
        pdf.cell(0, 10, "Empfänger:", ln=True)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(
            0,
            5,
            f"{client.get('company_name') or client.get('name', 'Kunde')}",
            ln=True)
        pdf.multi_cell(
            0, 5,
            f"{client.get('address') or (client.get('street', '') + ' ' + client.get('city', ''))}"
        )
        pdf.ln(10)

        # ТАБЛИЦА ТОВАРОВ (Главное исправление!)
        # Берем либо invoice_items, либо offer_items
        items = data.get('invoice_items') or data.get('offer_items') or []

        pdf.set_font("Helvetica", 'B', 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(100, 10, "Beschreibung", 1, 0, 'L', True)
        pdf.cell(30, 10, "Menge", 1, 0, 'C', True)
        pdf.cell(50, 10, "Gesamt (EUR)", 1, 1, 'C', True)

        pdf.set_font("Helvetica", size=10)
        for item in items:
            # Используем .get() так как в разных формах ключи могут отличаться (description/name)
            desc = item.get('description') or item.get('name') or "Position"
            qty = item.get('quantity') or item.get('qty') or 1
            total = item.get('total') or (float(item.get('price', 0)) *
                                          float(qty))

            pdf.cell(100, 10, f"{desc}", 1)
            pdf.cell(30, 10, f"{qty}", 1, 0, 'C')
            pdf.cell(50, 10, f"{total:.2f}", 1, 1, 'R')

        # ИТОГО
        pdf.ln(5)
        pdf.set_font("Helvetica", 'B', 12)
        pdf.cell(130, 10, "Gesamtbrutto:", 0, 0, 'R')
        pdf.cell(50, 10, f"{data.get('total_gross', 0):.2f} EUR", 0, 1, 'R')

        # Сохранение
        file_path = f"document_{int(time.time())}.pdf"
        pdf.output(file_path)

        with open(file_path, 'rb') as f:
            await update.message.reply_document(
                document=f, caption=f"📄 Ваш {title} готов!")

        os.remove(file_path)

    except Exception as e:
        logger.error(f"Ошибка PDF: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при генерации PDF.")


async def generate_pdf(update: Update, data: dict, profile: dict):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", 'B', 14)
        pdf.cell(0, 10, "DOKUMENT", ln=True, align='C')
        fname = f"Doc_{int(time.time())}.pdf"
        pdf.output(fname)
        with open(fname, 'rb') as f:
            await update.message.reply_document(document=f)
        os.remove(fname)
    except Exception as e:
        logger.error(f"PDF: {e}")


# --- ВЫЗОВЫ ИЗ КНОПОК МЕНЮ ---


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    encoded = base64.urlsafe_b64encode(json.dumps(
        profile or {}).encode()).decode().strip("=")
    url = f"{CREATE_INVOICE_FORM_URL}?data={urllib.parse.quote(encoded)}"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📄 Rechnung", web_app=WebAppInfo(url=url))],
         [KeyboardButton("🔙 Zurück")]],
        resize_keyboard=True)
    await update.message.reply_text("Details:", reply_markup=kb)


async def angebot_erstellen_start(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    encoded = base64.urlsafe_b64encode(json.dumps(
        profile or {}).encode()).decode().strip("=")
    url = f"{CREATE_OFFER_FORM_URL}?data={urllib.parse.quote(encoded)}"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📋 Angebot", web_app=WebAppInfo(url=url))],
         [KeyboardButton("🔙 Zurück")]],
        resize_keyboard=True)
    await update.message.reply_text("Details:", reply_markup=kb)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📝 Rechnung erstellen":
        await rechnung_erstellen_start(update, context)
    elif text == "📋 Angebot erstellen":
        await angebot_erstellen_start(update, context)
    elif text == "👥 Meine Kunden":
        await my_clients_command(update, context)
    elif text == "📊 Meine Rechnungen":
        await my_invoices_command(update, context)
    elif text == "📄 Meine Angebote":
        await my_offers_command(update, context)
    elif text == "⚙️ Einstellungen":
        await settings_main(update, context)
    elif text == "🔙 Zurück":
        await start_command(update, context)
