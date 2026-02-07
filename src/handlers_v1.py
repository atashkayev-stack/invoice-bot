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
    from .config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL
except ImportError:
    from database_v1 import Database
    from ai_service_v1 import AIService
    from config_v1 import SETTINGS_FORM_URL, CREATE_INVOICE_FORM_URL, CREATE_OFFER_FORM_URL

logger = logging.getLogger(__name__)
db, ai = Database(), AIService()

# Состояния
SETTINGS_MENU, WAITING_FOR_DOC = range(2)


# ----------------------------
# UI / Keyboard
# ----------------------------
def get_main_keyboard():
    return ReplyKeyboardMarkup([[
        KeyboardButton("📝 Rechnung erstellen"),
        KeyboardButton("📋 Angebot erstellen")
    ], [
        KeyboardButton("👥 Meine Kunden"),
        KeyboardButton("📊 Meine Rechnungen")
    ], [
        KeyboardButton("📄 Meine Angebote"),
        KeyboardButton("⚙️ Einstellungen")
    ], [KeyboardButton("🔙 Zurück")]],
                               resize_keyboard=True)


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
    encoded = base64.urlsafe_b64encode(
        json.dumps(profile).encode()).decode().strip("=")
    url = f"{CREATE_OFFER_FORM_URL}&data={encoded}"

    await update.message.reply_text(
        "Öffnen Sie das Formular:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📋 Angebot", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t == "📝 Rechnung erstellen":
        await rechnung_erstellen_start(update, context)
    elif t == "📋 Angebot erstellen":
        await angebot_erstellen_start(update, context)
    elif t == "⚙️ Einstellungen":
        await settings_command(update, context)
    elif t == "🔙 Zurück":
        await update.message.reply_text("Hauptменю",
                                        reply_markup=get_main_keyboard())


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
