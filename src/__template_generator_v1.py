"""
template_generator_v1.py
Система заполнения PDF шаблонов
"""
import io
import logging
from datetime import datetime
from typing import Dict, List
from lxml import etree

logger = logging.getLogger(__name__)


class TemplateGenerator:
    """Генератор документов на основе шаблонов"""
    
    def __init__(self):
        self.xml_namespaces = {
            'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
            'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
            'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
            'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100'
        }
    
    # ========== PDF ИЗ ШАБЛОНА ==========
    
    def fill_pdf_template(self, template_path: str, data: dict, profile: dict) -> io.BytesIO:
        """
        Заполнение PDF шаблона
        
        Args:
            template_path: Путь к шаблону (templates/invoice_template.pdf)
            data: Данные документа
            profile: Профиль пользователя
        """
        try:
            from pdfrw import PdfReader, PdfWriter, PageMerge
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            
            # 1. Создаём overlay с данными
            overlay = self._create_data_overlay(data, profile)
            
            # 2. Читаем шаблон
            template_pdf = PdfReader(template_path)
            
            # 3. Накладываем данные на шаблон
            overlay_pdf = PdfReader(overlay)
            
            for page in template_pdf.pages:
                merger = PageMerge(page)
                merger.add(overlay_pdf.pages[0]).render()
            
            # 4. Сохраняем результат
            output = io.BytesIO()
            PdfWriter(output, trailer=template_pdf).write()
            output.seek(0)
            
            return output
        
        except ImportError:
            logger.error("pdfrw not installed - using fillpdf fallback")
            return self._fill_pdf_fillpdf(template_path, data, profile)
    
    def _create_data_overlay(self, data: dict, profile: dict) -> io.BytesIO:
        """Создание overlay с текстовыми данными"""
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Координаты для полей (настраиваются под шаблон)
        # Эти координаты нужно подобрать под конкретный шаблон
        
        # Данные отправителя (верх справа)
        c.setFont("Helvetica", 10)
        y = height - 50
        c.drawRightString(width - 40, y, str(profile.get('company_name', '')))
        y -= 15
        c.drawRightString(width - 40, y, str(profile.get('street', '')))
        y -= 15
        c.drawRightString(width - 40, y, f"{profile.get('postal_code', '')} {profile.get('city', '')}")
        
        # Данные получателя (слева под шапкой)
        client = data.get('client_data', {})
        y = height - 150
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, str(client.get('company_name', '')))
        y -= 15
        c.setFont("Helvetica", 10)
        address = str(client.get('address', ''))
        for line in address.split(','):
            c.drawString(40, y, line.strip())
            y -= 15
        
        # Номер документа
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, height - 250, f"Nr: {data.get('invoice_number', 'RE-0001')}")
        
        # Дата
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 270, f"Datum: {data.get('invoice_date', datetime.now().strftime('%d.%m.%Y'))}")
        
        # Позиции (таблица)
        items = data.get('invoice_items') or data.get('offer_items') or []
        y = height - 320
        
        for item in items:
            desc = str(item.get('description', ''))
            qty = float(item.get('quantity', 1))
            unit = str(item.get('unit', 'Stk'))
            price = float(item.get('price', 0))
            total = float(item.get('total', 0))
            
            c.drawString(40, y, desc[:50])  # Обрезаем длинные описания
            c.drawString(300, y, f"{qty} {unit}")
            c.drawRightString(400, y, f"{price:.2f} €")
            c.drawRightString(500, y, f"{total:.2f} €")
            y -= 20
        
        # Итоги (внизу справа)
        y = 150
        c.setFont("Helvetica", 10)
        c.drawString(350, y, "Netto:")
        c.drawRightString(500, y, f"{float(data.get('total_net', 0)):.2f} €")
        y -= 15
        
        vat_rate = float(data.get('vat_rate', 19))
        if vat_rate > 0:
            c.drawString(350, y, f"MwSt ({vat_rate:.0f}%):")
            c.drawRightString(500, y, f"{float(data.get('total_vat', 0)):.2f} €")
            y -= 15
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(350, y, "Gesamt:")
        c.drawRightString(500, y, f"{float(data.get('total_gross', 0)):.2f} €")
        
        # Footer
        c.setFont("Helvetica", 8)
        footer = f"Steuernummer: {profile.get('tax_id', '')} | IBAN: {profile.get('iban', '')}"
        c.drawCentredString(width/2, 30, footer)
        
        c.save()
        buffer.seek(0)
        return buffer
    
    def _fill_pdf_fillpdf(self, template_path: str, data: dict, profile: dict) -> io.BytesIO:
        """Заполнение PDF через fillpdf (альтернатива)"""
        try:
            from fillpdf import fillpdfs
            
            # Подготовка данных для формы
            form_data = self._prepare_form_data(data, profile)
            
            # Заполнение
            output = io.BytesIO()
            fillpdfs.write_fillable_pdf(template_path, output, form_data)
            output.seek(0)
            
            return output
        
        except Exception as e:
            logger.error(f"fillpdf error: {e}")
            raise
    
    def _prepare_form_data(self, data: dict, profile: dict) -> dict:
        """Подготовка данных для PDF формы (имена полей)"""
        client = data.get('client_data', {})
        items = data.get('invoice_items') or data.get('offer_items') or []
        
        form_data = {
            # Отправитель
            'sender_company': profile.get('company_name', ''),
            'sender_street': profile.get('street', ''),
            'sender_city': f"{profile.get('postal_code', '')} {profile.get('city', '')}",
            'sender_tax_id': profile.get('tax_id', ''),
            'sender_iban': profile.get('iban', ''),
            
            # Получатель
            'client_company': client.get('company_name', ''),
            'client_address': client.get('address', ''),
            
            # Документ
            'invoice_number': data.get('invoice_number', 'RE-0001'),
            'invoice_date': data.get('invoice_date', datetime.now().strftime('%d.%m.%Y')),
            
            # Итоги
            'total_net': f"{float(data.get('total_net', 0)):.2f}",
            'total_vat': f"{float(data.get('total_vat', 0)):.2f}",
            'total_gross': f"{float(data.get('total_gross', 0)):.2f}",
            'vat_rate': f"{float(data.get('vat_rate', 19)):.0f}",
        }
        
        # Позиции (до 10 штук)
        for idx, item in enumerate(items[:10], 1):
            form_data[f'item_{idx}_description'] = item.get('description', '')
            form_data[f'item_{idx}_quantity'] = str(item.get('quantity', 1))
            form_data[f'item_{idx}_unit'] = item.get('unit', 'Stk')
            form_data[f'item_{idx}_price'] = f"{float(item.get('price', 0)):.2f}"
            form_data[f'item_{idx}_total'] = f"{float(item.get('total', 0)):.2f}"
        
        return form_data
    
    # ========== XML ГЕНЕРАЦИЯ ==========
    
    def generate_xml(self, data: dict, profile: dict) -> str:
        """Генерация XML (без изменений из предыдущей версии)"""
        # Копируй весь метод из document_generator_v1.py
        pass
    
    def embed_xml_in_pdf(self, pdf_bytes: bytes, xml_string: str) -> bytes:
        """Встраивание XML (без изменений)"""
        # Копируй из document_generator_v1.py
        pass
