"""pdf_from_template_v2.py - PDF через шаблоны + PDF/A-3"""
import io, os
from jinja2 import Template
from xhtml2pdf import pisa
from datetime import datetime, timedelta


class PDFFromTemplateV2:

    def __init__(self, templates_dir="templates/default"):
        self.templates_dir = templates_dir

    def generate_invoice_pdf(self,
                             data: dict,
                             profile: dict,
                             with_xml: bool = False) -> io.BytesIO:
        """Генерация PDF из invoice_template.html"""
        template_path = os.path.join(self.templates_dir,
                                     "invoice_template.html")

        # Подготовка данных
        template_data = self._prepare_invoice_data(data, profile)

        # Загрузка и рендер шаблона
        with open(template_path, 'r', encoding='utf-8') as f:
            template = Template(f.read())

        html = template.render(**template_data)

        # HTML → PDF
        pdf_bytes = self._html_to_pdf(html)

        # PDF/A-3 + XML
        if with_xml:
            from xml_generator_v2 import XMLGeneratorV2, embed_xml_in_pdf
            xml_gen = XMLGeneratorV2()
            xml_string = xml_gen.generate_zugferd_xml(data, profile)
            pdf_bytes = embed_xml_in_pdf(pdf_bytes, xml_string)

        return io.BytesIO(pdf_bytes)

    def _html_to_pdf(self, html_string: str) -> bytes:
        """HTML → PDF через xhtml2pdf"""
        result = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.BytesIO(html_string.encode('utf-8')),
                                     dest=result,
                                     encoding='utf-8')

        if pisa_status.err:
            raise Exception(f"PDF error: {pisa_status.err}")

        result.seek(0)
        return result.getvalue()

    def _prepare_invoice_data(self, data: dict, profile: dict) -> dict:
        """Подготовка данных для шаблона"""
        items = data.get('items', [])
        vat_per_item = data.get('vat_per_item', False)
        global_vat = data.get('global_vat_rate', 19)

        # Считаем subtotal (до скидок)
        subtotal = sum(item.get('total_price', 0) for item in items)

        # Скидка
        discount_percent = data.get('discount_percentage', 0)
        discount_amount = data.get('discount_amount', 0)
        if discount_percent > 0:
            discount_amount = subtotal * discount_percent / 100

        # Итого после скидки
        total_net = subtotal - discount_amount

        # Доставка
        shipping_cost = data.get('shipping_cost', 0)
        shipping_vat_rate = data.get('shipping_vat_rate', global_vat)
        total_net += shipping_cost

        # НДС
        total_vat = 0
        if vat_per_item:
            for item in items:
                item_vat = item.get('total_price', 0) * item.get(
                    'vat_rate', 0) / 100
                total_vat += item_vat
            total_vat += shipping_cost * shipping_vat_rate / 100
        else:
            total_vat = total_net * global_vat / 100

        # Skonto
        skonto_percentage = data.get('skonto_percentage', 0)
        skonto_days = data.get('skonto_days', 0)
        skonto_total = 0
        skonto_date = None
        if skonto_percentage > 0 and skonto_days > 0:
            skonto_total = (total_net + total_vat) * (1 -
                                                      skonto_percentage / 100)
            invoice_date = datetime.strptime(data.get('invoice_date'),
                                             '%Y-%m-%d')
            skonto_date = (invoice_date +
                           timedelta(days=skonto_days)).strftime('%d.%m.%Y')

        return {
            # Sender
            'sender_company':
            profile.get('company_name', ''),
            'sender_street':
            profile.get('street', ''),
            'sender_city':
            f"{profile.get('postal_code', '')} {profile.get('city', '')}".
            strip(),
            'sender_email':
            profile.get('email'),
            'sender_tax_id':
            profile.get('tax_id'),
            'sender_vat_id':
            profile.get('vat_id'),
            'sender_iban':
            profile.get('iban'),
            'sender_bic':
            profile.get('bic'),
            'bank_name':
            profile.get('bank_name'),

            # Client
            'client_company':
            data.get('client_name', ''),
            'client_address':
            f"{data.get('client_street', '')}, {data.get('client_postal_code', '')} {data.get('client_city', '')}"
            .strip(', '),
            'client_email':
            data.get('client_email'),
            'customer_id':
            data.get('customer_id'),

            # Document
            'invoice_number':
            data.get('invoice_number', 'RE-0001'),
            'invoice_date':
            self._format_date(data.get('invoice_date')),
            'delivery_date':
            self._format_date(data.get('delivery_date')),
            'due_date':
            self._format_date(data.get('due_date')),
            'purchase_order':
            data.get('purchase_order'),
            'contract_number':
            data.get('contract_number'),
            'project_number':
            data.get('project_number'),
            'vat_mode':
            data.get('vat_mode', 'standard'),

            # Items
            'items': [{
                'description': item.get('description', ''),
                'quantity': f"{float(item.get('quantity', 1)):.2f}",
                'unit': item.get('unit', 'Stk'),
                'price': f"{float(item.get('unit_price', 0)):.2f}",
                'vat_rate': f"{float(item.get('vat_rate', global_vat)):.0f}",
                'total': f"{float(item.get('total_price', 0)):.2f}"
            } for item in items],
            'vat_per_item':
            vat_per_item,

            # Totals
            'subtotal':
            f"{subtotal:.2f}",
            'discount_percentage':
            discount_percent,
            'discount_amount':
            f"{discount_amount:.2f}",
            'shipping_cost':
            f"{shipping_cost:.2f}",
            'shipping_vat_rate':
            shipping_vat_rate,

            # Totals (Берем данные из колонок БД)
            'total_net':
            f"{float(data.get('amount', 0)):.2f}",
            'total_vat':
            f"{float(data.get('tax_amount', 0)):.2f}",
            'total_gross':
            f"{float(data.get('total', 0)):.2f}",
            'vat_rate':
            f"{global_vat:.0f}",

            # Skonto
            'skonto_percentage':
            skonto_percentage,
            'skonto_days':
            skonto_days,
            'skonto_total':
            f"{skonto_total:.2f}" if skonto_total > 0 else None,
            'skonto_date':
            skonto_date,

            # Shipping address
            'ship_to_name':
            data.get('ship_to_name'),
            'ship_to_street':
            data.get('ship_to_street'),
            'ship_to_postal_code':
            data.get('ship_to_postal_code'),
            'ship_to_city':
            data.get('ship_to_city'),

            # Notes
            'notes':
            data.get('notes')
        }

    def _format_date(self, date_str):
        """Форматирование даты в DD.MM.YYYY"""
        if not date_str:
            return None
        try:
            return datetime.strptime(str(date_str),
                                     '%Y-%m-%d').strftime('%d.%m.%Y')
        except:
            return str(date_str)
