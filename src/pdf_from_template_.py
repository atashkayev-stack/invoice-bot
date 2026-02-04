"""
pdf_from_template.py
Генератор PDF из HTML шаблонов + ZUGFeRD XML
"""
import io
import os
from jinja2 import Template
from xhtml2pdf import pisa
from datetime import datetime

# Импортируем существующий XML генератор
try:
    from .xml_generator_v1 import XMLGenerator, embed_xml_in_pdf
except ImportError:
    from xml_generator_v1 import XMLGenerator, embed_xml_in_pdf


class PDFFromTemplate:
    """Генератор PDF из HTML шаблонов"""
    
    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir
        self.xml_gen = XMLGenerator()  # Используем существующий генератор
    
    def generate_invoice_pdf(self, data: dict, profile: dict, with_xml: bool = False) -> io.BytesIO:
        """
        Генерация счета из шаблона
        
        Args:
            data: Данные счета
            profile: Профиль пользователя
            with_xml: Встроить ZUGFeRD XML (True/False)
        """
        template_path = os.path.join(self.templates_dir, "invoice_template.html")
        
        # Подготовка данных для шаблона
        template_data = self._prepare_invoice_data(data, profile)
        
        # Заполнение шаблона
        with open(template_path, 'r', encoding='utf-8') as f:
            template = Template(f.read())
        
        html = template.render(**template_data)
        
        # Конвертация в PDF
        pdf_bytes = self._html_to_pdf(html)
        
        # Если нужен ZUGFeRD - встраиваем XML
        if with_xml:
            xml_string = self.xml_gen.generate_zugferd_xml(data, profile)
            pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)
        
        return io.BytesIO(pdf_bytes)
    
    def generate_offer_pdf(self, data: dict, profile: dict, with_xml: bool = False) -> io.BytesIO:
        """Генерация оффера из шаблона"""
        template_path = os.path.join(self.templates_dir, "offer_template.html")
        
        template_data = self._prepare_offer_data(data, profile)
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template = Template(f.read())
        
        html = template.render(**template_data)
        
        pdf_bytes = self._html_to_pdf(html)
        
        if with_xml:
            xml_string = self.xml_gen.generate_zugferd_xml(data, profile)
            pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)
        
        return io.BytesIO(pdf_bytes)
    
    def generate_xml_only(self, data: dict, profile: dict) -> str:
        """Генерация только XML (XRechnung)"""
        return self.xml_gen.generate_zugferd_xml(data, profile)
    
    def _html_to_pdf(self, html_string: str) -> bytes:
        """Конвертация HTML в PDF с помощью xhtml2pdf"""
        result = io.BytesIO()
        
        # xhtml2pdf требует bytes
        html_bytes = html_string.encode('utf-8')
        
        # Конвертация
        pisa_status = pisa.CreatePDF(
            io.BytesIO(html_bytes),
            dest=result,
            encoding='utf-8'
        )
        
        if pisa_status.err:
            raise Exception(f"PDF generation error: {pisa_status.err}")
        
        result.seek(0)
        return result.getvalue()
    
    def _prepare_invoice_data(self, data: dict, profile: dict) -> dict:
        """Подготовка данных для шаблона счета"""
        client = data.get('client_data', {})
        items = data.get('invoice_items', [])
        
        return {
            'sender_company': profile.get('company_name', ''),
            'sender_street': profile.get('street', ''),
            'sender_city': f"{profile.get('postal_code', '')} {profile.get('city', '')}".strip(),
            'sender_tax_id': profile.get('tax_id', ''),
            'sender_iban': profile.get('iban', ''),
            'client_company': client.get('company_name', ''),
            'client_address': client.get('address', ''),
            'invoice_number': data.get('invoice_number', 'RE-0001'),
            'invoice_date': self._format_date(data.get('invoice_date')),
            'due_date': self._format_date(data.get('due_date')) if data.get('due_date') else None,
            'items': [
                {
                    'description': item.get('description', ''),
                    'quantity': f"{float(item.get('quantity', 1)):.2f}",
                    'unit': item.get('unit', 'Stk'),
                    'price': f"{float(item.get('price', 0)):.2f}",
                    'total': f"{float(item.get('total', 0)):.2f}"
                }
                for item in items
            ],
            'total_net': f"{float(data.get('total_net', 0)):.2f}",
            'total_vat': f"{float(data.get('total_vat', 0)):.2f}",
            'total_gross': f"{float(data.get('total_gross', 0)):.2f}",
            'vat_rate': float(data.get('vat_rate', 19))
        }
    
    def _prepare_offer_data(self, data: dict, profile: dict) -> dict:
        """Подготовка данных для шаблона оффера"""
        client = data.get('client_data', {})
        items = data.get('offer_items', [])
        
        return {
            'sender_company': profile.get('company_name', ''),
            'sender_street': profile.get('street', ''),
            'sender_city': f"{profile.get('postal_code', '')} {profile.get('city', '')}".strip(),
            'sender_tax_id': profile.get('tax_id', ''),
            'sender_iban': profile.get('iban', ''),
            'client_company': client.get('company_name', ''),
            'client_address': client.get('address', ''),
            'offer_number': data.get('offer_number', 'ANG-0001'),
            'offer_date': self._format_date(data.get('offer_date')),
            'valid_until': self._format_date(data.get('valid_until')),
            'items': [
                {
                    'description': item.get('description', ''),
                    'quantity': f"{float(item.get('quantity', 1)):.2f}",
                    'unit': item.get('unit', 'Stk'),
                    'price': f"{float(item.get('price', 0)):.2f}",
                    'total': f"{float(item.get('total', 0)):.2f}"
                }
                for item in items
            ],
            'total_net': f"{float(data.get('total_net', 0)):.2f}",
            'total_vat': f"{float(data.get('total_vat', 0)):.2f}",
            'total_gross': f"{float(data.get('total_gross', 0)):.2f}",
            'vat_rate': float(data.get('vat_rate', 19)),
            'notes': data.get('notes', '')
        }
    
    def _format_date(self, date_str):
        """Форматирование даты в немецкий формат"""
        if not date_str:
            return datetime.now().strftime('%d.%m.%Y')
        
        try:
            if '-' in str(date_str):
                date_obj = datetime.strptime(str(date_str), '%Y-%m-%d')
                return date_obj.strftime('%d.%m.%Y')
            elif len(str(date_str)) == 8:
                date_obj = datetime.strptime(str(date_str), '%Y%m%d')
                return date_obj.strftime('%d.%m.%Y')
            else:
                return str(date_str)
        except:
            return str(date_str)
