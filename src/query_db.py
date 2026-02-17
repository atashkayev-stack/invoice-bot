"""
query_db.py — Drop-in замена Supabase SDK на локальный PostgreSQL (psycopg2).

Использование:
    from query_db import Database   # вместо database_v1
    db = Database()                 # читает DATABASE_URL из env
"""

import os
import logging
import sys
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot_errors.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

MONEY_Q = Decimal("0.01")


# ────────────────── helpers (из database_v1) ──────────────────

def get_vat_info(profile, vat_rate, vat_mode="standard"):
    is_klein = profile.get("is_kleinunternehmer", False)
    if is_klein:
        vat_mode = "klein"
    rate = float(vat_rate or 0)
    if vat_mode == "klein":
        return {"category": "E", "reason": "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet."}
    if vat_mode == "reverse":
        return {"category": "AE", "reason": "Steuerschuldnerschaft des Leistungsempfängers."}
    if vat_mode == "export":
        return {"category": "G", "reason": "Steuerfreie Ausfuhrlieferung."}
    return {"category": "S" if rate > 0 else "Z", "reason": None}


def _d(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _money(x: Decimal) -> Decimal:
    return x.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


# ────────────────── SQL helpers ──────────────────


class Database:

    def __init__(self):
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)

    # ── generic SQL ──

    def _exec(self, query, params=None, fetch="all"):
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch == "one":
                    row = cur.fetchone()
                    result = dict(row) if row else None
                elif fetch == "all":
                    result = [dict(r) for r in cur.fetchall()]
                else:
                    result = None
                conn.commit()
                return result
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _insert(self, table, data: Dict) -> Optional[Dict]:
        cols = list(data.keys())
        vals = list(data.values())
        ph = ", ".join(["%s"] * len(cols))
        sql = f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({ph}) RETURNING *'
        return self._exec(sql, vals, fetch="one")

    def _insert_many(self, table, rows: List[Dict]) -> List[Dict]:
        if not rows:
            return []
        cols = list(rows[0].keys())
        ph = ", ".join(["%s"] * len(cols))
        col_str = ", ".join(cols)
        conn = self._pool.getconn()
        try:
            result = []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for row in rows:
                    vals = [row.get(c) for c in cols]
                    cur.execute(f"INSERT INTO {table} ({col_str}) VALUES ({ph}) RETURNING *", vals)
                    r = cur.fetchone()
                    if r:
                        result.append(dict(r))
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _update(self, table, data: Dict, where: Dict):
        set_parts = [f"{k} = %s" for k in data]
        where_parts = [f"{k} = %s" for k in where]
        vals = list(data.values()) + list(where.values())
        sql = f'UPDATE {table} SET {", ".join(set_parts)} WHERE {" AND ".join(where_parts)}'
        self._exec(sql, vals, fetch=None)

    def _select_one(self, table, where: Dict) -> Optional[Dict]:
        where_parts = [f"{k} = %s" for k in where]
        vals = list(where.values())
        sql = f'SELECT * FROM {table} WHERE {" AND ".join(where_parts)} LIMIT 1'
        return self._exec(sql, vals, fetch="one")

    def _select(self, table, where: Dict = None, order=None, limit=None) -> List[Dict]:
        sql = f"SELECT * FROM {table}"
        vals = []
        if where:
            where_parts = [f"{k} = %s" for k in where]
            sql += " WHERE " + " AND ".join(where_parts)
            vals = list(where.values())
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += " LIMIT %s"
            vals.append(limit)
        return self._exec(sql, vals, fetch="all")

    def _delete(self, table, where: Dict) -> List[Dict]:
        where_parts = [f"{k} = %s" for k in where]
        vals = list(where.values())
        sql = f'DELETE FROM {table} WHERE {" AND ".join(where_parts)} RETURNING *'
        return self._exec(sql, vals, fetch="all")

    # ═══════════════════ PROFILES ═══════════════════

    def get_profile(self, user_id: int) -> Optional[Dict]:
        try:
            return self._select_one("profiles", {"id": user_id})
        except Exception as e:
            logger.error(f"Error get_profile: {e}")
            return None

    def create_profile(self, user_id: int, owner_name: str, username: str = None) -> bool:
        try:
            self._insert("profiles", {
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
                "legal_form": "Einzelunternehmer",
            })
            return True
        except Exception as e:
            logger.error(f"Error create_profile: {e}")
            return False

    def update_profile(self, user_id: int, data: Dict) -> bool:
        try:
            clean = {k: v for k, v in data.items() if k != "id"}
            self._update("profiles", clean, {"id": user_id})
            return True
        except Exception as e:
            logger.error(f"Error update_profile user={user_id}: {e}")
            return False

    # ═══════════════════ CLIENTS ═══════════════════

    def get_all_clients(self, user_id: int) -> List[Dict]:
        try:
            return self._select("clients", {"user_id": user_id}, order="company_name")
        except:
            return []

    def get_client(self, client_id: str) -> Optional[Dict]:
        try:
            return self._select_one("clients", {"id": client_id})
        except:
            return None

    def search_clients(self, user_id: int, search: str) -> List[Dict]:
        all_clients = self.get_all_clients(user_id)
        s = search.lower()
        return [
            c for c in all_clients
            if s in c.get("company_name", "").lower()
            or s in c.get("city", "").lower()
            or s in c.get("customer_id", "").lower()
        ]

    def create_or_update_client(self, user_id: int, client_data: Dict) -> Optional[str]:
        try:
            if client_data.get("customer_id"):
                existing = self._exec(
                    "SELECT * FROM clients WHERE user_id = %s AND customer_id = %s LIMIT 1",
                    [user_id, client_data["customer_id"]],
                    fetch="one",
                )
                if existing:
                    cid = existing["id"]
                    self._update("clients", client_data, {"id": cid})
                    return str(cid)
            client_data["user_id"] = user_id
            if not client_data.get("customer_id"):
                p = self.get_profile(user_id)
                if p:
                    prefix = p.get("customer_id_prefix", "KUND-")
                    next_num = p.get("next_customer_number", 1)
                    client_data["customer_id"] = f"{prefix}{next_num:03d}"
                    self.update_profile(user_id, {"next_customer_number": next_num + 1})
            row = self._insert("clients", client_data)
            return str(row["id"]) if row else None
        except:
            return None

    # ═══════════════════ INVOICES ═══════════════════

    def compute_invoice_financials(
        self,
        *,
        profile: Dict,
        invoice_payload: Dict,
        items_payload: List[Dict],
    ) -> Tuple[Dict, List[Dict], List[Dict]]:

        vat_mode = (invoice_payload.get("vat_mode") or "standard").lower()
        vat_per_item = bool(invoice_payload.get("vat_per_item", False))
        global_vat_rate = _d(invoice_payload.get("global_vat_rate", profile.get("default_vat_rate", 19)))
        discount_percent = _d(invoice_payload.get("discount_percentage", 0))
        discount_amount_form = _d(invoice_payload.get("discount_amount", 0))
        shipping_cost = _money(_d(invoice_payload.get("shipping_cost", 0)))
        shipping_vat_rate = _d(invoice_payload.get("shipping_vat_rate", 0))

        def effective_rate(r):
            return Decimal("0") if vat_mode != "standard" else r

        def pct(r):
            return r / Decimal("100")

        items_out, by_rate = [], {}

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
            b = by_rate.setdefault(str(r), {"taxable": Decimal("0"), "vat": Decimal("0")})
            b["taxable"] += line_net
            b["vat"] += line_vat

        items_net = sum((v["taxable"] for v in by_rate.values()), Decimal("0"))

        discount_final = Decimal("0")
        if items_net > 0:
            if discount_amount_form > 0:
                discount_final = discount_amount_form
            elif discount_percent > 0:
                discount_final = items_net * pct(discount_percent)
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

        ship_vat = _money(shipping_cost * pct(effective_rate(shipping_vat_rate)))
        sb = by_rate.setdefault(str(shipping_vat_rate), {"taxable": Decimal("0"), "vat": Decimal("0")})
        sb["taxable"] += shipping_cost
        sb["vat"] += ship_vat

        net = _money(sum(v["taxable"] for v in by_rate.values()))
        vat = _money(sum(v["vat"] for v in by_rate.values()))
        gross = _money(net + vat)

        invoices_update = {
            "amount": float(net),
            "vat_amount": float(vat),
            "total": float(gross),
            "vat_mode": vat_mode,
            "vat_per_item": vat_per_item,
            "global_vat_rate": str(global_vat_rate) if not vat_per_item else None,
            "discount_percentage": float(discount_percent),
            "discount_amount": float(discount_final),
            "shipping_cost": float(shipping_cost),
            "shipping_vat_rate": float(shipping_vat_rate),
        }

        breakdown_rows = []
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

    def create_invoice_vat_breakdown(self, invoice_id: str, rows: List[Dict]) -> bool:
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
            self._insert_many("invoice_vat_breakdown", payload)
            return True
        except Exception as e:
            logger.error(f"Error create_invoice_vat_breakdown: {e}")
            return False

    def create_invoice_items(self, invoice_id: str, items: List[Dict]) -> bool:
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
                    "total_price": it.get("total_price"),
                    "vat_rate": it.get("vat_rate"),
                    "vat_amount": it.get("vat_amount"),
                    "vat_category_code": it.get("vat_category_code"),
                    "article_number": it.get("article_number"),
                    "ean_code": it.get("ean_code"),
                }
                payload.append({k: v for k, v in row.items() if v is not None})
            self._insert_many("invoice_items", payload)
            return True
        except Exception as e:
            logger.error(f"Error create_invoice_items: {e}")
            return False

    def create_invoice(self, invoice_data: Dict) -> Optional[str]:
        try:
            user_id = invoice_data.get("user_id")
            if user_id is None:
                raise ValueError("invoice_data.user_id is required")

            items = invoice_data.get("items") or []
            if not isinstance(items, list) or len(items) == 0:
                raise ValueError("invoice_data.items is required and must be a non-empty list")

            profile = self.get_profile(user_id)
            if not profile:
                raise RuntimeError("Profile not found")

            invoices_update, items_to_insert, breakdown_rows = self.compute_invoice_financials(
                profile=profile,
                invoice_payload=invoice_data,
                items_payload=items,
            )

            header = dict(invoice_data)
            header.pop("items", None)
            header.update(invoices_update)

            row = self._insert("invoices", header)
            invoice_id = str(row["id"]) if row else None
            if not invoice_id:
                return None

            if not self.create_invoice_items(invoice_id, items_to_insert):
                return None
            if not self.create_invoice_vat_breakdown(invoice_id, breakdown_rows):
                return None

            return invoice_id

        except Exception as e:
            logger.error(f"Error create_invoice: {e}")
            return None

    def get_invoices(self, user_id: int, limit: int = 10) -> List[Dict]:
        try:
            return self._select("invoices", {"user_id": user_id}, order="created_at DESC", limit=limit)
        except:
            return []

    def get_invoice(self, invoice_id: str) -> Optional[Dict]:
        try:
            return self._select_one("invoices", {"id": invoice_id})
        except:
            return None

    def update_invoice(self, invoice_id: str, data: Dict) -> bool:
        try:
            self._update("invoices", data, {"id": invoice_id})
            return True
        except:
            return False

    def get_invoice_items(self, invoice_id: str) -> List[Dict]:
        try:
            return self._select("invoice_items", {"invoice_id": invoice_id}, order="position_number")
        except:
            return []

    def get_invoice_vat_breakdown(self, invoice_id: str) -> List[Dict]:
        return self._select("invoice_vat_breakdown", {"invoice_id": invoice_id}, order="vat_rate")

    def generate_invoice_number(self, user_id: int) -> str:
        p = self.get_profile(user_id)
        if not p:
            return f"RE-{datetime.now().year}-0001"
        prefix = p.get("invoice_number_prefix", "RE-")
        next_num = p.get("next_invoice_number", 1)
        digits = p.get("invoice_number_format", 4)
        return f"{prefix}{next_num:0{digits}d}"

    def increment_invoice_number(self, user_id: int) -> bool:
        try:
            p = self.get_profile(user_id)
            if p:
                self.update_profile(user_id, {"next_invoice_number": p.get("next_invoice_number", 1) + 1})
                return True
            return False
        except:
            return False

    # ═══════════════════ OFFERS ═══════════════════

    def compute_offer_financials(
        self,
        *,
        profile: Dict,
        offer_payload: Dict,
        items_payload: List[Dict],
    ) -> Tuple[Dict, List[Dict], List[Dict]]:

        vat_mode = (offer_payload.get("vat_mode") or "standard").lower()
        vat_per_item = bool(offer_payload.get("vat_per_item", False))
        global_vat_rate = _d(offer_payload.get("global_vat_rate", profile.get("default_vat_rate", 19)))
        discount_percent = _d(offer_payload.get("discount_percentage", 0))
        discount_amount_form = _d(offer_payload.get("discount_amount", 0))
        shipping_cost = _money(_d(offer_payload.get("shipping_cost", 0)))
        shipping_vat_rate = _d(offer_payload.get("shipping_vat_rate", 0))

        def effective_rate(r):
            return Decimal("0") if vat_mode != "standard" else r

        def pct(r):
            return r / Decimal("100")

        items_out, by_rate = [], {}

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
            b = by_rate.setdefault(str(r), {"taxable": Decimal("0"), "vat": Decimal("0")})
            b["taxable"] += line_net
            b["vat"] += line_vat

        items_net = sum((v["taxable"] for v in by_rate.values()), Decimal("0"))

        discount_final = Decimal("0")
        if items_net > 0:
            if discount_amount_form > 0:
                discount_final = discount_amount_form
            elif discount_percent > 0:
                discount_final = items_net * pct(discount_percent)
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

        ship_vat = _money(shipping_cost * pct(effective_rate(shipping_vat_rate)))
        sb = by_rate.setdefault(str(shipping_vat_rate), {"taxable": Decimal("0"), "vat": Decimal("0")})
        sb["taxable"] += shipping_cost
        sb["vat"] += ship_vat

        net = _money(sum(v["taxable"] for v in by_rate.values()))
        vat = _money(sum(v["vat"] for v in by_rate.values()))
        gross = _money(net + vat)

        offers_update = {
            "amount": float(net),
            "net_amount": float(net),
            "vat_amount": float(vat),
            "gross_amount": float(gross),
            "total": float(gross),
            "vat_mode": vat_mode,
            "vat_per_item": vat_per_item,
            "global_vat_rate": str(global_vat_rate) if not vat_per_item else None,
            "discount_percentage": float(discount_percent),
            "discount_amount": float(discount_final),
            "shipping_cost": float(shipping_cost),
            "shipping_vat_rate": float(shipping_vat_rate),
        }

        breakdown_rows = []
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

        return offers_update, items_out, breakdown_rows

    def create_offer_vat_breakdown(self, offer_id: str, rows: List[Dict]) -> bool:
        try:
            if not rows:
                return True
            payload = [{
                "offer_id": offer_id,
                "vat_rate": r.get("vat_rate"),
                "taxable_amount": r.get("taxable_amount"),
                "vat_amount": r.get("vat_amount"),
                "vat_category_code": r.get("vat_category_code"),
                "vat_exemption_reason": r.get("exemption_reason"),
            } for r in rows]
            self._insert_many("offer_vat_breakdown", payload)
            return True
        except Exception as e:
            logger.error(f"Error create_offer_vat_breakdown: {e}")
            return False

    def create_offer(self, offer_data: Dict) -> Optional[str]:
        try:
            user_id = offer_data.get("user_id")
            if user_id is None:
                raise ValueError("offer_data.user_id is required")

            items = offer_data.get("items") or []
            if not isinstance(items, list) or len(items) == 0:
                raise ValueError("offer_data.items is required and must be a non-empty list")

            profile = self.get_profile(user_id)
            if not profile:
                raise RuntimeError("Profile not found")

            offers_update, items_to_insert, breakdown_rows = self.compute_offer_financials(
                profile=profile,
                offer_payload=offer_data,
                items_payload=items,
            )

            header = dict(offer_data)
            header.pop("items", None)
            header.update(offers_update)

            row = self._insert("offers", header)
            offer_id = str(row["id"]) if row else None
            if not offer_id:
                return None

            if not self.create_offer_items_new(offer_id, items_to_insert):
                return None
            if not self.create_offer_vat_breakdown(offer_id, breakdown_rows):
                return None

            return offer_id

        except Exception as e:
            logger.error(f"Error create_offer: {e}")
            return None

    def get_offers(self, user_id: int, limit: int = 10) -> List[Dict]:
        try:
            return self._select("offers", {"user_id": user_id}, order="created_at DESC", limit=limit)
        except:
            return []

    def get_offer(self, offer_id: str) -> Optional[Dict]:
        try:
            return self._select_one("offers", {"id": offer_id})
        except:
            return None

    def update_offer(self, offer_id: str, data: Dict) -> bool:
        try:
            self._update("offers", data, {"id": offer_id})
            return True
        except:
            return False

    def create_offer_items_new(self, offer_id: str, items: List[Dict]) -> bool:
        try:
            payload = []
            for it in items:
                row = {
                    "offer_id": offer_id,
                    "position_number": it.get("position_number"),
                    "description": it.get("description"),
                    "quantity": it.get("quantity"),
                    "unit": it.get("unit"),
                    "unit_code": it.get("unit_code") or "C62",
                    "unit_price": it.get("unit_price"),
                    "total_price": it.get("total_price"),
                    "vat_rate": it.get("vat_rate"),
                    "vat_amount": it.get("vat_amount"),
                    "vat_category_code": it.get("vat_category_code"),
                    "article_number": it.get("article_number"),
                    "ean_code": it.get("ean_code"),
                }
                payload.append({k: v for k, v in row.items() if v is not None})
            self._insert_many("offer_items", payload)
            return True
        except Exception as e:
            logger.error(f"Error create_offer_items_new: {e}")
            return False

    def create_offer_items(self, offer_id: str, items: List[Dict]) -> bool:
        try:
            for idx, item in enumerate(items, 1):
                data = {"offer_id": offer_id, "position_number": idx, **item}
                self._insert("offer_items", data)
            return True
        except:
            return False

    def get_offer_items(self, offer_id: str) -> List[Dict]:
        try:
            return self._select("offer_items", {"offer_id": offer_id}, order="position_number")
        except:
            return []

    def get_offer_vat_breakdown(self, offer_id: str) -> List[Dict]:
        return self._select("offer_vat_breakdown", {"offer_id": offer_id}, order="vat_rate")

    def generate_offer_number(self, user_id: int) -> str:
        p = self.get_profile(user_id)
        if not p:
            return f"ANG-{datetime.now().year}-0001"
        prefix = p.get("offer_number_prefix", "ANG-")
        next_num = p.get("next_offer_number", 1)
        digits = p.get("offer_number_format", 4)
        return f"{prefix}{next_num:0{digits}d}"

    def increment_offer_number(self, user_id: int) -> bool:
        try:
            p = self.get_profile(user_id)
            if p:
                self.update_profile(user_id, {"next_offer_number": p.get("next_offer_number", 1) + 1})
                return True
            return False
        except:
            return False

    def convert_offer_to_invoice(self, offer_id: str) -> Optional[str]:
        try:
            offer = self.get_offer(offer_id)
            if not offer:
                return None

            invoice_number = self.generate_invoice_number(offer["user_id"])
            invoice_data = {
                "user_id": offer["user_id"],
                "client_id": offer.get("client_id"),
                "number": invoice_number,
                "invoice_date": datetime.now().date().isoformat(),
                "client_name": offer["client_name"],
                "client_address": offer.get("client_address"),
                "customer_id": offer.get("customer_id"),
                "purchase_order_number": offer.get("purchase_order_number"),
                "amount": offer["amount"],
                "vat_rate": offer["vat_rate"],
                "total": offer["total"],
                "format_type": offer.get("format_type", "ZUGFeRD"),
                "notes": f"Aus Angebot {offer['offer_number']}",
                "status": "draft",
            }

            invoice_id = self.create_invoice(invoice_data)
            if invoice_id:
                items = self.get_offer_items(offer_id)
                self.create_invoice_items(invoice_id, items)
                self.increment_invoice_number(offer["user_id"])
                self.update_offer(offer_id, {"converted_to_invoice_id": invoice_id})
                return invoice_id
            return None
        except:
            return None

    # ═══════════════════ DOCUMENT FILES ═══════════════════

    def save_document_file(self, user_id: int, document_type: str,
                           document_id: str, file_name: str,
                           file_data: bytes) -> Optional[str]:
        try:
            row = self._insert("document_files", {
                "user_id": user_id,
                "document_type": document_type,
                "document_id": document_id,
                "file_name": file_name,
                "file_data": psycopg2.Binary(file_data),
                "file_size": len(file_data),
                "mime_type": "application/pdf",
            })
            return str(row["id"]) if row else None
        except Exception as e:
            logger.error(f"Error save_document_file: {e}")
            return None

    def get_document_file(self, file_id: str) -> Optional[Dict]:
        try:
            return self._select_one("document_files", {"id": file_id})
        except:
            return None

    def get_document_files_by_document(self, document_id: str) -> List[Dict]:
        try:
            return self._select("document_files", {"document_id": document_id})
        except:
            return []

    def get_all_user_files(self, user_id: int) -> List[Dict]:
        try:
            return self._select("document_files", {"user_id": user_id})
        except:
            return []

    # ═══════════════════ USER LIMITS ═══════════════════

    def get_user_limits(self, user_id: int) -> Optional[Dict]:
        try:
            row = self._select_one("user_limits", {"user_id": user_id})
            if row:
                return row
            default_limits = {
                "user_id": user_id,
                "plan_type": "free",
                "invoices_limit": 5,
                "invoices_this_month": 0,
            }
            return self._insert("user_limits", default_limits)
        except Exception as e:
            logger.error(f"Error get_user_limits: {e}")
            return None

    def check_invoice_limit(self, user_id: int) -> Tuple[bool, str]:
        limits = self.get_user_limits(user_id)
        if not limits:
            return True, ""
        if limits.get("plan_type") == "paid":
            return True, ""
        current = limits.get("invoices_this_month", 0)
        limit = limits.get("invoices_limit", 5)
        if current >= limit:
            return False, (
                f"\U0001f6ab Вы достигли лимита бесплатного режима ({limit} счетов в месяц).\n\n"
                f"\U0001f48e Перейдите на платную версию:\n"
                f"\u2022 Неограниченное количество счетов\n"
                f"\u2022 Хранение всех документов\n"
                f"\u2022 Приоритетная поддержка\n\n"
                f"Используйте /upgrade для перехода на Pro."
            )
        remaining = limit - current
        warning = ""
        if remaining <= 2:
            warning = f"\n\n\u26a0\ufe0f Осталось {remaining} из {limit} бесплатных счетов в этом месяце."
        return True, warning

    def increment_invoice_count(self, user_id: int) -> bool:
        try:
            limits = self.get_user_limits(user_id)
            if limits:
                new_count = limits.get("invoices_this_month", 0) + 1
                self._update("user_limits", {
                    "invoices_this_month": new_count,
                    "updated_at": datetime.now().isoformat(),
                }, {"user_id": user_id})
            return True
        except:
            return False

    def upgrade_to_paid(self, user_id: int, months: int = 1) -> bool:
        try:
            paid_until = (datetime.now() + timedelta(days=30 * months)).date()
            self._update("user_limits", {
                "plan_type": "paid",
                "payment_status": "active",
                "paid_until": paid_until.isoformat(),
                "updated_at": datetime.now().isoformat(),
            }, {"user_id": user_id})
            return True
        except:
            return False

    # ═══════════════════ DELETE DATA ═══════════════════

    def delete_all_user_data(self, user_id: int) -> Dict[str, int]:
        stats = {"invoices": 0, "invoice_items": 0, "offers": 0, "offer_items": 0, "clients": 0, "files": 0}
        try:
            self._insert("data_deletion_logs", {
                "user_id": user_id,
                "deletion_type": "full",
                "requested_at": datetime.now().isoformat(),
            })

            invoices = self.get_invoices(user_id, limit=10000)
            for inv in invoices:
                self._delete("invoice_items", {"invoice_id": inv["id"]})
                self._delete("invoice_vat_breakdown", {"invoice_id": inv["id"]})
                stats["invoice_items"] += 1

            r = self._delete("invoices", {"user_id": user_id})
            stats["invoices"] = len(r)

            offers = self.get_offers(user_id, limit=10000)
            for off in offers:
                self._delete("offer_items", {"offer_id": off["id"]})
                self._delete("offer_vat_breakdown", {"offer_id": off["id"]})
                stats["offer_items"] += 1

            r = self._delete("offers", {"user_id": user_id})
            stats["offers"] = len(r)

            r = self._delete("clients", {"user_id": user_id})
            stats["clients"] = len(r)

            r = self._delete("document_files", {"user_id": user_id})
            stats["files"] = len(r)

            self._exec(
                "UPDATE data_deletion_logs SET completed_at = %s, items_deleted = %s WHERE user_id = %s",
                [datetime.now().isoformat(), sum(stats.values()), user_id],
                fetch=None,
            )
            return stats
        except Exception as e:
            logger.error(f"Error delete_all_user_data: {e}")
            return stats

    # ═══════════════════ ARCHIVES ═══════════════════

    def create_archive_request(self, user_id: int, email: str) -> Optional[str]:
        try:
            row = self._insert("document_archives", {"user_id": user_id, "email": email, "status": "pending"})
            return str(row["id"]) if row else None
        except:
            return None

    def get_archive_request(self, archive_id: str) -> Optional[Dict]:
        try:
            return self._select_one("document_archives", {"id": archive_id})
        except:
            return None

    def update_archive_status(self, archive_id: str, status: str, **kwargs) -> bool:
        try:
            data = {"status": status, **kwargs}
            if status == "sent":
                data["sent_at"] = datetime.now().isoformat()
            self._update("document_archives", data, {"id": archive_id})
            return True
        except:
            return False

    # ═══════════════════ FEEDBACK ═══════════════════

    def create_feedback(self, user_id: int, message: str,
                        feedback_type: str = "general",
                        subject: str = None,
                        contact_email: str = None) -> Optional[str]:
        try:
            row = self._insert("user_feedback", {
                "user_id": user_id,
                "feedback_type": feedback_type,
                "subject": subject,
                "message": message,
                "contact_email": contact_email,
                "status": "new",
            })
            return str(row["id"]) if row else None
        except:
            return None

    # ═══════════════════ LOCKING ═══════════════════

    def lock_invoice(self, invoice_id: str) -> bool:
        try:
            self._update("invoices", {"is_locked": True, "locked_at": datetime.now().isoformat()}, {"id": invoice_id})
            return True
        except:
            return False

    def is_invoice_locked(self, invoice_id: str) -> bool:
        invoice = self.get_invoice(invoice_id)
        return invoice.get("is_locked", False) if invoice else False

    def lock_offer(self, offer_id: str) -> bool:
        try:
            self._update("offers", {"is_locked": True}, {"id": offer_id})
            return True
        except:
            return False

    def is_offer_locked(self, offer_id: str) -> bool:
        offer = self.get_offer(offer_id)
        return offer.get("is_locked", False) if offer else False

    # ═══════════════════ COPY ═══════════════════

    def copy_invoice(self, invoice_id: str, user_id: int) -> Optional[str]:
        try:
            original = self.get_invoice(invoice_id)
            if not original or original.get("user_id") != user_id:
                return None
            new_number = self.generate_invoice_number(user_id)
            new_invoice = dict(original)
            for k in ("id", "created_at", "pdf_file_id", "is_locked", "locked_at"):
                new_invoice.pop(k, None)
            new_invoice["number"] = new_number
            new_invoice["invoice_date"] = datetime.now().date().isoformat()
            new_invoice["status"] = "draft"
            new_invoice["notes"] = f"Kopie von {original.get('number', '')}"
            items = self.get_invoice_items(invoice_id)
            items_clean = []
            for item in items:
                it = dict(item)
                for k in ("id", "invoice_id", "created_at"):
                    it.pop(k, None)
                items_clean.append(it)
            new_invoice["items"] = items_clean
            new_id = self.create_invoice(new_invoice)
            if new_id:
                self.increment_invoice_number(user_id)
            return new_id
        except Exception as e:
            logger.error(f"Error copy_invoice: {e}")
            return None

    def copy_offer(self, offer_id: str, user_id: int) -> Optional[str]:
        try:
            original = self.get_offer(offer_id)
            if not original or original.get("user_id") != user_id:
                return None
            new_number = self.generate_offer_number(user_id)
            new_offer = dict(original)
            for k in ("id", "created_at", "pdf_file_id", "is_locked", "converted_to_invoice_id"):
                new_offer.pop(k, None)
            new_offer["offer_number"] = new_number
            new_offer["offer_date"] = datetime.now().date().isoformat()
            new_offer["notes"] = f"Kopie von {original.get('offer_number', '')}"
            items = self.get_offer_items(offer_id)
            items_clean = []
            for item in items:
                it = dict(item)
                for k in ("id", "offer_id", "created_at"):
                    it.pop(k, None)
                items_clean.append(it)
            new_offer["items"] = items_clean
            new_id = self.create_offer(new_offer)
            if new_id:
                self.increment_offer_number(user_id)
            return new_id
        except Exception as e:
            logger.error(f"Error copy_offer: {e}")
            return None
