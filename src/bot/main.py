import os
import logging
import json
import base64
import io
import urllib.parse
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    filters,
    ConversationHandler
)
import anthropic

# 1. Настройки и Логирование
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. Инициализация клиентов
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Состояния диалога
WAITING_FOR_DOCUMENT = 1

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 Rechnung erstellen")],
        [KeyboardButton("⚙️ Einstellungen"), KeyboardButton("📋 Meine Rechnungen")],
        [KeyboardButton("❓ Hilfe")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = f"👋 Hallo, {user.first_name}!\n\n"
    
    try:
        response = supabase.table("profiles").select("*").eq("id", user.id).execute()
        if not response.data:
            supabase.table("profiles").insert({
                "id": user.id, 
                "owner_name": user.first_name,
                "username": user.username
            }).execute()
            welcome_message += "Willkommen! Bitte richte zuerst dein Profil ein → ⚙️ Einstellungen"
        else:
            profile = response.data[0]
            if profile.get('company_name'):
                welcome_message += f"Bereit für eine neue Rechnung für {profile.get('company_name')}?"
            else:
                welcome_message += "Bitte vervollständige dein Profil в ⚙️ Einstellungen."
    except Exception as e:
        logger.error(f"Supabase error: {e}")
        welcome_message += "Datenbank-Verbindungsproblem."

    await update.message.reply_text(welcome_message, reply_markup=get_main_keyboard())

async def create_invoice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [KeyboardButton("📄 Dokument hochladen (AI)")],
        [KeyboardButton("✍️ Manuell ausfüllen")],
        [KeyboardButton("❌ Abbrechen")]
    ]
    await update.message.reply_text(
        "🆕 Как вы хотите ввести данные клиента?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return WAITING_FOR_DOCUMENT

async def prompt_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вызывается при нажатии на кнопку 'Документ'"""
    await update.message.reply_text(
        "📤 Скиньте фото визитки или счета клиента (JPG/PNG):",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Abbrechen")]], resize_keyboard=True)
    )
    return WAITING_FOR_DOCUMENT

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Обработка документа...")
    processing_msg = await update.message.reply_text("⏳ Анализирую... Bitte warten.")
    
    anthropic_content = []

    try:
        # --- БЛОК ПОДГОТОВКИ КОНТЕНТА (Твой код остается таким же) ---
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            out = io.BytesIO()
            await file.download_to_memory(out)
            img_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
            anthropic_content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": "Extract client data to JSON: company_name, street, postal_code, city, tax_id, iban. Only JSON output."}
            ]
        elif update.message.document and update.message.document.mime_type == 'application/pdf':
            import pypdf
            file = await context.bot.get_file(update.message.document.file_id)
            pdf_bytes = io.BytesIO()
            await file.download_to_memory(pdf_bytes)
            reader = pypdf.PdfReader(pdf_bytes)
            pdf_text = "".join([page.extract_text() for page in reader.pages])
            if not pdf_text.strip():
                await processing_msg.edit_text("❌ В PDF нет текста. Пришлите фото.")
                return WAITING_FOR_DOCUMENT
            anthropic_content = [
                {"type": "text", "text": f"Extract client data to JSON from this German invoice text:\n\n{pdf_text}"}
            ]
        
        # --- ЗАПРОС К CLAUDE ---
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{"role": "user", "content": anthropic_content}]
        )

        ai_response = response.content[0].text
        
        # --- УЛУЧШЕННЫЙ ПАРСИНГ ---
        import re
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if match:
            client_data = json.loads(match.group(0))
            # Гибкий поиск названия
            company = client_data.get('company_name') or client_data.get('name') or client_data.get('recipient') or "Неизвестно"
        else:
            client_data = {}
            company = "Неизвестно"

        # --- ГЕНЕРАЦИЯ ССЫЛКИ ДЛЯ WEB APP ---
        # Кодируем данные в Base64 для передачи через URL
        data_json = json.dumps(client_data)
        data_encoded = base64.b64encode(data_json.encode()).decode()
        
        # Замени URL на свой актуальный адрес GitHub Pages
        base_url = "https://atashkayev-stack.github.io/invoice-bot/create_invoice.html"
        web_app_url = f"{base_url}?data={urllib.parse.quote(data_encoded)}"

        await processing_msg.delete() # Удаляем сообщение "Анализирую"
        
        await update.message.reply_text(
            f"✅ Данные извлечены для: **{company}**\n\nНажмите кнопку ниже, чтобы проверить и выставить счет.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📝 Rechnung ausfüllen", web_app=WebAppInfo(url=web_app_url))],
                [KeyboardButton("🔙 Zurück")]
            ], resize_keyboard=True)
        )
        
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")
        return WAITING_FOR_DOCUMENT

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логика сохранения счета или настроек"""
    data = json.loads(update.effective_message.web_app_data.data)
    # ... здесь твой код сохранения в Supabase из предыдущего сообщения ...
    await update.message.reply_text("✅ Данные приняты!", reply_markup=get_main_keyboard())


async def debug_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    state = user_data.get('state', 'Unknown') # Если используешь свой трекинг
    print(f"--- DEBUG ---")
    print(f"Пришло сообщение типа: {update.message.effective_attachment or 'Text'}")
    print(f"Текст: {update.message.text}")
    print(f"--- END DEBUG ---")
# --- MAIN ---

def main() -> None:
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    # Сначала — логгер ВСЕГО, что видит бот
    application.add_handler(MessageHandler(filters.ALL, debug_all_messages), group=-1)

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Rechnung erstellen$"), create_invoice_start)],
        states={
            WAITING_FOR_DOCUMENT: [
                # Важно: добавь фильтр ALL здесь для теста, чтобы понять, видит ли бот что-то в этом состоянии
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_document_upload),
                MessageHandler(filters.Regex("^📄 Dokument hochladen"), prompt_for_document),
                MessageHandler(filters.Regex("^❌ Abbrechen$"), cancel_operation)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_operation)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    
    application.run_polling()

if __name__ == '__main__':
    main()