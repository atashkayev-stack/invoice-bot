import os
import logging
import json
import base64
import io
import urllib.parse
import re
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
import anthropic

# 1. Einstellungen & Initialisierung
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

supabase: Client = create_client(os.getenv("SUPABASE_URL"),
                                 os.getenv("SUPABASE_KEY"))
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Zustände für ConversationHandler
SETTINGS_MENU, WAITING_FOR_DOC = range(2)

# --- HILFSFUNKTIONEN ---


def get_profile_url(user_id):
    """Holt Daten aus Supabase und erstellt eine URL für settings.html"""
    base_url = "https://atashkayev-stack.github.io/invoice-bot/settings.html"
    try:
        res = supabase.table("profiles").select("*").eq("id",
                                                        user_id).execute()
        if res.data:
            p = res.data[0]
            data = {
                "company_name": p.get("company_name"),
                "street": p.get("street"),
                "postal_code": p.get("zip"),
                "city": p.get("city"),
                "email": p.get("email"),
                "phone": p.get("phone"),
                "tax_id": p.get("tax_id"),
                "iban": p.get("iban")
            }
            encoded = base64.urlsafe_b64encode(
                json.dumps(data).encode()).decode().strip("=")
            return f"{base_url}?data={urllib.parse.quote(encoded)}"
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Profils: {e}")
    return base_url


def get_invoice_url(user_id):
    """Holt Profildaten und erstellt eine URL für create_invoice.html"""
    base_url = "https://atashkayev-stack.github.io/invoice-bot/create_invoice.html"
    try:
        res = supabase.table("profiles").select("*").eq("id",
                                                        user_id).execute()
        if res.data:
            p = res.data[0]
            # Данные отправителя для предзаполнения формы счета
            data = {
                "sender_name": p.get("company_name"),
                "sender_address":
                f"{p.get('street')}, {p.get('zip')} {p.get('city')}",
                "sender_email": p.get("email"),
                "sender_iban": p.get("iban"),
                "sender_tax_id": p.get("tax_id")
            }
            encoded = base64.urlsafe_b64encode(
                json.dumps(data).encode()).decode().strip("=")
            return f"{base_url}?data={urllib.parse.quote(encoded)}"
    except Exception as e:
        logger.error(f"Fehler für Invoice-URL: {e}")
    return base_url


def get_main_keyboard():
    return ReplyKeyboardMarkup([[
        KeyboardButton("📝 Rechnung erstellen"),
        KeyboardButton("⚙️ Einstellungen")
    ],
                                [
                                    KeyboardButton("📋 Meine Rechnungen"),
                                    KeyboardButton("📧 Entwickler kontaktieren")
                                ]],
                               resize_keyboard=True)


# --- HANDLER ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Willkommen im Hauptmenü:",
                                    reply_markup=get_main_keyboard())


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки создания счета"""
    user_id = update.effective_user.id
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()

    if not res.data:
        await update.message.reply_text(
            "⚠️ Bitte füllen Sie zuerst Ihr Profil in den Einstellungen aus!",
            reply_markup=get_main_keyboard())
        return

    invoice_url = get_invoice_url(user_id)
    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("📄 Rechnung ausfüllen",
                       web_app=WebAppInfo(url=invoice_url))
    ], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

    await update.message.reply_text(
        "Öffnen Sie das Formular, um die Rechnungsdetails einzugeben:",
        reply_markup=keyboard)


async def settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    web_app_url = get_profile_url(user_id)

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📄 Aus Dokument laden")],
         [
             KeyboardButton("✍️ Manuell eingeben",
                            web_app=WebAppInfo(url=web_app_url))
         ],
         [KeyboardButton("🔍 Überprüfen", web_app=WebAppInfo(url=web_app_url))],
         [KeyboardButton("🔙 Zurück")]],
        resize_keyboard=True)

    await update.message.reply_text(
        "Profileinstellungen. Bitte wählen Sie eine Option:",
        reply_markup=keyboard)
    return SETTINGS_MENU


async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Bitte senden Sie ein Foto oder ein PDF Ihrer Rechnung (Absenderdaten)."
    )
    return WAITING_FOR_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Dokument wird analysiert...")
    try:
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            out = io.BytesIO()
            await file.download_to_memory(out)
            img_b64 = base64.urlsafe_b64encode(out.getvalue()).decode('utf-8')
            content = [{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_b64
                }
            }, {
                "type":
                "text",
                "text":
                "Extract SENDER JSON: company_name, street, postal_code, city, email, phone, tax_id, iban."
            }]
        # (Остальная логика OCR как была...)
        # Для краткости пропустим внутренности OCR, они у тебя рабочие.
        pass
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await msg.edit_text("❌ Fehler bei der Analyse.")
    return SETTINGS_MENU


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    try:
        # 1. Получаем данные из Web App
        raw_data = json.loads(update.effective_message.web_app_data.data)
        data_type = raw_data.get("type")

        logger.info(f"Daten erhalten. Typ: {data_type}")

        # --- ЛОГИКА СОХРАНЕНИЯ ПРОФИЛЯ (SETTINGS) ---
        # Срабатывает, если есть тип 'profile_update' или просто прилетели поля профиля
        if data_type == "profile_update" or ("company_name" in raw_data and
                                             "invoice_data" not in raw_data):
            profile_data = {
                "id": update.effective_user.id,
                "company_name": raw_data.get("company_name"),
                "street": raw_data.get("street"),
                "city": raw_data.get("city"),
                "zip": raw_data.get("postal_code"),
                "email": raw_data.get("email"),
                "phone": raw_data.get("phone"),
                "tax_id": raw_data.get("tax_id"),
                "iban": raw_data.get("iban")
            }

            # Сохранение профиля с защитой от разрыва соединения (наша прошлая правка)
            try:
                supabase.table("profiles").upsert(profile_data).execute()
            except Exception as e:
                logger.warning(
                    f"Verbindungsproblem (10054?), versuche erneut: {e}")
                supabase.table("profiles").upsert(profile_data).execute()

            await update.message.reply_text(
                "🎉 Profil erfolgreich gespeichert!",
                reply_markup=get_main_keyboard())

        # --- ЛОГИКА СОЗДАНИЯ СЧЕТА (INVOICE) ---
        elif data_type == "create_invoice" or "invoice_data" in raw_data:
            inv = raw_data.get("invoice_data")

            # Подготовка данных для новой таблицы 'invoices'
            db_invoice_data = {
                "user_id": update.effective_user.id,
                "client_name": inv.get("client_name"),
                "client_address": inv.get("client_address"),
                "client_email": inv.get("client_email"),
                "description": inv.get("description"),
                "amount": inv.get("amount"),
                "vat_rate": inv.get("vat_rate"),
                "total": inv.get("total"),
                "invoice_date": inv.get("date"),
                "status": "created"
            }

            # Сохраняем счет в базу (тоже с защитой от разрыва)
            try:
                supabase.table("invoices").insert(db_invoice_data).execute()
            except Exception:
                logger.warning(
                    "Verbindung verloren beim Speichern der Rechnung, versuche erneut..."
                )
                supabase.table("invoices").insert(db_invoice_data).execute()

            await update.message.reply_text(
                f"✅ Rechnung für {inv.get('client_name')} über {inv.get('total')} € wurde gespeichert!\n"
                "Ich bereite die PDF-Datei vor...",
                reply_markup=get_main_keyboard())
            # Сюда позже добавим: await send_invoice_pdf(update, inv)

    except Exception as e:
        logger.error(f"Kritischer Fehler im web_app_data_handler: {e}")
        await update.message.reply_text(f"❌ Fehler: {str(e)}",
                                        reply_markup=get_main_keyboard())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Zurück zum Hauptmenü.",
                                    reply_markup=get_main_keyboard())
    return ConversationHandler.END


# --- MAIN ---


def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    settings_regex = r"Einstellungen"
    rechnung_regex = r"Rechnung erstellen"
    history_regex = r"Meine Rechnungen"
    dev_regex = r"Entwickler"

    settings_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(settings_regex), settings_main)
        ],
        states={
            SETTINGS_MENU: [
                MessageHandler(filters.Regex(r"Aus Dokument laden"),
                               ask_for_document),
                MessageHandler(filters.Regex(r"Zurück"), cancel)
            ],
            WAITING_FOR_DOC: [
                MessageHandler(filters.PHOTO | filters.Document.ALL,
                               handle_profile_document),
                MessageHandler(filters.Regex(r"Zurück"), settings_main)
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(settings_conv)
    app.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA,
                       web_app_data_handler))

    # Кнопка создания счета теперь ведет на реальную функцию
    app.add_handler(
        MessageHandler(filters.Regex(rechnung_regex),
                       rechnung_erstellen_start))

    app.add_handler(
        MessageHandler(filters.Regex(history_regex),
                       lambda u, c: u.message.reply_text("In Entwicklung...")))
    app.add_handler(
        MessageHandler(
            filters.Regex(dev_regex),
            lambda u, c: u.message.reply_text("Kontakt: @your_handle")))

    print("Bot läuft...")
    app.run_polling()


if __name__ == "__main__":
    main()
