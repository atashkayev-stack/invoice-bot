import os, logging
from supabase import create_client, Client
from typing import Optional, Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class Database:

    def __init__(self):
        self.client: Client = create_client(os.getenv("SUPABASE_URL"),
                                            os.getenv("SUPABASE_KEY"))

    def get_profile(self, user_id: int) -> Optional[Dict]:
        try:
            r = self.client.table("profiles").select("*").eq(
                "id", user_id).execute()
            return r.data[0] if r.data else None
        except Exception as e:
            logger.error(f"Error get_profile: {e}")
        return None

    def create_profile(self,
                       user_id: int,
                       owner_name: str,
                       username: str = None) -> bool:
        try:
            data = {
                "id": user_id,
                "owner_name": owner_name,
                "username": username,
                "invoice_number_prefix": "RE-",
                "invoice_number_format": 4,
                "customer_id_prefix": "KUND-",
                "offer_number_prefix": "ANG-",
                "next_invoice_number": 1,
                "default_vat_rate": 19.0,
                "postal_code": "",
                "street": "",
                "city": "",
                "country_code": "DE",
                "legal_form": "Einzelunternehmer"
            }
            self.client.table("profiles").insert(data).execute()
            return True
        except Exception as e:
            logger.error(f"Error create_profile: {e}")
        return False

    def update_profile(self, user_id: int, data: Dict) -> bool:
        try:
            self.client.table("profiles").update(data).eq("id",
                                                          user_id).execute()
            return True
        except:
            return False

    def get_all_clients(self, user_id: int) -> List[Dict]:
        try:
            r = self.client.table("clients").select("*").eq(
                "user_id", user_id).order("company_name").execute()
            return r.data or []
        except:
            return []

    def get_client(self, client_id: str) -> Optional[Dict]:
        try:
            r = self.client.table("clients").select("*").eq(
                "id", client_id).execute()
            return r.data[0] if r.data else None
        except:
            return None

    def search_clients(self, user_id: int, search: str) -> List[Dict]:
        all_clients = self.get_all_clients(user_id)
        s = search.lower()
        return [
            c for c in all_clients
            if s in c.get('company_name', '').lower() or s in c.get(
                'city', '').lower() or s in c.get('customer_id', '').lower()
        ]

    def create_or_update_client(self, user_id: int,
                                client_data: Dict) -> Optional[str]:
        try:
            if client_data.get('customer_id'):
                existing = self.client.table("clients").select("*").eq(
                    "user_id",
                    user_id).eq("customer_id",
                                client_data['customer_id']).execute()
                if existing.data:
                    cid = existing.data[0]['id']
                    self.client.table("clients").update(client_data).eq(
                        "id", cid).execute()
                    return cid
            client_data['user_id'] = user_id
            if not client_data.get('customer_id'):
                p = self.get_profile(user_id)
                if p:
                    prefix = p.get('customer_id_prefix', 'KUND-')
                    next_num = p.get('next_customer_number', 1)
                    client_data['customer_id'] = f"{prefix}{next_num:03d}"
                    self.update_profile(user_id,
                                        {"next_customer_number": next_num + 1})
            result = self.client.table("clients").insert(client_data).execute()
            return result.data[0]['id'] if result.data else None
        except:
            return None

    # INVOICES
    def create_invoice(self, invoice_data: Dict) -> Optional[str]:
        try:
            r = self.client.table("invoices").insert(invoice_data).execute()
            return r.data[0]['id'] if r.data else None
        except:
            return None

    def get_invoices(self, user_id: int, limit: int = 10) -> List[Dict]:
        try:
            r = self.client.table("invoices").select("*").eq(
                "user_id", user_id).order("created_at",
                                          desc=True).limit(limit).execute()
            return r.data or []
        except:
            return []

    def get_invoice(self, invoice_id: str) -> Optional[Dict]:
        try:
            r = self.client.table("invoices").select("*").eq(
                "id", invoice_id).execute()
            return r.data[0] if r.data else None
        except:
            return None

    def update_invoice(self, invoice_id: str, data: Dict) -> bool:
        try:
            self.client.table("invoices").update(data).eq(
                "id", invoice_id).execute()
            return True
        except:
            return False

    def create_invoice_items(self, invoice_id: str, items: List[Dict]) -> bool:
        try:
            for idx, item in enumerate(items, 1):
                self.client.table("invoice_items").insert({
                    "invoice_id": invoice_id,
                    "position_number": idx,
                    **item
                }).execute()
            return True
        except:
            return False

    def get_invoice_items(self, invoice_id: str) -> List[Dict]:
        try:
            r = self.client.table("invoice_items").select("*").eq(
                "invoice_id", invoice_id).order("position_number").execute()
            return r.data or []
        except:
            return []

    def generate_invoice_number(self, user_id: int) -> str:
        p = self.get_profile(user_id)
        if not p: return f"RE-{datetime.now().year}-0001"
        prefix = p.get('invoice_number_prefix', 'RE-')
        next_num = p.get('next_invoice_number', 1)
        digits = p.get('invoice_number_format', 4)
        return f"{prefix}{next_num:0{digits}d}"

    def increment_invoice_number(self, user_id: int) -> bool:
        try:
            p = self.get_profile(user_id)
            if p:
                self.update_profile(user_id, {
                    "next_invoice_number":
                    p.get('next_invoice_number', 1) + 1
                })
                return True
            return False
        except:
            return False

    # OFFERS
    def create_offer(self, offer_data: Dict) -> Optional[str]:
        try:
            r = self.client.table("offers").insert(offer_data).execute()
            return r.data[0]['id'] if r.data else None
        except:
            return None

    def get_offers(self, user_id: int, limit: int = 10) -> List[Dict]:
        try:
            r = self.client.table("offers").select("*").eq(
                "user_id", user_id).order("created_at",
                                          desc=True).limit(limit).execute()
            return r.data or []
        except:
            return []

    def get_offer(self, offer_id: str) -> Optional[Dict]:
        try:
            r = self.client.table("offers").select("*").eq("id",
                                                           offer_id).execute()
            return r.data[0] if r.data else None
        except:
            return None

    def update_offer(self, offer_id: str, data: Dict) -> bool:
        try:
            self.client.table("offers").update(data).eq("id",
                                                        offer_id).execute()
            return True
        except:
            return False

    def create_offer_items(self, offer_id: str, items: List[Dict]) -> bool:
        try:
            for idx, item in enumerate(items, 1):
                self.client.table("offer_items").insert({
                    "offer_id": offer_id,
                    "position_number": idx,
                    **item
                }).execute()
            return True
        except:
            return False

    def get_offer_items(self, offer_id: str) -> List[Dict]:
        try:
            r = self.client.table("offer_items").select("*").eq(
                "offer_id", offer_id).order("position_number").execute()
            return r.data or []
        except:
            return []

    def generate_offer_number(self, user_id: int) -> str:
        p = self.get_profile(user_id)
        if not p: return f"ANG-{datetime.now().year}-0001"
        prefix = p.get('offer_number_prefix', 'ANG-')
        next_num = p.get('next_offer_number', 1)
        digits = p.get('offer_number_format', 4)
        return f"{prefix}{next_num:0{digits}d}"

    def increment_offer_number(self, user_id: int) -> bool:
        try:
            p = self.get_profile(user_id)
            if p:
                self.update_profile(
                    user_id,
                    {"next_offer_number": p.get('next_offer_number', 1) + 1})
                return True
            return False
        except:
            return False

    def convert_offer_to_invoice(self, offer_id: str) -> Optional[str]:
        try:
            offer = self.get_offer(offer_id)
            if not offer: return None

            invoice_number = self.generate_invoice_number(offer['user_id'])
            invoice_data = {
                "user_id": offer['user_id'],
                "client_id": offer.get('client_id'),
                "number": invoice_number,
                "invoice_date": datetime.now().date().isoformat(),
                "client_name": offer['client_name'],
                "client_address": offer.get('client_address'),
                "customer_id": offer.get('customer_id'),
                "purchase_order_number": offer.get('purchase_order_number'),
                "amount": offer['amount'],
                "vat_rate": offer['vat_rate'],
                "total": offer['total'],
                "format_type": offer.get('format_type', 'ZUGFeRD'),
                "notes": f"Aus Angebot {offer['offer_number']}",
                "status": "draft"
            }

            invoice_id = self.create_invoice(invoice_data)
            if invoice_id:
                items = self.get_offer_items(offer_id)
                self.create_invoice_items(invoice_id, items)
                self.increment_invoice_number(offer['user_id'])
                self.update_offer(offer_id,
                                  {"converted_to_invoice_id": invoice_id})
                return invoice_id
            return None
        except:
            return None
