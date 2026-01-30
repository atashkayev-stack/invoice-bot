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

# 1. Настройки и инициализация
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключение к Supabase
supabase: Client = create_client(os.getenv("SUPABASE_URL"),
                                 os.getenv("SUPABASE_KEY"))

# Подключение к Claude AI
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

WAITING_FOR_PROFILE_DOC = 1


def get_main_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("📝 Rechnung erstellen")],
                                [KeyboardButton("⚙️ Profil-Setup (AI)")],
                                [KeyboardButton("📋 Мои счета")]],
                               resize_keyboard=True)


# --- ОБРАБОТЧИКИ ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Willkommen! Я помогу настроить ваш профиль.\n"
        "Просто пришлите свой счет (как продавца), и я извлеку данные автоматически.",
        reply_markup=get_main_keyboard())


async def profile_setup_start(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Пришлите скан или фото ВАШЕГО счета.\n"
        "Я найду данные вашей компании (Absender) и заполню настройки.")
    return WAITING_FOR_PROFILE_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "⏳ Анализирую документ... Пожалуйста, подождите.")
    content = []

    try:
        # Обработка Фото
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            out = io.BytesIO()
            await file.download_to_memory(out)
            img_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
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
                "Extract SENDER (Seller/Absender) data to JSON: company_name, street, postal_code, city, email, phone, tax_id, iban. Use null if not found."
            }]
        # Обработка PDF
        elif update.message.document and update.message.document.mime_type == 'application/pdf':
            import pypdf
            file = await context.bot.get_file(update.message.document.file_id)
            pdf_bytes = io.BytesIO()
            await file.download_to_memory(pdf_bytes)
            reader = pypdf.PdfReader(pdf_bytes)
            text = "".join([p.extract_text() for p in reader.pages])
            content = [{
                "type":
                "text",
                "text":
                f"Extract SENDER (Seller/Absender) JSON: company_name, street, postal_code, city, email, phone, tax_id, iban from text:\n\n{text}"
            }]

        if not content:
            await msg.edit_text("❌ Файл не распознан. Пришлите фото или PDF.")
            return WAITING_FOR_PROFILE_DOC

        # Запрос к Claude AI
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": content
            }])

        ai_response = response.content[0].text
        print(
            f"\n--- [RAW AI RESPONSE] ---\n{ai_response}\n--------------------------\n"
        )

        # Парсинг JSON
        match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if match:
            raw_json = json.loads(match.group(0))

            # Умный маппинг (сопоставление полей)
            processed_data = {
                "company_name":
                raw_json.get("company_name") or raw_json.get("sender_name")
                or raw_json.get("company"),
                "street":
                raw_json.get("street") or raw_json.get("address"),
                "postal_code":
                raw_json.get("postal_code") or raw_json.get("zip")
                or raw_json.get("plz"),
                "city":
                raw_json.get("city"),
                "email":
                raw_json.get("email") or raw_json.get("e-mail"),
                "phone":
                raw_json.get("phone") or raw_json.get("tel")
                or raw_json.get("telefon"),
                "tax_id":
                raw_json.get("tax_id") or raw_json.get("ust_id")
                or raw_json.get("steuernummer"),
                "iban":
                raw_json.get("iban")
            }

            # Кодируем данные для Web App
            data_encoded = base64.urlsafe_b64encode(
                json.dumps(processed_data).encode()).decode().strip("=")
            web_app_url = f"https://atashkayev-stack.github.io/invoice-bot/settings.html?data={urllib.parse.quote(data_encoded)}"

            await msg.delete()
            await update.message.reply_text(
                f"✅ Данные извлечены для: {processed_data.get('company_name', 'Неизвестно')}",
                reply_markup=ReplyKeyboardMarkup([[
                    KeyboardButton("⚙️ Profil prüfen",
                                   web_app=WebAppInfo(url=web_app_url))
                ], [KeyboardButton("🔙 Abbrechen")]],
                                                 resize_keyboard=True))
            return ConversationHandler.END
        else:
            await msg.edit_text("❌ Не удалось распознать структуру данных.")
            return WAITING_FOR_PROFILE_DOC

    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await msg.edit_text(f"❌ Ошибка анализа: {type(e).__name__}")
        return ConversationHandler.END


async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """ Сохранение данных из Web App в Supabase """
    try:
        raw_data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        # СООТВЕТСТВИЕ КОЛОНКАМ ТВОЕЙ БД:
        profile_data = {
            "id": user_id,
            "company_name": raw_data.get("company_name"),
            "street": raw_data.get("street"),
            "city": raw_data.get("city"),
            "zip": raw_data.get("postal_code"),  # Маппинг postal_code -> zip
            "tax_id": raw_data.get("tax_id"),
            "iban": raw_data.get("iban"),
            "phone": raw_data.get("phone"),
            "email": raw_data.get("email"),
            "owner_name": update.effective_user.first_name
        }

        # Выполняем UPSERT
        supabase.table("profiles").upsert(profile_data).execute()

        await update.message.reply_text(
            "🎉 Профиль успешно сохранен в базе данных!",
            reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Save error: {e}")
        # Защита: бот не замолчит, а вернет меню
        await update.message.reply_text(f"⚠️ Ошибка при сохранении: {str(e)}",
                                        reply_markup=get_main_keyboard())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.",
                                    reply_markup=get_main_keyboard())
    return ConversationHandler.END


# --- ЗАПУСК ---


def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^⚙️ Profil-Setup"),
                           profile_setup_start)
        ],
        states={
            WAITING_FOR_PROFILE_DOC: [
                MessageHandler(filters.PHOTO | filters.Document.ALL,
                               handle_profile_document),
                MessageHandler(filters.Regex("^🔙 Abbrechen"), cancel)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA,
                       web_app_data_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
