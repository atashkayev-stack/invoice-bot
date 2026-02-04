"""xml_generator_v2.py - ZUGFeRD 2.4 Extended с B2B полями"""
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
        
        # Context
        ctx = etree.SubElement(root, f"{{{self.ns['rsm']}}}ExchangedDocumentContext")
        guide = etree.SubElement(ctx, f"{{{self.ns['ram']}}}GuidelineSpecifiedDocumentContextParameter")
        etree.SubElement(guide, f"{{{self.ns['ram']}}}ID").text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:extended"
        
        # Document
        doc = etree.SubElement(root, f"{{{self.ns['rsm']}}}ExchangedDocument")
        etree.SubElement(doc, f"{{{self.ns['ram']}}}ID").text = data.get('invoice_number', 'RE-0001')
        etree.SubElement(doc, f"{{{self.ns['ram']}}}TypeCode").text = "380"
        
        issue_dt = etree.SubElement(doc, f"{{{self.ns['ram']}}}IssueDateTime")
        etree.SubElement(issue_dt, f"{{{self.ns['udt']}}}DateTimeString", format="102").text = \
            (data.get('invoice_date') or datetime.now().strftime('%Y%m%d')).replace('-', '')
        
        # Transaction
        tx = etree.SubElement(root, f"{{{self.ns['rsm']}}}SupplyChainTradeTransaction")
        
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
            
            # VAT per item
            item_vat_rate = item.get('vat_rate') if vat_per_item else global_vat
            tax = etree.SubElement(settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
            etree.SubElement(tax, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
            etree.SubElement(tax, f"{{{self.ns['ram']}}}CategoryCode").text = self._get_vat_category(item_vat_rate, profile)
            etree.SubElement(tax, f"{{{self.ns['ram']}}}RateApplicablePercent").text = f"{item_vat_rate:.2f}"
            
            monet = etree.SubElement(settle, f"{{{self.ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
            etree.SubElement(monet, f"{{{self.ns['ram']}}}LineTotalAmount").text = f"{item.get('total', 0):.2f}"
        
        # Trade Agreement (Seller/Buyer)
        agr = etree.SubElement(tx, f"{{{self.ns['ram']}}}ApplicableHeaderTradeAgreement")
        
        # Seller
        seller = etree.SubElement(agr, f"{{{self.ns['ram']}}}SellerTradeParty")
        etree.SubElement(seller, f"{{{self.ns['ram']}}}Name").text = profile.get('company_name', 'Firma')
        if profile.get('legal_form'):
            etree.SubElement(seller, f"{{{self.ns['ram']}}}SpecifiedLegalOrganization").text = profile.get('legal_form')
        
        seller_addr = etree.SubElement(seller, f"{{{self.ns['ram']}}}PostalTradeAddress")
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}PostcodeCode").text = profile.get('postal_code', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}LineOne").text = profile.get('street', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}CityName").text = profile.get('city', '')
        etree.SubElement(seller_addr, f"{{{self.ns['ram']}}}CountryID").text = profile.get('country_code', 'DE')
        
        seller_tax = etree.SubElement(seller, f"{{{self.ns['ram']}}}SpecifiedTaxRegistration")
        etree.SubElement(seller_tax, f"{{{self.ns['ram']}}}ID", schemeID="VA").text = profile.get('vat_id', '')
        
        # Buyer
        buyer = etree.SubElement(agr, f"{{{self.ns['ram']}}}BuyerTradeParty")
        etree.SubElement(buyer, f"{{{self.ns['ram']}}}Name").text = data.get('client_name', 'Kunde')
        
        # B2B поля
        if data.get('client_type') == 'b2b':
            if data.get('client_legal_form'):
                etree.SubElement(buyer, f"{{{self.ns['ram']}}}SpecifiedLegalOrganization").text = data.get('client_legal_form')
            if data.get('buyer_reference'):
                etree.SubElement(buyer, f"{{{self.ns['ram']}}}BuyerReference").text = data.get('buyer_reference')
        
        buyer_addr = etree.SubElement(buyer, f"{{{self.ns['ram']}}}PostalTradeAddress")
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}PostcodeCode").text = data.get('client_postal_code', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}LineOne").text = data.get('client_street', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}CityName").text = data.get('client_city', '')
        etree.SubElement(buyer_addr, f"{{{self.ns['ram']}}}CountryID").text = data.get('client_country', 'DE')
        
        if data.get('client_vat_id'):
            buyer_tax = etree.SubElement(buyer, f"{{{self.ns['ram']}}}SpecifiedTaxRegistration")
            etree.SubElement(buyer_tax, f"{{{self.ns['ram']}}}ID", schemeID="VA").text = data.get('client_vat_id')
        
        # Purchase Order
        if data.get('purchase_order'):
            etree.SubElement(agr, f"{{{self.ns['ram']}}}BuyerOrderReferencedDocument") \
                .append(etree.Element(f"{{{self.ns['ram']}}}IssuerAssignedID")).text = data.get('purchase_order')
        
        # Trade Delivery
        delivery = etree.SubElement(tx, f"{{{self.ns['rsm']}}}ApplicableHeaderTradeDelivery")
        deliv_event = etree.SubElement(delivery, f"{{{self.ns['ram']}}}ActualDeliverySupplyChainEvent")
        deliv_dt = etree.SubElement(deliv_event, f"{{{self.ns['ram']}}}OccurrenceDateTime")
        etree.SubElement(deliv_dt, f"{{{self.ns['udt']}}}DateTimeString", format="102").text = \
            (data.get('delivery_date') or data.get('invoice_date') or datetime.now().strftime('%Y%m%d')).replace('-', '')
        
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
        
        # Tax Total
        tax_total = etree.SubElement(settle, f"{{{self.ns['ram']}}}ApplicableTradeTax")
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}CalculatedAmount").text = f"{data.get('total_vat', 0):.2f}"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}TypeCode").text = "VAT"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}BasisAmount").text = f"{data.get('total_net', 0):.2f}"
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}CategoryCode").text = self._get_vat_category(global_vat, profile)
        etree.SubElement(tax_total, f"{{{self.ns['ram']}}}RateApplicablePercent").text = f"{global_vat:.2f}"
        
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
    
    def _get_vat_category(self, vat_rate: float, profile: dict) -> str:
        if profile.get('is_kleinunternehmer'):
            return 'E'
        elif vat_rate == 0:
            return 'Z'
        else:
            return 'S'


def embed_xml_in_pdf(pdf_bytes: bytes, xml_string: str) -> bytes:
    try:
        import pikepdf
        pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        pdf.attachments['factur-x.xml'] = xml_string.encode('utf-8')
        output = io.BytesIO()
        pdf.save(output)
        output.seek(0)
        return output.getvalue()
    except:
        return pdf_bytes
