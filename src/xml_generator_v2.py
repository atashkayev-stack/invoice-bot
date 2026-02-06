# src/xml_generator_v2.py
"""xml_generator_v2.py - ZUGFeRD 2.4 COMPLIANT (Dec 2025)"""
import io
from datetime import datetime
from lxml import etree
from decimal import Decimal, ROUND_HALF_UP

# --- Decimal helpers (same idea as in PDF generator) ---
MONEY_Q = Decimal("0.01")
PERCENT_Q = Decimal("0.01")


def _d(x) -> Decimal:
    """Safe Decimal converter for numeric strings / floats / ints / None."""
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        s = str(x).strip()
        if not s:
            return Decimal("0")
        s = s.replace("%", "").replace(",", ".")
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _m(x: Decimal) -> Decimal:
    """Money rounding to 2 decimals."""
    return x.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _p(x: Decimal) -> Decimal:
    """Percent rounding to 2 decimals."""
    return x.quantize(PERCENT_Q, rounding=ROUND_HALF_UP)


class XMLGeneratorV2:

    def __init__(self):
        self.ns = {
            "rsm":
            "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
            "ram":
            "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
            "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
            "udt":
            "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
        }

    def generate_zugferd_xml(self, data: dict, profile: dict) -> str:
        # ЛОКАЛЬНЫЙ ИМПОРТ (чтобы избежать circular import error)
        try:
            from .handlers_v1 import get_vat_info
        except ImportError:
            from handlers_v1 import get_vat_info

        root = etree.Element(f"{{{self.ns['rsm']}}}CrossIndustryInvoice",
                             nsmap=self.ns)

        # Context
        ctx = etree.SubElement(
            root, f"{{{self.ns['rsm']}}}ExchangedDocumentContext")
        guide = etree.SubElement(
            ctx,
            f"{{{self.ns['ram']}}}GuidelineSpecifiedDocumentContextParameter")
        etree.SubElement(
            guide, f"{{{self.ns['ram']}}}ID"
        ).text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:extended"

        # Document
        doc = etree.SubElement(root, f"{{{self.ns['rsm']}}}ExchangedDocument")
        etree.SubElement(doc, f"{{{self.ns['ram']}}}ID").text = data.get(
            "invoice_number", "RE-0000")
        etree.SubElement(doc, f"{{{self.ns['ram']}}}TypeCode").text = "380"

        issue_dt = etree.SubElement(doc, f"{{{self.ns['ram']}}}IssueDateTime")
        dt_str = (data.get("invoice_date")
                  or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        etree.SubElement(issue_dt,
                         f"{{{self.ns['udt']}}}DateTimeString",
                         format="102").text = dt_str

        # Transaction
        tx = etree.SubElement(
            root, f"{{{self.ns['rsm']}}}SupplyChainTradeTransaction")

        # --- Core flags / canon totals (from DB, like in PDF generator) ---
        vat_mode = (data.get("vat_mode") or "standard").strip().lower()
        vat_per_item = bool(data.get("vat_per_item", False))

        items = data.get("items", []) or []
        vat_breakdown = data.get("vat_breakdown", []) or []

        # global vat rate: only as fallback/for display
        global_vat = _d(
            data.get("global_vat_rate", profile.get("default_vat_rate", 19)))

        # Canon totals
        total_net_db = _m(_d(data.get("amount", 0)))
        total_vat_db = _m(_d(data.get("vat_amount", data.get("tax_amount",
                                                             0))))
        total_gross_db = _m(_d(data.get("total", 0)))

        # --- LINE ITEMS ---
        for idx, item in enumerate(items, 1):
            line_item = etree.SubElement(
                tx, f"{{{self.ns['ram']}}}IncludedSupplyChainTradeLineItem")

            # Line ID
            assoc = etree.SubElement(
                line_item,
                f"{{{self.ns['ram']}}}AssociatedDocumentLineDocument")
            etree.SubElement(assoc, f"{{{self.ns['ram']}}}LineID").text = str(
                item.get("position_number") or idx)

            # Product
            prod = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedTradeProduct")
            etree.SubElement(prod,
                             f"{{{self.ns['ram']}}}Name").text = item.get(
                                 "description", "Position")

            # Agreement (Price)
            agr = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeAgreement")
            net_price = etree.SubElement(
                agr, f"{{{self.ns['ram']}}}NetPriceProductTradePrice")

            unit_price = _d(item.get("unit_price", 0))
            etree.SubElement(net_price,
                             f"{{{self.ns['ram']}}}ChargeAmount").text = (
                                 f"{_m(unit_price):.2f}")

            # Delivery (Quantity)
            deliv = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeDelivery")

            qty = _d(item.get("quantity", 1))
            unit_code = (item.get("unit_code") or "C62")
            billed_qty = etree.SubElement(
                deliv,
                f"{{{self.ns['ram']}}}BilledQuantity",
                unitCode=str(unit_code))
            billed_qty.text = f"{_m(qty):.2f}"

            # Settlement (Tax & Total)
            settle = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeSettlement")

            # --- line net: CANON from DB if present, else fallback qty*unit_price ---
            if item.get("total_price") is not None:
                line_net = _m(_d(item.get("total_price", 0)))
            else:
                line_net = _m(qty * unit_price)

            # Stored rate (always stored in DB even if non-standard)
            stored_rate = _d(item.get("vat_rate", global_vat))

            # Effective rate for XML output (0 if not standard)
            effective_rate = Decimal(
                "0") if vat_mode != "standard" else stored_rate

            vat_info = get_vat_info(profile,
                                    float(effective_rate),
                                    vat_mode=vat_mode)

            tax = etree.SubElement(settle,
                                   f"{{{self.ns['ram']}}}ApplicableTradeTax")
            etree.SubElement(tax, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
            etree.SubElement(tax, f"{{{self.ns['ram']}}}CategoryCode"
                             ).text = vat_info.get("category") or "S"
            etree.SubElement(
                tax, f"{{{self.ns['ram']}}}RateApplicablePercent").text = (
                    f"{_p(effective_rate):.2f}")

            summation = etree.SubElement(
                settle,
                f"{{{self.ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation"
            )
            etree.SubElement(summation, f"{{{self.ns['ram']}}}LineTotalAmount"
                             ).text = f"{line_net:.2f}"

        # --- HEADER TRADE AGREEMENT ---
        h_agr = etree.SubElement(
            tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeAgreement")

        # Seller
        seller = etree.SubElement(h_agr,
                                  f"{{{self.ns['ram']}}}SellerTradeParty")
        etree.SubElement(seller,
                         f"{{{self.ns['ram']}}}Name").text = profile.get(
                             "company_name", "My Company")

        # Buyer
        buyer = etree.SubElement(h_agr, f"{{{self.ns['ram']}}}BuyerTradeParty")
        etree.SubElement(buyer, f"{{{self.ns['ram']}}}Name").text = data.get(
            "client_name", "Client")

        # --- HEADER TRADE DELIVERY ---
        h_deliv = etree.SubElement(
            tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeDelivery")
        event = etree.SubElement(
            h_deliv, f"{{{self.ns['ram']}}}ActualDeliverySupplyChainEvent")
        occurrence = etree.SubElement(
            event, f"{{{self.ns['ram']}}}OccurrenceDateTime")
        deliv_date = (data.get("delivery_date") or data.get("invoice_date")
                      or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        etree.SubElement(occurrence,
                         f"{{{self.ns['udt']}}}DateTimeString",
                         format="102").text = deliv_date

        # --- HEADER TRADE SETTLEMENT ---
        h_settle = etree.SubElement(
            tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeSettlement")
        etree.SubElement(
            h_settle, f"{{{self.ns['ram']}}}InvoiceCurrencyCode").text = "EUR"

        # --- TAX BREAKDOWN (prefer DB breakdown if provided) ---
        if vat_breakdown:
            # invoice_vat_breakdown rows from DB:
            # vat_rate, taxable_amount, vat_amount, vat_category_code, exemption_reason
            for row in vat_breakdown:
                rate_stored = _d(row.get("vat_rate", 0))
                taxable = _m(_d(row.get("taxable_amount", 0)))
                vat_amt = _m(_d(row.get("vat_amount", 0)))

                effective_rate = Decimal(
                    "0") if vat_mode != "standard" else rate_stored

                # Category/reason from DB preferred, else from get_vat_info
                category = (row.get("vat_category_code") or "").strip()
                reason = (row.get("exemption_reason") or "").strip() or None
                if not category:
                    info = get_vat_info(profile,
                                        float(effective_rate),
                                        vat_mode=vat_mode)
                    category = info.get("category") or "S"
                    if not reason:
                        reason = info.get("reason")

                trade_tax = etree.SubElement(
                    h_settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
                etree.SubElement(
                    trade_tax, f"{{{self.ns['ram']}}}CalculatedAmount"
                ).text = (
                    f"{(vat_amt if vat_mode == 'standard' else Decimal('0')):.2f}"
                )
                etree.SubElement(trade_tax,
                                 f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
                etree.SubElement(
                    trade_tax,
                    f"{{{self.ns['ram']}}}BasisAmount").text = f"{taxable:.2f}"
                etree.SubElement(
                    trade_tax,
                    f"{{{self.ns['ram']}}}CategoryCode").text = category
                etree.SubElement(
                    trade_tax,
                    f"{{{self.ns['ram']}}}RateApplicablePercent").text = (
                        f"{_p(effective_rate):.2f}")

                if reason:
                    etree.SubElement(
                        trade_tax,
                        f"{{{self.ns['ram']}}}ExemptionReason").text = reason
        else:
            # Fallback: try build from items (without shipping buckets),
            # if still empty -> single block from totals.
            groups = {}  # (category, rate_str, reason) -> {basis, vat}
            for it in items:
                # basis (line net)
                ln = _m(_d(
                    it.get("total_price",
                           0))) if it.get("total_price") is not None else _m(
                               _d(it.get("quantity", 1)) *
                               _d(it.get("unit_price", 0)))

                rate_stored = _d(it.get("vat_rate", global_vat))
                effective_rate = Decimal(
                    "0") if vat_mode != "standard" else rate_stored

                info = get_vat_info(profile,
                                    float(effective_rate),
                                    vat_mode=vat_mode)
                category = info.get("category") or "S"
                reason = info.get("reason") or None

                # VAT amount: use stored item vat_amount if present, else compute for standard only
                if it.get("vat_amount") is not None:
                    vamt = _m(_d(it.get("vat_amount", 0)))
                else:
                    vamt = _m(ln * (effective_rate / Decimal("100"))
                              ) if vat_mode == "standard" else Decimal("0")

                key = (category, str(_p(effective_rate)), reason or "")
                bucket = groups.setdefault(key, {
                    "basis": Decimal("0"),
                    "vat": Decimal("0")
                })
                bucket["basis"] += ln
                bucket["vat"] += vamt

            if groups:
                for (category, rate_str, reason), v in groups.items():
                    taxable = _m(v["basis"])
                    vat_amt = _m(
                        v["vat"]) if vat_mode == "standard" else Decimal("0")
                    eff_rate = _d(rate_str)

                    trade_tax = etree.SubElement(
                        h_settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
                    etree.SubElement(
                        trade_tax,
                        f"{{{self.ns['ram']}}}CalculatedAmount").text = (
                            f"{vat_amt:.2f}")
                    etree.SubElement(
                        trade_tax,
                        f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
                    etree.SubElement(
                        trade_tax, f"{{{self.ns['ram']}}}BasisAmount").text = (
                            f"{taxable:.2f}")
                    etree.SubElement(
                        trade_tax,
                        f"{{{self.ns['ram']}}}CategoryCode").text = category
                    etree.SubElement(
                        trade_tax,
                        f"{{{self.ns['ram']}}}RateApplicablePercent").text = (
                            f"{_p(eff_rate):.2f}")
                    if reason:
                        etree.SubElement(
                            trade_tax, f"{{{self.ns['ram']}}}ExemptionReason"
                        ).text = reason
            else:
                # last resort: single block from totals
                effective_global = Decimal(
                    "0") if vat_mode != "standard" else global_vat
                info = get_vat_info(profile,
                                    float(effective_global),
                                    vat_mode=vat_mode)

                trade_tax = etree.SubElement(
                    h_settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
                etree.SubElement(
                    trade_tax, f"{{{self.ns['ram']}}}CalculatedAmount"
                ).text = (
                    f"{(total_vat_db if vat_mode == 'standard' else Decimal('0')):.2f}"
                )
                etree.SubElement(trade_tax,
                                 f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
                etree.SubElement(trade_tax,
                                 f"{{{self.ns['ram']}}}BasisAmount").text = (
                                     f"{total_net_db:.2f}")
                etree.SubElement(trade_tax,
                                 f"{{{self.ns['ram']}}}CategoryCode").text = (
                                     info.get("category") or "S")
                etree.SubElement(
                    trade_tax,
                    f"{{{self.ns['ram']}}}RateApplicablePercent").text = (
                        f"{_p(effective_global):.2f}")
                if info.get("reason"):
                    etree.SubElement(trade_tax,
                                     f"{{{self.ns['ram']}}}ExemptionReason"
                                     ).text = info.get("reason")

        # --- MONETARY SUMMATION ---
        # LineTotalAmount должен соответствовать сумме строк.
        # TaxBasis/TaxTotal/GrandTotal/DuePayable берём из канона invoices (как в PDF)
        line_total_sum = _m(
            sum((_d(it.get("total_price", 0)) for it in items), Decimal("0")))

        total_sum = etree.SubElement(
            h_settle,
            f"{{{self.ns['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation"
        )
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}LineTotalAmount"
                         ).text = f"{line_total_sum:.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}TaxBasisTotalAmount"
                         ).text = f"{total_net_db:.2f}"
        etree.SubElement(total_sum,
                         f"{{{self.ns['ram']}}}TaxTotalAmount",
                         currencyID="EUR").text = f"{total_vat_db:.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}GrandTotalAmount"
                         ).text = f"{total_gross_db:.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}DuePayableAmount"
                         ).text = f"{total_gross_db:.2f}"

        return etree.tostring(root,
                              pretty_print=True,
                              xml_declaration=True,
                              encoding="UTF-8").decode("utf-8")


def embed_xml_in_pdf(pdf_bytes: bytes, xml_string: str) -> bytes:
    import pikepdf
    from pikepdf import Dictionary, Name, Array

    pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))

    # PDF/A-3 metadata
    with pdf.open_metadata() as meta:
        meta["pdfaid:part"] = "3"
        meta["pdfaid:conformance"] = "B"
        meta["dc:format"] = "application/pdf"
        meta["pdfaExtension:schemas"] = "Factur-X PDFA Extension Schema"

    xml_stream = pikepdf.Stream(pdf, xml_string.encode("utf-8"))
    xml_stream.Subtype = Name("/text/xml")

    embedded = Dictionary(F=xml_stream,
                          UF=xml_stream,
                          Type=Name("/Filespec"),
                          AFRelationship=Name("/Data"),
                          Desc="Factur-X XML")

    if "/Names" not in pdf.Root:
        pdf.Root.Names = Dictionary()
    if "/EmbeddedFiles" not in pdf.Root.Names:
        pdf.Root.Names.EmbeddedFiles = Dictionary()
    pdf.Root.Names.EmbeddedFiles.Names = Array(["factur-x.xml", embedded])

    if "/AF" not in pdf.Root:
        pdf.Root.AF = Array()
    pdf.Root.AF.append(embedded)

    output = io.BytesIO()
    pdf.save(output, min_version="1.7")
    return output.getvalue()
