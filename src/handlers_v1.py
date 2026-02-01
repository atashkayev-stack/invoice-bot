"""
handlers_v1.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
Логика как в рабочем main.py + добавлены Angebote
"""
import logging, json, base64, urllib.parse, io
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
import time
from .database_v1 import Database
from .ai_service_v1 import AIService
from .config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL

logger = logging.getLogger(__name__)
db, ai = Database(), AIService()

# States для настроек (сканирование документа ЮЗЕРА)
SETTINGS_MENU, WAITING_FOR_DOC = range(2)

def get_main_keyboard():
    """Главное меню"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Rechnung erstellen"), KeyboardButton("📋 Angebot erstellen")],
        [KeyboardButton("👥 Meine Kunden"), KeyboardButton("📊 Meine Rechnungen")],
        [KeyboardButton("📄 Meine Angebote"), KeyboardButton("⚙️ Einstellungen")]
    ], resize_keyboard=True)

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text("Willkommen im Hauptmenü:", reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    await update.message.reply_text(
        "🤖 RechnungAgent\n\n"
        "📝 Rechnung/Angebot erstellen\n"
        "👥 Kunden verwalten\n"
        "⚙️ Einstellungen\n\n"
        "E-Rechnung ab 2025 Pflicht!",
        reply_markup=get_main_keyboard()
    )

# ==================== НАСТРОЙКИ (сканирование данных ЮЗЕРА) ====================

async def settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки профиля ЮЗЕРА"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    
    if profile:
        data_json = json.dumps({
            "company_name": profile.get("company_name", ""),
            "street": profile.get("street", ""),
            "postal_code": profile.get("postal_code", ""),
            "city": profile.get("city", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
            "tax_id": profile.get("tax_id", ""),
            "iban": profile.get("iban", "")
        })
        encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
        web_app_url = f"{SETTINGS_FORM_URL}?data={urllib.parse.quote(encoded)}"
    else:
        web_app_url = SETTINGS_FORM_URL
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📄 Aus Dokument laden")],
        [KeyboardButton("✍️ Manuell eingeben", web_app=WebAppInfo(url=web_app_url))],
        [KeyboardButton("🔍 Überprüfen", web_app=WebAppInfo(url=web_app_url))],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)
    
    await update.message.reply_text("Profileinstellungen:", reply_markup=keyboard)
    return SETTINGS_MENU

async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос документа ЮЗЕРА"""
    await update.message.reply_text(
        "📤 Bitte senden Sie ein Foto вашего счета (данные отправителя)."
    )
    return WAITING_FOR_DOC

async def handle_profile_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документа ЮЗЕРА с AI"""
    msg = await update.message.reply_text("⏳ Dokument wird analysiert...")
    
    try:
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        else:
            await msg.edit_text("❌ Bitte ein Foto senden!")
            return SETTINGS_MENU
        
        file = await context.bot.get_file(file_id)
        out = io.BytesIO()
        await file.download_to_memory(out)
        img_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
        
        # AI распознавание
        import anthropic
        anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
                }, {
                    "type": "text",
                    "text": "Extract SENDER JSON: company_name, street, postal_code, city, email, phone, tax_id, iban. Return ONLY JSON."
                }]
            }])
        
        import re
        json_match = re.search(r'\{.*\}', response.content[0].text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            user_id = update.effective_user.id
            
            profile_data = {
                "id": user_id,
                "company_name": data.get("company_name"),
                "street": data.get("street"),
                "postal_code": data.get("postal_code"),
                "city": data.get("city"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "tax_id": data.get("tax_id"),
                "iban": data.get("iban")
            }
            
            # Используем БД v1
            import os
            from supabase import create_client
            supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
            supabase.table("profiles").upsert(profile_data).execute()
            
            # Генерируем новую ссылку
            new_data = json.dumps(profile_data)
            new_encoded = base64.urlsafe_b64encode(new_data.encode()).decode().strip("=")
            new_web_app_url = f"{SETTINGS_FORM_URL}?data={urllib.parse.quote(new_encoded)}"
            
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton("🔍 Überprüfen & Speichern", web_app=WebAppInfo(url=new_web_app_url))],
                [KeyboardButton("🔙 Zurück")]
            ], resize_keyboard=True)
            
            # Удаляем старое сообщение
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
            
            # Отправляем новое
            await update.message.reply_text(
                "✅ Данные из документа получены!\nНажми кнопку ниже, чтобы проверить их в форме:",
                reply_markup=keyboard
            )
        else:
            await msg.edit_text("❌ JSON не найден. Попробуйте другое фото.")
    
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await msg.edit_text(f"❌ API Fehler: {str(e)}")
    
    return SETTINGS_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    await start_command(update, context)
    return ConversationHandler.END

# ==================== СОЗДАНИЕ СЧЕТА (СРАЗУ ФОРМА) ====================

async def rechnung_erstellen_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание счета - СРАЗУ открывает форму"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    
    if not profile:
        await update.message.reply_text(
            "⚠️ Bitte сначала заполните профиль!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Формируем URL с данными ЮЗЕРА
    import os
    from supabase import create_client
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if res.data:
        p = res.data[0]
        data = {
            "sender_name": p.get("company_name"),
            "sender_address": f"{p.get('street')}, {p.get('postal_code')} {p.get('city')}",
            "sender_email": p.get("email"),
            "sender_iban": p.get("iban"),
            "sender_tax_id": p.get("tax_id")
        }
        encoded = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().strip("=")
        invoice_url = f"{CREATE_INVOICE_FORM_URL}?data={urllib.parse.quote(encoded)}"
    else:
        invoice_url = CREATE_INVOICE_FORM_URL
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📄 Rechnung ausfüllen", web_app=WebAppInfo(url=invoice_url))],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)
    
    await update.message.reply_text("Rechnungsdetails:", reply_markup=keyboard)

# ==================== СОЗДАНИЕ ANGEBOT (СРАЗУ ФОРМА) ====================

async def angebot_erstellen_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание оффера - СРАЗУ открывает форму"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    
    if not profile:
        await update.message.reply_text(
            "⚠️ Bitte сначала заполните профиль!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Формируем URL с данными ЮЗЕРА
    import os
    from supabase import create_client
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if res.data:
        p = res.data[0]
        data = {
            "sender_name": p.get("company_name"),
            "sender_address": f"{p.get('street')}, {p.get('postal_code')} {p.get('city')}",
            "sender_email": p.get("email"),
            "sender_iban": p.get("iban"),
            "sender_tax_id": p.get("tax_id")
        }
        encoded = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().strip("=")
        offer_url = f"{CREATE_OFFER_FORM_URL}?data={urllib.parse.quote(encoded)}"
    else:
        offer_url = CREATE_OFFER_FORM_URL
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📄 Angebot ausfüllen", web_app=WebAppInfo(url=offer_url))],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)
    
    await update.message.reply_text("Angebotsdetails:", reply_markup=keyboard)

# ==================== СПИСКИ ====================

async def my_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список клиентов"""
    clients = db.get_all_clients(update.effective_user.id)
    if not clients:
        await update.message.reply_text("👥 Keine Kunden", reply_markup=get_main_keyboard())
        return
    msg = f"👥 {len(clients)} Kunden:\n\n" + "\n".join([f"🏢 {c['company_name']}" for c in clients[:20]])
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def my_invoices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список счетов"""
    invoices = db.get_invoices(update.effective_user.id)
    if not invoices:
        await update.message.reply_text("📊 Keine Rechnungen", reply_markup=get_main_keyboard())
        return
    msg = "📊 Rechnungen:\n\n" + "\n".join([f"📝 {i.get('number','—')} | {i.get('total',0):.2f}€" for i in invoices[:10]])
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def my_offers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список офферов"""
    offers = db.get_offers(update.effective_user.id)
    if not offers:
        await update.message.reply_text("📄 Keine Angebote", reply_markup=get_main_keyboard())
        return
    keyboard = [[InlineKeyboardButton(f"{o['offer_number']} | {o['total']:.2f}€", callback_data=f"view_offer_{o['id']}")] for o in offers[:10]]
    await update.message.reply_text("📄 Angebote:", reply_markup=InlineKeyboardMarkup(keyboard))

async def view_offer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр оффера"""
    query = update.callback_query
    await query.answer()
    offer = db.get_offer(query.data.replace("view_offer_", ""))
    if not offer:
        await query.edit_message_text("❌ Nicht gefunden")
        return
    msg = f"📄 {offer['offer_number']}\n🏢 {offer['client_name']}\n💰 {offer['total']:.2f}€"
    keyboard = [[InlineKeyboardButton("✅ In Rechnung umwandeln", callback_data=f"convert_offer_{offer['id']}")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def convert_offer_to_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Конвертация оффера в счет"""
    query = update.callback_query
    await query.answer()
    invoice_id = db.convert_offer_to_invoice(query.data.replace("convert_offer_", ""))
    if invoice_id:
        await query.edit_message_text("✅ In Rechnung umgewandelt!")
    else:
        await query.edit_message_text("❌ Fehler")

# ==================== WEB APP DATA (ТВОЯ ЛОГИКА) ====================

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из WebApp - ТВОЯ РАБОЧАЯ ЛОГИКА"""
    import os
    from supabase import create_client
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    
    try:
        raw_data = json.loads(update.effective_message.web_app_data.data)
        data_type = raw_data.get("type")
        
        # Обновление профиля
        if data_type == "profile_update" or ("company_name" in raw_data and "invoice_data" not in raw_data and "offer_items" not in raw_data):
            profile_data = {
                "id": update.effective_user.id,
                "company_name": raw_data.get("company_name"),
                "street": raw_data.get("street"),
                "city": raw_data.get("city"),
                "postal_code": raw_data.get("postal_code"),
                "email": raw_data.get("email"),
                "phone": raw_data.get("phone"),
                "tax_id": raw_data.get("tax_id"),
                "iban": raw_data.get("iban")
            }
            supabase.table("profiles").upsert(profile_data).execute()
            await update.message.reply_text("🎉 Profil gespeichert!", reply_markup=get_main_keyboard())
        
        # Создание счета
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
            await update.message.reply_text(f"✅ Rechnung {gen_num} gespeichert!", reply_markup=get_main_keyboard())
        
        # Создание оффера
        elif "offer_items" in raw_data:
            client_data = raw_data.get('client_data', {})
            offer_number = db.generate_offer_number(update.effective_user.id)
            offer_data = {
                "user_id": update.effective_user.id,
                "offer_number": offer_number,
                "offer_date": raw_data.get('offer_date'),
                "valid_until": raw_data.get('valid_until'),
                "client_name": client_data.get('company_name'),
                "client_address": f"{client_data.get('street','')} {client_data.get('postal_code','')} {client_data.get('city','')}".strip(),
                "amount": raw_data.get('total_net'),
                "vat_rate": raw_data.get('vat_rate'),
                "total": raw_data.get('total_gross'),
                "format_type": raw_data.get('format_type', 'ZUGFeRD'),
                "notes": raw_data.get('notes')
            }
            offer_id = db.create_offer(offer_data)
            if offer_id:
                db.create_offer_items(offer_id, raw_data.get('offer_items', []))
                db.increment_offer_number(update.effective_user.id)
                await update.message.reply_text(f"✅ Angebot {offer_number}!\n💰 {raw_data.get('total_gross'):.2f}€", reply_markup=get_main_keyboard())
    
    except Exception as e:
        logger.error(f"WebApp error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}", reply_markup=get_main_keyboard())

# ==================== BUTTON HANDLER ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    text = update.message.text
    
    if text == "📝 Rechnung erstellen":
        return await rechnung_erstellen_start(update, context)
    elif text == "📋 Angebot erstellen":
        return await angebot_erstellen_start(update, context)
    elif text == "👥 Meine Kunden":
        return await my_clients_command(update, context)
    elif text == "📊 Meine Rechnungen":
        return await my_invoices_command(update, context)
    elif text == "📄 Meine Angebote":
        return await my_offers_command(update, context)
    elif text == "⚙️ Einstellungen":
        return await settings_main(update, context)
    elif text == "🔙 Zurück":
        await update.message.reply_text("Hauptmenü:", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    else:
        await update.message.reply_text("ℹ️ Nutze Schaltflächen", reply_markup=get_main_keyboard())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Error handler"""
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Fehler", reply_markup=get_main_keyboard())
