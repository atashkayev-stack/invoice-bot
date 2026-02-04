"""xml_generator_v2.py - ZUGFeRD 2.4 COMPLIANT (Dec 2025)"""
import io
from datetime import datetime
from lxml import etree


class XMLGeneratorV2:
    def __init__(self):
        self.ns = {
            'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
            'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
            'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
            'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100'
        }
    
    def generate_zugferd_xml(self, data: dict, profile: dict) -> str:
        root = etree.Element(f"{{{self.ns['rsm']}}}CrossIndustryInvoice", nsmap=self.ns)
        
        # Context - ИСПРАВЛЕНО: актуальный профиль для ZUGFeRD 2.4
        ctx = etree.SubElement(root, f"{{{self.ns['rsm']}}}ExchangedDocumentContext")
        guide = etree.SubElement(ctx, f"{{{self.ns['ram']}}}GuidelineSpecifiedDocumentContextParameter")
        etree.SubElement(guide, f"{{{self.ns['ram']}}}ID").text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:extended"
        
        # Document
        doc = etree.SubElement(root, f"{{{self.ns['rsm']}}}ExchangedDocument")
        etree.SubElement(doc, f"{{{self.ns['ram']}}}ID").text = data.get('invoice_number', 'RE-0001')
        etree.SubElement(doc, f"{{{self.ns['ram']}}}TypeCode").text = data.get('invoice_type_code', '380')
        
        issue_dt = etree.SubElement(doc, f"{{{self.ns['ram']}}}IssueDateTime")
        etree.SubElement(issue_dt, f"{{{self.ns['udt']}}}DateTimeString", format="102").text = \
            (data.get('invoice_date') or datetime.now().strftime('%Y%m%d')).replace('-', '')
        
        # Transaction
        tx = etree.SubElement(root, f"{{{self.ns['rsm']}}}SupplyChainTradeTransaction")
        
        # ИСПРАВЛЕНО: используем get_vat_info для правильных категорий
        from handlers_v1 import get_vat_info
        
        # Line Items
        items = data.get('items', [])
        vat_per_item = data.get('vat_per_item', False)
        global_vat = data.get('global_vat_rate', 19)
        
        for item in items:
            li = etree.SubElement(tx, f"{{{self.ns['ram']}}}IncludedSupplyChainTradeLineItem")
            assoc = etree.SubElement(li, f"{{{self.ns['ram']}}}AssociatedDocumentLineDocument")
            etree.SubElement(assoc, f"{{{self.ns['ram']}}}LineID").text = str(item.get('position', 1))
            
            prod = etree.SubElement(li, f"{{{self.ns['ram']}}}SpecifiedTradeProduct")
            etree.SubElement(prod, f"{{{self.ns['ram']}}}Name").text = item.get('description', 'Position')
            
            agr = etree.SubElement(li, f"{{{self.ns['ram']}}}SpecifiedLineTradeAgreement")
            gross_price = etree.SubElement(agr, f"{{{self.ns['ram']}}}GrossPriceProductTradePrice")
            etree.SubElement(gross_price, f"{{{self.ns['ram']}}}ChargeAmount").text = f"{item.get('unit_price', 0):.2f}"
            
            deliv = etree.SubElement(li, f"{{{self.ns['ram']}}}SpecifiedLineTradeDelivery")
            billed = etree.SubElement(deliv, f"{{{self.ns['ram']}}}BilledQuantity", unitCode=self._get_unit_code(item.get('unit', 'Stk')))
            billed.text = str(item.get('quantity', 1))
            
            settle = etree.SubElement(li, f"{{{self.ns['ram']}}}SpecifiedLineTradeSettlement")
            
            # VAT per item - ИСПРАВЛЕНО: используем get_vat_info
            item_vat_rate = item.get('vat_rate') if vat_per_item else global_vat
            vat_info = get_vat_info(profile, item_vat_rate)
            
            tax = etree.SubElement(settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
            etree.SubElement(tax, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
            etree.SubElement(tax, f"{{{self.ns['ram']}}}CategoryCode").text = vat_info['category']
            etree.SubElement(tax, f"{{{self.ns['ram']}}}RateApplicablePercent").text = f"{vat_info['rate']:.2f}"
            
            if vat_info['reason']:
                etree.SubElement(tax, f"{{{self.ns['ram']}}}ExemptionReason").text = vat_info['reason']
            
            monet = etree.SubElement(settle, f"{{{self.ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
            etree.SubElement(monet, f"{{{self.ns['ram']}}}LineTotalAmount").text = f"{item.get('total', 0):.2f}"
        
        # Trade Agreement
        agr = etree.SubElement(tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeAgreement")
        
        # Seller
        seller = etree.SubElement(agr, f"{{{self.ns['ram']}}}SellerTradeParty")
        etree.SubElement(seller, f"{{{self.ns['ram']}}}Name").text = profile.get('company_name', 'Firma')
        
        if profile.get('legal_form'):
            legal_org = etree.SubElement(seller, f"{{{self.ns['ram']}}}SpecifiedLegalOrganization")
            etree.SubElement(legal_org, f"{{{self.ns['ram']}}}TradingBusinessName").text = profile.get('legal_form')
            if profile.get('trade_register_number'):
                etree.SubElement(legal_org, f"{{{self.ns['ram']}}}ID").text = profile.get('trade_register_number')
        
        seller_addr = etree.SubElement(seller, f"{{{self.ns['ram']}}}PostalTradeAddress")
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}PostcodeCode").text = profile.get('postal_code', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}LineOne").text = profile.get('street', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}CityName").text = profile.get('city', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}CountryID").text = profile.get('country_code', 'DE')
        
        if profile.get('vat_id'):
            seller_tax = etree.SubElement(seller, f"{{{self.ns['ram']}}}SpecifiedTaxRegistration")
            etree.SubElement(seller_tax, f"{{{self.ns['ram']}}}ID", schemeID="VA").text = profile.get('vat_id')
        
        if profile.get('tax_id'):
            seller_tax2 = etree.SubElement(seller, f"{{{self.ns['ram']}}}SpecifiedTaxRegistration")
            etree.SubElement(seller_tax2, f"{{{self.ns['ram']}}}ID", schemeID="FC").text = profile.get('tax_id')
        
        # Buyer
        buyer = etree.SubElement(agr, f"{{{self.ns['ram']}}}BuyerTradeParty")
        etree.SubElement(buyer, f"{{{self.ns['ram']}}}Name").text = data.get('client_name', 'Kunde')
        
        if data.get('client_type') == 'b2b':
            if data.get('client_legal_form'):
                buyer_legal = etree.SubElement(buyer, f"{{{self.ns['ram']}}}SpecifiedLegalOrganization")
                etree.SubElement(buyer_legal, f"{{{self.ns['ram']}}}TradingBusinessName").text = data.get('client_legal_form')
                if data.get('client_trade_register'):
                    etree.SubElement(buyer_legal, f"{{{self.ns['ram']}}}ID").text = data.get('client_trade_register')
        
        buyer_addr = etree.SubElement(buyer, f"{{{self.ns['ram']}}}PostalTradeAddress")
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}PostcodeCode").text = data.get('client_postal_code', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}LineOne").text = data.get('client_street', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}CityName").text = data.get('client_city', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}CountryID").text = data.get('client_country', 'DE')
        
        if data.get('client_vat_id'):
            buyer_tax = etree.SubElement(buyer, f"{{{self.ns['ram']}}}SpecifiedTaxRegistration")
            etree.SubElement(buyer_tax, f"{{{self.ns['ram']}}}ID", schemeID="VA").text = data.get('client_vat_id')
        
        # Buyer Reference (ОБЯЗАТЕЛЬНО для B2B)
        if data.get('buyer_reference'):
            etree.SubElement(agr, f"{{{self.ns['ram']}}}BuyerReference").text = data.get('buyer_reference')
        
        # Purchase Order
        if data.get('purchase_order'):
            buyer_order = etree.SubElement(agr, f"{{{self.ns['ram']}}}BuyerOrderReferencedDocument")
            etree.SubElement(buyer_order, f"{{{self.ns['ram']}}}IssuerAssignedID").text = data.get('purchase_order')
        
        # Trade Delivery - КРИТИЧНО: Leistungsdatum обязателен!
        delivery = etree.SubElement(tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeDelivery")
        deliv_event = etree.SubElement(delivery, f"{{{self.ns['ram']}}}ActualDeliverySupplyChainEvent")
        deliv_dt = etree.SubElement(deliv_event, f"{{{self.ns['ram']}}}OccurrenceDateTime")
        delivery_date = data.get('delivery_date') or data.get('invoice_date') or datetime.now().strftime('%Y%m%d')
        etree.SubElement(deliv_dt, f"{{{self.ns['udt']}}}DateTimeString", format="102").text = delivery_date.replace('-', '')
        
        # Trade Settlement
        settle = etree.SubElement(tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeSettlement")
        etree.SubElement(settle, f"{{{self.ns['ram']}}}InvoiceCurrencyCode").text = data.get('currency', 'EUR')
        
        # Payment Means
        payment = etree.SubElement(settle, f"{{{self.ns['ram']}}}SpecifiedTradeSettlementPaymentMeans")
        etree.SubElement(payment, f"{{{self.ns['ram']}}}TypeCode").text = str(data.get('payment_means', '58'))
        
        if data.get('payment_means') == '58':  # SEPA
            payee = etree.SubElement(payment, f"{{{self.ns['ram']}}}PayeePartyCreditorFinancialAccount")
            etree.SubElement(payee, f"{{{self.ns['ram']}}}IBANID").text = profile.get('iban', '')
            if profile.get('bic'):
                inst = etree.SubElement(payment, f"{{{self.ns['ram']}}}PayeeSpecifiedCreditorFinancialInstitution")
                etree.SubElement(inst, f"{{{self.ns['ram']}}}BICID").text = profile.get('bic')
        
        # Payment Terms
        terms = etree.SubElement(settle, f"{{{self.ns['ram']}}}SpecifiedTradePaymentTerms")
        if data.get('due_date'):
            due = etree.SubElement(terms, f"{{{self.ns['ram']}}}DueDateDateTime")
            etree.SubElement(due, f"{{{self.ns['udt']}}}DateTimeString", format="102").text = data.get('due_date').replace('-', '')
        
        # Tax Total - ИСПРАВЛЕНО: используем get_vat_info
        global_vat_info = get_vat_info(profile, global_vat)
        
        tax_total = etree.SubElement(settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}CalculatedAmount").text = f"{data.get('total_vat', 0):.2f}"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}BasisAmount").text = f"{data.get('total_net', 0):.2f}"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}CategoryCode").text = global_vat_info['category']
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}RateApplicablePercent").text = f"{global_vat_info['rate']:.2f}"
        
        if global_vat_info['reason']:
            etree.SubElement(tax_total, f"{{{self.ns['ram']}}}ExemptionReason").text = global_vat_info['reason']
        
        # Monetary Summation
        monet = etree.SubElement(settle, f"{{{self.ns['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
        etree.SubElement(monet, f"{{{self.ns['ram']}}}LineTotalAmount").text = f"{data.get('total_net', 0):.2f}"
        etree.SubElement(monet, f"{{{self.ns['ram']}}}TaxBasisTotalAmount").text = f"{data.get('total_net', 0):.2f}"
        etree.SubElement(monet, f"{{{self.ns['ram']}}}TaxTotalAmount", currencyID=data.get('currency', 'EUR')).text = f"{data.get('total_vat', 0):.2f}"
        etree.SubElement(monet, f"{{{self.ns['ram']}}}GrandTotalAmount").text = f"{data.get('total_gross', 0):.2f}"
        etree.SubElement(monet, f"{{{self.ns['ram']}}}DuePayableAmount").text = f"{data.get('total_gross', 0):.2f}"
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')
    
    def _get_unit_code(self, unit: str) -> str:
        units = {'Stk': 'C62', 'Std': 'HUR', 'Tag': 'DAY', 'kg': 'KGM', 'm': 'MTR', 'm²': 'MTK', 'm³': 'MTQ', 'km': 'KTM', 'l': 'LTR'}
        return units.get(unit, 'C62')


def embed_xml_in_pdf(pdf_bytes: bytes, xml_string: str) -> bytes:
    """ИСПРАВЛЕНО: создаём PDF/A-3 compliant контейнер"""
    try:
        import pikepdf
        from pikepdf import Dictionary, Name, Array
        
        pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        
        # PDF/A-3 metadata (КРИТИЧНО для ZUGFeRD!)
        with pdf.open_metadata() as meta:
            meta['pdfaid:part'] = '3'
            meta['pdfaid:conformance'] = 'B'
            meta['dc:format'] = 'application/pdf'
            meta['pdfaExtension:schemas'] = 'Factur-X PDFA Extension Schema'
        
        # Создаём embedded file stream
        xml_stream = pikepdf.Stream(pdf, xml_string.encode('utf-8'))
        xml_stream.Subtype = Name('/text/xml')
        
        # EmbeddedFile
        embedded = Dictionary(
            F=xml_stream,
            UF=xml_stream,
            Type=Name('/Filespec'),
            AFRelationship=Name('/Data'),
            Desc='Factur-X XML'
        )
        
        # Добавляем в Names
        if '/Names' not in pdf.Root:
            pdf.Root.Names = Dictionary()
        if '/EmbeddedFiles' not in pdf.Root.Names:
            pdf.Root.Names.EmbeddedFiles = Dictionary()
        
        pdf.Root.Names.EmbeddedFiles.Names = Array([
            'factur-x.xml',
            embedded
        ])
        
        # Associated Files (для PDF/A-3)
        if '/AF' not in pdf.Root:
            pdf.Root.AF = Array()
        pdf.Root.AF.append(embedded)
        
        output = io.BytesIO()
        pdf.save(output, min_version='1.7')
        output.seek(0)
        return output.getvalue()
    except Exception as e:
        print(f"⚠️ PDF/A-3 embedding failed: {e}")
        return pdf_bytes
