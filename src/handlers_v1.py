import logging, json, base64, urllib.parse, io, os, time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from fpdf import FPDF
from datetime import datetime

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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на команду /start"""
    user = update.effective_user
    # Проверяем наличие профиля в Supabase
    profile = db.get_profile(user.id)
    if not profile:
        db.create_profile(user.id, user.first_name, user.username)

    await update.message.reply_text(
        f"Hallo {user.first_name}! Willkommen beim InvoiceBot.\n"
        "Nutzen Sie die Menютasten unten, um Dokumente zu erstellen.",
        reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на команду /help - ТА САМАЯ ФУНКЦИЯ"""
    help_text = (
        "📖 **Hilfe & Dokumentation**\n\n"
        "**Befehle:**\n"
        "/start - Hauptmenü öffnen\n"
        "/help - Diese Hilfe anzeigen\n\n"
        "**Dokumente:**\n"
        "1. Klicken Sie auf 'Rechnung' oder 'Angebot'.\n"
        "2. Füllen Sie die Tabs (Kunde, Positionen, Extra) aus.\n"
        "3. Senden Sie das Dokument ab.\n\n"
        "**Einstellungen:**\n"
        "Unter 'Einstellungen' können Sie Ihre Firmendaten und den Kleinunternehmer-Status (0% MwSt) verwalten."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{SETTINGS_FORM_URL}?data={encoded}"

    kb = ReplyKeyboardMarkup([[
        KeyboardButton("⚙️ Einstellungen öffnen", web_app=WebAppInfo(url=url))
    ]],
                             resize_keyboard=True)
    await update.message.reply_text("Hier können Sie Ihr Profil bearbeiten:",
                                    reply_markup=kb)


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    raw_data = json.loads(update.effective_message.web_app_data.data)
    user_id = update.effective_user.id
    logger.info(f"ДАННЫЕ ИЗ WEBAPP: {raw_data}")

    # ЛОГИКА СОХРАНЕНИЯ ПРОФИЛЯ
    if raw_data.get("type") == "profile_update":
        clean_data = raw_data.copy()
        clean_data.pop("type", None)
        if db.update_profile(user_id, clean_data):
            await update.message.reply_text(
                "✅ Einstellungen erfolgreich gespeichert!")
        else:
            await update.message.reply_text(
                "❌ Fehler beim Speichern in der Datenbank.")
        return

    # ЛОГИКА ГЕНЕРАЦИИ PDF (Счет или Оффер)
    is_invoice = "invoice_items" in raw_data
    items_key = "invoice_items" if is_invoice else "offer_items"
    items = raw_data.get(items_key, [])

    profile = db.get_profile(user_id) or {}
    pdf_buffer = generate_document_pdf(raw_data, profile,
                                       "Rechnung" if is_invoice else "Angebot")

    doc_name = f"{'Rechnung' if is_invoice else 'Angebot'}_{datetime.now().strftime('%Y%m%d')}.pdf"
    await update.message.reply_document(document=pdf_buffer,
                                        filename=doc_name,
                                        caption="Hier ist Ihr Dokument.")


def generate_document_pdf(data, profile, title):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)

    # Header
    pdf.cell(0, 10, title, 0, 1, 'R')
    pdf.set_font("Helvetica", '', 10)

    # Absender (Вы)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(0, 5, profile.get('company_name', 'Mein Unternehmen'), 0, 1)
    pdf.set_font("Helvetica", '', 9)
    pdf.cell(
        0, 5,
        f"{profile.get('street', '')}, {profile.get('postal_code', '')} {profile.get('city', '')}",
        0, 1)
    pdf.ln(10)

    # Empfänger (Клиент)
    pdf.set_font("Helvetica", 'B', 10)
    client = data.get('client_data', {})
    pdf.cell(0, 5, client.get('company_name', 'Kunde'), 0, 1)
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(0, 5, f"{client.get('street', client.get('address', ''))}", 0, 1)
    pdf.cell(0, 5, f"{client.get('postal_code', '')} {client.get('city', '')}",
             0, 1)
    pdf.ln(10)

    # Таблица товаров
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 8, "Beschreibung", 1, 0, 'L', True)
    pdf.cell(20, 8, "Menge", 1, 0, 'C', True)
    pdf.cell(30, 8, "Einzelpreis", 1, 0, 'C', True)
    pdf.cell(40, 8, "Gesamt", 1, 1, 'C', True)

    items = data.get('invoice_items') or data.get('offer_items') or []
    for item in items:
        pdf.cell(90, 8, str(item.get('description', '')), 1)
        pdf.cell(20, 8, f"{item.get('quantity', 1)} {item.get('unit', 'Stk')}",
                 1, 0, 'C')
        pdf.cell(30, 8, f"{item.get('price', 0):.2f} EUR", 1, 0, 'R')
        pdf.cell(40, 8, f"{item.get('total', 0):.2f} EUR", 1, 1, 'R')

    pdf.ln(5)

    # ИТОГИ И НАЛОГИ
    is_klein = profile.get('is_kleinunternehmer',
                           False) or data.get('vat_rate') == 0

    pdf.cell(140, 8, "Netto Gesamt:", 0, 0, 'R')
    pdf.cell(40, 8, f"{data.get('total_net', 0):.2f} EUR", 0, 1, 'R')

    if is_klein:
        pdf.set_font("Helvetica", 'I', 10)
        pdf.multi_cell(0, 10,
                       "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
    else:
        vat_val = data.get('total_vat', 0)
        pdf.cell(140, 8, f"MwSt ({data.get('vat_rate', 19)}%):", 0, 0, 'R')
        pdf.cell(40, 8, f"{vat_val:.2f} EUR", 0, 1, 'R')

    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(140, 10, "Gesamtbetrag:", 0, 0, 'R')
    pdf.cell(40, 10, f"{data.get('total_gross', 0):.2f} EUR", 0, 1, 'R')

    buffer = io.BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    if profile.get('is_kleinunternehmer'): profile['vat_rate'] = 0

    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_INVOICE_FORM_URL}?data={encoded}"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📝 Rechnung", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True)
    await update.message.reply_text("Details:", reply_markup=kb)


async def angebot_erstellen_start(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    if profile.get('is_kleinunternehmer'): profile['vat_rate'] = 0

    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_OFFER_FORM_URL}?data={encoded}"
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📋 Angebot", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True)
    await update.message.reply_text("Details:", reply_markup=kb)
