import logging, json, base64, urllib.parse
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from .database_v1 import Database
from .ai_service_v1 import AIService
from .config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL

logger = logging.getLogger(__name__)
db, ai = Database(), AIService()
WAITING_FOR_DOCUMENT, WAITING_FOR_CLIENT_SEARCH, SELECTING_CLIENT = 1, 2, 3

def get_main_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("📝 Rechnung erstellen"), KeyboardButton("📋 Angebot erstellen")], [KeyboardButton("👥 Kunden"), KeyboardButton("📊 Rechnungen"), KeyboardButton("📄 Angebote")], [KeyboardButton("⚙️ Einstellungen"), KeyboardButton("❓ Hilfe")]], resize_keyboard=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = db.get_profile(user.id)
    if not profile:
        db.create_profile(user.id, user.first_name, user.username)
        msg = f"👋 Hallo, {user.first_name}!\n\n🎉 Willkommen!\n\n✅ E-Rechnung 2025\n✅ ZUGFeRD & XRechnung\n✅ KI-Erkennung\n\n1. ⚙️ Einstellungen\n2. 📝 Rechnung erstellen"
    else:
        msg = f"👋 {user.first_name}!\n\n🏢 {profile.get('company_name', 'Profil einrichten')}" if profile.get('company_name') else "Bitte Profil einrichten:\n→ ⚙️ Einstellungen"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 RechnungAgent\n\n📝 Rechnung/Angebot erstellen\n👥 Kunden verwalten\n⚙️ Einstellungen\n\nE-Rechnung ab 2025 Pflicht!", reply_markup=get_main_keyboard())

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profile = db.get_profile(update.effective_user.id)
    if profile:
        info = f"📊 Profil:\n🏢 {profile.get('company_name','—')}\n📍 {profile.get('street','')} {profile.get('postal_code','')} {profile.get('city','')}\n"
        data_json = json.dumps(profile, default=str)
        url = f"{SETTINGS_FORM_URL}?data={urllib.parse.quote(base64.b64encode(data_json.encode()).decode())}"
    else:
        info, url = "ℹ️ Profil leer\n", SETTINGS_FORM_URL
    await update.message.reply_text(info + "Klicke:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("✏️ Bearbeiten", web_app=WebAppInfo(url=url))], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True))

async def create_invoice_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.get_profile(update.effective_user.id) or not db.get_profile(update.effective_user.id).get('company_name'):
        await update.message.reply_text("⚠️ Profil einrichten!\n→ ⚙️ Einstellungen", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("🆕 Rechnung\n\n👤 Kunde wählen\n📄 Scannen (KI)\n✍️ Manuell", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("👤 Kunde auswählen")], [KeyboardButton("📄 Dokument scannen")], [KeyboardButton("✍️ Neuer Kunde")], [KeyboardButton("❌ Abbrechen")]], resize_keyboard=True))
    context.user_data['invoice_mode'] = True
    return WAITING_FOR_DOCUMENT

async def create_offer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.get_profile(update.effective_user.id) or not db.get_profile(update.effective_user.id).get('company_name'):
        await update.message.reply_text("⚠️ Profil einrichten!", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("🆕 Angebot\n\n👤 Kunde wählen\n📄 Scannen (KI)\n✍️ Manuell", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("👤 Kunde auswählen")], [KeyboardButton("📄 Dokument scannen")], [KeyboardButton("✍️ Neuer Kunde")], [KeyboardButton("❌ Abbrechen")]], resize_keyboard=True))
    context.user_data['invoice_mode'] = False
    return WAITING_FOR_DOCUMENT

async def select_existing_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clients = db.get_all_clients(update.effective_user.id)
    if not clients:
        await update.message.reply_text("📋 Keine Kunden\n\n📄 Scannen\n✍️ Manuell", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📄 Dokument scannen")], [KeyboardButton("✍️ Neuer Kunde")], [KeyboardButton("❌ Abbrechen")]], resize_keyboard=True))
        return WAITING_FOR_DOCUMENT
    msg = "👥 Kunden:\n\n" + "\n".join([f"{i}. {c['company_name']}" + (f" ({c['city']})" if c.get('city') else "") for i, c in enumerate(clients[:10], 1)])
    await update.message.reply_text(msg + "\n\n🔍 Suche:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Abbrechen")]], resize_keyboard=True))
    return WAITING_FOR_CLIENT_SEARCH

async def search_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() == "❌ abbrechen": return await cancel_operation(update, context)
    matched = db.search_clients(update.effective_user.id, update.message.text)
    if not matched:
        await update.message.reply_text(f"🔍 Nichts für '{update.message.text}'")
        return WAITING_FOR_CLIENT_SEARCH
    keyboard = [[InlineKeyboardButton(c['company_name'] + (f" ({c['city']})" if c.get('city') else ""), callback_data=f"select_client_{c['id']}")] for c in matched[:5]]
    keyboard.append([InlineKeyboardButton("❌ Abbrechen", callback_data="cancel_client")])
    await update.message.reply_text(f"✅ {len(matched)} gefunden:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_CLIENT

async def client_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_client":
        await query.edit_message_text("❌ Abgebrochen")
        await query.message.reply_text("Hauptmenü:", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    client = db.get_client(query.data.replace("select_client_", ""))
    if not client:
        await query.edit_message_text("❌ Nicht gefunden")
        return ConversationHandler.END
    await query.edit_message_text(f"✅ {client['company_name']}\n📍 {client.get('street','')} {client.get('postal_code','')} {client.get('city','')}")
    data_json, data_encoded = json.dumps(client, default=str), base64.b64encode(json.dumps(client, default=str).encode()).decode()
    invoice_mode = context.user_data.get('invoice_mode', True)
    url = f"{CREATE_INVOICE_FORM_URL if invoice_mode else CREATE_OFFER_FORM_URL}?client={urllib.parse.quote(data_encoded)}"
    await query.message.reply_text("Klicke:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📝 Formular", web_app=WebAppInfo(url=url))], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True))
    return ConversationHandler.END

async def prompt_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📤 Foto senden:\n💡 Visitenkarte/Rechnung", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Abbrechen")]], resize_keyboard=True))
    return WAITING_FOR_DOCUMENT

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ KI analysiert...")
    try:
        if update.message.photo: file, media = await context.bot.get_file(update.message.photo[-1].file_id), "image/jpeg"
        elif update.message.document: file, media = await context.bot.get_file(update.message.document.file_id), update.message.document.mime_type
        else:
            await msg.edit_text("❌ Foto senden!")
            return WAITING_FOR_DOCUMENT
        data = ai.extract_client_data(await file.download_as_bytearray(), media)
        if not data:
            await msg.edit_text("❌ Keine Daten erkannt")
            return WAITING_FOR_DOCUMENT
        await msg.edit_text(f"✅ Erkannt!\n🏢 {data.get('company_name','—')}\n📍 {ai.format_address(data)}")
        data_json = json.dumps(data, default=str)
        invoice_mode = context.user_data.get('invoice_mode', True)
        url = f"{CREATE_INVOICE_FORM_URL if invoice_mode else CREATE_OFFER_FORM_URL}?client={urllib.parse.quote(base64.b64encode(data_json.encode()).decode())}"
        await update.message.reply_text("Klicke:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📝 Formular", web_app=WebAppInfo(url=url))], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True))
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Doc error: {e}")
        await msg.edit_text(f"❌ Fehler: {e}")
        return WAITING_FOR_DOCUMENT

async def manual_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    invoice_mode = context.user_data.get('invoice_mode', True)
    url = CREATE_INVOICE_FORM_URL if invoice_mode else CREATE_OFFER_FORM_URL
    await update.message.reply_text("✍️ Manuell", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📝 Formular", web_app=WebAppInfo(url=url))], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True))
    return ConversationHandler.END

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Abgebrochen", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def my_clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clients = db.get_all_clients(update.effective_user.id)
    if not clients:
        await update.message.reply_text("👥 Keine Kunden", reply_markup=get_main_keyboard())
        return
    msg = f"👥 {len(clients)} Kunden:\n\n" + "\n".join([f"🏢 {c['company_name']}\n   🆔 {c.get('customer_id','—')}\n" for c in clients[:20]])
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def my_invoices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    invoices = db.get_invoices(update.effective_user.id)
    if not invoices:
        await update.message.reply_text("📊 Keine Rechnungen", reply_markup=get_main_keyboard())
        return
    msg = "📊 Rechnungen:\n\n" + "\n".join([f"📝 {i.get('number','—')} | {i.get('total',0):.2f}€\n   📅 {i.get('invoice_date','—')}\n" for i in invoices])
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())

async def my_offers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offers = db.get_offers(update.effective_user.id)
    if not offers:
        await update.message.reply_text("📄 Keine Angebote", reply_markup=get_main_keyboard())
        return
    keyboard = [[InlineKeyboardButton(f"{o['offer_number']} | {o['total']:.2f}€", callback_data=f"view_offer_{o['id']}")] for o in offers]
    await update.message.reply_text("📄 Angebote:", reply_markup=InlineKeyboardMarkup(keyboard))

async def view_offer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offer = db.get_offer(query.data.replace("view_offer_", ""))
    if not offer:
        await query.edit_message_text("❌ Nicht gefunden")
        return
    msg = f"📄 {offer['offer_number']}\n\n🏢 {offer['client_name']}\n💰 {offer['total']:.2f}€\n📅 {offer['offer_date']}\n⏰ Gültig bis: {offer['valid_until']}"
    keyboard = [[InlineKeyboardButton("✅ In Rechnung umwandeln", callback_data=f"convert_offer_{offer['id']}")], [InlineKeyboardButton("🔙 Zurück", callback_data="back_offers")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def convert_offer_to_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = db.convert_offer_to_invoice(query.data.replace("convert_offer_", ""))
    if invoice_id:
        await query.edit_message_text("✅ In Rechnung umgewandelt!")
    else:
        await query.edit_message_text("❌ Fehler")

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = json.loads(update.effective_message.web_app_data.data)
    user_id = update.effective_user.id
    try:
        if data.get('type') == 'profile_update':
            db.update_profile(user_id, {"company_name": data.get("company_name"), "street": data.get("street"), "postal_code": data.get("postal_code"), "city": data.get("city"), "tax_id": data.get("tax_id"), "vat_id": data.get("vat_id"), "iban": data.get("iban"), "bic": data.get("bic"), "bank_name": data.get("bank_name"), "email": data.get("email"), "phone": data.get("phone"), "invoice_number_prefix": data.get("invoice_number_prefix"), "invoice_number_format": data.get("invoice_number_format"), "next_invoice_number": data.get("next_invoice_number"), "customer_id_prefix": data.get("customer_id_prefix"), "offer_number_prefix": data.get("offer_number_prefix"), "offer_number_format": data.get("offer_number_format"), "next_offer_number": data.get("next_offer_number")})
            await update.message.reply_text(f"✅ Gespeichert!\n🏢 {data.get('company_name')}", reply_markup=get_main_keyboard())
        elif 'invoice_items' in data:
            client_data = data.get('client_data', {})
            client_id = db.create_or_update_client(user_id, {'company_name': client_data.get('company_name'), 'customer_id': client_data.get('customer_id'), 'street': client_data.get('street'), 'postal_code': client_data.get('postal_code'), 'city': client_data.get('city'), 'email': client_data.get('email'), 'phone': client_data.get('phone'), 'tax_id': client_data.get('tax_id'), 'vat_id': client_data.get('vat_id')})
            invoice_number = db.generate_invoice_number(user_id)
            invoice_id = db.create_invoice({"user_id": user_id, "client_id": client_id, "number": invoice_number, "invoice_date": data.get('invoice_date'), "client_name": client_data.get('company_name'), "client_address": f"{client_data.get('street','')} {client_data.get('postal_code','')} {client_data.get('city','')}".strip(), "customer_id": client_data.get('customer_id'), "purchase_order_number": data.get('purchase_order'), "amount": data.get('total_net'), "vat_rate": data.get('vat_rate'), "total": data.get('total_gross'), "format_type": data.get('format_type', 'ZUGFeRD'), "notes": data.get('notes'), "status": "draft"})
            if invoice_id:
                db.create_invoice_items(invoice_id, data.get('invoice_items', []))
                db.increment_invoice_number(user_id)
                await update.message.reply_text(f"✅ Rechnung {invoice_number}!\n💰 {data.get('total_gross'):.2f}€", reply_markup=get_main_keyboard())
        elif 'offer_items' in data:
            client_data = data.get('client_data', {})
            client_id = db.create_or_update_client(user_id, {'company_name': client_data.get('company_name'), 'customer_id': client_data.get('customer_id'), 'street': client_data.get('street'), 'postal_code': client_data.get('postal_code'), 'city': client_data.get('city'), 'email': client_data.get('email'), 'phone': client_data.get('phone')})
            offer_number = db.generate_offer_number(user_id)
            offer_id = db.create_offer({"user_id": user_id, "client_id": client_id, "offer_number": offer_number, "offer_date": data.get('offer_date'), "valid_until": data.get('valid_until'), "client_name": client_data.get('company_name'), "client_address": f"{client_data.get('street','')} {client_data.get('postal_code','')} {client_data.get('city','')}".strip(), "customer_id": client_data.get('customer_id'), "purchase_order_number": data.get('purchase_order'), "amount": data.get('total_net'), "vat_rate": data.get('vat_rate'), "total": data.get('total_gross'), "format_type": data.get('format_type', 'ZUGFeRD'), "notes": data.get('notes')})
            if offer_id:
                db.create_offer_items(offer_id, data.get('offer_items', []))
                db.increment_offer_number(user_id)
                await update.message.reply_text(f"✅ Angebot {offer_number}!\n💰 {data.get('total_gross'):.2f}€", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"WebApp error: {e}")
        await update.message.reply_text(f"❌ Fehler: {e}", reply_markup=get_main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📝 Rechnung erstellen": return await create_invoice_start(update, context)
    elif text == "📋 Angebot erstellen": return await create_offer_start(update, context)
    elif text == "👥 Kunden": return await my_clients_command(update, context)
    elif text == "📊 Rechnungen": return await my_invoices_command(update, context)
    elif text == "📄 Angebote": return await my_offers_command(update, context)
    elif text == "⚙️ Einstellungen": return await settings_command(update, context)
    elif text == "❓ Hilfe": return await help_command(update, context)
    elif text == "🔙 Zurück":
        await update.message.reply_text("Hauptmenü:", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    else: await update.message.reply_text("ℹ️ Nutze Schaltflächen", reply_markup=get_main_keyboard())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Fehler", reply_markup=get_main_keyboard())
