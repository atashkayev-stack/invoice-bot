"""
document_generator_v1.py
Единый модуль для генерации PDF и XML
"""
import io
import logging
from datetime import datetime
from fpdf import FPDF
from lxml import etree

logger = logging.getLogger(__name__)


class DocumentGenerator:
    """Генератор PDF и XML документов"""
    
    def __init__(self):
        self.xml_namespaces = {
            'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
            'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
            'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
            'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100'
        }
    
    # ========== PDF ГЕНЕРАЦИЯ ==========
    
    def generate_pdf(self, data: dict, profile: dict, title: str = "RECHNUNG") -> io.BytesIO:
        """Генерация PDF с правильным форматированием"""
        pdf = FPDF()
        pdf.add_page()
        
        # 1. ЗАГОЛОВОК ДОКУМЕНТА
        pdf.set_font("Arial", 'B', 20)
        pdf.cell(0, 15, txt=title, ln=1, align='C')
        pdf.ln(5)
        
        # 2. ФИРМА ОТПРАВИТЕЛЯ (справа)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 6, txt=self._safe_str(profile.get('company_name', 'Firma')), ln=1, align='R')
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 5, txt=self._safe_str(profile.get('street', '')), ln=1, align='R')
        pdf.cell(0, 5, txt=f"{profile.get('postal_code', '')} {profile.get('city', '')}".strip(), ln=1, align='R')
        pdf.ln(10)
        
        # 3. ПОЛУЧАТЕЛЬ
        client = data.get('client_data', {})
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(0, 6, txt="Empfaenger:", ln=1)
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 5, txt=self._safe_str(client.get('company_name', 'Kunde')), ln=1)
        
        # Адрес клиента (может быть многострочным)
        address = self._safe_str(client.get('address', ''))
        if address:
            pdf.multi_cell(0, 5, txt=address)
        pdf.ln(8)
        
        # 4. ТАБЛИЦА ПОЗИЦИЙ
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(100, 8, txt="Beschreibung", border=1, align='C', fill=True)
        pdf.cell(25, 8, txt="Menge", border=1, align='C', fill=True)
        pdf.cell(30, 8, txt="Preis", border=1, align='C', fill=True)
        pdf.cell(35, 8, txt="Gesamt", border=1, ln=1, align='C', fill=True)
        
        pdf.set_font("Arial", '', 10)
        items = data.get('invoice_items') or data.get('offer_items') or []
        for item in items:
            desc = self._safe_str(item.get('description', ''))
            qty = float(item.get('quantity', 1))
            unit = self._safe_str(item.get('unit', 'Stk'))
            price = float(item.get('price', 0))
            total = float(item.get('total', 0))
            
            pdf.cell(100, 7, txt=desc, border=1)
            pdf.cell(25, 7, txt=f"{qty} {unit}", border=1, align='C')
            pdf.cell(30, 7, txt=f"{price:.2f} EUR", border=1, align='R')
            pdf.cell(35, 7, txt=f"{total:.2f} EUR", border=1, ln=1, align='R')
        
        # 5. ИТОГИ
        pdf.ln(5)
        pdf.set_font("Arial", '', 10)
        
        # Netto
        pdf.cell(155, 7, txt="Netto:", align='R')
        pdf.cell(35, 7, txt=f"{float(data.get('total_net', 0)):.2f} EUR", ln=1, align='R')
        
        # MwSt (только если > 0)
        vat_rate = float(data.get('vat_rate', 19))
        if vat_rate > 0:
            pdf.cell(155, 7, txt=f"MwSt ({vat_rate:.0f}%):", align='R')
            pdf.cell(35, 7, txt=f"{float(data.get('total_vat', 0)):.2f} EUR", ln=1, align='R')
        else:
            # Kleinunternehmer
            pdf.set_font("Arial", 'I', 9)
            pdf.multi_cell(0, 5, txt="Gemaess Par. 19 UStG wird keine Umsatzsteuer berechnet.")
            pdf.set_font("Arial", '', 10)
        
        # Gesamtbetrag
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(155, 10, txt="Gesamtbetrag:", align='R')
        pdf.cell(35, 10, txt=f"{float(data.get('total_gross', 0)):.2f} EUR", ln=1, align='R')
        
        # 6. FUSSZEILE
        pdf.ln(15)
        pdf.set_font("Arial", 'I', 8)
        footer_parts = []
        if profile.get('tax_id'):
            footer_parts.append(f"Steuernummer: {profile.get('tax_id')}")
        if profile.get('iban'):
            footer_parts.append(f"IBAN: {profile.get('iban')}")
        if footer_parts:
            pdf.cell(0, 5, txt=" | ".join(footer_parts), ln=1, align='C')
        
        # Возврат BytesIO
        output = io.BytesIO()
        pdf.output(output)
        output.seek(0)
        return output
    
    # ========== XML ГЕНЕРАЦИЯ ==========
    
    def generate_xml(self, data: dict, profile: dict) -> str:
        """Генерация ZUGFeRD/XRechnung XML"""
        root = etree.Element(
            f"{{{self.xml_namespaces['rsm']}}}CrossIndustryInvoice",
            nsmap=self.xml_namespaces
        )
        
        # ExchangedDocumentContext
        context = etree.SubElement(root, f"{{{self.xml_namespaces['rsm']}}}ExchangedDocumentContext")
        guideline = etree.SubElement(context, f"{{{self.xml_namespaces['ram']}}}GuidelineSpecifiedDocumentContextParameter")
        guideline_id = etree.SubElement(guideline, f"{{{self.xml_namespaces['ram']}}}ID")
        guideline_id.text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"
        
        # ExchangedDocument
        doc = etree.SubElement(root, f"{{{self.xml_namespaces['rsm']}}}ExchangedDocument")
        doc_id = etree.SubElement(doc, f"{{{self.xml_namespaces['ram']}}}ID")
        doc_id.text = data.get('invoice_number', 'RE-0001')
        
        doc_type = etree.SubElement(doc, f"{{{self.xml_namespaces['ram']}}}TypeCode")
        doc_type.text = "380"  # Commercial invoice
        
        issue_date = etree.SubElement(doc, f"{{{self.xml_namespaces['ram']}}}IssueDateTime")
        date_string = etree.SubElement(issue_date, f"{{{self.xml_namespaces['udt']}}}DateTimeString")
        date_string.set("format", "102")
        date_string.text = data.get('invoice_date', datetime.now().strftime('%Y%m%d'))
        
        # SupplyChainTradeTransaction
        transaction = etree.SubElement(root, f"{{{self.xml_namespaces['rsm']}}}SupplyChainTradeTransaction")
        
        # Line Items
        items = data.get('invoice_items') or data.get('offer_items') or []
        for idx, item in enumerate(items, 1):
            self._add_line_item(transaction, item, idx, data.get('vat_rate', 19))
        
        # Seller & Buyer
        agreement = etree.SubElement(transaction, f"{{{self.xml_namespaces['ram']}}}ApplicableHeaderTradeAgreement")
        self._add_seller(agreement, profile)
        self._add_buyer(agreement, data.get('client_data', {}))
        
        # Settlement
        settlement = etree.SubElement(transaction, f"{{{self.xml_namespaces['rsm']}}}ApplicableHeaderTradeSettlement")
        self._add_tax_totals(settlement, data)
        self._add_monetary_summation(settlement, data)
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')
    
    # ========== XML EMBEDDING ==========
    
    def embed_xml_in_pdf(self, pdf_bytes: bytes, xml_string: str) -> bytes:
        """Встраивание XML в PDF для ZUGFeRD"""
        try:
            from PyPDF2 import PdfReader, PdfWriter
            
            pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
            pdf_writer = PdfWriter()
            
            for page in pdf_reader.pages:
                pdf_writer.add_page(page)
            
            pdf_writer.add_attachment("factur-x.xml", xml_string.encode('utf-8'))
            
            output = io.BytesIO()
            pdf_writer.write(output)
            output.seek(0)
            return output.getvalue()
        
        except ImportError:
            logger.warning("PyPDF2 not installed - returning PDF without XML")
            return pdf_bytes
    
    # ========== HELPER METHODS ==========
    
    def _safe_str(self, text: any) -> str:
        """Безопасное преобразование в строку с заменой спецсимволов"""
        s = str(text).strip()
        # Замена немецких символов для FPDF (не поддерживает UTF-8)
        replacements = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
            'ß': 'ss'
        }
        for old, new in replacements.items():
            s = s.replace(old, new)
        return s
    
    def _add_line_item(self, transaction, item, idx, vat_rate):
        """Добавление позиции в XML"""
        line_item = etree.SubElement(transaction, f"{{{self.xml_namespaces['ram']}}}IncludedSupplyChainTradeLineItem")
        
        assoc_doc = etree.SubElement(line_item, f"{{{self.xml_namespaces['ram']}}}AssociatedDocumentLineDocument")
        line_id = etree.SubElement(assoc_doc, f"{{{self.xml_namespaces['ram']}}}LineID")
        line_id.text = str(idx)
        
        product = etree.SubElement(line_item, f"{{{self.xml_namespaces['ram']}}}SpecifiedTradeProduct")
        product_name = etree.SubElement(product, f"{{{self.xml_namespaces['ram']}}}Name")
        product_name.text = item.get('description', 'Position')
        
        agreement = etree.SubElement(line_item, f"{{{self.xml_namespaces['ram']}}}SpecifiedLineTradeAgreement")
        gross_price = etree.SubElement(agreement, f"{{{self.xml_namespaces['ram']}}}GrossPriceProductTradePrice")
        charge_amount = etree.SubElement(gross_price, f"{{{self.xml_namespaces['ram']}}}ChargeAmount")
        charge_amount.text = f"{item.get('price', 0):.2f}"
        
        delivery = etree.SubElement(line_item, f"{{{self.xml_namespaces['ram']}}}SpecifiedLineTradeDelivery")
        billed_qty = etree.SubElement(delivery, f"{{{self.xml_namespaces['ram']}}}BilledQuantity")
        billed_qty.set("unitCode", self._get_unit_code(item.get('unit', 'Stk')))
        billed_qty.text = str(item.get('quantity', 1))
        
        settlement = etree.SubElement(line_item, f"{{{self.xml_namespaces['ram']}}}SpecifiedLineTradeSettlement")
        monetary_summation = etree.SubElement(settlement, f"{{{self.xml_namespaces['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
        line_total = etree.SubElement(monetary_summation, f"{{{self.xml_namespaces['ram']}}}LineTotalAmount")
        line_total.text = f"{item.get('total', 0):.2f}"
    
    def _add_seller(self, agreement, profile):
        """Добавление продавца в XML"""
        seller = etree.SubElement(agreement, f"{{{self.xml_namespaces['ram']}}}SellerTradeParty")
        seller_name = etree.SubElement(seller, f"{{{self.xml_namespaces['ram']}}}Name")
        seller_name.text = profile.get('company_name', 'Firma')
        
        seller_address = etree.SubElement(seller, f"{{{self.xml_namespaces['ram']}}}PostalTradeAddress")
        seller_postcode = etree.SubElement(seller_address, f"{{{self.xml_namespaces['ram']}}}PostcodeCode")
        seller_postcode.text = profile.get('postal_code', '')
        seller_line_one = etree.SubElement(seller_address, f"{{{self.xml_namespaces['ram']}}}LineOne")
        seller_line_one.text = profile.get('street', '')
        seller_city = etree.SubElement(seller_address, f"{{{self.xml_namespaces['ram']}}}CityName")
        seller_city.text = profile.get('city', '')
        seller_country = etree.SubElement(seller_address, f"{{{self.xml_namespaces['ram']}}}CountryID")
        seller_country.text = "DE"
        
        if profile.get('tax_id'):
            seller_tax = etree.SubElement(seller, f"{{{self.xml_namespaces['ram']}}}SpecifiedTaxRegistration")
            seller_tax_id = etree.SubElement(seller_tax, f"{{{self.xml_namespaces['ram']}}}ID")
            seller_tax_id.set("schemeID", "FC")
            seller_tax_id.text = profile.get('tax_id')
    
    def _add_buyer(self, agreement, client_data):
        """Добавление покупателя в XML"""
        buyer = etree.SubElement(agreement, f"{{{self.xml_namespaces['ram']}}}BuyerTradeParty")
        buyer_name = etree.SubElement(buyer, f"{{{self.xml_namespaces['ram']}}}Name")
        buyer_name.text = client_data.get('company_name', 'Kunde')
    
    def _add_tax_totals(self, settlement, data):
        """Добавление налоговых итогов в XML"""
        currency = etree.SubElement(settlement, f"{{{self.xml_namespaces['ram']}}}InvoiceCurrencyCode")
        currency.text = "EUR"
        
        tax_total = etree.SubElement(settlement, f"{{{self.xml_namespaces['ram']}}}ApplicableTradeTax")
        calculated_amount = etree.SubElement(tax_total, f"{{{self.xml_namespaces['ram']}}}CalculatedAmount")
        calculated_amount.text = f"{data.get('total_vat', 0):.2f}"
        tax_type_code = etree.SubElement(tax_total, f"{{{self.xml_namespaces['ram']}}}TypeCode")
        tax_type_code.text = "VAT"
        basis_amount = etree.SubElement(tax_total, f"{{{self.xml_namespaces['ram']}}}BasisAmount")
        basis_amount.text = f"{data.get('total_net', 0):.2f}"
        tax_category_code = etree.SubElement(tax_total, f"{{{self.xml_namespaces['ram']}}}CategoryCode")
        tax_category_code.text = "S" if data.get('vat_rate', 0) > 0 else "Z"
        tax_percent = etree.SubElement(tax_total, f"{{{self.xml_namespaces['ram']}}}RateApplicablePercent")
        tax_percent.text = str(data.get('vat_rate', 19))
    
    def _add_monetary_summation(self, settlement, data):
        """Добавление денежных итогов в XML"""
        monetary = etree.SubElement(settlement, f"{{{self.xml_namespaces['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
        
        line_total_amount = etree.SubElement(monetary, f"{{{self.xml_namespaces['ram']}}}LineTotalAmount")
        line_total_amount.text = f"{data.get('total_net', 0):.2f}"
        
        tax_basis_total = etree.SubElement(monetary, f"{{{self.xml_namespaces['ram']}}}TaxBasisTotalAmount")
        tax_basis_total.text = f"{data.get('total_net', 0):.2f}"
        
        tax_total_amount = etree.SubElement(monetary, f"{{{self.xml_namespaces['ram']}}}TaxTotalAmount")
        tax_total_amount.set("currencyID", "EUR")
        tax_total_amount.text = f"{data.get('total_vat', 0):.2f}"
        
        grand_total = etree.SubElement(monetary, f"{{{self.xml_namespaces['ram']}}}GrandTotalAmount")
        grand_total.text = f"{data.get('total_gross', 0):.2f}"
        
        due_payable = etree.SubElement(monetary, f"{{{self.xml_namespaces['ram']}}}DuePayableAmount")
        due_payable.text = f"{data.get('total_gross', 0):.2f}"
    
    def _get_unit_code(self, unit: str) -> str:
        """Конвертация единиц измерения в UN/ECE коды"""
        unit_map = {
            'Stk': 'C62', 'Std': 'HUR', 'Tag': 'DAY',
            'kg': 'KGM', 'm': 'MTR', 'm²': 'MTK',
            'm³': 'MTQ', 'km': 'KTM', 'l': 'LTR'
        }
        return unit_map.get(unit, 'C62')
