import os, logging
from supabase import create_client, Client
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot_errors.log", encoding="utf-8")
    ])

# Отдельный логгер для supabase (очень полезно)
logging.getLogger("supabase").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.WARNING)

MONEY_Q = Decimal("0.01")


def get_vat_info(profile, vat_rate, vat_mode="standard"):
    is_klein = profile.get("is_kleinunternehmer", False)

    if is_klein:
        vat_mode = "klein"

    rate = float(vat_rate or 0)

    if vat_mode == "klein":
        return {
            "category": "E",
            "reason": "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."
        }

    if vat_mode == "reverse":
        return {
            "category": "AE",
            "reason": "Steuerschuldnerschaft des Leistungsempfängers."
        }

    if vat_mode == "export":
        return {"category": "G", "reason": "Steuerfreie Ausfuhrlieferung."}

    # standard
    return {"category": "S" if rate > 0 else "Z", "reason": None}


def _d(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _money(x: Decimal) -> Decimal:
    return x.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


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
    def compute_invoice_financials(
        self,
        *,
        profile: Dict,
        invoice_payload: Dict,
        items_payload: List[Dict],
    ) -> Tuple[Dict, List[Dict], List[Dict]]:

        vat_mode = (invoice_payload.get("vat_mode") or "standard").lower()
        vat_per_item = bool(invoice_payload.get("vat_per_item", False))

        global_vat_rate = _d(
            invoice_payload.get("global_vat_rate",
                                profile.get("default_vat_rate", 19)))

        discount_percent = _d(invoice_payload.get("discount_percentage", 0))
        discount_amount_form = _d(invoice_payload.get("discount_amount", 0))

        shipping_cost = _money(_d(invoice_payload.get("shipping_cost", 0)))
        shipping_vat_rate = _d(invoice_payload.get("shipping_vat_rate", 0))

        def effective_rate(r: Decimal) -> Decimal:
            return Decimal("0") if vat_mode != "standard" else r

        def pct(r: Decimal) -> Decimal:
            return r / Decimal("100")

        items_out: List[Dict] = []
        by_rate: Dict[str, Dict[str, Decimal]] = {}

        # ---------- ITEMS ----------
        for idx, it in enumerate(items_payload, 1):
            qty = _d(it.get("quantity", 0))
            unit_price = _d(it.get("unit_price", 0))
            line_net = _money(qty * unit_price)

            r = _d(it.get("vat_rate")) if vat_per_item else global_vat_rate
            r_eff = effective_rate(r)
            line_vat = _money(line_net * pct(r_eff))

            info = get_vat_info(profile, float(r_eff), vat_mode)

            item = dict(it)
            item.update({
                "position_number": it.get("position_number") or idx,
                "total_price": str(line_net),
                "vat_rate": str(r),
                "vat_amount": str(line_vat),
                "vat_category_code": info["category"],
            })
            items_out.append(item)

            b = by_rate.setdefault(str(r), {
                "taxable": Decimal("0"),
                "vat": Decimal("0")
            })
            b["taxable"] += line_net
            b["vat"] += line_vat

        items_net = sum((v["taxable"] for v in by_rate.values()), Decimal("0"))

        # ---------- DISCOUNT ----------
        discount_final = Decimal("0")
        if items_net > 0:
            if discount_percent > 0:
                discount_final = items_net * pct(discount_percent)
            elif discount_amount_form > 0:
                discount_final = discount_amount_form

        discount_final = _money(min(discount_final, items_net))

        if discount_final > 0 and items_net > 0:
            factor = (items_net - discount_final) / items_net

            for v in by_rate.values():
                v["taxable"] = _money(v["taxable"] * factor)
                v["vat"] = _money(v["vat"] * factor)

            for it in items_out:
                ln = _money(_d(it["total_price"]) * factor)
                r = _d(it["vat_rate"])
                it["total_price"] = str(ln)
                it["vat_amount"] = str(_money(ln * pct(effective_rate(r))))

        # ---------- SHIPPING ----------
        ship_vat = _money(shipping_cost *
                          pct(effective_rate(shipping_vat_rate)))

        sb = by_rate.setdefault(str(shipping_vat_rate), {
            "taxable": Decimal("0"),
            "vat": Decimal("0")
        })
        sb["taxable"] += shipping_cost
        sb["vat"] += ship_vat

        # ---------- TOTALS ----------
        net = _money(sum(v["taxable"] for v in by_rate.values()))
        vat = _money(sum(v["vat"] for v in by_rate.values()))
        gross = _money(net + vat)

        invoices_update = {
            "amount": float(net),
            "vat_amount": float(vat),
            "total": float(gross),
            "vat_mode": vat_mode,
            "vat_per_item": vat_per_item,
            "global_vat_rate":
            str(global_vat_rate) if not vat_per_item else None,
            "discount_percentage": float(discount_percent),
            "discount_amount": float(discount_final),
            "shipping_cost": float(shipping_cost),
            "shipping_vat_rate": float(shipping_vat_rate),
        }

        # ---------- VAT BREAKDOWN ----------
        breakdown_rows: List[Dict] = []
        for rate_str, v in by_rate.items():
            if v["taxable"] == 0 and v["vat"] == 0:
                continue

            r = _d(rate_str)
            info = get_vat_info(profile, float(effective_rate(r)), vat_mode)

            breakdown_rows.append({
                "vat_rate": str(r),
                "taxable_amount": str(_money(v["taxable"])),
                "vat_amount": str(_money(v["vat"])),
                "vat_category_code": info["category"],
                "exemption_reason": info["reason"],
            })

        return invoices_update, items_out, breakdown_rows

    def create_invoice_vat_breakdown(self, invoice_id: str,
                                     rows: List[Dict]) -> bool:
        try:
            if not rows:
                return True

            payload = [{
                "invoice_id": invoice_id,
                "vat_rate": r.get("vat_rate"),
                "taxable_amount": r.get("taxable_amount"),
                "vat_amount": r.get("vat_amount"),
                "vat_category_code": r.get("vat_category_code"),
                "exemption_reason": r.get("exemption_reason"),
            } for r in rows]

            self.client.table("invoice_vat_breakdown").insert(
                payload).execute()
            return True
        except Exception as e:
            logger.error(f"Error create_invoice_vat_breakdown: {e}")
            return False

    def create_invoice_items(self, invoice_id: str, items: List[Dict]) -> bool:
        """
        ✅ Перезапись: vat_rate и vat_amount уже рассчитаны сервером.
        """
        try:
            payload = []
            for it in items:
                row = {
                    "invoice_id": invoice_id,
                    "position_number": it.get("position_number"),
                    "description": it.get("description"),
                    "quantity": it.get("quantity"),
                    "unit": it.get("unit"),
                    "unit_code": it.get("unit_code") or "C62",
                    "unit_price": it.get("unit_price"),
                    "total_price": it.get("total_price"),  # line net
                    "vat_rate": it.get("vat_rate"),  # всегда есть
                    "vat_amount": it.get("vat_amount"),  # всегда есть
                    "vat_category_code": it.get("vat_category_code"),
                    "article_number": it.get("article_number"),
                    "ean_code": it.get("ean_code"),
                }
                payload.append({k: v for k, v in row.items() if v is not None})

            self.client.table("invoice_items").insert(payload).execute()
            return True
        except Exception as e:
            logger.error(f"Error create_invoice_items: {e}")
            return False

    def create_invoice(self, invoice_data: Dict) -> Optional[str]:
        """
        ✅ Перезапись старого метода (имя то же):
        - ожидает invoice_data['items'] (не пустой список)
        - считает totals + vat_amount по строкам + доставке (канон = БД)
        - пишет invoices + invoice_items + invoice_vat_breakdown
        """
        try:
            user_id = invoice_data.get("user_id")
            if user_id is None:
                raise ValueError("invoice_data.user_id is required")

            items = invoice_data.get("items") or []
            if not isinstance(items, list) or len(items) == 0:
                raise ValueError(
                    "invoice_data.items is required and must be a non-empty list"
                )

            profile = self.get_profile(user_id)
            if not profile:
                raise RuntimeError("Profile not found")

            invoices_update, items_to_insert, breakdown_rows = self.compute_invoice_financials(
                profile=profile,
                invoice_payload=invoice_data,
                items_payload=items,
            )

            # header: items убираем
            header = dict(invoice_data)
            header.pop("items", None)

            # ⚠️ если раньше ты писал amount/total/vat_rate с формы — теперь перезаписываем каноном
            header.update(invoices_update)

            r = self.client.table("invoices").insert(header).execute()
            invoice_id = r.data[0]["id"] if r.data else None
            if not invoice_id:
                return None

            if not self.create_invoice_items(invoice_id, items_to_insert):
                return None

            if not self.create_invoice_vat_breakdown(invoice_id,
                                                     breakdown_rows):
                return None

            return invoice_id

        except Exception as e:
            logger.error(f"Error create_invoice (new): {e}")
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

    def get_invoice_vat_breakdown(self, invoice_id: str):
        r = self.client.table("invoice_vat_breakdown").select("*").eq(
            "invoice_id", invoice_id).order("vat_rate").execute()
        return r.data or []
