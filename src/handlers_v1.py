import logging, json, base64, urllib.parse, io, os, time, traceback
from datetime import datetime
from telegram import (Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
                      InlineKeyboardButton, InlineKeyboardMarkup)
from telegram.ext import ContextTypes, ConversationHandler

from src.pdf_from_template import PDFFromTemplateV2
from src.xml_generator_v2 import XMLGeneratorV2, embed_xml_in_pdf

# Импорты модулей
try:
    from .database_v1 import Database
    from .ai_service_v1 import AIService
    from .config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL, BASE_URL
except ImportError:
    from database_v1 import Database
    from ai_service_v1 import AIService
    from config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL, BASE_URL

logger = logging.getLogger(__name__)
db, ai = Database(), AIService()

# Состояния
SETTINGS_MENU, WAITING_FOR_DOC = range(2)


# ----------------------------
# UI / Keyboard
# ----------------------------
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📝 Rechnungen"), KeyboardButton("📋 Angebote")],
        [KeyboardButton("⚙️ Einstellungen")]
    ], resize_keyboard=True)


def get_invoices_submenu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Neue Rechnung")],
        [KeyboardButton("📊 Rechnungen anzeigen")],
        [KeyboardButton("🔢 Nummerierung einstellen")],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)


def get_offers_submenu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Neues Angebot")],
        [KeyboardButton("📄 Angebote anzeigen")],
        [KeyboardButton("🔢 Nummerierung einstellen")],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)


def get_settings_submenu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🏢 Firmendaten")],
        [KeyboardButton("📜 Rechtliche Hinweise")],
        [KeyboardButton("🗑️ Alle Daten löschen")],
        [KeyboardButton("💬 Feedback senden")],
        [KeyboardButton("🔙 Zurück")]
    ], resize_keyboard=True)


# ----------------------------
# VAT mapping (категория/причина)
# ----------------------------
def get_vat_info(profile, vat_rate=None, vat_mode='standard'):
    """Маппинг НДС для всех форматов (XML, PDF, HTML)"""
    is_kleinunternehmer = bool(profile.get('is_kleinunternehmer', False))
    if is_kleinunternehmer:
        vat_mode = 'klein'

    # default fallback
    default_rate = float(profile.get('default_vat_rate', 19) or 19)

    try:
        rate = float(vat_rate) if vat_rate is not None else default_rate
    except Exception:
        rate = default_rate

    if vat_mode == 'klein':
        return {
            'rate': 0.00,
            'category': 'E',
            'reason': 'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.'
        }
    elif vat_mode == 'reverse':
        return {
            'rate':
            0.00,
            'category':
            'AE',
            'reason':
            'Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).'
        }
    elif vat_mode == 'export':
        return {
            'rate': 0.00,
            'category': 'G',
            'reason': 'Steuerfreie Ausfuhrlieferung.'
        }
    else:
        category = 'S' if rate > 0 else 'Z'
        return {'rate': rate, 'category': category, 'reason': None}


# ----------------------------
# Unit codes (UNECE Rec.20) – практический маппинг
# ----------------------------
# Почему “мало единиц”? Потому что полный список Rec.20 = сотни кодов.
# На практике UI показывает 10-20 популярных, а backend принимает любой корректный unit_code.
UNIT_TO_CODE = {
    # штуки/кол-во
    "Stk": "C62",
    "Stück": "C62",
    "piece": "C62",
    "pcs": "C62",
    "pc": "C62",
    "Paar": "NPR",
    "pair": "NPR",
    "Set": "SET",
    "set": "SET",

    # время
    "Std": "HUR",
    "Stunde": "HUR",
    "h": "HUR",
    "hr": "HUR",
    "hour": "HUR",
    "Min": "MIN",
    "Minute": "MIN",
    "min": "MIN",
    "Sek": "SEC",
    "Sekunde": "SEC",
    "sec": "SEC",
    "Tag": "DAY",
    "Tage": "DAY",
    "day": "DAY",
    "Woche": "WEE",
    "week": "WEE",
    "Monat": "MON",
    "month": "MON",
    "Jahr": "ANN",
    "year": "ANN",

    # масса
    "kg": "KGM",
    "Kilogramm": "KGM",
    "g": "GRM",
    "Gramm": "GRM",
    "t": "TNE",
    "Tonne": "TNE",

    # длина / площадь / объем
    "m": "MTR",
    "Meter": "MTR",
    "cm": "CMT",
    "mm": "MMT",
    "km": "KMT",
    "m²": "MTK",
    "qm": "MTK",
    "Quadratmeter": "MTK",
    "cm²": "CMK",
    "mm²": "MMK",
    "m³": "MTQ",
    "cbm": "MTQ",
    "Kubikmeter": "MTQ",
    "l": "LTR",
    "L": "LTR",
    "Liter": "LTR",
    "ml": "MLT",

    # упаковки / прочее популярное
    "Karton": "CT",
    "carton": "CT",
    "Pack": "NMP",
    "Paket": "NMP",
    "Flasche": "BO",
    "bottle": "BO",
}


# Важно: Rec.20/21 содержит очень много кодов. Мы:
# - маппим популярные unit -> unit_code
# - если unit_code уже прислали — используем как есть
def normalize_unit_code(unit: str, unit_code: str | None) -> str:
    if unit_code and str(unit_code).strip():
        return str(unit_code).strip()
    u = (unit or "").strip()
    if not u:
        return "C62"
    return UNIT_TO_CODE.get(u, "C62")


# ----------------------------
# Helpers
# ----------------------------
def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        return float(str(x).replace(",", "."))
    except Exception:
        return default


def _safe_int(x, default=0) -> int:
    try:
        if x is None:
            return default
        return int(float(str(x).replace(",", ".")))
    except Exception:
        return default


# ----------------------------
# MAIN HANDLER
# ----------------------------
async def web_app_data_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received WebApp data update")

    if not update.effective_message:
        logger.error("effective_message is None in web_app_data_handler")
        return

    raw_data = update.effective_message.web_app_data.data
    try:
        data = json.loads(raw_data)
    except Exception as e:
        logger.error("Invalid JSON from webapp: %s", e)
        await update.effective_message.reply_text(
            "❌ Fehler: Ungültige Daten vom Formular.")
        return

    user_id = update.effective_user.id

    # ========== НАСТРОЙКИ НУМЕРАЦИИ СЧЕТОВ ==========
    if data.get('type') == 'invoice_numbering_update':
        update_data = {
            'invoice_number_prefix': data.get('invoice_number_prefix', 'RE-'),
            'next_invoice_number': _safe_int(data.get('next_invoice_number'), 1),
            'invoice_number_format': _safe_int(data.get('invoice_number_format'), 4)
        }
        
        if db.update_profile(user_id, update_data):
            await update.effective_message.reply_text(
                "✅ Rechnungsnummerierung aktualisiert!",
                reply_markup=get_invoices_submenu()
            )
        else:
            await update.effective_message.reply_text("❌ Fehler beim Speichern!")
        return

    # ========== НАСТРОЙКИ НУМЕРАЦИИ ОФФЕРОВ ==========
    if data.get('type') == 'offer_numbering_update':
        update_data = {
            'offer_number_prefix': data.get('offer_number_prefix', 'ANG-'),
            'next_offer_number': _safe_int(data.get('next_offer_number'), 1),
            'offer_number_format': _safe_int(data.get('offer_number_format'), 4)
        }
        
        if db.update_profile(user_id, update_data):
            await update.effective_message.reply_text(
                "✅ Angebotsnummerierung aktualisiert!",
                reply_markup=get_offers_submenu()
            )
        else:
            await update.effective_message.reply_text("❌ Fehler beim Speichern!")
        return

    # ========== СОХРАНЕНИЕ ПРОФИЛЯ ==========
    if data.get('type') == 'profile_update':
        profile_data = {
            "id":
            user_id,
            "company_name":
            data.get("company_name"),
            "street":
            data.get("street"),
            "postal_code":
            data.get("postal_code"),
            "city":
            data.get("city"),
            "country_code":
            data.get("country_code", "DE"),
            "email":
            data.get("email"),
            "phone":
            data.get("phone"),
            "fax":
            data.get("fax"),
            "website":
            data.get("website"),
            "legal_form":
            data.get("legal_form"),
            "trade_register_number":
            data.get("trade_register_number"),
            "trade_register_court":
            data.get("trade_register_court"),
            "managing_director":
            data.get("managing_director"),
            "contact_person":
            data.get("contact_person"),
            "contact_department":
            data.get("contact_department"),
            "tax_id":
            data.get("tax_id"),
            "vat_id":
            data.get("vat_id"),
            "tax_office":
            data.get("tax_office"),
            "is_kleinunternehmer":
            bool(data.get("is_kleinunternehmer", False)),
            "default_vat_rate":
            _safe_float(data.get("default_vat_rate", 19), 19),
            "global_location_number":
            data.get("global_location_number"),
            "duns_number":
            data.get("duns_number"),
            "bank_name":
            data.get("bank_name"),
            "iban":
            data.get("iban"),
            "bic":
            data.get("bic"),
            "sepa_creditor_id":
            data.get("sepa_creditor_id"),
            "sepa_mandate_reference":
            data.get("sepa_mandate_reference"),
            "payment_terms_days":
            _safe_int(data.get("payment_terms_days", 14), 14),
            "invoice_number_prefix":
            data.get("invoice_number_prefix", "RE-"),
            "invoice_number_format":
            _safe_int(data.get("invoice_number_format", 4), 4),
            "next_invoice_number":
            _safe_int(data.get("next_invoice_number", 1), 1),
            "offer_number_prefix":
            data.get("offer_number_prefix", "ANG-"),
            "offer_number_format":
            _safe_int(data.get("offer_number_format", 4), 4),
            "next_offer_number":
            _safe_int(data.get("next_offer_number", 1), 1),
            "offer_validity_days":
            _safe_int(data.get("offer_validity_days", 14), 14),
            "customer_id_prefix":
            data.get("customer_id_prefix", "KUND-"),
            "next_customer_number":
            _safe_int(data.get("next_customer_number", 1), 1),
            "default_currency":
            data.get("default_currency", "EUR"),
            "default_language":
            data.get("default_language", "de"),
            "invoice_note_default":
            data.get("invoice_note_default"),
            "gdpr_consent":
            bool(data.get("gdpr_consent", False)),
            "gdpr_consent_date":
            data.get("gdpr_consent_date"),
        }

        if db.update_profile(user_id, profile_data):
            await update.effective_message.reply_text(
                "✅ Profil gespeichert!", reply_markup=get_main_keyboard())
        else:
            await update.effective_message.reply_text(
                "❌ Fehler beim Speichern!")
        return

    # ========== СОЗДАНИЕ СЧЕТА ==========
    if data.get('type') == 'invoice_creation':
        profile = db.get_profile(user_id)
        if not profile:
            logger.error("Profile not found for user_id=%s", user_id)
            profile = {}

        vat_mode = (data.get('vat_mode') or 'standard').strip().lower()

        # 1) Create/update client
        client_data = {
            'company_name': data.get('client_name'),
            'street': data.get('client_street'),
            'postal_code': data.get('client_postal_code'),
            'city': data.get('client_city'),
            'country_code': data.get('client_country', 'DE'),
            'email': data.get('client_email'),
            'customer_id': data.get('customer_id'),
            'vat_id': data.get('client_vat_id'),
            'legal_form': data.get('client_legal_form'),
            'trade_register_number': data.get('client_trade_register'),
            'buyer_reference': data.get('buyer_reference'),
        }
        client_id = db.create_or_update_client(user_id, client_data)

        # 2) Items normalization
        raw_items = data.get('items') or []
        vat_per_item = bool(data.get("vat_per_item", False))
        global_vat_rate = _safe_float(data.get("global_vat_rate"),
                                      None) if not vat_per_item else None

        items = []
        for idx, it in enumerate(raw_items, 1):
            unit = it.get("unit") or "Stk"
            unit_code = normalize_unit_code(unit, it.get("unit_code"))

            # VAT rate rules:
            # - если vat_per_item=True — ставка должна прийти на строке (если не пришла, fallback в 0)
            # - если vat_per_item=False — ставка на строке не обязательна, но для канона можно проставить global
            if vat_per_item:
                rate = _safe_float(it.get("vat_rate"), 0.0)
            else:
                rate = _safe_float(
                    global_vat_rate if global_vat_rate is not None else
                    profile.get("default_vat_rate", 19), 19.0)

            items.append({
                "position_number": it.get("position_number") or idx,
                "description": it.get("description") or "",
                "quantity": _safe_float(it.get("quantity"), 0.0),
                "unit": unit,
                "unit_code": unit_code,
                "unit_price": _safe_float(it.get("unit_price"), 0.0),
                "vat_rate": rate,
                # total_price/vat_amount не берем — БД посчитает
            })

        # 3) Invoice header
        invoice_data = {
            "user_id":
            user_id,
            "client_id":
            client_id,
            "number":
            data.get("invoice_number"),
            "invoice_date":
            data.get("invoice_date"),
            "delivery_date":
            data.get("delivery_date") or data.get("invoice_date"),
            "due_date":
            data.get("due_date"),
            "client_name":
            data.get("client_name"),
            "client_address":
            f"{data.get('client_street','')}, {data.get('client_postal_code','')} {data.get('client_city','')}"
            .strip(", "),
            "customer_id":
            data.get("customer_id"),
            "buyer_reference":
            data.get("buyer_reference"),
            "purchase_order_number":
            data.get("purchase_order") or data.get("purchase_order_number"),
            "currency_code":
            data.get("currency_code") or profile.get("default_currency")
            or "EUR",
            "payment_means_code":
            data.get("payment_means") or "58",
            "payment_reference":
            data.get("payment_reference"),
            "vat_mode":
            vat_mode,
            "vat_per_item":
            vat_per_item,
            "global_vat_rate":
            global_vat_rate,  # важное правило: только если vat_per_item=False
            "discount_percentage":
            _safe_float(data.get("discount_percentage"), 0.0),
            "discount_amount":
            _safe_float(data.get("discount_amount"), 0.0),
            "skonto_percentage":
            _safe_float(data.get("skonto_percentage"), 0.0),
            "skonto_days":
            _safe_int(data.get("skonto_days"), 0),
            "shipping_cost":
            _safe_float(data.get("shipping_cost"), 0.0),
            "shipping_vat_rate":
            _safe_float(data.get("shipping_vat_rate"), 0.0),
            "format_type":
            data.get("format_type") or data.get("format") or "ZUGFeRD",
            "notes":
            data.get("notes"),
            "status":
            "draft",
            "payment_status":
            "unpaid",
            "items":
            items,
        }

        invoice_data = {k: v for k, v in invoice_data.items() if v is not None}

        # 4) Save invoice (DB computes totals + vat breakdown)
        invoice_id = db.create_invoice(invoice_data)
        if not invoice_id:
            await update.effective_message.reply_text(
                "❌ Fehler beim Speichern in der DB!")
            return

        # increment number AFTER save
        try:
            db.increment_invoice_number(user_id)
        except Exception:
            logger.warning("increment_invoice_number failed (non-fatal)",
                           exc_info=True)

        # 5) Canonical payload for docs = from DB ONLY
        invoice_db = db.get_invoice(invoice_id) or {}
        items_db = db.get_invoice_items(invoice_id) or []

        # !!! require method in DB:
        # def get_invoice_vat_breakdown(self, invoice_id: str) -> List[Dict]:
        #     return self.client.table("invoice_vat_breakdown").select("*").eq("invoice_id", invoice_id).order("vat_rate").execute().data or []
        try:
            vat_rows = db.get_invoice_vat_breakdown(invoice_id) or []
        except Exception:
            vat_rows = []
            logger.warning("get_invoice_vat_breakdown not available or failed",
                           exc_info=True)

        payload_for_docs = dict(invoice_db)
        payload_for_docs["invoice_number"] = invoice_db.get(
            "number")  # template expects invoice_number
        payload_for_docs["items"] = items_db
        payload_for_docs[
            "vat_breakdown"] = vat_rows  # <-- ключ к правильному VAT breakdown

        # 6) Generate PDF / XML
        try:
            logger.info("Starting PDF/XML generation...")

            pdf_gen_v3 = PDFFromTemplateV2(templates_dir="templates/default")
            xml_gen = XMLGeneratorV2()

            pdf_buf = pdf_gen_v3.generate_invoice_pdf(payload_for_docs,
                                                      profile,
                                                      with_xml=False)
            pdf_bytes = pdf_buf.getvalue()
            filename = f"Rechnung_{invoice_db.get('number') or invoice_data.get('number')}.pdf"

            if (invoice_db.get("format_type")
                    or invoice_data.get("format_type")) == "ZUGFeRD":
                logger.info("Generating ZUGFeRD XML...")
                xml_string = xml_gen.generate_zugferd_xml(
                    payload_for_docs, profile)
                pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)
                caption = "✅ Ваша Rechnung (ZUGFeRD)"
            else:
                caption = "✅ Ваша Rechnung (Standard PDF)"

            await update.effective_message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename=filename,
                caption=caption)

            await update.effective_message.reply_text(
                "✅ Rechnung gespeichert und versendet!",
                reply_markup=get_main_keyboard())

        except Exception as e:
            logger.error("Error during file generation/sending: %s", e)
            logger.error(traceback.format_exc())
            await update.effective_message.reply_text(
                f"❌ Fehler bei der Datei-Erstellung: {str(e)}")


# ----------------------------
# Commands / Navigation
# ----------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not db.get_profile(user.id):
        db.create_profile(user.id, user.first_name, user.username)
    await update.message.reply_text("Hallo!", reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nutzen Sie die Buttons.")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
    url = f"{SETTINGS_FORM_URL}&data={urllib.parse.quote(encoded)}"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("📝 Ihre Kontaktdaten eingeben / prüfen",
                       web_app=WebAppInfo(url=url))
    ], [KeyboardButton("📄 Aus Dokument laden")], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

    await update.message.reply_text("⚙️ Einstellungen:", reply_markup=keyboard)
    return SETTINGS_MENU


async def ask_for_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bitte Foto senden.")
    return WAITING_FOR_DOC


async def handle_profile_document(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Dokument erhalten (Dummy)")
    return SETTINGS_MENU


async def settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await settings_command(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Abgebrochen.",
                                    reply_markup=get_main_keyboard())
    return ConversationHandler.END


async def rechnung_erstellen_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    # ⚠️ ПРОВЕРКА: Профиль заполнен и согласие дано?
    if not profile.get('gdpr_consent') or not profile.get('company_name'):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⚙️ Firmendaten eingeben", 
                callback_data="goto_settings"
            )
        ]])
        
        missing = []
        if not profile.get('gdpr_consent'):
            missing.append("• Zustimmung zu Datenschutz & Nutzungsbedingungen")
        if not profile.get('company_name'):
            missing.append("• Firmendaten (Name, Adresse, etc.)")
        
        await update.message.reply_text(
            "⚠️ **Profil unvollständig**\n\n"
            "Bevor Sie Rechnungen erstellen können, müssen Sie:\n\n" +
            "\n".join(missing) + "\n\n"
            "Bitte gehen Sie zu den Einstellungen und füllen Sie "
            "Ihr Firmenprofil aus.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return  # ❌ БЛОКИРУЕМ создание
    
    # ✅ Всё ОК - открываем форму
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")

    url = f"{CREATE_INVOICE_FORM_URL}&data={encoded}"
    await update.message.reply_text(
        "Öffnen Sie das Formular:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📝 Rechnung", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True))


async def angebot_erstellen_start(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    # ⚠️ ПРОВЕРКА: Профиль заполнен и согласие дано?
    if not profile.get('gdpr_consent') or not profile.get('company_name'):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⚙️ Firmendaten eingeben", 
                callback_data="goto_settings"
            )
        ]])
        
        missing = []
        if not profile.get('gdpr_consent'):
            missing.append("• Zustimmung zu Datenschutz & Nutzungsbedingungen")
        if not profile.get('company_name'):
            missing.append("• Firmendaten (Name, Adresse, etc.)")
        
        await update.message.reply_text(
            "⚠️ **Profil unvollständig**\n\n"
            "Bevor Sie Angebote erstellen können, müssen Sie:\n\n" +
            "\n".join(missing) + "\n\n"
            "Bitte gehen Sie zu den Einstellungen und füllen Sie "
            "Ihr Firmenprofil aus.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return  # ❌ БЛОКИРУЕМ создание
    
    # ✅ Всё ОК - открываем форму
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_OFFER_FORM_URL}&data={encoded}"

    await update.message.reply_text(
        "Öffnen Sie das Formular:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📋 Angebot", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    user_id = update.effective_user.id

    # ===== ГЛАВНОЕ МЕНЮ =====
    if txt == "📝 Rechnungen":
        context.user_data['current_menu'] = 'invoices'
        await update.message.reply_text(
            "📝 Rechnungen verwalten:",
            reply_markup=get_invoices_submenu()
        )
    elif txt == "📋 Angebote":
        context.user_data['current_menu'] = 'offers'
        await update.message.reply_text(
            "📋 Angebote verwalten:",
            reply_markup=get_offers_submenu()
        )
    elif txt == "⚙️ Einstellungen":
        context.user_data['current_menu'] = 'settings'
        await update.message.reply_text(
            "⚙️ Einstellungen:",
            reply_markup=get_settings_submenu()
        )
    
    # ===== ПОДМЕНЮ СЧЕТОВ =====
    elif txt == "➕ Neue Rechnung":
        await rechnung_erstellen_start(update, context)
    elif txt == "📊 Rechnungen anzeigen":
        await show_invoices_list(update, context)
    elif txt == "🔢 Nummerierung einstellen":
        # Определяем из какого меню
        if context.user_data.get('current_menu') == 'offers':
            await show_offer_numbering_settings(update, context)
        else:
            await show_invoice_numbering_settings(update, context)
    
    # ===== ПОДМЕНЮ ОФФЕРОВ =====
    elif txt == "➕ Neues Angebot":
        await angebot_erstellen_start(update, context)
    elif txt == "📄 Angebote anzeigen":
        await show_offers_list(update, context)
    
    # ===== ПОДМЕНЮ НАСТРОЕК =====
    elif txt == "🏢 Firmendaten":
        await settings_command(update, context)
    elif txt == "📜 Rechtliche Hinweise":
        await show_legal_info(update, context)
    elif txt == "🗑️ Alle Daten löschen":
        await delete_all_data_handler(update, context)
    elif txt == "💬 Feedback senden":
        await show_feedback_form(update, context)
    
    # ===== НАЗАД =====
    elif txt == "🔙 Zurück":
        await update.message.reply_text(
            "Hauptmenü:",
            reply_markup=get_main_keyboard()
        )
    
    else:
        await update.message.reply_text(
            "Unbekannter Befehl. Bitte verwenden Sie die Buttons.",
            reply_markup=get_main_keyboard()
        )


# ----------------------------
# Списки документов
# ----------------------------
async def show_invoices_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список счетов"""
    user_id = update.effective_user.id
    
    # Получаем данные
    invoices = db.get_invoices(user_id, limit=20)  # Ограничим до 20 последних
    limits = db.get_user_limits(user_id)
    
    if not invoices:
        await update.message.reply_text(
            "📊 У вас пока нет счетов.\n\n"
            "Создайте первый счёт с помощью кнопки '➕ Neue Rechnung'",
            reply_markup=get_invoices_submenu()
        )
        return
    
    # Формируем текстовый список
    text = "📊 **Ваши последние счета:**\n\n"
    
    for idx, inv in enumerate(invoices[:10], 1):  # Показываем только 10
        status_emoji = {
            'draft': '📝',
            'sent': '📤', 
            'paid': '✅',
            'overdue': '⚠️'
        }.get(inv.get('status', 'draft'), '📄')
        
        date = inv.get('invoice_date', '')[:10] if inv.get('invoice_date') else '-'
        number = inv.get('number', 'N/A')
        client = inv.get('client_name', 'Unbekannt')[:20]
        total = f"{float(inv.get('total', 0)):.2f} €"
        
        text += f"{status_emoji} **{number}**\n"
        text += f"   {client} • {date} • {total}\n\n"
    
    if len(invoices) > 10:
        text += f"... und {len(invoices) - 10} weitere\n\n"
    
    # Статистика
    if limits:
        if limits.get('plan_type') == 'paid':
            text += "💎 Pro Plan aktiv\n"
        else:
            current = limits.get('invoices_this_month', 0)
            limit = limits.get('invoices_limit', 5)
            text += f"📊 {current}/{limit} Rechnungen diesen Monat\n"
    
    text += f"\nGesamt: {len(invoices)} Rechnung(en)"
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=get_invoices_submenu()
    )


async def show_offers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список офферов"""
    user_id = update.effective_user.id
    
    # Получаем данные
    offers = db.get_offers(user_id, limit=20)
    limits = db.get_user_limits(user_id)
    
    if not offers:
        await update.message.reply_text(
            "📄 У вас пока нет предложений.\n\n"
            "Создайте первое предложение с помощью кнопки '➕ Neues Angebot'",
            reply_markup=get_offers_submenu()
        )
        return
    
    # Формируем текстовый список
    text = "📄 **Ваши последние предложения:**\n\n"
    
    for idx, off in enumerate(offers[:10], 1):
        locked_emoji = "🔒" if off.get('is_locked') else "📝"
        converted = "➡️📄" if off.get('converted_to_invoice_id') else ""
        
        date = off.get('offer_date', '')[:10] if off.get('offer_date') else '-'
        number = off.get('offer_number', 'N/A')
        client = off.get('client_name', 'Unbekannt')[:20]
        total = f"{float(off.get('total', 0)):.2f} €"
        
        text += f"{locked_emoji} **{number}** {converted}\n"
        text += f"   {client} • {date} • {total}\n\n"
    
    if len(offers) > 10:
        text += f"... und {len(offers) - 10} weitere\n\n"
    
    text += f"\nGesamt: {len(offers)} Angebot(e)"
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=get_offers_submenu()
    )


# ----------------------------
# Копирование документов
# ----------------------------
async def handle_copy_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: str):
    """Обработка копирования счёта"""
    user_id = update.effective_user.id
    
    new_id = db.copy_invoice(invoice_id, user_id)
    if new_id:
        await update.effective_message.reply_text(
            "✅ Rechnung wurde kopiert!\n\nSie können sie jetzt bearbeiten und speichern."
        )
        # Можно открыть форму редактирования
    else:
        await update.effective_message.reply_text("❌ Fehler beim Kopieren der Rechnung.")


async def handle_copy_offer(update: Update, context: ContextTypes.DEFAULT_TYPE, offer_id: str):
    """Обработка копирования оффера"""
    user_id = update.effective_user.id
    
    new_id = db.copy_offer(offer_id, user_id)
    if new_id:
        await update.effective_message.reply_text(
            "✅ Angebot wurde kopiert!\n\nSie können es jetzt bearbeiten und speichern."
        )
    else:
        await update.effective_message.reply_text("❌ Fehler beim Kopieren des Angebots.")


# ----------------------------
# Удаление всех данных
# ----------------------------
async def delete_all_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка удаления всех данных пользователя"""
    user_id = update.effective_user.id
    
    # Подтверждение
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ALLE DATEN LÖSCHEN", callback_data=f"confirm_delete_{user_id}")],
        [InlineKeyboardButton("🔙 Abbrechen", callback_data="cancel_delete")]
    ])
    
    await update.message.reply_text(
        "⚠️ ACHTUNG!\n\n"
        "Sie sind dabei, ALLE Ihre Daten zu löschen:\n"
        "• Alle Rechnungen\n"
        "• Alle Angebote\n"
        "• Alle Kunden\n"
        "• Alle gespeicherten Dateien\n\n"
        "Diese Aktion kann nicht rückgängig gemacht werden!\n\n"
        "Sind Sie sicher?",
        reply_markup=keyboard
    )


async def handle_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    await query.edit_message_text("⏳ Lösche Daten...")
    
    stats = db.delete_all_user_data(user_id)
    
    await query.edit_message_text(
        "✅ Alle Daten wurden gelöscht!\n\n"
        f"Gelöscht:\n"
        f"• Rechnungen: {stats.get('invoices', 0)}\n"
        f"• Angebote: {stats.get('offers', 0)}\n"
        f"• Kunden: {stats.get('clients', 0)}\n"
        f"• Dateien: {stats.get('files', 0)}"
    )


# ----------------------------
# Архив документов
# ----------------------------
async def request_documents_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос архива всех документов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    
    if not profile or not profile.get('user_email'):
        await update.message.reply_text(
            "📧 Bitte geben Sie zuerst Ihre E-Mail-Adresse in den Einstellungen an."
        )
        return
    
    email = profile['user_email']
    
    # Создаём запрос
    archive_id = db.create_archive_request(user_id, email)
    
    if archive_id:
        await update.message.reply_text(
            f"✅ Ihr Archiv wird erstellt und an {email} gesendet.\n\n"
            "Dies kann einige Minuten dauern."
        )
        
        # TODO: Запустить фоновую задачу создания архива
        # Пока заглушка
    else:
        await update.message.reply_text("❌ Fehler beim Erstellen der Anfrage.")


# ----------------------------
# Обратная связь
# ----------------------------
async def show_feedback_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать форму обратной связи"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💡 Vorschlag", callback_data="feedback_feature")],
        [InlineKeyboardButton("🐛 Bug melden", callback_data="feedback_bug")],
        [InlineKeyboardButton("🤝 Zusammenarbeit", callback_data="feedback_cooperation")],
        [InlineKeyboardButton("💬 Allgemein", callback_data="feedback_general")],
    ])
    
    await update.message.reply_text(
        "📧 Kontakt zum Entwickler\n\n"
        "Wählen Sie eine Kategorie:",
        reply_markup=keyboard
    )


async def handle_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа обратной связи"""
    query = update.callback_query
    await query.answer()
    
    feedback_type = query.data.replace('feedback_', '')
    
    types_map = {
        'feature': 'Vorschlag',
        'bug': 'Bug',
        'cooperation': 'Zusammenarbeit',
        'general': 'Allgemeine Anfrage'
    }
    
    context.user_data['feedback_type'] = feedback_type
    
    await query.edit_message_text(
        f"📝 {types_map.get(feedback_type, 'Nachricht')}\n\n"
        "Bitte schreiben Sie Ihre Nachricht:"
    )


# ----------------------------
# PayPal "Спасибо"
# ----------------------------
async def show_donation_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать сообщение с благодарностью и ссылкой на PayPal"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ Sag Danke mit PayPal", url="https://paypal.me/YOURPAYPAL")],
    ])
    
    await update.effective_message.reply_text(
        "🎉 Rechnung erfolgreich erstellt!\n\n"
        "💚 Wenn Ihnen dieser Service geholfen hat, können Sie dem Entwickler ein Dankeschön senden:",
        reply_markup=keyboard
    )


# ----------------------------
# Upgrade на платную версию
# ----------------------------
async def show_upgrade_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о платной версии"""
    user_id = update.effective_user.id
    limits = db.get_user_limits(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Pro Plan kaufen", callback_data="buy_pro")],
        [InlineKeyboardButton("ℹ️ Mehr Info", callback_data="upgrade_info")],
    ])
    
    current = limits.get('invoices_this_month', 0) if limits else 0
    limit = limits.get('invoices_limit', 5) if limits else 5
    
    await update.message.reply_text(
        "💎 RechnungAgent Pro\n\n"
        f"Aktuell: {current}/{limit} Rechnungen diesen Monat\n\n"
        "**Pro Features:**\n"
        "✅ Unbegrenzte Rechnungen\n"
        "✅ Unbegrenzte Angebote\n"
        "✅ Alle Dokumente gespeichert\n"
        "✅ Prioritäts-Support\n"
        "✅ Erweiterte Vorlagen\n\n"
        "**Preis:** 9,99 € / Monat",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )


# ----------------------------
# Настройки нумерации
# ----------------------------
async def show_invoice_numbering_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать форму настройки нумерации счетов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
    
    url = f"{BASE_URL}/invoice_numbering.html?data={urllib.parse.quote(encoded)}"
    
    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("🔢 Nummerierung öffnen", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True)
    
    current_prefix = profile.get('invoice_number_prefix', 'RE-')
    current_next = profile.get('next_invoice_number', 1)
    current_format = profile.get('invoice_number_format', 4)
    
    await update.message.reply_text(
        f"🔢 Rechnungsnummerierung\n\n"
        f"Aktuell:\n"
        f"Präfix: {current_prefix}\n"
        f"Nächste Nummer: {current_next}\n"
        f"Format: {current_format} Stellen\n\n"
        f"Beispiel: {current_prefix}{str(current_next).zfill(current_format)}",
        reply_markup=keyboard
    )


async def show_offer_numbering_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать форму настройки нумерации офферов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")
    
    url = f"{BASE_URL}/offer_numbering.html?data={urllib.parse.quote(encoded)}"
    
    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("🔢 Nummerierung öffnen", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("🔙 Zurück")]], resize_keyboard=True)
    
    current_prefix = profile.get('offer_number_prefix', 'ANG-')
    current_next = profile.get('next_offer_number', 1)
    current_format = profile.get('offer_number_format', 4)
    
    await update.message.reply_text(
        f"🔢 Angebotsnummerierung\n\n"
        f"Aktuell:\n"
        f"Präfix: {current_prefix}\n"
        f"Nächste Nummer: {current_next}\n"
        f"Format: {current_format} Stellen\n\n"
        f"Beispiel: {current_prefix}{str(current_next).zfill(current_format)}",
        reply_markup=keyboard
    )


# ----------------------------
# Правовая информация / защита
# ----------------------------
async def show_legal_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать правовую информацию и защиту"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    # URL на Terms of Service
    terms_url = f"{BASE_URL}/terms_of_service.html"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Nutzungsbedingungen", url=terms_url)],
        [InlineKeyboardButton("✅ Akzeptiert" if profile.get('accepted_terms') else "❌ Nicht akzeptiert", 
                            callback_data="toggle_terms")],
    ])
    
    terms_date = profile.get('accepted_terms_date', 'Nie')
    
    await update.message.reply_text(
        "📜 Rechtliche Hinweise\n\n"
        "⚠️ WICHTIG: Haftungsausschluss\n\n"
        "Dieser Bot dient nur zur Unterstützung bei der Rechnungserstellung. "
        "Der Entwickler übernimmt KEINE Haftung für:\n\n"
        "• Richtigkeit der Dokumente\n"
        "• Steuerrechtliche Konformität\n"
        "• Finanzielle Schäden\n"
        "• Datenverlust\n\n"
        "Sie sind selbst verantwortlich für:\n"
        "✅ Prüfung aller Dokumente vor Versand\n"
        "✅ Einhaltung lokaler Steuergesetze\n"
        "✅ Korrekte Angaben\n\n"
        f"Status: {'✅ Akzeptiert am ' + str(terms_date) if profile.get('accepted_terms') else '❌ Nicht akzeptiert'}\n\n"
        "Bitte lesen Sie die vollständigen Nutzungsbedingungen.",
        reply_markup=keyboard
    )


async def handle_toggle_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка принятия/отклонения условий"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}
    
    current_status = profile.get('accepted_terms', False)
    new_status = not current_status
    
    update_data = {
        'accepted_terms': new_status,
        'accepted_terms_date': datetime.now().isoformat() if new_status else None
    }
    
    if db.update_profile(user_id, update_data):
        status_text = "✅ akzeptiert" if new_status else "❌ zurückgezogen"
        await query.edit_message_text(
            f"Status: Nutzungsbedingungen {status_text}.\n\n"
            "Sie können diese Einstellung jederzeit ändern."
        )
    else:
        await query.edit_message_text("❌ Fehler beim Aktualisieren.")


async def handle_goto_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход в настройки при нажатии кнопки"""
    query = update.callback_query
    await query.answer()
    
    # Просто вызываем settings_command
    await settings_command(query, context)




async def view_offer_details(update, context):
    pass


async def convert_offer_to_invoice(update, context):
    pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("====== GLOBAL ERROR HANDLER ======")

    if update:
        logger.error("Update: %s", update)

    err = context.error
    logger.error("Exception type: %s", type(err))
    logger.error("Exception message: %s", err)

    tb = "".join(traceback.format_exception(None, err, err.__traceback__))
    logger.error("Full traceback:\n%s", tb)
    logger.error("====== END ERROR ======")
