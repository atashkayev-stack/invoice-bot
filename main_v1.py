import os, logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from telegram import Update

load_dotenv()
from src.config_v1 import CONVERSATION_TIMEOUT
from src import handlers_v1

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)


def main():
    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    # Команды
    app.add_handler(CommandHandler("start", handlers_v1.start_command))
    app.add_handler(CommandHandler("help", handlers_v1.help_command))

    # ConversationHandler ТОЛЬКО для настроек
    settings_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^⚙️ Einstellungen$"),
                           handlers_v1.settings_main)
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

    logging.info("🤖 RechnungAgent v1 gestartet!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__': main()
