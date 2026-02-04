"""pdf_generator_v3.py - ПОЛНЫЙ макет с VAT per item, скидками, доставкой"""
import io
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class PDFGeneratorV3:

    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir
        self.setup_fonts()

    def setup_fonts(self):
        try:
            pdfmetrics.registerFont(
                TTFont('DejaVu',
                       '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
            pdfmetrics.registerFont(
                TTFont('DejaVu-Bold',
                       '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        except:
            pass

    def generate_invoice_pdf(self,
                             data: dict,
                             profile: dict,
                             with_xml: bool = False) -> io.BytesIO:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4

        # Header
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(w / 2, h - 40 * mm, "RECHNUNG")

        # Sender (top right)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 11)
        y = h - 50 * mm
        c.drawRightString(w - 20 * mm, y, profile.get('company_name', ''))
        c.setFont("Helvetica", 9)
        y -= 4 * mm
        c.drawRightString(w - 20 * mm, y, profile.get('street', ''))
        y -= 4 * mm
        c.drawRightString(
            w - 20 * mm, y,
            f"{profile.get('postal_code', '')} {profile.get('city', '')}")

        # Client box
        c.setFillColorRGB(0.95, 0.95, 0.95)
        c.rect(20 * mm, h - 100 * mm, 85 * mm, 30 * mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(22 * mm, h - 73 * mm, "Empfänger:")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(22 * mm, h - 78 * mm, data.get('client_name', ''))
        c.setFont("Helvetica", 9)
        c.drawString(22 * mm, h - 83 * mm, data.get('client_street', ''))
        c.drawString(
            22 * mm, h - 88 * mm,
            f"{data.get('client_postal_code', '')} {data.get('client_city', '')}"
        )
        if data.get('client_country') and data.get('client_country') != 'DE':
            c.drawString(22 * mm, h - 93 * mm,
                         f"{data.get('client_country', '')}")

        # Document info
        c.setFont("Helvetica-Bold", 9)
        y = h - 110 * mm
        c.drawString(20 * mm, y, "Rechnungsnummer:")
        c.setFont("Helvetica", 9)
        c.drawString(65 * mm, y, data.get('invoice_number', 'RE-0001'))

        y -= 5 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, "Rechnungsdatum:")
        c.setFont("Helvetica", 9)
        c.drawString(65 * mm, y, self._format_date(data.get('invoice_date')))

        y -= 5 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, "Leistungsdatum:")
        c.setFont("Helvetica", 9)
        c.drawString(65 * mm, y, self._format_date(data.get('delivery_date')))

        if data.get('due_date'):
            y -= 5 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(20 * mm, y, "Fälligkeitsdatum:")
            c.setFont("Helvetica", 9)
            c.drawString(65 * mm, y, self._format_date(data.get('due_date')))

        if data.get('purchase_order'):
            y -= 5 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(20 * mm, y, "Bestellnummer:")
            c.setFont("Helvetica", 9)
            c.drawString(65 * mm, y, str(data.get('purchase_order')))

        # Items table header
        y = h - 145 * mm
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 8)

        vat_per_item = data.get('vat_per_item', False)

        if vat_per_item:
            # С колонкой VAT
            c.drawString(20 * mm, y, "Beschreibung")
            c.drawString(95 * mm, y, "Menge")
            c.drawString(115 * mm, y, "Preis")
            c.drawString(135 * mm, y, "MwSt")
            c.drawRightString(w - 20 * mm, y, "Gesamt")
        else:
            # Без VAT колонки
            c.drawString(20 * mm, y, "Beschreibung")
            c.drawString(110 * mm, y, "Menge")
            c.drawString(135 * mm, y, "Preis")
            c.drawRightString(w - 20 * mm, y, "Gesamt")

        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0, 0.4, 0.8)
        c.line(20 * mm, y - 2 * mm, w - 20 * mm, y - 2 * mm)

        # Items
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 8)
        y -= 7 * mm

        for item in data.get('items', []):
            desc = item.get('description', '')[:45]
            qty = item.get('quantity', 1)
            unit = item.get('unit', 'Stk')
            price = item.get('unit_price', 0)
            total = item.get('total_price', 0)

            if vat_per_item:
                vat = item.get('vat_rate', 19)
                c.drawString(20 * mm, y, desc)
                c.drawString(95 * mm, y, f"{qty} {unit}")
                c.drawString(115 * mm, y, f"{price:.2f} €")
                c.drawString(135 * mm, y, f"{vat:.0f}%")
                c.drawRightString(w - 20 * mm, y, f"{total:.2f} €")
            else:
                c.drawString(20 * mm, y, desc)
                c.drawString(110 * mm, y, f"{qty} {unit}")
                c.drawString(135 * mm, y, f"{price:.2f} €")
                c.drawRightString(w - 20 * mm, y, f"{total:.2f} €")

            y -= 5 * mm

        c.setLineWidth(1)
        c.line(20 * mm, y, w - 20 * mm, y)

        # Totals section
        y -= 10 * mm
        c.setFont("Helvetica", 9)

        # Zwischensumme
        subtotal = data.get('total_net', 0)
        if data.get('discount_amount', 0) > 0 or data.get(
                'discount_percentage', 0) > 0:
            subtotal_before_discount = subtotal + data.get(
                'discount_amount', 0)
            c.drawString(125 * mm, y, "Zwischensumme:")
            c.drawRightString(w - 20 * mm, y,
                              f"{subtotal_before_discount:.2f} €")
            y -= 5 * mm

            # Rabatt
            discount_pct = data.get('discount_percentage', 0)
            discount_amt = data.get('discount_amount', 0)
            if discount_pct > 0:
                c.drawString(125 * mm, y, f"Rabatt ({discount_pct:.1f}%):")
            else:
                c.drawString(125 * mm, y, "Rabatt:")
            c.drawRightString(w - 20 * mm, y, f"-{discount_amt:.2f} €")
            y -= 5 * mm

        # Netto
        c.drawString(125 * mm, y, "Netto:")
        c.drawRightString(w - 20 * mm, y, f"{subtotal:.2f} €")

        # Versand
        shipping = data.get('shipping_cost', 0)
        if shipping > 0:
            y -= 5 * mm
            c.drawString(125 * mm, y, "Versandkosten:")
            c.drawRightString(w - 20 * mm, y, f"{shipping:.2f} €")

        # MwSt
        y -= 5 * mm
        vat_per_item = data.get('vat_per_item', False)
        total_vat = data.get('total_vat', 0)
        vat_rate = data.get('vat_rate')

        # Kleinunternehmer проверка
        is_kleinunternehmer = profile.get('is_kleinunternehmer', False)

        if is_kleinunternehmer or (vat_rate is not None and vat_rate == 0):
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(105 * mm, y,
                         "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
        elif total_vat > 0:
            if vat_per_item:
                c.setFont("Helvetica", 9)
                c.drawString(125 * mm, y, "MwSt (gemischt):")
            else:
                c.setFont("Helvetica", 9)
                display_vat = vat_rate if vat_rate is not None else profile.get(
                    'default_vat_rate', 19)
                c.drawString(125 * mm, y, f"MwSt ({display_vat:.0f}%):")
            c.drawRightString(w - 20 * mm, y, f"{total_vat:.2f} €")

        # Gesamtbetrag
        y -= 7 * mm
        c.setLineWidth(2)
        c.setStrokeColorRGB(0, 0.4, 0.8)
        c.line(125 * mm, y, w - 20 * mm, y)

        y -= 7 * mm
        c.setFillColorRGB(0, 0.4, 0.8)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(125 * mm, y, "Gesamtbetrag:")
        c.drawRightString(w - 20 * mm, y,
                          f"{data.get('total_gross', 0):.2f} €")

        # Skonto
        if data.get('skonto_percentage', 0) > 0:
            y -= 7 * mm
            c.setFillColorRGB(0.2, 0.6, 0.2)
            c.setFont("Helvetica", 8)
            skonto_pct = data.get('skonto_percentage')
            skonto_days = data.get('skonto_days', 0)
            skonto_amount = data.get('total_gross', 0) * skonto_pct / 100
            c.drawString(
                105 * mm, y,
                f"Bei Zahlung innerhalb {skonto_days} Tagen: {skonto_pct:.1f}% Skonto (-{skonto_amount:.2f} €)"
            )

        # Notes
        if data.get('notes'):
            y -= 15 * mm
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(20 * mm, y, "Hinweise:")
            y -= 5 * mm
            c.setFont("Helvetica", 8)
            notes = data.get('notes', '')
            for line in notes.split('\n')[:3]:
                c.drawString(20 * mm, y, line[:100])
                y -= 4 * mm

        # Lieferadresse (wenn abweichend)
        if data.get('ship_to_name'):
            y -= 10 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(20 * mm, y, "Lieferadresse:")
            y -= 5 * mm
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, data.get('ship_to_name', ''))
            y -= 4 * mm
            c.drawString(20 * mm, y, data.get('ship_to_street', ''))
            y -= 4 * mm
            c.drawString(
                20 * mm, y,
                f"{data.get('ship_to_postal_code', '')} {data.get('ship_to_city', '')}"
            )

        # Footer
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.setFont("Helvetica", 7)
        footer_parts = []
        if profile.get('tax_id'):
            footer_parts.append(f"Steuernummer: {profile.get('tax_id')}")
        if profile.get('vat_id'):
            footer_parts.append(f"USt-IdNr: {profile.get('vat_id')}")
        if profile.get('iban'):
            footer_parts.append(f"IBAN: {profile.get('iban')}")
        if profile.get('trade_register_number'):
            footer_parts.append(f"HRB: {profile.get('trade_register_number')}")

        footer = " | ".join(footer_parts)
        c.drawCentredString(w / 2, 20 * mm, footer)

        c.save()
        buf.seek(0)

        # Convert to PDF/A-3 if needed
        if with_xml:
            return self._make_pdfa3(buf.getvalue())
        return buf

    def _make_pdfa3(self, pdf_bytes: bytes) -> io.BytesIO:
        """PDF/A-3 конверсия"""
        try:
            import pikepdf
            pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))

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
            return datetime.strptime(str(date_str),
                                     '%Y-%m-%d').strftime('%d.%m.%Y')
        except:
            return str(date_str)
