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

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📝 Rechnung erstellen$"),
                           handlers_v1.create_invoice_start),
            MessageHandler(filters.Regex("^📋 Angebot erstellen$"),
                           handlers_v1.create_offer_start)
        ],
        states={
            handlers_v1.WAITING_FOR_DOCUMENT: [
                MessageHandler(filters.Regex("^👤 Kunde auswählen$"),
                               handlers_v1.select_existing_client),
                MessageHandler(filters.Regex("^📄 Dokument scannen$"),
                               handlers_v1.prompt_for_document),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE,
                               handlers_v1.handle_document_upload),
                MessageHandler(filters.Regex("^✍️ Neuer Kunde$"),
                               handlers_v1.manual_creation),
                MessageHandler(filters.Regex("^❌ Abbrechen$"),
                               handlers_v1.cancel_operation)
            ],
            handlers_v1.WAITING_FOR_CLIENT_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handlers_v1.search_client)
            ],
            handlers_v1.SELECTING_CLIENT: [
                CallbackQueryHandler(handlers_v1.client_selected,
                                     pattern="^select_client_|^cancel_client$")
            ]
        },
        fallbacks=[
            MessageHandler(filters.Regex("^🔙.*$|^❌.*$"),
                           handlers_v1.cancel_operation)
        ],
        #  conversation_timeout=CONVERSATION_TIMEOUT,
        per_message=False)

    app.add_handler(CommandHandler("start", handlers_v1.start_command))
    app.add_handler(CommandHandler("help", handlers_v1.help_command))
    app.add_handler(CommandHandler("settings", handlers_v1.settings_command))
    app.add_handler(CommandHandler("invoices",
                                   handlers_v1.my_invoices_command))
    app.add_handler(CommandHandler("clients", handlers_v1.my_clients_command))
    app.add_handler(CommandHandler("offers", handlers_v1.my_offers_command))
    app.add_handler(conv)
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
