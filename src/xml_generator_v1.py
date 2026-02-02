"""
xml_generator_v1.py
ИСПРАВЛЕНО: Используется pikepdf вместо PyPDF2
"""
import io
from datetime import datetime
from lxml import etree


class XMLGenerator:
    """Генератор XML для E-Rechnung"""
    
    def __init__(self):
        self.namespaces = {
            'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
            'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
            'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
            'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100'
        }
    
    def generate_zugferd_xml(self, invoice_data: dict, profile: dict) -> str:
        """Генерация ZUGFeRD XML (встраивается в PDF)"""
        
        # Корневой элемент
        root = etree.Element(
            f"{{{self.namespaces['rsm']}}}CrossIndustryInvoice",
            nsmap=self.namespaces
        )
        
        # ExchangedDocumentContext
        context = etree.SubElement(root, f"{{{self.namespaces['rsm']}}}ExchangedDocumentContext")
        guideline = etree.SubElement(context, f"{{{self.namespaces['ram']}}}GuidelineSpecifiedDocumentContextParameter")
        guideline_id = etree.SubElement(guideline, f"{{{self.namespaces['ram']}}}ID")
        guideline_id.text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"
        
        # ExchangedDocument
        doc = etree.SubElement(root, f"{{{self.namespaces['rsm']}}}ExchangedDocument")
        
        doc_id = etree.SubElement(doc, f"{{{self.namespaces['ram']}}}ID")
        doc_id.text = invoice_data.get('invoice_number') or invoice_data.get('offer_number', 'RE-0001')
        
        doc_type = etree.SubElement(doc, f"{{{self.namespaces['ram']}}}TypeCode")
        doc_type.text = "380"  # Commercial invoice
        
        issue_date = etree.SubElement(doc, f"{{{self.namespaces['ram']}}}IssueDateTime")
        date_string = etree.SubElement(issue_date, f"{{{self.namespaces['udt']}}}DateTimeString")
        date_string.set("format", "102")
        date_string.text = invoice_data.get('invoice_date') or invoice_data.get('offer_date', datetime.now().strftime('%Y%m%d'))
        
        # SupplyChainTradeTransaction
        transaction = etree.SubElement(root, f"{{{self.namespaces['rsm']}}}SupplyChainTradeTransaction")
        
        # Line Items
        items = invoice_data.get('invoice_items') or invoice_data.get('offer_items') or []
        for idx, item in enumerate(items, 1):
            line_item = etree.SubElement(transaction, f"{{{self.namespaces['ram']}}}IncludedSupplyChainTradeLineItem")
            
            assoc_doc = etree.SubElement(line_item, f"{{{self.namespaces['ram']}}}AssociatedDocumentLineDocument")
            line_id = etree.SubElement(assoc_doc, f"{{{self.namespaces['ram']}}}LineID")
            line_id.text = str(idx)
            
            product = etree.SubElement(line_item, f"{{{self.namespaces['ram']}}}SpecifiedTradeProduct")
            product_name = etree.SubElement(product, f"{{{self.namespaces['ram']}}}Name")
            product_name.text = item.get('description', 'Position')
            
            agreement = etree.SubElement(line_item, f"{{{self.namespaces['ram']}}}SpecifiedLineTradeAgreement")
            gross_price = etree.SubElement(agreement, f"{{{self.namespaces['ram']}}}GrossPriceProductTradePrice")
            charge_amount = etree.SubElement(gross_price, f"{{{self.namespaces['ram']}}}ChargeAmount")
            charge_amount.text = f"{item.get('price', 0):.2f}"
            
            delivery = etree.SubElement(line_item, f"{{{self.namespaces['ram']}}}SpecifiedLineTradeDelivery")
            billed_qty = etree.SubElement(delivery, f"{{{self.namespaces['ram']}}}BilledQuantity")
            billed_qty.set("unitCode", self._get_unit_code(item.get('unit', 'Stk')))
            billed_qty.text = str(item.get('quantity', 1))
            
            settlement = etree.SubElement(line_item, f"{{{self.namespaces['ram']}}}SpecifiedLineTradeSettlement")
            monetary_summation = etree.SubElement(settlement, f"{{{self.namespaces['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
            line_total = etree.SubElement(monetary_summation, f"{{{self.namespaces['ram']}}}LineTotalAmount")
            line_total.text = f"{item.get('total', 0):.2f}"
        
        # Applicable Header Trade Agreement (Seller/Buyer)
        agreement = etree.SubElement(transaction, f"{{{self.namespaces['ram']}}}ApplicableHeaderTradeAgreement")
        
        # Seller
        seller = etree.SubElement(agreement, f"{{{self.namespaces['ram']}}}SellerTradeParty")
        seller_name = etree.SubElement(seller, f"{{{self.namespaces['ram']}}}Name")
        seller_name.text = profile.get('company_name', 'Firma')
        
        # Buyer
        buyer = etree.SubElement(agreement, f"{{{self.namespaces['ram']}}}BuyerTradeParty")
        buyer_name = etree.SubElement(buyer, f"{{{self.namespaces['ram']}}}Name")
        buyer_name.text = invoice_data.get('client_data', {}).get('company_name', 'Kunde')
        
        # Applicable Header Trade Settlement
        settlement = etree.SubElement(transaction, f"{{{self.namespaces['rsm']}}}ApplicableHeaderTradeSettlement")
        currency = etree.SubElement(settlement, f"{{{self.namespaces['ram']}}}InvoiceCurrencyCode")
        currency.text = "EUR"
        
        # Monetary Summation
        monetary = etree.SubElement(settlement, f"{{{self.namespaces['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
        
        grand_total = etree.SubElement(monetary, f"{{{self.namespaces['ram']}}}GrandTotalAmount")
        grand_total.text = f"{invoice_data.get('total_gross', 0):.2f}"
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')
    
    def _get_unit_code(self, unit: str) -> str:
        """Конвертация единиц измерения в UN/ECE коды"""
        unit_map = {
            'Stk': 'C62', 'Std': 'HUR', 'Tag': 'DAY',
            'kg': 'KGM', 'm': 'MTR', 'm²': 'MTK',
            'm³': 'MTQ', 'km': 'KTM', 'l': 'LTR'
        }
        return unit_map.get(unit, 'C62')


def embed_xml_in_pdf(pdf_bytes: bytes, xml_string: str) -> bytes:
    """
    Встраивание XML в PDF для ZUGFeRD
    ИСПРАВЛЕНО: Используется pikepdf вместо PyPDF2
    """
    try:
        import pikepdf
        
        # Открываем PDF
        pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        
        # Создаем вложение
        xml_bytes = xml_string.encode('utf-8')
        
        # Добавляем XML как embedded file
        pdf.attachments['factur-x.xml'] = xml_bytes
        
        # Сохраняем
        output = io.BytesIO()
        pdf.save(output)
        output.seek(0)
        
        return output.getvalue()
    
    except ImportError:
        print("⚠️ pikepdf не установлен - XML не встроен в PDF")
        return pdf_bytes
    except Exception as e:
        print(f"⚠️ Ошибка встраивания XML: {e}")
        return pdf_bytes
