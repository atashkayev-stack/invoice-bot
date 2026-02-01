import os
import logging
import json
import base64
import io
import urllib.parse
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
import anthropic
from fpdf import FPDF

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
    base_url = "https://atashkayev-stack.github.io/invoice-bot/settings.html"
    try:
        res = supabase.table("profiles").select("*").eq("id",
                                                        user_id).execute()
        if res.data:
            p = res.data[0]
            data = {
                "company_name": p.get("company_name") or "",
                "street": p.get("street") or "",
                "postal_code": p.get("zip") or "",
                "city": p.get("city") or "",
                "email": p.get("email") or "",
                "phone": p.get("phone") or "",
                "tax_id": p.get("tax_id") or "",
                "iban": p.get("iban") or ""
            }
            encoded = base64.urlsafe_b64encode(
                json.dumps(data).encode()).decode().strip("=")
            return f"{base_url}?data={urllib.parse.quote(encoded)}"
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Profils: {e}")
    return base_url


def get_invoice_url(user_id):
    base_url = "https://atashkayev-stack.github.io/invoice-bot/create_invoice.html"
    try:
        res = supabase.table("profiles").select("*").eq("id",
                                                        user_id).execute()
        if res.data:
            p = res.data[0]
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
    await update.message.reply_text("Profileinstellungen:",
                                    reply_markup=keyboard)
    return SETTINGS_MENU


async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Bitte senden Sie ein Foto или PDF вашего счета (данные отправителя)."
    )
    return WAITING_FOR_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Dokument wird analysiert...")
    try:

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            await msg.edit_text("❌ Bitte ein Foto senden!")
            return SETTINGS_MENU

        # ... (код получения картинки остается прежним) ...
        file = await context.bot.get_file(file_id)
        out = io.BytesIO()
        await file.download_to_memory(out)
        img_b64 = base64.b64encode(out.getvalue()).decode('utf-8')

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{
                "role":
                "user",
                "content": [{
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
                    "Extract SENDER JSON: company_name, street, postal_code, city, email, phone, tax_id, iban. Return ONLY JSON."
                }]
            }])

        json_match = re.search(r'\{.*\}', response.content[0].text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            user_id = update.effective_user.id
            profile_data = {
                "id": user_id,
                "company_name": data.get("company_name"),
                "street": data.get("street"),
                "zip": data.get("postal_code"),  # Важно: в базе 'zip'
                "city": data.get("city"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "tax_id": data.get("tax_id"),
                "iban": data.get("iban")
            }
            supabase.table("profiles").upsert(profile_data).execute()

            # --- ИСПРАВЛЕНИЕ ОШИБКИ ТУТ ---
            # 1. Генерируем НОВУЮ ссылку
            new_web_app_url = get_profile_url(user_id)

            # 2. Создаем клавиатуру
            keyboard = ReplyKeyboardMarkup([[
                KeyboardButton("🔍 Überprüfen & Speichern",
                               web_app=WebAppInfo(url=new_web_app_url))
            ], [KeyboardButton("🔙 Zurück")]],
                                           resize_keyboard=True)

            # 3. Удаляем сообщение "⏳ Dokument wird analysiert..."
            await context.bot.delete_message(chat_id=update.effective_chat.id,
                                             message_id=msg.message_id)

            # 4. Отправляем новое сообщение с кнопками
            await update.message.reply_text(
                "✅ Данные из документа получены!\nНажми кнопку ниже, чтобы проверить их в форме:",
                reply_markup=keyboard)
        else:
            # Для ошибки тоже используем удаление или просто редактируем текст без кнопок
            await msg.edit_text("❌ JSON не найден. Попробуйте другое фото.")

    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await msg.edit_text(f"❌ API Fehler: {str(e)}")
    return SETTINGS_MENU


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    try:
        raw_data = json.loads(update.effective_message.web_app_data.data)
        data_type = raw_data.get("type")

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
            supabase.table("profiles").upsert(profile_data).execute()
            await update.message.reply_text("🎉 Profil gespeichert!",
                                            reply_markup=get_main_keyboard())

        elif data_type == "create_invoice" or "invoice_data" in raw_data:
            inv = raw_data.get("invoice_data")
            gen_num = f"RE-{datetime.now().year}-{int(time.time()) % 1000000}"
            db_invoice_data = {
                "user_id": update.effective_user.id,
                "client_name": inv.get("client_name") or "Kunde",
                "client_address": inv.get("client_address") or "",
                "amount": float(inv.get("amount") or 0),
                "vat_rate": float(inv.get("vat_rate") or 0),
                "total": float(inv.get("total") or 0),
                "invoice_date": inv.get("date"),
                "description": inv.get("description"),
                "number": gen_num,
                "status": "created"
            }
            supabase.table("invoices").insert(db_invoice_data).execute()
            res = supabase.table("profiles").select("*").eq(
                "id", update.effective_user.id).single().execute()
            profile = res.data if res.data else {}
            await update.message.reply_text(
                f"✅ Rechnung {gen_num} gespeichert!")
            await generate_invoice_pdf(update, db_invoice_data, profile)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Fehler: {str(e)}")


async def generate_invoice_pdf(update: Update, inv_data: dict, profile: dict):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)

    pdf.cell(0,
             10,
             f"{profile.get('company_name') or 'Meine Firma'}",
             ln=True,
             align='R')
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, f"{profile.get('street') or ''}", ln=True, align='R')
    pdf.cell(0,
             5,
             f"{profile.get('zip') or ''} {profile.get('city') or ''}",
             ln=True,
             align='R')
    pdf.cell(0, 5, f"Email: {profile.get('email') or ''}", ln=True, align='R')
    pdf.ln(20)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Empfänger:", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, f"{inv_data.get('client_name') or 'Kunde'}", ln=True)
    pdf.multi_cell(0, 5, f"{inv_data.get('client_address') or ''}")
    pdf.ln(10)

    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"Rechnung Nr.: {inv_data.get('number')}", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, f"Datum: {inv_data.get('invoice_date') or ''}", ln=True)
    pdf.ln(10)

    pdf.set_fill_color(240, 240, 240)
    pdf.cell(120, 10, "Beschreibung", 1, 0, 'C', fill=True)
    pdf.cell(70, 10, "Betrag", 1, 1, 'C', fill=True)
    pdf.cell(120, 15, f"{inv_data.get('description') or 'Dienstleistung'}", 1)
    pdf.cell(70, 15, f"{inv_data.get('amount'):.2f} EUR", 1, 1, 'R')

    pdf.ln(5)
    pdf.cell(120, 10, "Netto:", 0, 0, 'R')
    pdf.cell(70, 10, f"{inv_data.get('amount'):.2f} EUR", 0, 1, 'R')
    vat_sum = (inv_data.get('total') or 0) - (inv_data.get('amount') or 0)
    pdf.cell(120, 10, f"MwSt ({inv_data.get('vat_rate')}%):", 0, 0, 'R')
    pdf.cell(70, 10, f"{vat_sum:.2f} EUR", 0, 1, 'R')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(120, 10, "Gesamtbetrag:", 0, 0, 'R')
    pdf.cell(70, 10, f"{inv_data.get('total'):.2f} EUR", 0, 1, 'R')

    pdf.ln(20)
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(
        0, 5,
        f"Steuernummer: {profile.get('tax_id') or ''} | IBAN: {profile.get('iban') or ''}",
        0, 1, 'C')

    file_name = f"invoice_{inv_data.get('number')}.pdf"
    pdf.output(file_name)
    with open(file_name, 'rb') as f:
        await update.message.reply_document(document=f,
                                            caption=f"📄 {file_name}")
    os.remove(file_name)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if not res.data:
        await update.message.reply_text("⚠️ Bitte сначала заполните профиль!",
                                        reply_markup=get_main_keyboard())
        return
    invoice_url = get_invoice_url(user_id)
    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("📄 Rechnung ausfüllen",
                       web_app=WebAppInfo(url=invoice_url))
    ], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)
    await update.message.reply_text("Rechnungsdetails:", reply_markup=keyboard)


# --- MAIN ---


def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    back_regex = r".*Zurück"
    settings_regex = r".*Einstellungen"
    rechnung_regex = r".*Rechnung erstellen"

    settings_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(settings_regex), settings_main)
        ],
        states={
            SETTINGS_MENU: [
                MessageHandler(filters.Regex(r"📄 Aus Dokument laden"),
                               ask_for_document),
                MessageHandler(filters.Regex(back_regex), cancel)
            ],
            WAITING_FOR_DOC: [
                MessageHandler(filters.PHOTO | filters.Document.ALL,
                               handle_profile_document),
                MessageHandler(filters.Regex(back_regex), settings_main)
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(settings_conv)
    app.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA,
                       web_app_data_handler))
    app.add_handler(
        MessageHandler(filters.Regex(rechnung_regex),
                       rechnung_erstellen_start))
    app.add_handler(MessageHandler(filters.Regex(back_regex), cancel))

    print("Bot läuft...")
    app.run_polling()


if __name__ == "__main__":
    main()
