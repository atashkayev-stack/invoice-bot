import os
import logging
from dotenv import load_dotenv
from supabase import create_client, Client # Добавили импорт
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    # 1. Сразу создаем текст по умолчанию
    welcome_message = f"👋 Привет, {user.first_name}! Рад тебя видеть."

    try:
        # 2. Логика Supabase
        response = supabase.table("profiles").select("*").eq("id", user.id).execute()
        
        if not response.data:
            supabase.table("profiles").insert({
                "id": user.id, 
                "owner_name": user.first_name
            }).execute()
            welcome_message = f"👋 Привет, {user.first_name}! Я внес тебя в базу. Давай настроим твой профиль для счетов?"
        else:
            welcome_message = f"👋 С возвращением, {user.first_name}! Твой профиль активен. Готов создать счет? /create"

    except Exception as e:
        logger.error(f"Ошибка в блоке Supabase: {e}")
        # Если база упала, мы всё равно отвечаем пользователю, но сообщаем о проблеме
        welcome_message = f"👋 Привет, {user.first_name}! Я работаю, но базу данных пока не вижу. Попробуем позже."

    # 3. Теперь эта строка всегда сработает, так как welcome_message точно существует
    await update.message.reply_text(welcome_message)
    
    

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /help
    """
    help_text = """
🤖 Помощь по Invoice Bot

Основные команды:
/start - Начать работу с ботом
/create - Создать новый счет
/list - Посмотреть все счета
/settings - Настроить профиль

💡 Как создать счет:
1. Используй /create
2. Ответь на несколько вопросов
3. Получи готовый PDF счет
4. Отправь клиенту!

Нужна помощь? Пиши @your_support
    """
    
    await update.message.reply_text(help_text)


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /create
    TODO: Реализуем полностью позже
    """
    await update.message.reply_text(
        "🚧 Функция создания счетов в разработке!\n"
        "Скоро здесь будет полноценный процесс создания счетов."
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /list
    TODO: Реализуем полностью позже
    """
    await update.message.reply_text(
        "📋 У тебя пока нет счетов.\n"
        "Создай первый: /create"
    )



async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик ошибок
    """
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Попробуй еще раз или напиши /help"
        )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Замени URL на тот, который даст GitHub Pages (или пока используй любой для теста)
    web_app_url = "https://atashkayev-stack.github.io/invoice-bot/" 
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("⚙️ Открыть настройки", web_app=WebAppInfo(url=web_app_url))]
    ], resize_keyboard=True)

    await update.message.reply_text(
        "Нажми на кнопку ниже, чтобы заполнить реквизиты профиля:",
        reply_markup=keyboard
    )
    
    empty_fields = [k for k, v in fields.items() if not v]
    
    if empty_fields:
        text = "⚠️ **Ваш профиль не заполнен!**\n\nНе хватает: " + ", ".join(empty_fields)
        text += "\n\nСкоро я добавлю кнопку редактирования, а пока мы можем заполнить их через команду."
    else:
        text = (
            f"✅ **Ваш профиль настроен:**\n"
            f"🏢 {p['company_name']}\n"
            f"📍 {p['street']}, {p['city']}\n"
            f"🔢 Tax ID: {p['tax_id']}\n"
            f"💳 IBAN: {p['iban']}"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")

def main() -> None:
    """
    Главная функция - запуск бота
    """
    # Получаем токен из переменных окружения
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables!")
    
    # Создаем приложение
    application = Application.builder().token(token).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("create", create_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("settings", settings_command))
    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()