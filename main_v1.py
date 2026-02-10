import os, logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from telegram import Update
import sys
import traceback

load_dotenv()
from src.config_v1 import CONVERSATION_TIMEOUT
from src import handlers_v1
from src.handlers_v1 import error_handler  # <-- именно тот async error_handler


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot_errors.log", encoding="utf-8"),
        ],
    )

    # Supabase / HTTP клиент часто шумит — но при отладке Supabase полезно DEBUG
    logging.getLogger("supabase").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.INFO)


def setup_global_excepthook():

    def global_exception_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger = logging.getLogger("global")
        tb = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.error("UNCAUGHT EXCEPTION:\n%s", tb)

    sys.excepthook = global_exception_hook


def main():
    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    setup_logging()
    setup_global_excepthook()

    # Команды
    app.add_handler(CommandHandler("start", handlers_v1.start_command))
    app.add_handler(CommandHandler("help", handlers_v1.help_command))

    # ConversationHandler ТОЛЬКО для настроек
    settings_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^⚙️ Einstellungen$"),
                           handlers_v1.settings_command)
        ],
        states={
            handlers_v1.SETTINGS_MENU: [
                MessageHandler(filters.Regex(r"📄 Aus Dokument laden"),
                               handlers_v1.ask_for_document),
                MessageHandler(filters.Regex(r"🔙 Zurück"), handlers_v1.cancel)
            ],
            handlers_v1.WAITING_FOR_DOC: [
                MessageHandler(filters.PHOTO | filters.Document.ALL,
                               handlers_v1.handle_profile_document),
                MessageHandler(filters.Regex(r"🔙 Zurück"),
                               handlers_v1.settings_main)
            ]
        },
        fallbacks=[CommandHandler("start", handlers_v1.start_command)],
        allow_reentry=True)

    app.add_handler(settings_conv)
    app.add_handler(
        CallbackQueryHandler(handlers_v1.view_offer_details,
                             pattern="^view_offer_"))
    app.add_handler(
        CallbackQueryHandler(handlers_v1.convert_offer_to_invoice,
                             pattern="^convert_offer_"))
    app.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA,
                       handlers_v1.web_app_data_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND,
                       handlers_v1.button_handler))
    app.add_error_handler(handlers_v1.error_handler)

    app.add_error_handler(error_handler)

    app.add_handler(
        CallbackQueryHandler(handlers_v1.handle_goto_settings,
                             pattern="^goto_settings$"))

    logging.info("🤖 RechnungAgent v1 gestartet!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__': main()
