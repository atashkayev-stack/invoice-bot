import os
import logging
import json
import base64
import io
import urllib.parse
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

WAITING_FOR_PROFILE_DOC = 1

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Rechnung erstellen")],
        [KeyboardButton("⚙️ Profil-Setup (AI)")], # Кнопка для загрузки своего счета
        [KeyboardButton("📋 Мои счета")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Willkommen! Настройте профиль компании через AI, отправив свой счет.", reply_markup=get_main_keyboard())

async def profile_setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📤 Пришлите скан или фото ВАШЕГО счета. Я извлеку данные вашей компании (Absender).")
    return WAITING_FOR_PROFILE_DOC

async def handle_profile_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Анализирую данные вашей компании...")
    content = []

    try:
        # Обработка Фото или PDF
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            out = io.BytesIO()
            await file.download_to_memory(out)
            img_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": "Extract SENDER (Seller) data to JSON: company_name, street, postal_code, city, tax_id, iban."}
            ]
        elif update.message.document and update.message.document.mime_type == 'application/pdf':
            import pypdf
            file = await context.bot.get_file(update.message.document.file_id)
            pdf_bytes = io.BytesIO()
            await file.download_to_memory(pdf_bytes)
            reader = pypdf.PdfReader(pdf_bytes)
            text = "".join([p.extract_text() for p in reader.pages])
            content = [{"type": "text", "text": f"Extract SENDER (Seller) JSON from text:\n\n{text}"}]

        if not content:
            await msg.edit_text("❌ Файл не распознан.")
            return WAITING_FOR_PROFILE_DOC

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}]
        )

        # Парсинг и отправка в Web App
        match = re.search(r'\{.*\}', response.content[0].text, re.DOTALL)
        client_data = json.loads(match.group(0)) if match else {}
        
        # Кодируем для URL (Settings Page)
        data_encoded = base64.urlsafe_b64encode(json.dumps(client_data).encode()).decode().strip("=")
        web_app_url = f"https://atashkayev-stack.github.io/invoice-bot/settings.html?data={urllib.parse.quote(data_encoded)}"

        await msg.delete()
        await update.message.reply_text(
            f"✅ Данные компании {client_data.get('company_name', 'Неизвестно')} готовы!",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⚙️ Profil prüfen", web_app=WebAppInfo(url=web_app_url))]], resize_keyboard=True)
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(e)
        await msg.edit_text("❌ Ошибка при анализе.")
        return ConversationHandler.END

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ловим данные из Web App и сохраняем в профиль
    raw_data = json.loads(update.effective_message.web_app_data.data)
    user_id = update.effective_user.id
    
    supabase.table("profiles").upsert({
        "id": user_id,
        "company_name": raw_data.get("company_name"),
        "street": raw_data.get("street"),
        "city": raw_data.get("city"),
        "zip": raw_data.get("postal_code"),
        "iban": raw_data.get("iban")
    }).execute()
    
    await update.message.reply_text("✅ ВАШ профиль сохранен в базе данных!")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚙️ Profil-Setup"), profile_setup_start)],
        states={WAITING_FOR_PROFILE_DOC: [MessageHandler(filters.PHOTO | filters.Document.ALL, handle_profile_document)]},
        fallbacks=[]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    app.run_polling()

if __name__ == "__main__":
    import re
    main()