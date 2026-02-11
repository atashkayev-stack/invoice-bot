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
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x).replace(",", "."))
    except Exception:
        return Decimal("0")


def _m(x: Decimal) -> Decimal:
    return x.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class PDFFromTemplateV2:

    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir

    def generate_invoice_pdf(self,
                             data: dict,
                             profile: dict,
                             with_xml: bool = False) -> io.BytesIO:

        template_path = os.path.join(self.templates_dir,
                                     "invoice_template.html")
        template_data = self._prepare_invoice_data(data, profile)

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())

        try:
            html = template.render(**template_data)
        except Exception:
            logger.exception("Jinja2 render error")
            raise

        pdf_bytes = self._html_to_pdf(html)
        return io.BytesIO(pdf_bytes)

    def _html_to_pdf(self, html_string: str) -> bytes:
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
        КАНОН:
        - totals / vat_breakdown берём ТОЛЬКО из БД
        - PDF не считает НДС
        """

        items = data.get("items", []) or []
        vat_breakdown = data.get("vat_breakdown", []) or []
        vat_mode = (data.get("vat_mode") or "standard").lower()

        # -------- Items ----------
        prepared_items = []
        subtotal = Decimal("0")

        for item in items:
            qty = _d(item.get("quantity", 1))
            unit_price = _d(item.get("unit_price", 0))
            line_total = _d(item.get("total_price", 0))
            subtotal += line_total

            prepared_items.append({
                "description": item.get("description", ""),
                "quantity": f"{_m(qty):.2f}",
                "unit": item.get("unit", "Stk"),
                "price": f"{_m(unit_price):.2f}",
                "vat_rate": f"{_d(item.get('vat_rate', 0)):.0f}",
                "total": f"{_m(line_total):.2f}",
            })

        subtotal = _m(subtotal)

        # -------- Totals (ONLY DB) ----------
        total_net = _m(_d(data.get("amount", 0)))
        total_vat = _m(_d(data.get("vat_amount", 0)))
        total_gross = _m(_d(data.get("total", 0)))

        # -------- VAT breakdown (CANON) ----------
        vat_rows = []
        for row in vat_breakdown:
            vat_rows.append({
                "vat_rate":
                f"{_d(row.get('vat_rate')):.0f}",
                "taxable_amount":
                f"{_m(_d(row.get('taxable_amount'))):.2f}",
                "vat_amount":
                f"{_m(_d(row.get('vat_amount'))):.2f}",
                "vat_category_code":
                row.get("vat_category_code") or "",
                "exemption_reason":
                row.get("exemption_reason") or "",
            })

        has_vat_breakdown = len(vat_rows) > 0

        # -------- Discounts / shipping (display only) ----------
        discount_percentage = _d(data.get("discount_percentage", 0))
        discount_amount = _d(data.get("discount_amount", 0))
        shipping_cost = _d(data.get("shipping_cost", 0))

        # -------- Skonto ----------
        skonto_percentage = _d(data.get("skonto_percentage", 0))
        skonto_days = int(_d(data.get("skonto_days", 0)))
        skonto_total = None
        skonto_date = None

        if skonto_percentage > 0 and skonto_days > 0:
            skonto_total = _m(total_gross *
                              (Decimal("1") - skonto_percentage / 100))
            try:
                invoice_date = datetime.strptime(str(data.get("invoice_date")),
                                                 "%Y-%m-%d")
                skonto_date = (
                    invoice_date +
                    timedelta(days=skonto_days)).strftime("%d.%m.%Y")
            except Exception:
                pass

        # -------- Client address ----------
        addr = (f"{data.get('client_street', '')}, "
                f"{data.get('client_postal_code', '')} "
                f"{data.get('client_city', '')}").strip(", ")

        return {
            # Sender
            "sender_company":
            profile.get("company_name", ""),
            "sender_street":
            profile.get("street", ""),
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
            "client_name":
            data.get("client_name", ""),
            "client_street":
            data.get("client_street", ""),
            "client_postal_code":
            data.get("client_postal_code", ""),
            "client_city":
            data.get("client_city", ""),
            "client_country":
            data.get("client_country", ""),
            "client_address":
            addr,
            "client_email":
            data.get("client_email"),
            "client_vat_id":
            data.get("client_vat_id"),
            "customer_id":
            data.get("customer_id"),

            # Document
            "invoice_number":
            data.get("invoice_number") or data.get("number"),
            "invoice_date":
            self._format_date(data.get("invoice_date")),
            "delivery_date":
            self._format_date(data.get("delivery_date")),
            "due_date":
            self._format_date(data.get("due_date")),
            "purchase_order":
            data.get("purchase_order"),
            "contract_number":
            data.get("contract_number"),
            "project_number":
            data.get("project_number"),
            "vat_mode":
            vat_mode,

            # Profile (ADDED!)
            "profile":
            profile,

            # Items
            "items":
            prepared_items,

            # Totals
            "subtotal":
            f"{subtotal:.2f}",
            "discount_percentage":
            float(discount_percentage),
            "discount_amount":
            float(discount_amount),
            "shipping_cost":
            float(shipping_cost),
            "amount":
            float(total_net),
            "total_net":
            float(total_net),
            "total_vat":
            float(total_vat),
            "total":
            float(total_gross),
            "total_gross":
            float(total_gross),

            # VAT breakdown (KEY)
            "vat_breakdown":
            vat_rows,
            "vat_rows":
            vat_rows,
            "has_vat_breakdown":
            has_vat_breakdown,

            # Skonto
            "skonto_percentage":
            float(skonto_percentage),
            "skonto_days":
            skonto_days,
            "skonto_total":
            f"{skonto_total:.2f}" if skonto_total else None,
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
        if not date_str:
            return None
        try:
            return datetime.strptime(str(date_str),
                                     "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            return str(date_str)
