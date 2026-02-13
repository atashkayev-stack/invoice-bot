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
    return ReplyKeyboardMarkup([[
        KeyboardButton("📄 Rechnungen"),
        KeyboardButton("📋 Angebote"),
        KeyboardButton("⚙️ Einstellungen")
    ]],
                               resize_keyboard=True)


def get_invoices_submenu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("➕ Neue Rechnung")], [KeyboardButton("📊 Liste")],
         [KeyboardButton("🔢 Nummerierung")], [KeyboardButton("🔙 Zurück")]],
        resize_keyboard=True)


def get_offers_submenu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("➕ Neues Angebot")], [KeyboardButton("📄 Liste")],
         [KeyboardButton("🔢 Nummerierung")], [KeyboardButton("🔙 Zurück")]],
        resize_keyboard=True)


def get_settings_submenu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏢 Firmendaten")], [KeyboardButton("🔒 Datenschutz")],
         [KeyboardButton("🗑️ Daten löschen")],
         [KeyboardButton("💬 Feedback senden")], [KeyboardButton("🔙 Zurück")]],
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

    # ========== НАСТРОЙКИ НУМЕРАЦИИ СЧЕТОВ ==========
    if data.get('type') == 'invoice_numbering_update':
        update_data = {
            'invoice_number_prefix':
            data.get('invoice_number_prefix', 'RE-'),
            'next_invoice_number':
            _safe_int(data.get('next_invoice_number'), 1),
            'invoice_number_format':
            _safe_int(data.get('invoice_number_format'), 4)
        }

        if db.update_profile(user_id, update_data):
            await update.effective_message.reply_text(
                "✅ Rechnungsnummerierung aktualisiert!",
                reply_markup=get_invoices_submenu())
        else:
            await update.effective_message.reply_text(
                "❌ Fehler beim Speichern!")
        return

    # ========== НАСТРОЙКИ НУМЕРАЦИИ ОФФЕРОВ ==========
    if data.get('type') == 'offer_numbering_update':
        update_data = {
            'offer_number_prefix': data.get('offer_number_prefix', 'ANG-'),
            'next_offer_number': _safe_int(data.get('next_offer_number'), 1),
            'offer_number_format': _safe_int(data.get('offer_number_format'),
                                             4)
        }

        if db.update_profile(user_id, update_data):
            await update.effective_message.reply_text(
                "✅ Angebotsnummerierung aktualisiert!",
                reply_markup=get_offers_submenu())
        else:
            await update.effective_message.reply_text(
                "❌ Fehler beim Speichern!")
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
            "client_street":
            data.get("client_street"),
            "client_postal_code":
            data.get("client_postal_code"),
            "client_city":
            data.get("client_city"),
            "client_country":
            data.get("client_country"),
            "client_email":
            data.get("client_email"),
            "client_vat_id":
            data.get("client_vat_id"),
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

            # Отправляем PDF пользователю
            sent_msg = await update.effective_message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename=filename,
                caption=caption)

            # Сохраняем PDF в БД
            pdf_db_id = save_pdf_to_db(user_id=user_id,
                                       document_id=str(invoice_id),
                                       document_type='invoice',
                                       pdf_bytes=pdf_bytes,
                                       filename=filename)

            # Обновляем invoice с ID файла
            if pdf_db_id:
                db.update_invoice(invoice_id, {'pdf_file_id': pdf_db_id})

            # Кнопки: Email и Донат
            keyboard = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📧 Per E-Mail senden",
                        callback_data=f"email_invoice_{invoice_id}")
                ],
                 [
                     InlineKeyboardButton(
                         "☕ Sag Danke (PayPal)",
                         url="https://paypal.me/DEIN_PAYPAL_USERNAME")
                 ]])

            await update.effective_message.reply_text(
                "✅ Rechnung gespeichert und versendet!",
                reply_markup=get_main_keyboard())

            await update.effective_message.reply_text(
                "🙏 Gefällt Ihnen der Bot?\n"
                "Unterstützen Sie die Entwicklung mit einem kleinen Beitrag!",
                reply_markup=keyboard)

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
    if not profile.get('gdpr_consent') or not profile.get(
            'accepted_terms') or not profile.get('company_name'):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ Firmendaten eingeben",
                                 callback_data="goto_settings")
        ]])

        missing = []
        if not profile.get('gdpr_consent'):
            missing.append("• GDPR-Zustimmung")
        if not profile.get('accepted_terms'):
            missing.append("• Nutzungsbedingungen (AGB)")
        if not profile.get('company_name'):
            missing.append("• Firmendaten (Name, Adresse, etc.)")

        await update.message.reply_text(
            "⚠️ **Profil unvollständig**\n\n"
            "Bevor Sie Rechnungen erstellen können, müssen Sie:\n\n" +
            "\n".join(missing) + "\n\n"
            "Bitte gehen Sie zu den Einstellungen und füllen Sie "
            "Ihr Firmenprofil aus.",
            parse_mode='Markdown',
            reply_markup=keyboard)
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
    if not profile.get('gdpr_consent') or not profile.get(
            'accepted_terms') or not profile.get('company_name'):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ Firmendaten eingeben",
                                 callback_data="goto_settings")
        ]])

        missing = []
        if not profile.get('gdpr_consent'):
            missing.append("• GDPR-Zustimmung")
        if not profile.get('accepted_terms'):
            missing.append("• Nutzungsbedingungen (AGB)")
        if not profile.get('company_name'):
            missing.append("• Firmendaten (Name, Adresse, etc.)")

        await update.message.reply_text(
            "⚠️ **Profil unvollständig**\n\n"
            "Bevor Sie Angebote erstellen können, müssen Sie:\n\n" +
            "\n".join(missing) + "\n\n"
            "Bitte gehen Sie zu den Einstellungen und füllen Sie "
            "Ihr Firmenprofil aus.",
            parse_mode='Markdown',
            reply_markup=keyboard)
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
    if txt == "📄 Rechnungen":
        context.user_data['current_menu'] = 'invoices'
        await update.message.reply_text("📄 Rechnungen:",
                                        reply_markup=get_invoices_submenu())

    elif txt == "📋 Angebote":
        context.user_data['current_menu'] = 'offers'
        await update.message.reply_text("📋 Angebote:",
                                        reply_markup=get_offers_submenu())

    elif txt == "⚙️ Einstellungen":
        context.user_data['current_menu'] = 'settings'
        await update.message.reply_text("⚙️ Einstellungen:",
                                        reply_markup=get_settings_submenu())

    # ===== ПОДМЕНЮ СЧЕТОВ =====
    elif txt == "➕ Neue Rechnung":
        await rechnung_erstellen_start(update, context)
    elif txt == "📊 Liste" and context.user_data.get(
            'current_menu') == 'invoices':
        await show_invoices_list(update, context)
    elif txt == "🔢 Nummerierung" and context.user_data.get(
            'current_menu') == 'invoices':
        await show_invoice_numbering_settings(update, context)

    # ===== ПОДМЕНЮ ОФФЕРОВ =====
    elif txt == "➕ Neues Angebot":
        await angebot_erstellen_start(update, context)
    elif txt == "📄 Liste" and context.user_data.get(
            'current_menu') == 'offers':
        await show_offers_list(update, context)
    elif txt == "🔢 Nummerierung" and context.user_data.get(
            'current_menu') == 'offers':
        await show_offer_numbering_settings(update, context)

    # ===== ПОДМЕНЮ НАСТРОЕК =====
    elif txt == "🏢 Firmendaten":
        await settings_command(update, context)
    elif txt == "🔒 Datenschutz":
        await show_privacy_menu(update, context)
    elif txt == "🗑️ Daten löschen":
        await show_deletion_menu(update, context)
    elif txt == "💬 Feedback senden":
        await show_feedback_form(update, context)

    # ===== НАЗАД =====
    elif txt == "🔙 Zurück":
        await update.message.reply_text("Hauptmenü:",
                                        reply_markup=get_main_keyboard())

    else:
        await update.message.reply_text(
            "Unbekannter Befehl. Bitte verwenden Sie die Buttons.",
            reply_markup=get_main_keyboard())


# ----------------------------
# Списки документов
# ----------------------------
async def show_invoices_list(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Показать список счетов"""
    user_id = update.effective_user.id

    # Получаем данные
    invoices = db.get_invoices(user_id, limit=20)  # Ограничим до 20 последних
    limits = db.get_user_limits(user_id)

    if not invoices:
        await update.message.reply_text(
            "📊 У вас пока нет счетов.\n\n"
            "Создайте первый счёт с помощью кнопки '➕ Neue Rechnung'",
            reply_markup=get_invoices_submenu())
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

        date = inv.get('invoice_date',
                       '')[:10] if inv.get('invoice_date') else '-'
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

    await update.message.reply_text(text,
                                    parse_mode='Markdown',
                                    reply_markup=get_invoices_submenu())


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
            reply_markup=get_offers_submenu())
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

    await update.message.reply_text(text,
                                    parse_mode='Markdown',
                                    reply_markup=get_offers_submenu())


# ----------------------------
# Копирование документов
# ----------------------------
async def handle_copy_invoice(update: Update,
                              context: ContextTypes.DEFAULT_TYPE,
                              invoice_id: str):
    """Обработка копирования счёта"""
    user_id = update.effective_user.id

    new_id = db.copy_invoice(invoice_id, user_id)
    if new_id:
        await update.effective_message.reply_text(
            "✅ Rechnung wurde kopiert!\n\nSie können sie jetzt bearbeiten und speichern."
        )
        # Можно открыть форму редактирования
    else:
        await update.effective_message.reply_text(
            "❌ Fehler beim Kopieren der Rechnung.")


async def handle_copy_offer(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            offer_id: str):
    """Обработка копирования оффера"""
    user_id = update.effective_user.id

    new_id = db.copy_offer(offer_id, user_id)
    if new_id:
        await update.effective_message.reply_text(
            "✅ Angebot wurde kopiert!\n\nSie können es jetzt bearbeiten und speichern."
        )
    else:
        await update.effective_message.reply_text(
            "❌ Fehler beim Kopieren des Angebots.")


# ----------------------------
# Удаление всех данных
# ----------------------------
async def show_privacy_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """Меню Datenschutz - только GDPR и Terms"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    gdpr = profile.get('gdpr_consent', False)
    gdpr_date = profile.get('gdpr_consent_date', '-')
    terms = profile.get('accepted_terms', False)
    terms_date = profile.get('accepted_terms_date', '-')

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📜 Datenschutzerklärung lesen",
                                 callback_data="show_privacy_policy")
        ],
        [
            InlineKeyboardButton("📋 Nutzungsbedingungen lesen",
                                 callback_data="show_terms")
        ],
        [
            InlineKeyboardButton(
                "✅ GDPR akzeptieren" if not gdpr else "✓ GDPR akzeptiert",
                callback_data="accept_gdpr")
        ],
        [
            InlineKeyboardButton(
                "✅ AGB akzeptieren" if not terms else "✓ AGB akzeptiert",
                callback_data="accept_terms")
        ],
    ])

    await update.message.reply_text(
        f"🔒 Datenschutz\n\n"
        f"📊 Status:\n"
        f"• GDPR: {'✅' if gdpr else '❌'} {f'({gdpr_date})' if gdpr else ''}\n"
        f"• AGB: {'✅' if terms else '❌'} {f'({terms_date})' if terms else ''}",
        reply_markup=keyboard)


async def show_deletion_menu(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Меню удаления данных - отдельно от Datenschutz"""
    user_id = update.effective_user.id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Rechnungen löschen",
                                 callback_data="delete_invoices")
        ],
        [
            InlineKeyboardButton("🗑️ Angebote löschen",
                                 callback_data="delete_offers")
        ],
        [
            InlineKeyboardButton("⚠️ ALLE DATEN LÖSCHEN",
                                 callback_data=f"confirm_delete_{user_id}")
        ],
    ])

    await update.message.reply_text(
        "🗑️ Daten löschen\n\n"
        "⚠️ Achtung: Gelöschte Daten können nicht wiederhergestellt werden!\n\n"
        "Wählen Sie eine Option:",
        reply_markup=keyboard)


async def delete_all_data_handler(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Обработка удаления всех данных пользователя"""
    user_id = update.effective_user.id

    # Подтверждение
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ ALLE DATEN LÖSCHEN",
                             callback_data=f"confirm_delete_{user_id}")
    ], [InlineKeyboardButton("🔙 Abbrechen", callback_data="cancel_delete")]])

    await update.message.reply_text(
        "⚠️ ACHTUNG!\n\n"
        "Sie sind dabei, ALLE Ihre Daten zu löschen:\n"
        "• Alle Rechnungen\n"
        "• Alle Angebote\n"
        "• Alle Kunden\n"
        "• Alle gespeicherten Dateien\n\n"
        "Diese Aktion kann nicht rückgängig gemacht werden!\n\n"
        "Sind Sie sicher?",
        reply_markup=keyboard)


async def handle_confirm_delete(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    await query.edit_message_text("⏳ Lösche Daten...")

    stats = db.delete_all_user_data(user_id)

    await query.edit_message_text("✅ Alle Daten wurden gelöscht!\n\n"
                                  f"Gelöscht:\n"
                                  f"• Rechnungen: {stats.get('invoices', 0)}\n"
                                  f"• Angebote: {stats.get('offers', 0)}\n"
                                  f"• Kunden: {stats.get('clients', 0)}\n"
                                  f"• Dateien: {stats.get('files', 0)}")


async def handle_delete_invoices(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Удаление только счетов"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "❌ JA, LÖSCHEN",
            callback_data=f"confirm_delete_invoices_{user_id}")
    ], [InlineKeyboardButton("🔙 Abbrechen", callback_data="cancel_delete")]])

    await query.edit_message_text(
        "⚠️ Alle Rechnungen löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden!",
        reply_markup=keyboard)


async def handle_delete_offers(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Удаление только офферов"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ JA, LÖSCHEN",
                             callback_data=f"confirm_delete_offers_{user_id}")
    ], [InlineKeyboardButton("🔙 Abbrechen", callback_data="cancel_delete")]])

    await query.edit_message_text(
        "⚠️ Alle Angebote löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden!",
        reply_markup=keyboard)


async def handle_confirm_delete_invoices(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления счетов"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    await query.edit_message_text("⏳ Lösche Rechnungen...")

    # Удаляем только счета
    count = db.delete_user_invoices(user_id)

    await query.edit_message_text(f"✅ Gelöscht: {count} Rechnungen")


async def handle_confirm_delete_offers(update: Update,
                                       context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления офферов"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    await query.edit_message_text("⏳ Lösche Angebote...")

    # Удаляем только офферы
    count = db.delete_user_offers(user_id)

    await query.edit_message_text(f"✅ Gelöscht: {count} Angebote")


async def handle_cancel_delete(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Отмена удаления"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Abgebrochen")


# ----------------------------
# Архив документов
# ----------------------------
async def request_documents_archive(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
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
            "Dies kann einige Minuten dauern.")

        # TODO: Запустить фоновую задачу создания архива
        # Пока заглушка
    else:
        await update.message.reply_text("❌ Fehler beim Erstellen der Anfrage.")


# ----------------------------
# Обратная связь
# ----------------------------
async def show_feedback_form(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Показать форму обратной связи"""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Vorschlag",
                                 callback_data="feedback_feature")
        ],
        [InlineKeyboardButton("🐛 Bug melden", callback_data="feedback_bug")],
        [
            InlineKeyboardButton("🤝 Zusammenarbeit",
                                 callback_data="feedback_cooperation")
        ],
        [
            InlineKeyboardButton("💬 Allgemein",
                                 callback_data="feedback_general")
        ],
    ])

    await update.message.reply_text(
        "📧 Kontakt zum Entwickler\n\n"
        "Wählen Sie eine Kategorie:",
        reply_markup=keyboard)


async def handle_feedback_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
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
        "Bitte schreiben Sie Ihre Nachricht:")


# ----------------------------
# PayPal "Спасибо"
# ----------------------------
async def show_donation_message(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Показать сообщение с благодарностью и ссылкой на PayPal"""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("☕ Sag Danke mit PayPal",
                                 url="https://paypal.me/t1@ukr.net")
        ],
    ])

    await update.effective_message.reply_text(
        "🎉 Rechnung erfolgreich erstellt!\n\n"
        "💚 Wenn Ihnen dieser Service geholfen hat, können Sie dem Entwickler ein Dankeschön senden:",
        reply_markup=keyboard)


# ----------------------------
# Upgrade на платную версию
# ----------------------------
async def show_upgrade_info(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
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
        parse_mode='Markdown')


# ----------------------------
# Настройки нумерации
# ----------------------------
async def show_numbering_settings(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Объединённая форма настройки нумерации счетов И офферов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")

    # Используем общую форму для обеих нумераций
    url = f"{BASE_URL}/invoice_numbering.html?data={urllib.parse.quote(encoded)}&mode=combined"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("🔢 Nummerierung öffnen", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

    inv_prefix = profile.get('invoice_number_prefix', 'RE-')
    inv_next = profile.get('next_invoice_number', 1)
    inv_format = profile.get('invoice_number_format', 4)

    off_prefix = profile.get('offer_number_prefix', 'AN-')
    off_next = profile.get('next_offer_number', 1)
    off_format = profile.get('offer_number_format', 4)

    await update.message.reply_text(
        f"🔢 Nummerierung\n\n"
        f"📄 Rechnungen:\n"
        f"• Präfix: {inv_prefix}\n"
        f"• Nächste: {inv_next}\n"
        f"• Beispiel: {inv_prefix}{str(inv_next).zfill(inv_format)}\n\n"
        f"📋 Angebote:\n"
        f"• Präfix: {off_prefix}\n"
        f"• Nächste: {off_next}\n"
        f"• Beispiel: {off_prefix}{str(off_next).zfill(off_format)}",
        reply_markup=keyboard)


async def show_invoice_numbering_settings(update: Update,
                                          context: ContextTypes.DEFAULT_TYPE):
    """Показать форму настройки нумерации счетов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")

    url = f"{BASE_URL}/invoice_numbering.html?data={urllib.parse.quote(encoded)}"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("🔢 Nummerierung öffnen", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

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
        reply_markup=keyboard)


async def show_offer_numbering_settings(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """Показать форму настройки нумерации офферов"""
    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    data_json = json.dumps(profile, default=str)
    encoded = base64.urlsafe_b64encode(data_json.encode()).decode().strip("=")

    url = f"{BASE_URL}/offer_numbering.html?data={urllib.parse.quote(encoded)}"

    keyboard = ReplyKeyboardMarkup([[
        KeyboardButton("🔢 Nummerierung öffnen", web_app=WebAppInfo(url=url))
    ], [KeyboardButton("🔙 Zurück")]],
                                   resize_keyboard=True)

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
        reply_markup=keyboard)


# ----------------------------
# Правовая информация / защита
# ----------------------------
async def show_legal_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Impressum + rechtliche Hinweise"""
    text = """⚖️ **IMPRESSUM**

**Anbieter:**
[Dein Name/Firma]
[Straße Hausnummer]
[PLZ Stadt]
[Land]

**Kontakt:**
E-Mail: [Deine E-Mail]
Telefon: [Deine Telefonnummer]

**Registereintrag:** (falls GmbH/UG)
Handelsregister: [Amtsgericht]
Registernummer: [HRB...]

**Umsatzsteuer-ID:**
[Deine USt-IdNr]

**Verantwortlich für Inhalte:**
[Dein Name]

**Streitschlichtung:**
Wir sind nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.

**Haftungsausschluss:**
Trotz sorgfältiger Prüfung übernehmen wir keine Haftung für:
• Richtigkeit der Dokumente
• Steuerrechtliche Konformität
• Vollständigkeit der Rechnungen
• Schäden durch fehlerhafte Nutzung

Sie sind selbst verantwortlich für die Überprüfung aller Dokumente vor Versand an Kunden.
"""

    await update.message.reply_text(text, parse_mode='Markdown')


async def handle_toggle_terms(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Обработка принятия/отклонения условий"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    profile = db.get_profile(user_id) or {}

    current_status = profile.get('accepted_terms', False)
    new_status = not current_status

    update_data = {
        'accepted_terms': new_status,
        'accepted_terms_date':
        datetime.now().isoformat() if new_status else None
    }

    if db.update_profile(user_id, update_data):
        status_text = "✅ akzeptiert" if new_status else "❌ zurückgezogen"
        await query.edit_message_text(
            f"Status: Nutzungsbedingungen {status_text}.\n\n"
            "Sie können diese Einstellung jederzeit ändern.")
    else:
        await query.edit_message_text("❌ Fehler beim Aktualisieren.")


async def handle_goto_settings(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
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


# ----------------------------
# Сохранение PDF в БД
# ----------------------------
def save_pdf_to_db(user_id: int, document_id: str, document_type: str,
                   pdf_bytes: bytes, filename: str):
    """Сохранение PDF в таблицу document_files"""
    try:
        import base64

        file_data = {
            'user_id': user_id,
            'document_id': document_id,
            'document_type': document_type,
            'file_data':
            base64.b64encode(pdf_bytes).decode('utf-8'),  # Base64 для bytea
            'file_name': filename,
            'file_size': len(pdf_bytes),
            'mime_type': 'application/pdf'
        }

        # ПРАВИЛЬНО: db.client
        response = db.client.table('document_files').insert(
            file_data).execute()

        logger.info(
            f"PDF saved to DB: {filename}, size: {len(pdf_bytes)} bytes")
        return response.data[0]['id'] if response.data else None

    except Exception as e:
        logger.error(f"Error saving PDF to DB: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def send_pdf_to_email(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            pdf_bytes: bytes, filename: str, user_id: int):
    """Отправка PDF на email пользователя"""
    profile = db.get_profile(user_id) or {}
    email = profile.get('email')

    if not email:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ E-Mail hinzufügen",
                                 callback_data="goto_settings")
        ]])
        await update.effective_message.reply_text(
            "❌ Keine E-Mail-Adresse hinterlegt!\n"
            "Bitte fügen Sie Ihre E-Mail in den Einstellungen hinzu.",
            reply_markup=keyboard)
        return False

    # TODO: SMTP Integration (SendGrid, AWS SES, etc.)
    # import smtplib
    # from email.mime.multipart import MIMEMultipart
    # from email.mime.application import MIMEApplication

    await update.effective_message.reply_text(
        f"📧 Dokument-Versand an {email}...\n\n"
        f"⚠️ E-Mail-Funktion noch in Entwicklung!\n"
        f"Bitte laden Sie das Dokument aus dem Chat herunter.")
    return True


# ----------------------------
# GDPR & Legal
# ----------------------------
async def accept_gdpr_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Принятие GDPR"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    from datetime import datetime
    db.update_profile(
        user_id, {
            'gdpr_consent': True,
            'gdpr_consent_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    await query.edit_message_text("✅ GDPR-Zustimmung erteilt!")


async def accept_terms_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Принятие Terms of Service"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    from datetime import datetime
    db.update_profile(
        user_id, {
            'accepted_terms': True,
            'accepted_terms_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    await query.edit_message_text("✅ AGB akzeptiert!")


async def show_privacy_policy_callback(update: Update,
                                       context: ContextTypes.DEFAULT_TYPE):
    """Показать политику конфиденциальности (GDPR compliant)"""
    query = update.callback_query
    await query.answer()

    text = """📜 **DATENSCHUTZERKLÄRUNG (DSGVO)**

**1. Verantwortlicher**
[Dein Name/Firma]
[Deine Adresse]
E-Mail: [Deine E-Mail]

**2. Erhobene Daten**
Wir verarbeiten folgende Daten:
• Firmendaten (Name, Adresse, Steuernummern)
• Kundendaten (Name, Adresse)
• Rechnungsdaten (Positionen, Beträge)
• Telegram User-ID (technisch erforderlich)

**3. Rechtsgrundlage (Art. 6 Abs. 1 DSGVO)**
• Einwilligung (Art. 6 Abs. 1 lit. a)
• Vertragserfüllung (Art. 6 Abs. 1 lit. b)

**4. Speicherdauer**
• Rechnungsdaten: 10 Jahre (§147 AO)
• Sonstige Daten: bis zur Löschung durch Sie

**5. Ihre Rechte**
• Auskunft (Art. 15 DSGVO)
• Berichtigung (Art. 16 DSGVO)
• Löschung (Art. 17 DSGVO)
• Datenübertragbarkeit (Art. 20 DSGVO)
• Widerruf der Einwilligung (Art. 7 Abs. 3 DSGVO)
• Beschwerde bei Aufsichtsbehörde (Art. 77 DSGVO)

**6. Datenweitergabe**
• Keine Weitergabe an Dritte
• Speicherung auf Supabase (EU-Server)

**7. Kontakt Datenschutz**
E-Mail: [Deine E-Mail]
"""

    await query.edit_message_text(text, parse_mode='Markdown')


async def show_terms_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Показать условия использования (AGB)"""
    query = update.callback_query
    await query.answer()

    text = """📋 **ALLGEMEINE GESCHÄFTSBEDINGUNGEN (AGB)**

**§1 Geltungsbereich**
Diese AGB gelten für die Nutzung des RechnungAgent Telegram-Bots.

**§2 Leistungsumfang**
(1) Der Bot dient zur Erstellung von Rechnungen und Angeboten
(2) Erstellung von ZUGFeRD-konformen XML-Dateien
(3) Speicherung Ihrer Daten

**§3 Pflichten des Nutzers**
(1) Sie sind für die Richtigkeit Ihrer Daten verantwortlich
(2) Sie müssen die gesetzlichen Anforderungen beachten (UStG, AO)
(3) Missbrauch ist untersagt

**§4 Haftung**
(1) Wir haften nicht für fehlerhafte Rechnungen
(2) Sie sind selbst verantwortlich für steuerliche Korrektheit
(3) Bei grober Fahrlässigkeit haften wir nach gesetzlichen Bestimmungen

**§5 Kündigung**
(1) Sie können den Service jederzeit beenden
(2) Löschung aller Daten über die Bot-Funktion möglich
(3) Rechnungsdaten müssen ggf. 10 Jahre aufbewahrt werden (§147 AO)

**§6 Änderungen**
Änderungen dieser AGB werden Ihnen mitgeteilt.

**§7 Gerichtsstand**
Es gilt deutsches Recht.

**Stand:** Februar 2026
"""

    await query.edit_message_text(text, parse_mode='Markdown')
