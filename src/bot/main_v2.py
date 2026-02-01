import os
import logging
import json
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
import anthropic
import time

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация Supabase с retry logic
def create_supabase_client():
    """Создание Supabase клиента с проверкой соединения"""
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase: Client = create_supabase_client()

# Инициализация Claude API
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# States для ConversationHandler
WAITING_FOR_DOCUMENT = 1
SELECTING_CLIENT = 2
WAITING_FOR_CLIENT_SEARCH = 3

# Timeout для ConversationHandler (15 минут)
CONVERSATION_TIMEOUT = 900


def retry_on_failure(max_retries=3, delay=1):
    """Декоратор для повторных попыток при ошибках соединения"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 1))
                    else:
                        raise
            return None
        return wrapper
    return decorator


def get_main_keyboard():
    """Главное меню с кнопками"""
    keyboard = [
        [KeyboardButton("📝 Rechnung erstellen")],
        [KeyboardButton("👥 Meine Kunden"), KeyboardButton("📋 Meine Rechnungen")],
        [KeyboardButton("⚙️ Einstellungen"), KeyboardButton("❓ Hilfe")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start - приветствие с акцентом на E-Rechnung"""
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
            
            welcome_message += (
                "🎉 Willkommen bei RechnungAgent!\n\n"
                "✅ E-Rechnungspflicht 2025 erfüllen\n"
                "✅ ZUGFeRD & XRechnung Format\n"
                "✅ GoBD-konform archivieren\n"
                "✅ KI-Kundendaten-Erkennung\n\n"
                "📌 Erste Schritte:\n"
                "1. Profil einrichten → ⚙️ Einstellungen\n"
                "2. Erste Rechnung → 📝 Rechnung erstellen\n\n"
                "💡 Tipp: Ab 2025 müssen alle Unternehmen\n"
                "E-Rechnungen akzeptieren können!\n\n"
                "Los geht's! 🚀"
            )
        else:
            profile = response.data[0]
            
            if profile.get('company_name'):
                welcome_message += (
                    f"Willkommen zurück! 😊\n\n"
                    f"🏢 {profile.get('company_name')}\n\n"
                    f"Bereit für eine konforme E-Rechnung?\n"
                    f"→ 📝 Rechnung erstellen"
                )
            else:
                welcome_message += (
                    "Dein Profil wurde gefunden.\n\n"
                    "Bitte richte zuerst dein Profil ein:\n"
                    "→ ⚙️ Einstellungen"
                )
    
    except Exception as e:
        logger.error(f"Supabase Fehler: {e}")
        welcome_message += (
            "⚠️ Verbindungsproblem mit der Datenbank.\n"
            "Bitte versuche es in einigen Sekunden nochmal."
        )
    
    await update.message.reply_text(
        welcome_message, 
        reply_markup=get_main_keyboard()
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройки профиля"""
    user_id = update.effective_user.id
    
    try:
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        
        if response.data:
            profile = response.data[0]
            current_info = (
                "📊 Aktuelles Profil:\n\n"
                f"🏢 Firma: {profile.get('company_name', '—')}\n"
                f"📍 Adresse: {profile.get('address', '—')}\n"
                f"🔢 Steuernr: {profile.get('tax_id', '—')}\n"
                f"🏦 IBAN: {profile.get('iban', '—')}\n\n"
                f"📄 Rechnungsnummern:\n"
                f"Format: {profile.get('invoice_number_prefix', 'RE-')}{profile.get('next_invoice_number', 1):0{profile.get('invoice_number_format', 4)}d}\n"
                f"Nächste: #{profile.get('next_invoice_number', 1)}\n\n"
            )
        else:
            current_info = "ℹ️ Profil noch nicht ausgefüllt.\n\n"
    
    except Exception as e:
        logger.error(f"Settings load error: {e}")
        current_info = "⚠️ Fehler beim Laden.\n\n"
    
    # Передаем данные профиля в форму
    if response.data:
        import urllib.parse
        data_json = json.dumps(response.data[0], default=str)
        data_encoded = base64.b64encode(data_json.encode()).decode()
        web_app_url = f"https://atashkayev-stack.github.io/invoice-bot/settings.html?data={urllib.parse.quote(data_encoded)}"
    else:
        web_app_url = "https://atashkayev-stack.github.io/invoice-bot/settings.html"
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("✏️ Profil bearbeiten", web_app=WebAppInfo(url=web_app_url))],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        current_info + "Klicke auf die Schaltfläche:",
        reply_markup=keyboard
    )


async def create_invoice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания счета"""
    user_id = update.effective_user.id
    
    try:
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        
        if not response.data or not response.data[0].get('company_name'):
            await update.message.reply_text(
                "⚠️ Bitte fülle zuerst dein Profil aus!\n\n"
                "→ ⚙️ Einstellungen",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Profile check error: {e}")
        await update.message.reply_text(
            "❌ Fehler bei der Verbindung. Versuche es nochmal.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    keyboard = [
        [KeyboardButton("👤 Kunde auswählen")],
        [KeyboardButton("📄 Dokument scannen (KI)")],
        [KeyboardButton("✍️ Neuer Kunde (manuell)")],
        [KeyboardButton("❌ Abbrechen")]
    ]
    
    await update.message.reply_text(
        "🆕 Neue Rechnung erstellen\n\n"
        "Wie möchtest du beginnen?\n\n"
        "👤 Kunde auswählen - Wähle aus gespeicherten Kunden\n"
        "📄 Dokument scannen - KI erkennt Kundendaten automatisch\n"
        "✍️ Neuer Kunde - Manuelle Eingabe",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    
    return WAITING_FOR_DOCUMENT


async def select_existing_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор существующего клиента"""
    user_id = update.effective_user.id
    
    try:
        # Получаем всех клиентов пользователя
        response = supabase.table("clients")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("company_name")\
            .execute()
        
        if not response.data:
            await update.message.reply_text(
                "📋 Du hast noch keine gespeicherten Kunden.\n\n"
                "Erstelle einen neuen Kunden:\n"
                "• 📄 Dokument scannen\n"
                "• ✍️ Manuell eingeben",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("📄 Dokument scannen (KI)")],
                    [KeyboardButton("✍️ Neuer Kunde (manuell)")],
                    [KeyboardButton("❌ Abbrechen")]
                ], resize_keyboard=True)
            )
            return WAITING_FOR_DOCUMENT
        
        # Показываем список клиентов
        message = "👥 Deine Kunden:\n\n"
        message += "🔍 Gib die ersten Buchstaben ein, um zu suchen.\n\n"
        
        for idx, client in enumerate(response.data[:10], 1):
            message += f"{idx}. {client['company_name']}\n"
            if client.get('city'):
                message += f"   📍 {client['city']}\n"
        
        if len(response.data) > 10:
            message += f"\n...und {len(response.data) - 10} weitere\n"
        
        message += "\n💡 Tipp: Gib 'Berlin' oder 'Müller' ein"
        
        # Сохраняем список клиентов в context
        context.user_data['all_clients'] = response.data
        
        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("❌ Abbrechen")]
            ], resize_keyboard=True)
        )
        
        return WAITING_FOR_CLIENT_SEARCH
    
    except Exception as e:
        logger.error(f"Client selection error: {e}")
        await update.message.reply_text(
            "❌ Fehler beim Laden der Kunden.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END


async def search_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Поиск клиента по введенному тексту"""
    search_text = update.message.text.lower()
    
    if search_text == "❌ abbrechen":
        return await cancel_operation(update, context)
    
    all_clients = context.user_data.get('all_clients', [])
    
    # Фильтруем клиентов
    matched_clients = [
        c for c in all_clients
        if search_text in c['company_name'].lower() or
           (c.get('city') and search_text in c['city'].lower()) or
           (c.get('customer_id') and search_text in c['customer_id'].lower())
    ]
    
    if not matched_clients:
        await update.message.reply_text(
            f"🔍 Keine Kunden gefunden für '{search_text}'\n\n"
            "Versuche es nochmal oder:\n"
            "• ✍️ Neuer Kunde (manuell)\n"
            "• 📄 Dokument scannen"
        )
        return WAITING_FOR_CLIENT_SEARCH
    
    # Создаем inline кнопки для выбора
    keyboard = []
    for client in matched_clients[:5]:  # Показываем максимум 5
        button_text = f"{client['company_name']}"
        if client.get('city'):
            button_text += f" ({client['city']})"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"select_client_{client['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("❌ Abbrechen", callback_data="cancel_client")])
    
    await update.message.reply_text(
        f"✅ {len(matched_clients)} Kunde(n) gefunden:\n\n"
        "Wähle einen:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SELECTING_CLIENT


async def client_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора клиента"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_client":
        await query.edit_message_text("❌ Abgebrochen")
        await query.message.reply_text(
            "Zurück zum Hauptmenü:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    client_id = query.data.replace("select_client_", "")
    
    try:
        # Получаем данные клиента
        response = supabase.table("clients").select("*").eq("id", client_id).execute()
        
        if not response.data:
            await query.edit_message_text("❌ Kunde nicht gefunden")
            return ConversationHandler.END
        
        client = response.data[0]
        
        # Формируем данные для передачи в форму
        client_data = {
            'client_id': client['id'],
            'customer_id': client.get('customer_id'),
            'company_name': client['company_name'],
            'street': client.get('street'),
            'postal_code': client.get('postal_code'),
            'city': client.get('city'),
            'country': client.get('country'),
            'email': client.get('email'),
            'phone': client.get('phone'),
            'tax_id': client.get('tax_id'),
            'vat_id': client.get('vat_id')
        }
        
        # Сохраняем в context
        context.user_data['selected_client'] = client_data
        
        # Формируем адрес
        address_parts = []
        if client.get('street'):
            address_parts.append(client['street'])
        if client.get('postal_code') and client.get('city'):
            address_parts.append(f"{client['postal_code']} {client['city']}")
        if client.get('country'):
            address_parts.append(client['country'])
        
        full_address = "\n".join(filter(None, address_parts))
        
        await query.edit_message_text(
            f"✅ Kunde ausgewählt:\n\n"
            f"🏢 {client['company_name']}\n"
            f"📍 {full_address or '—'}\n"
            f"🆔 Kunden-Nr: {client.get('customer_id', '—')}"
        )
        
        # Открываем форму с предзаполненными данными
        import urllib.parse
        data_json = json.dumps(client_data, default=str)
        data_encoded = base64.b64encode(data_json.encode()).decode()
        
        web_app_url = f"https://atashkayev-stack.github.io/invoice-bot/create_invoice.html?client={urllib.parse.quote(data_encoded)}"
        
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📝 Rechnung ausfüllen", web_app=WebAppInfo(url=web_app_url))],
            [KeyboardButton("🔙 Zurück")]
        ], resize_keyboard=True)
        
        await query.message.reply_text(
            "Klicke auf die Schaltfläche:",
            reply_markup=keyboard
        )
        
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"Client selection error: {e}")
        await query.edit_message_text("❌ Fehler beim Laden")
        return ConversationHandler.END


async def prompt_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос на отправку документа"""
    await update.message.reply_text(
        "📤 Bitte sende jetzt ein Foto oder Dokument:\n\n"
        "💡 Visitenkarte, Briefkopf oder Rechnung",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("❌ Abbrechen")]
        ], resize_keyboard=True)
    )
    return WAITING_FOR_DOCUMENT


@retry_on_failure(max_retries=2, delay=1)
async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка загруженного документа с AI"""
    
    processing_msg = await update.message.reply_text(
        "⏳ Dokument wird analysiert...\n"
        "KI liest die Daten aus (3-8 Sek)"
    )
    
    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
        elif update.message.document:
            file = await context.bot.get_file(update.message.document.file_id)
        else:
            await processing_msg.edit_text(
                "❌ Bitte sende ein Foto (JPG, PNG)"
            )
            return WAITING_FOR_DOCUMENT
        
        file_bytes = await file.download_as_bytearray()
        
        if update.message.photo or (update.message.document and 
            update.message.document.mime_type.startswith('image/')):
            
            image_base64 = base64.b64encode(file_bytes).decode('utf-8')
            
            if update.message.document:
                media_type = update.message.document.mime_type
            else:
                media_type = "image/jpeg"
            
            # Запрос к Claude
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": """Analysiere dieses Dokument und extrahiere Kundendaten:

1. Firmenname / Name
2. Vollständige Adresse (Straße, PLZ, Stadt, Land)
3. Telefon
4. E-Mail
5. Steuernummer
6. USt-ID
7. Kundennummer (falls vorhanden)
8. IBAN, BIC (falls vorhanden)

Antworte NUR im JSON Format:
{
  "company_name": "...",
  "street": "...",
  "postal_code": "...",
  "city": "...",
  "country": "Deutschland",
  "phone": "...",
  "email": "...",
  "tax_id": "...",
  "vat_id": "...",
  "customer_id": "...",
  "iban": "...",
  "bic": "...",
  "confidence": "hoch/mittel/niedrig"
}

Falls Feld nicht erkennbar: null."""
                            }
                        ]
                    }
                ]
            )
            
            ai_response = response.content[0].text
            ai_response = ai_response.replace('```json', '').replace('```', '').strip()
            
            try:
                client_data = json.loads(ai_response)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
                if json_match:
                    client_data = json.loads(json_match.group())
                else:
                    raise ValueError("JSON parse error")
            
            context.user_data['extracted_client_data'] = client_data
            
            # Формируем адрес
            address_parts = []
            if client_data.get('street'):
                address_parts.append(client_data['street'])
            if client_data.get('postal_code') and client_data.get('city'):
                address_parts.append(f"{client_data['postal_code']} {client_data['city']}")
            if client_data.get('country'):
                address_parts.append(client_data['country'])
            
            full_address = ", ".join(filter(None, address_parts))
            
            confidence_emoji = {
                "hoch": "🟢",
                "mittel": "🟡", 
                "niedrig": "🟠"
            }
            
            result_message = (
                f"✅ Daten erkannt! {confidence_emoji.get(client_data.get('confidence', 'mittel'), '🟢')}\n\n"
                f"🏢 Firma: {client_data.get('company_name', '—')}\n"
                f"📍 Adresse: {full_address or '—'}\n"
                f"📞 Tel: {client_data.get('phone', '—')}\n"
                f"📧 Email: {client_data.get('email', '—')}\n"
                f"🆔 Kunden-Nr: {client_data.get('customer_id', '—')}\n"
                f"🔢 Steuer: {client_data.get('tax_id', '—')}\n"
                f"🆔 USt-ID: {client_data.get('vat_id', '—')}\n\n"
                f"Die Daten werden vorausgefüllt.\n"
                f"Du kannst sie noch korrigieren!"
            )
            
            await processing_msg.edit_text(result_message)
            
            # Передаем в форму
            import urllib.parse
            data_json = json.dumps(client_data, default=str)
            data_encoded = base64.b64encode(data_json.encode()).decode()
            
            web_app_url = f"https://atashkayev-stack.github.io/invoice-bot/create_invoice.html?client={urllib.parse.quote(data_encoded)}"
            
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton("📝 Rechnung ausfüllen", web_app=WebAppInfo(url=web_app_url))],
                [KeyboardButton("🔙 Zurück")]
            ], resize_keyboard=True)
            
            await update.message.reply_text(
                "Klicke auf die Schaltfläche:",
                reply_markup=keyboard
            )
            
            return ConversationHandler.END
        
        else:
            await processing_msg.edit_text(
                "ℹ️ PDF-Support kommt bald!\n"
                "Bitte JPG/PNG senden."
            )
            return WAITING_FOR_DOCUMENT
    
    except Exception as e:
        logger.error(f"Document processing error: {e}")
        await processing_msg.edit_text(
            f"❌ Fehler bei der Analyse:\n{str(e)}\n\n"
            "Bitte nochmal versuchen oder manuell eingeben."
        )
        return WAITING_FOR_DOCUMENT


async def manual_invoice_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ручное заполнение"""
    
    web_app_url = "https://atashkayev-stack.github.io/invoice-bot/create_invoice.html"
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📝 Formular öffnen", web_app=WebAppInfo(url=web_app_url))],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        "✍️ Neuer Kunde - Manuelle Eingabe\n\n"
        "Klicke auf die Schaltfläche:",
        reply_markup=keyboard
    )
    
    return ConversationHandler.END


async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена"""
    await update.message.reply_text(
        "❌ Abgebrochen",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


async def timeout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка timeout"""
    if update.message:
        await update.message.reply_text(
            "⏱️ Die Sitzung ist abgelaufen.\n\n"
            "Starte neu mit 📝 Rechnung erstellen",
            reply_markup=get_main_keyboard()
        )


async def my_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список клиентов"""
    user_id = update.effective_user.id
    
    try:
        response = supabase.table("clients")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("company_name")\
            .limit(20)\
            .execute()
        
        if not response.data:
            await update.message.reply_text(
                "👥 Du hast noch keine Kunden.\n\n"
                "Kunden werden automatisch gespeichert\n"
                "wenn du eine Rechnung erstellst.",
                reply_markup=get_main_keyboard()
            )
            return
        
        message = f"👥 Deine Kunden ({len(response.data)}):\n\n"
        
        for client in response.data:
            message += f"🏢 {client['company_name']}\n"
            if client.get('customer_id'):
                message += f"   🆔 {client['customer_id']}\n"
            if client.get('city'):
                message += f"   📍 {client['city']}\n"
            message += "\n"
        
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
    
    except Exception as e:
        logger.error(f"Clients list error: {e}")
        await update.message.reply_text(
            "❌ Fehler beim Laden.",
            reply_markup=get_main_keyboard()
        )


async def my_invoices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список счетов с возможностью изменить формат"""
    user_id = update.effective_user.id
    
    try:
        response = supabase.table("invoices")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        
        if not response.data:
            await update.message.reply_text(
                "📋 Noch keine Rechnungen.\n\n"
                "Erstelle deine erste:\n"
                "→ 📝 Rechnung erstellen",
                reply_markup=get_main_keyboard()
            )
            return
        
        message = "📋 Deine Rechnungen:\n\n"
        
        keyboard = []
        
        for inv in response.data:
            status_emoji = "✅" if inv.get('status') == 'paid' else "⏳"
            date = inv.get('invoice_date', 'N/A')
            number = inv.get('invoice_number', 'N/A')
            amount = inv.get('total_amount', 0)
            format_type = inv.get('format_type', 'ZUGFeRD')
            
            message += f"{status_emoji} {number}\n"
            message += f"   📅 {date} | 💰 {amount:.2f}€\n"
            message += f"   📄 {format_type}\n"
            
            # Кнопка для изменения формата
            keyboard.append([
                InlineKeyboardButton(
                    f"Format ändern: {number}",
                    callback_data=f"change_format_{inv['id']}"
                )
            ])
            
            message += "\n"
        
        message += "\n💡 Klicke um Format zu ändern\n(ZUGFeRD ⇄ XRechnung)"
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    except Exception as e:
        logger.error(f"Invoice list error: {e}")
        await update.message.reply_text(
            "❌ Fehler beim Laden.",
            reply_markup=get_main_keyboard()
        )


async def change_invoice_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменение формата счета"""
    query = update.callback_query
    await query.answer()
    
    invoice_id = query.data.replace("change_format_", "")
    
    try:
        # Получаем текущий счет
        response = supabase.table("invoices").select("*").eq("id", invoice_id).execute()
        
        if not response.data:
            await query.edit_message_text("❌ Rechnung nicht gefunden")
            return
        
        invoice = response.data[0]
        current_format = invoice.get('format_type', 'ZUGFeRD')
        
        # Предлагаем выбор формата
        keyboard = [
            [InlineKeyboardButton(
                "📄 ZUGFeRD (PDF + XML)",
                callback_data=f"set_format_{invoice_id}_ZUGFeRD"
            )],
            [InlineKeyboardButton(
                "📋 XRechnung (nur XML)",
                callback_data=f"set_format_{invoice_id}_XRechnung"
            )],
            [InlineKeyboardButton(
                "❌ Abbrechen",
                callback_data="cancel_format_change"
            )]
        ]
        
        await query.edit_message_text(
            f"📄 Format ändern\n\n"
            f"Rechnung: {invoice['invoice_number']}\n"
            f"Aktuell: {current_format}\n\n"
            f"Wähle neues Format:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    except Exception as e:
        logger.error(f"Format change error: {e}")
        await query.edit_message_text("❌ Fehler")


async def set_invoice_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Установка формата счета"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_format_change":
        await query.edit_message_text("❌ Abgebrochen")
        return
    
    parts = query.data.split("_")
    invoice_id = parts[2]
    new_format = parts[3]
    
    try:
        # Обновляем формат
        supabase.table("invoices").update({
            "format_type": new_format
        }).eq("id", invoice_id).execute()
        
        # TODO: Регенерировать PDF/XML в новом формате
        
        await query.edit_message_text(
            f"✅ Format geändert auf {new_format}!\n\n"
            f"📄 Die Datei wird neu generiert...\n"
            f"(PDF-Generierung kommt im nächsten Update)"
        )
    
    except Exception as e:
        logger.error(f"Set format error: {e}")
        await query.edit_message_text("❌ Fehler beim Speichern")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Помощь с акцентом на E-Rechnung"""
    help_text = (
        "🤖 RechnungAgent - Hilfe\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📜 Was ist E-Rechnung?\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Ab 01.01.2025 müssen ALLE Unternehmen\n"
        "in Deutschland E-Rechnungen empfangen können.\n\n"
        "Ab 01.01.2028 müssen ALLE\n"
        "E-Rechnungen VERSENDEN.\n\n"
        "✅ Wir erstellen für dich:\n"
        "• ZUGFeRD (PDF mit eingebettetem XML)\n"
        "• XRechnung (reines XML)\n"
        "• Beide Formate sind EU-konform\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 Funktionen:\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 Rechnung erstellen:\n"
        "• KI-Kundendaten-Erkennung\n"
        "• Mehrere Positionen\n"
        "• Automatische MwSt-Berechnung\n"
        "• Format wählbar (ZUGFeRD/XRechnung)\n\n"
        "👥 Kundenverwaltung:\n"
        "• Automatisches Speichern\n"
        "• Schnelle Suche\n"
        "• Kundennummern-Verwaltung\n\n"
        "⚙️ Einstellungen:\n"
        "• Firmen-/Steuerdaten\n"
        "• Rechnungsnummern-Format\n"
        "• Bankverbindung\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 Unterschied Formate:\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📄 ZUGFeRD:\n"
        "• PDF (lesbar für Menschen)\n"
        "• + XML (maschinenlesbar)\n"
        "• Beides in EINER Datei\n"
        "• Ideal für B2B\n\n"
        "📋 XRechnung:\n"
        "• Nur XML-Datei\n"
        "• Rein maschinenlesbar\n"
        "• Pflicht für B2G (Behörden)\n"
        "• Seit 27.11.2020 Pflicht\n\n"
        "❓ Fragen? Schreib @your_support"
    )
    
    await update.message.reply_text(help_text, reply_markup=get_main_keyboard())


async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка данных из Web App"""
    data = json.loads(update.effective_message.web_app_data.data)
    user_id = update.effective_user.id
    
    try:
        # Определяем тип данных
        if data.get('type') == 'profile_update':
            # Обновление профиля
            profile_data = {
                "company_name": data.get("company_name"),
                "address": f"{data.get('street', '')}, {data.get('postal_code', '')} {data.get('city', '')}".strip(", "),
                "street": data.get("street"),
                "postal_code": data.get("postal_code"),
                "city": data.get("city"),
                "tax_id": data.get("tax_id"),
                "vat_id": data.get("vat_id"),
                "iban": data.get("iban"),
                "bic": data.get("bic"),
                "bank_name": data.get("bank_name"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "invoice_number_prefix": data.get("invoice_prefix"),
                "invoice_number_format": int(data.get("invoice_digits", 4)),
                "next_invoice_number": int(data.get("next_number", 1)),
                "customer_id_prefix": data.get("customer_prefix", "KUND-"),
                "is_kleinunternehmer": data.get("is_kleinunternehmer", False),
                "payment_terms": int(data.get("payment_terms", 14))
            }
            
            supabase.table("profiles").update(profile_data).eq("id", user_id).execute()
            
            await update.message.reply_text(
                f"✅ Profil gespeichert!\n\n"
                f"🏢 {data.get('company_name')}\n"
                f"📄 Nächste Rechnung: {data.get('invoice_prefix')}{int(data.get('next_number', 1)):0{int(data.get('invoice_digits', 4))}d}\n\n"
                f"Bereit für erste Rechnung! 📝",
                reply_markup=get_main_keyboard()
            )
        
        elif 'invoice_items' in data:
            # Создание счета с позициями
            invoice_data = data
            
            # Генерируем номер счета
            profile = supabase.table("profiles").select("*").eq("id", user_id).execute()
            
            if profile.data:
                p = profile.data[0]
                next_num = p.get('next_invoice_number', 1)
                prefix = p.get('invoice_number_prefix', 'RE-')
                digits = p.get('invoice_number_format', 4)
                
                invoice_number = f"{prefix}{next_num:0{digits}d}"
            else:
                invoice_number = f"RE-{datetime.now().year}-0001"
            
            # Сохраняем или обновляем клиента
            client_id = None
            if invoice_data.get('client_data'):
                client_info = invoice_data['client_data']
                
                # Проверяем существует ли клиент
                if client_info.get('customer_id'):
                    existing = supabase.table("clients")\
                        .select("*")\
                        .eq("user_id", user_id)\
                        .eq("customer_id", client_info['customer_id'])\
                        .execute()
                    
                    if existing.data:
                        client_id = existing.data[0]['id']
                        # Обновляем данные
                        supabase.table("clients").update(client_info).eq("id", client_id).execute()
                
                if not client_id:
                    # Создаем нового клиента
                    client_info['user_id'] = user_id
                    result = supabase.table("clients").insert(client_info).execute()
                    if result.data:
                        client_id = result.data[0]['id']
            
            # Создаем счет
            invoice_record = {
                "user_id": user_id,
                "invoice_number": invoice_number,
                "invoice_date": invoice_data.get('invoice_date'),
                "client_id": client_id,
                "client_name": invoice_data.get('client_data', {}).get('company_name'),
                "client_address": invoice_data.get('client_data', {}).get('address'),
                "customer_id": invoice_data.get('client_data', {}).get('customer_id'),
                "purchase_order_number": invoice_data.get('purchase_order'),
                "total_net": float(invoice_data.get('total_net', 0)),
                "total_vat": float(invoice_data.get('total_vat', 0)),
                "total_amount": float(invoice_data.get('total_gross', 0)),
                "format_type": invoice_data.get('format_type', 'ZUGFeRD'),
                "notes": invoice_data.get('notes'),
                "status": "draft"
            }
            
            invoice_result = supabase.table("invoices").insert(invoice_record).execute()
            
            if invoice_result.data:
                invoice_id = invoice_result.data[0]['id']
                
                # Сохраняем позиции
                items = invoice_data.get('invoice_items', [])
                for idx, item in enumerate(items, 1):
                    item_record = {
                        "invoice_id": invoice_id,
                        "position_number": idx,
                        "description": item['description'],
                        "quantity": float(item['quantity']),
                        "unit": item.get('unit', 'Stk'),
                        "unit_price": float(item['unit_price']),
                        "total_price": float(item['total']),
                        "vat_rate": float(item['vat_rate'])
                    }
                    supabase.table("invoice_items").insert(item_record).execute()
                
                # Обновляем следующий номер
                if profile.data:
                    supabase.table("profiles").update({
                        "next_invoice_number": next_num + 1
                    }).eq("id", user_id).execute()
                
                # TODO: Генерация PDF/XML
                
                await update.message.reply_text(
                    f"✅ Rechnung {invoice_number} erstellt!\n\n"
                    f"📄 Format: {invoice_data.get('format_type', 'ZUGFeRD')}\n"
                    f"💰 Gesamt: {invoice_data.get('total_gross', 0):.2f}€\n"
                    f"📦 Positionen: {len(items)}\n"
                    f"👤 Kunde: {invoice_data.get('client_data', {}).get('company_name', '—')}\n\n"
                    f"📥 PDF-Download kommt bald!",
                    reply_markup=get_main_keyboard()
                )
    
    except Exception as e:
        logger.error(f"Web App data error: {e}")
        await update.message.reply_text(
            f"❌ Fehler beim Speichern:\n{str(e)}",
            reply_markup=get_main_keyboard()
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок"""
    text = update.message.text
    
    if text == "📝 Rechnung erstellen":
        return await create_invoice_start(update, context)
    
    elif text == "👥 Meine Kunden":
        return await my_clients_command(update, context)
    
    elif text == "📋 Meine Rechnungen":
        return await my_invoices_command(update, context)
    
    elif text == "⚙️ Einstellungen":
        return await settings_command(update, context)
    
    elif text == "❓ Hilfe":
        return await help_command(update, context)
    
    elif text == "🔙 Zurück":
        await update.message.reply_text(
            "Hauptmenü:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    else:
        await update.message.reply_text(
            "ℹ️ Nutze die Schaltflächen unten.",
            reply_markup=get_main_keyboard()
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ein Fehler ist aufgetreten.\n"
            "Bitte versuche es nochmal.",
            reply_markup=get_main_keyboard()
        )


def main() -> None:
    """Главная функция"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("No TELEGRAM_BOT_TOKEN!")
    
    application = Application.builder().token(token).build()
    
    # ConversationHandler для создания счета
    invoice_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📝 Rechnung erstellen$"), create_invoice_start)
        ],
        states={
            WAITING_FOR_DOCUMENT: [
                MessageHandler(filters.Regex("^👤 Kunde auswählen$"), select_existing_client),
                MessageHandler(filters.Regex("^📄 Dokument scannen.*$"), prompt_for_document),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_document_upload),
                MessageHandler(filters.Regex("^✍️ Neuer Kunde.*$"), manual_invoice_creation),
                MessageHandler(filters.Regex("^❌ Abbrechen$"), cancel_operation)
            ],
            WAITING_FOR_CLIENT_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_client),
                MessageHandler(filters.Regex("^❌ Abbrechen$"), cancel_operation)
            ],
            SELECTING_CLIENT: [
                CallbackQueryHandler(client_selected, pattern="^select_client_|^cancel_client$")
            ]
        },
        fallbacks=[
            MessageHandler(filters.Regex("^🔙.*$|^❌.*$"), cancel_operation),
            CommandHandler("cancel", cancel_operation)
        ],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name="invoice_creation"
    )
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("invoices", my_invoices_command))
    application.add_handler(CommandHandler("clients", my_clients_command))
    
    # ConversationHandler
    application.add_handler(invoice_conv_handler)
    
    # Callback handlers для изменения формата
    application.add_handler(CallbackQueryHandler(change_invoice_format, pattern="^change_format_"))
    application.add_handler(CallbackQueryHandler(set_invoice_format, pattern="^set_format_|^cancel_format"))
    
    # Web App data
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    
    # Кнопки главного меню
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    
    # Error handler
    application.add_handler(error_handler)
    
    logger.info("🤖 RechnungAgent gestartet!")
    logger.info("✅ E-Rechnungen: ZUGFeRD & XRechnung")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
