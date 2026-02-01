import logging, json, base64, urllib.parse, io, os, time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from fpdf import FPDF
from datetime import datetime

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


# --- ГЕНЕРАЦИЯ PDF ---


def generate_pdf(data, profile, title="RECHNUNG"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)

    # Заголовок
    pdf.cell(0, 10, f"{title}", 0, 1, 'L')
    pdf.set_font("Helvetica", '', 10)

    # Твои данные (из профиля)
    pdf.cell(0, 5, f"{profile.get('company_name', 'Meine Firma')}", 0, 1)
    pdf.cell(
        0, 5,
        f"{profile.get('street', '')}, {profile.get('postal_code', '')} {profile.get('city', '')}",
        0, 1)
    pdf.ln(10)

    # Данные клиента
    client = data.get('client_data', {})
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(0, 5, "Empfänger:", 0, 1)
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(0, 5, f"{client.get('company_name', '')}", 0, 1)
    pdf.cell(0, 5, f"{client.get('address', '')}", 0, 1)
    pdf.ln(10)

    # Таблица позиций
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(100, 8, "Beschreibung", 1)
    pdf.cell(20, 8, "Menge", 1)
    pdf.cell(30, 8, "Preis", 1)
    pdf.cell(30, 8, "Gesamt", 1, 1)

    pdf.set_font("Helvetica", '', 10)
    items = data.get('invoice_items') or data.get('offer_items') or []
    for item in items:
        pdf.cell(100, 8, str(item.get('description', '')), 1)
        pdf.cell(20, 8, str(item.get('quantity', 1)), 1)
        pdf.cell(30, 8, f"{item.get('price', 0):.2f} EUR", 1)
        pdf.cell(30, 8, f"{item.get('total', 0):.2f} EUR", 1, 1)

    # Итоги
    pdf.ln(5)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(150, 8, "Gesamt Netto:", 0, 0, 'R')
    pdf.cell(30, 8, f"{data.get('total_net', 0):.2f} EUR", 0, 1, 'R')

    # Проверка на Kleinunternehmer
    if profile.get('is_kleinunternehmer'):
        pdf.ln(5)
        pdf.set_font("Helvetica", 'I', 9)
        pdf.multi_cell(0, 5,
                       "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
    else:
        pdf.set_font("Helvetica", 'B', 10)
        pdf.cell(150, 8, f"MwSt ({data.get('vat_rate', 19)}%):", 0, 0, 'R')
        pdf.cell(30, 8, f"{data.get('total_vat', 0):.2f} EUR", 0, 1, 'R')

    pdf.cell(150, 10, "Gesamtbetrag:", 0, 0, 'R')
    pdf.cell(30, 10, f"{data.get('total_gross', 0):.2f} EUR", 0, 1, 'R')

    out = io.BytesIO()
    pdf.output(out)
    out.seek(0)
    return out


# --- ОБРАБОТКА ДАННЫХ ИЗ WEB APP ---

# ЗАМЕНИ функцию web_app_data_handler полностью (строка ~129):


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из WebApp"""
    raw_data = update.effective_message.web_app_data.data
    data = json.loads(raw_data)
    user_id = update.effective_user.id

    # ========== СОХРАНЕНИЕ ПРОФИЛЯ ==========
    if data.get('type') == 'profile_update':
        import os
        from supabase import create_client
        supabase = create_client(os.getenv("SUPABASE_URL"),
                                 os.getenv("SUPABASE_KEY"))

        profile_data = {
            "id": user_id,
            "company_name": data.get("company_name"),
            "street": data.get("street"),
            "city": data.get("city"),
            "postal_code": data.get("postal_code"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "tax_id": data.get("tax_id"),
            "iban": data.get("iban"),
            "is_kleinunternehmer": data.get("is_kleinunternehmer", False),
            "default_vat_rate": data.get("default_vat_rate", 19)
        }

        supabase.table("profiles").upsert(profile_data).execute()
        await update.message.reply_text("✅ Profil gespeichert!",
                                        reply_markup=get_main_keyboard())
        return

    # ========== СОЗДАНИЕ СЧЕТА/ОФФЕРА ==========
    profile = db.get_profile(user_id) or {}
    doc_type = "ANGEBOT" if data.get(
        'type') == "offer_creation" else "RECHNUNG"

    await update.message.reply_text(f"⌛ Generiere {doc_type}...")

    # Генерируем PDF
    pdf_file = generate_pdf(data, profile, title=doc_type)
    filename = f"{doc_type}_{datetime.now().strftime('%Y%m%d')}.pdf"

    await update.message.reply_document(
        document=pdf_file,
        filename=filename,
        caption=f"Hier ist Ihr {doc_type.lower()}.")


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
    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("📄 Aus Dokument laden"),
        KeyboardButton("ввести руками")
    ], [KeyboardButton("🔙 Zurück")]],
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
    elif t == "ввести руками" or t == "✍️ Manuell eingeben":
        # Открываем форму настроек
        user_id = update.effective_user.id
        profile = db.get_profile(user_id) or {}
        encoded = base64.urlsafe_b64encode(
            json.dumps(profile).encode()).decode().strip("=")
        url = f"{SETTINGS_FORM_URL}?data={encoded}"
        await update.message.reply_text(
            "Öffnen Sie das Formular:",
            reply_markup=ReplyKeyboardMarkup([[
                KeyboardButton("📝 Einstellungen", web_app=WebAppInfo(url=url))
            ], [KeyboardButton("🔙 Zurück")]],
                                             resize_keyboard=True))
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
