# src/pdf_from_template_v2.py
"""pdf_from_template_v2.py - PDF через шаблоны + PDF/A-3"""
import io
import os
import logging
from jinja2 import Template
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

MONEY_Q = Decimal("0.01")


def _d(x) -> Decimal:
    """Safe Decimal converter for numeric strings / floats / ints / None."""
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x).replace(",", "."))
    except Exception:
        return Decimal("0")


def _m(x: Decimal) -> Decimal:
    """Money rounding to 2 decimals."""
    return x.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class PDFFromTemplateV2:

    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir

    def generate_invoice_pdf(self,
                             data: dict,
                             profile: dict,
                             with_xml: bool = False) -> io.BytesIO:
        """Генерация PDF из invoice_template.html"""
        template_path = os.path.join(self.templates_dir,
                                     "invoice_template.html")

        template_data = self._prepare_invoice_data(data, profile)

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())

        # Рендерим 1 раз + расширенный дебаг типов
        try:
            html = template.render(**template_data)
        except TypeError as e:
            logger.error(
                "!!! СТОП !!! Ошибка типов в Jinja2. Проверяем переменные:")

            fields_to_check = [
                "discount_amount", "discount_percentage", "subtotal",
                "shipping_cost", "shipping_vat_rate", "total_net", "total_vat",
                "total_gross", "vat_rate", "vat_mode"
            ]
            for field in fields_to_check:
                val = template_data.get(field)
                logger.error(
                    f"Поле '{field}': значение={val}, тип={type(val)}")

            # + проверка items
            items = template_data.get("items", [])
            logger.error(f"items count = {len(items)}")
            if items:
                for i, it in enumerate(items[:5], 1):
                    logger.error(
                        f"item[{i}] keys={list(it.keys())} values={it}")

            raise

        pdf_bytes = self._html_to_pdf(html)

        if with_xml:
            from xml_generator_v2 import XMLGeneratorV2, embed_xml_in_pdf
            xml_gen = XMLGeneratorV2()
            xml_string = xml_gen.generate_zugferd_xml(data, profile)
            pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)

        return io.BytesIO(pdf_bytes)

    def _html_to_pdf(self, html_string: str) -> bytes:
        """HTML → PDF через xhtml2pdf"""
        result = io.BytesIO()
        pisa_status = pisa.CreatePDF(
            io.BytesIO(html_string.encode("utf-8")),
            dest=result,
            encoding="utf-8",
        )

        if pisa_status.err:
            raise Exception(f"PDF error: {pisa_status.err}")

        result.seek(0)
        return result.getvalue()

    def _prepare_invoice_data(self, data: dict, profile: dict) -> dict:
        """
        Подготовка данных для шаблона.

        КАНОН:
        - totals берём из БД: amount (net), vat_amount, total (gross)
        - item.total_price = line_net
        - item.unit_price обязателен для PDF-таблицы (если нет — ставим 0)
        """

        items = data.get("items", []) or []
        vat_per_item = bool(data.get("vat_per_item", False))
        vat_mode = (data.get("vat_mode") or "standard").strip().lower()

        # global vat rate: только для отображения
        global_vat = _d(
            data.get("global_vat_rate", profile.get("default_vat_rate", 19)))

        # ---- Subtotal: сумма line_net (total_price = line_net)
        subtotal = Decimal("0")
        for item in items:
            subtotal += _d(item.get("total_price", 0))
        subtotal = _m(subtotal)

        # ---- Discount: у тебя "discount_percentage" может не существовать.
        # Делаем мягко: если есть percent — используем, иначе amount.
        discount_percent = _d(data.get("discount_percentage", 0))
        discount_amount = _d(data.get("discount_amount", 0))

        if discount_percent > 0:
            discount_amount = _m(subtotal * discount_percent / Decimal("100"))
        else:
            discount_amount = _m(discount_amount)

        # ---- Shipping
        shipping_cost = _m(_d(data.get("shipping_cost", 0)))
        # Если режим не standard — ставка доставки 0 (чтобы PDF не вводил в заблуждение)
        if vat_mode != "standard":
            shipping_vat_rate = Decimal("0")
        else:
            shipping_vat_rate = _d(data.get("shipping_vat_rate", global_vat))

        # ---- Totals from DB canon
        total_net_db = _m(_d(data.get("amount", 0)))
        total_vat_db = _m(_d(data.get("vat_amount", 0)))  # FIX: vat_amount
        total_gross_db = _m(_d(data.get("total", 0)))

        # ---- Skonto (опционально)
        skonto_percentage = _d(data.get("skonto_percentage", 0))
        skonto_days = int(_d(data.get("skonto_days", 0)))
        skonto_total = Decimal("0")
        skonto_date = None

        if skonto_percentage > 0 and skonto_days > 0:
            skonto_total = _m(
                total_gross_db *
                (Decimal("1") - skonto_percentage / Decimal("100")))
            try:
                invoice_date = datetime.strptime(str(data.get("invoice_date")),
                                                 "%Y-%m-%d")
                skonto_date = (
                    invoice_date +
                    timedelta(days=skonto_days)).strftime("%d.%m.%Y")
            except Exception:
                skonto_date = None

        # ---- Items for template
        prepared_items = []
        for item in items:
            qty = _d(item.get("quantity", 1))
            unit_price = _d(item.get("unit_price", 0))  # важно: никогда None
            line_total = _d(item.get("total_price", 0))  # line net by canon

            rate_raw = item.get("vat_rate", None)
            rate_dec = global_vat if rate_raw is None else _d(rate_raw)

            prepared_items.append({
                "description":
                item.get("description", "") or "",
                "quantity":
                f"{_m(qty):.2f}",
                "unit":
                item.get("unit", "Stk") or "Stk",
                "price":
                f"{_m(unit_price):.2f}",
                "vat_rate":
                f"{rate_dec:.0f}",
                "total":
                f"{_m(line_total):.2f}",
            })

        # ---- Client address fallback:
        # если пришло из БД как одной строкой (client_address) — используем его
        addr_parts = (
            f"{data.get('client_street', '')}, {data.get('client_postal_code', '')} {data.get('client_city', '')}"
        ).strip(", ").strip()
        client_address = addr_parts if addr_parts else (
            data.get("client_address") or "")

        return {
            # Sender
            "sender_company":
            profile.get("company_name", "") or "",
            "sender_street":
            profile.get("street", "") or "",
            "sender_city":
            f"{profile.get('postal_code', '')} {profile.get('city', '')}".
            strip(),
            "sender_email":
            profile.get("email"),
            "sender_tax_id":
            profile.get("tax_id"),
            "sender_vat_id":
            profile.get("vat_id"),
            "sender_iban":
            profile.get("iban"),
            "sender_bic":
            profile.get("bic"),
            "bank_name":
            profile.get("bank_name"),

            # Client
            "client_company":
            data.get("client_name", "") or "",
            "client_address":
            client_address,
            "client_email":
            data.get("client_email"),
            "customer_id":
            data.get("customer_id"),

            # Document
            "invoice_number":
            data.get("invoice_number") or data.get("number") or "RE-0001",
            "invoice_date":
            self._format_date(data.get("invoice_date")),
            "delivery_date":
            self._format_date(data.get("delivery_date")),
            "due_date":
            self._format_date(data.get("due_date")),
            "purchase_order":
            data.get("purchase_order") or data.get("purchase_order_number"),
            "contract_number":
            data.get("contract_number"),
            "project_number":
            data.get("project_number"),
            "vat_mode":
            vat_mode,

            # Items
            "items":
            prepared_items,
            "vat_per_item":
            vat_per_item,

            # Totals (strings for template)
            "subtotal":
            f"{subtotal:.2f}",
            "discount_percentage":
            float(discount_percent) if discount_percent else 0,
            "discount_amount":
            float(discount_amount),
            "shipping_cost":
            float(shipping_cost),
            "total_net":
            float(total_net_db),
            "total_vat":
            float(total_vat_db),
            "total_gross":
            float(total_gross_db),

            # Для строки "MwSt (X%)": только если vat_mode == standard и vat_per_item == False
            # (если vat_per_item=True, в шаблоне всё равно печатаем VAT по строкам)
            "vat_rate":
            f"{global_vat:.0f}",

            # Skonto
            "skonto_percentage":
            float(skonto_percentage) if skonto_percentage else 0,
            "skonto_days":
            skonto_days,
            "skonto_total":
            f"{skonto_total:.2f}" if skonto_total > 0 else None,
            "skonto_date":
            skonto_date,

            # Shipping address
            "ship_to_name":
            data.get("ship_to_name"),
            "ship_to_street":
            data.get("ship_to_street"),
            "ship_to_postal_code":
            data.get("ship_to_postal_code"),
            "ship_to_city":
            data.get("ship_to_city"),

            # Notes
            "notes":
            data.get("notes"),
        }

    def _format_date(self, date_str):
        """Форматирование даты в DD.MM.YYYY"""
        if not date_str:
            return None
        try:
            return datetime.strptime(str(date_str),
                                     "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            return str(date_str)
