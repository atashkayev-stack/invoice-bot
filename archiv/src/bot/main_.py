import os
import logging
import json
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация Supabase
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = f"👋 Привет, {user.first_name}!"

    try:
        response = supabase.table("profiles").select("*").eq("id", user.id).execute()
        
        if not response.data:
            supabase.table("profiles").insert({
                "id": user.id, 
                "owner_name": user.first_name
            }).execute()
            welcome_message += "\nЯ внес тебя в базу. Давай настроим профиль? /settings"
        else:
            welcome_message += "\nТвой профиль активен. Готов создать счет? /create"

    except Exception as e:
        logger.error(f"Ошибка Supabase: {e}")
        welcome_message += "\nЯ работаю, но базу данных пока не вижу."

    await update.message.reply_text(welcome_message)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Добавляем ?v=1 для сброса кэша Telegram
    web_app_url = "https://atashkayev-stack.github.io/invoice-bot/index.html?v=1" 
    
    # Кнопка для открытия формы
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("⚙️ Открыть форму настроек", web_app=WebAppInfo(url=web_app_url))]
    ], resize_keyboard=True)

    await update.message.reply_text(
        "Нажми на кнопку ниже, чтобы заполнить реквизиты профиля:",
        reply_markup=keyboard
    )

# НОВЫЙ ОБРАБОТЧИК: Получение данных из формы
async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = json.loads(update.effective_message.web_app_data.data)
    user_id = update.effective_user.id
    
    try:
        # Сохраняем данные в Supabase
        supabase.table("profiles").update({
            "company_name": data.get("company_name"),
            "iban": data.get("iban")
        }).eq("id", user_id).execute()
        
        await update.message.reply_text(
            f"✅ Данные сохранены!\nКомпании: {data.get('company_name')}\nIBAN: {data.get('iban')}"
        )
    except Exception as e:
        logger.error(f"Save error: {e}")
        await update.message.reply_text("❌ Ошибка при сохранении в базу.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = "🤖 Команды:\n/start - Старт\n/settings - Настройки\n/create - Создать счет"
    await update.message.reply_text(help_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")



async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Используем ту же страницу настроек для теста или созданную нами create_invoice.html
    web_app_url = "https://atashkayev-stack.github.io/invoice-bot/index.html?v=2" 
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📝 Заполнить данные счета", web_app=WebAppInfo(url=web_app_url))]
    ], resize_keyboard=True)

    await update.message.reply_text(
        "Нажми на кнопку ниже, чтобы создать счет:",
        reply_markup=keyboard
    )
    
def main() -> None:
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("No token found!")
    
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create", create_command)) # ИСПРАВЛЕНО
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    
    # Этот обработчик ловит данные из Web App
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    
    application.add_error_handler(error_handler)
    
    logger.info("Бот запущен и готов к работе...")
    application.run_polling()

if __name__ == '__main__':
    main()