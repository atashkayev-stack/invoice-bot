"""xml_generator_v2.py - ZUGFeRD 2.4 COMPLIANT (Dec 2025)"""
import io
from datetime import datetime
from lxml import etree


class XMLGeneratorV2:

    def __init__(self):
        self.ns = {
            'rsm':
            'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
            'ram':
            'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
            'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
            'udt':
            'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100'
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
            'invoice_number', 'RE-0000')
        etree.SubElement(doc, f"{{{self.ns['ram']}}}TypeCode").text = "380"

        issue_dt = etree.SubElement(doc, f"{{{self.ns['ram']}}}IssueDateTime")
        dt_str = (data.get('invoice_date')
                  or datetime.now().strftime('%Y-%m-%d')).replace('-', '')
        etree.SubElement(issue_dt,
                         f"{{{self.ns['udt']}}}DateTimeString",
                         format="102").text = dt_str

        # Transaction
        tx = etree.SubElement(
            root, f"{{{self.ns['rsm']}}}SupplyChainTradeTransaction")

        # Налоговые параметры
        vat_mode = data.get('vat_mode', 'standard')
        global_vat = float(data.get('global_vat_rate', 19))

        items = data.get('items', [])

        # --- LINE ITEMS ---
        for idx, item in enumerate(items, 1):
            line_item = etree.SubElement(
                tx, f"{{{self.ns['ram']}}}IncludedSupplyChainTradeLineItem")

            # Line ID
            assoc = etree.SubElement(
                line_item,
                f"{{{self.ns['ram']}}}AssociatedDocumentLineDocument")
            etree.SubElement(assoc,
                             f"{{{self.ns['ram']}}}LineID").text = str(idx)

            # Product
            prod = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedTradeProduct")
            etree.SubElement(prod,
                             f"{{{self.ns['ram']}}}Name").text = item.get(
                                 'description', 'Position')

            # Agreement (Price)
            agr = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeAgreement")
            net_price = etree.SubElement(
                agr, f"{{{self.ns['ram']}}}NetPriceProductTradePrice")
            etree.SubElement(net_price, f"{{{self.ns['ram']}}}ChargeAmount"
                             ).text = f"{float(item.get('unit_price', 0)):.2f}"

            # Delivery (Quantity)
            deliv = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeDelivery")
            billed_qty = etree.SubElement(
                deliv, f"{{{self.ns['ram']}}}BilledQuantity", unitCode="C62")
            billed_qty.text = f"{float(item.get('quantity', 1)):.2f}"

            # Settlement (Tax & Total)
            settle = etree.SubElement(
                line_item, f"{{{self.ns['ram']}}}SpecifiedLineTradeSettlement")

            # РАСЧЕТ НДС ПО ПОЗИЦИИ
            item_rate = float(item.get('vat_rate', global_vat))
            # Если режим не стандартный, ставка для XML всегда 0
            effective_rate = 0 if vat_mode != 'standard' else item_rate
            vat_info = get_vat_info(profile, effective_rate)

            tax = etree.SubElement(settle,
                                   f"{{{self.ns['ram']}}}ApplicableTradeTax")
            etree.SubElement(tax, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
            etree.SubElement(tax, f"{{{self.ns['ram']}}}CategoryCode"
                             ).text = vat_info['category']
            etree.SubElement(tax, f"{{{self.ns['ram']}}}RateApplicablePercent"
                             ).text = f"{vat_info['rate']:.2f}"

            summation = etree.SubElement(
                settle,
                f"{{{self.ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation"
            )
            line_net = float(item.get('quantity', 0)) * float(
                item.get('unit_price', 0))
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
                             'company_name', 'My Company')

        # Buyer
        buyer = etree.SubElement(h_agr, f"{{{self.ns['ram']}}}BuyerTradeParty")
        etree.SubElement(buyer, f"{{{self.ns['ram']}}}Name").text = data.get(
            'client_name', 'Client')

        # --- HEADER TRADE DELIVERY ---
        h_deliv = etree.SubElement(
            tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeDelivery")
        event = etree.SubElement(
            h_deliv, f"{{{self.ns['ram']}}}ActualDeliverySupplyChainEvent")
        occurrence = etree.SubElement(
            event, f"{{{self.ns['ram']}}}OccurrenceDateTime")
        deliv_date = (data.get('delivery_date') or data.get('invoice_date')
                      or datetime.now().strftime('%Y-%m-%d')).replace('-', '')
        etree.SubElement(occurrence,
                         f"{{{self.ns['udt']}}}DateTimeString",
                         format="102").text = deliv_date

        # --- HEADER TRADE SETTLEMENT ---
        h_settle = etree.SubElement(
            tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeSettlement")
        etree.SubElement(
            h_settle, f"{{{self.ns['ram']}}}InvoiceCurrencyCode").text = "EUR"

        # ИТОГОВЫЙ НДС
        # ИТОГОВЫЙ НДС
        effective_global_rate = 0 if vat_mode != 'standard' else global_vat
        g_vat_info = get_vat_info(profile,
                                  effective_global_rate,
                                  vat_mode=data.get('vat_mode', 'standard'))

        # Секция Tax Total (Используем tax_amount и amount вместо total_vat)
        trade_tax = etree.SubElement(
            h_settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
        etree.SubElement(trade_tax, f"{{{self.ns['ram']}}}CalculatedAmount"
                         ).text = f"{float(data.get('tax_amount', 0)):.2f}"
        etree.SubElement(trade_tax,
                         f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
        etree.SubElement(trade_tax, f"{{{self.ns['ram']}}}BasisAmount"
                         ).text = f"{float(data.get('amount', 0)):.2f}"
        etree.SubElement(
            trade_tax,
            f"{{{self.ns['ram']}}}CategoryCode").text = g_vat_info['category']
        etree.SubElement(trade_tax,
                         f"{{{self.ns['ram']}}}RateApplicablePercent"
                         ).text = f"{g_vat_info['rate']:.2f}"

        if g_vat_info['reason']:
            etree.SubElement(trade_tax, f"{{{self.ns['ram']}}}ExemptionReason"
                             ).text = g_vat_info['reason']

        # Monetary Summation (Используем amount, tax_amount и total)
        total_sum = etree.SubElement(
            h_settle,
            f"{{{self.ns['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation"
        )
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}LineTotalAmount"
                         ).text = f"{float(data.get('amount', 0)):.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}TaxBasisTotalAmount"
                         ).text = f"{float(data.get('amount', 0)):.2f}"
        etree.SubElement(
            total_sum, f"{{{self.ns['ram']}}}TaxTotalAmount",
            currencyID="EUR").text = f"{float(data.get('tax_amount', 0)):.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}GrandTotalAmount"
                         ).text = f"{float(data.get('total', 0)):.2f}"
        etree.SubElement(total_sum, f"{{{self.ns['ram']}}}DuePayableAmount"
                         ).text = f"{float(data.get('total', 0)):.2f}"

        return etree.tostring(root,
                              pretty_print=True,
                              xml_declaration=True,
                              encoding='UTF-8').decode('utf-8')


def embed_xml_in_pdf(pdf_bytes: bytes, xml_string: str) -> bytes:
    import pikepdf
    from pikepdf import Dictionary, Name, Array

    pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))

    # PDF/A-3 metadata
    with pdf.open_metadata() as meta:
        meta['pdfaid:part'] = '3'
        meta['pdfaid:conformance'] = 'B'
        meta['dc:format'] = 'application/pdf'
        meta['pdfaExtension:schemas'] = 'Factur-X PDFA Extension Schema'

    xml_stream = pikepdf.Stream(pdf, xml_string.encode('utf-8'))
    xml_stream.Subtype = Name('/text/xml')

    embedded = Dictionary(F=xml_stream,
                          UF=xml_stream,
                          Type=Name('/Filespec'),
                          AFRelationship=Name('/Data'),
                          Desc='Factur-X XML')

    if '/Names' not in pdf.Root: pdf.Root.Names = Dictionary()
    if '/EmbeddedFiles' not in pdf.Root.Names:
        pdf.Root.Names.EmbeddedFiles = Dictionary()
    pdf.Root.Names.EmbeddedFiles.Names = Array(['factur-x.xml', embedded])

    if '/AF' not in pdf.Root: pdf.Root.AF = Array()
    pdf.Root.AF.append(embedded)

    output = io.BytesIO()
    pdf.save(output, min_version='1.7')
    return output.getvalue()
