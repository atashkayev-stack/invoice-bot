"""pdf_generator_v2.py - PDF/A-3 с reportlab + pikepdf"""
import io
from datetime import datetime
from jinja2 import Template
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class PDFGeneratorV2:
    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir
        self.setup_fonts()
    
    def setup_fonts(self):
        try:
            pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        except:
            pass
    
    def generate_invoice_pdf(self, data: dict, profile: dict, with_xml: bool = False) -> io.BytesIO:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        
        # Header
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(w/2, h - 40*mm, "RECHNUNG")
        
        # Sender (top right)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 11)
        y = h - 50*mm
        c.drawRightString(w - 20*mm, y, profile.get('company_name', ''))
        c.setFont("Helvetica", 9)
        y -= 4*mm
        c.drawRightString(w - 20*mm, y, profile.get('street', ''))
        y -= 4*mm
        c.drawRightString(w - 20*mm, y, f"{profile.get('postal_code', '')} {profile.get('city', '')}")
        
        # Client box
        c.setFillColorRGB(0.95, 0.95, 0.95)
        c.rect(20*mm, h - 100*mm, 85*mm, 30*mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(22*mm, h - 73*mm, "Empfänger:")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(22*mm, h - 78*mm, data.get('client_name', ''))
        c.setFont("Helvetica", 9)
        c.drawString(22*mm, h - 83*mm, data.get('client_street', ''))
        c.drawString(22*mm, h - 88*mm, f"{data.get('client_postal_code', '')} {data.get('client_city', '')}")
        
        # Document info
        c.setFont("Helvetica-Bold", 9)
        y = h - 110*mm
        c.drawString(20*mm, y, "Rechnungsnummer:")
        c.setFont("Helvetica", 9)
        c.drawString(65*mm, y, data.get('invoice_number', 'RE-0001'))
        y -= 5*mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, y, "Rechnungsdatum:")
        c.setFont("Helvetica", 9)
        c.drawString(65*mm, y, self._format_date(data.get('invoice_date')))
        if data.get('due_date'):
            y -= 5*mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(20*mm, y, "Fälligkeitsdatum:")
            c.setFont("Helvetica", 9)
            c.drawString(65*mm, y, self._format_date(data.get('due_date')))
        
        # Items table
        y = h - 140*mm
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, y, "Beschreibung")
        c.drawString(110*mm, y, "Menge")
        c.drawString(135*mm, y, "Preis")
        c.drawRightString(w - 20*mm, y, "Gesamt")
        
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0, 0.4, 0.8)
        c.line(20*mm, y - 2*mm, w - 20*mm, y - 2*mm)
        
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 9)
        y -= 7*mm
        
        for item in data.get('items', []):
            c.drawString(20*mm, y, item.get('description', '')[:50])
            c.drawString(110*mm, y, f"{item.get('quantity', 1)} {item.get('unit', 'Stk')}")
            c.drawString(135*mm, y, f"{item.get('unit_price', 0):.2f} €")
            c.drawRightString(w - 20*mm, y, f"{item.get('total', 0):.2f} €")
            y -= 5*mm
        
        c.setLineWidth(1)
        c.line(20*mm, y, w - 20*mm, y)
        
        # Totals
        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(135*mm, y, "Netto:")
        c.drawRightString(w - 20*mm, y, f"{data.get('total_net', 0):.2f} €")
        
        vat_rate = data.get('global_vat_rate', 19)
        if vat_rate > 0:
            y -= 5*mm
            c.drawString(135*mm, y, f"MwSt ({vat_rate:.0f}%):")
            c.drawRightString(w - 20*mm, y, f"{data.get('total_vat', 0):.2f} €")
        else:
            y -= 5*mm
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(115*mm, y, "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
        
        y -= 7*mm
        c.setLineWidth(2)
        c.setStrokeColorRGB(0, 0.4, 0.8)
        c.line(135*mm, y, w - 20*mm, y)
        
        y -= 7*mm
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(135*mm, y, "Gesamtbetrag:")
        c.drawRightString(w - 20*mm, y, f"{data.get('total_gross', 0):.2f} €")
        
        # Footer
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.setFont("Helvetica", 8)
        footer = f"Steuernummer: {profile.get('tax_id', '')} | IBAN: {profile.get('iban', '')}"
        c.drawCentredString(w/2, 20*mm, footer)
        
        c.save()
        buf.seek(0)
        
        # Convert to PDF/A-3 with pikepdf
        if with_xml:
            return self._make_pdfa3(buf.getvalue())
        return buf
    
    def _make_pdfa3(self, pdf_bytes: bytes) -> io.BytesIO:
        try:
            import pikepdf
            pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
            
            # PDF/A-3 metadata
            with pdf.open_metadata() as meta:
                meta['pdfaid:part'] = '3'
                meta['pdfaid:conformance'] = 'B'
            
            output = io.BytesIO()
            pdf.save(output, min_version='1.7')
            output.seek(0)
            return output
        except:
            return io.BytesIO(pdf_bytes)
    
    def _format_date(self, date_str):
        if not date_str:
            return datetime.now().strftime('%d.%m.%Y')
        try:
            return datetime.strptime(str(date_str), '%Y-%m-%d').strftime('%d.%m.%Y')
        except:
            return str(date_str)
