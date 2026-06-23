"""Spinny — live listing API.

Spinny serves its Pune inventory from a JSON API, so we read that directly
instead of parsing HTML. Each car comes with its real photos, price, and
specs. This is the cleanest kind of source: a stable JSON feed. The other
modules in this folder parse HTML, which is more fragile; where a site offers
a feed like this, prefer it.
"""
import requests

from ..base import BaseScraper, HEADERS, record_health

API = "https://api.spinny.com/v3/api/listing/v3/"


class SpinnyScraper(BaseScraper):
    name = "spinny"
    label = "Spinny Pune"
    expected_min = 20
    pages = 10        # ~30 cars per page
    size = 30

    def list_urls(self):
        return [API]  # not used; run() is overridden

    def parse(self, html, url):
        return []

    def run(self, db, filters=None):
        from ...db import upsert_vehicle
        from ..base import match_filters

        rows, error = [], None
        try:
            for page in range(1, self.pages + 1):
                params = {"city": "pune", "product_type": "cars", "page": page, "size": self.size}
                resp = requests.get(API, params=params, headers=HEADERS, timeout=25)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    break
                for r in results:
                    if r.get("sold"):
                        continue
                    rows.append(self._to_row(r))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        cap = (filters or {}).get("max_per_source")
        saved = 0
        for row in rows:
            if not row.get("external_id"):
                continue
            if not match_filters(row, filters):
                continue
            upsert_vehicle(db, row)
            saved += 1
            if cap and saved >= cap:
                break

        fetched = len(rows)
        ok = error is None and fetched >= self.expected_min
        record_health(db, self.name, ok, fetched, self.expected_min,
                       error or ("ok" if ok else "returned fewer rows than expected"))
        db.commit()
        return saved, ok, error

    def _to_row(self, r):
        img = None
        for im in (r.get("images") or []):
            a = (im.get("file") or {}).get("absurl")
            if a:
                img = ("https:" + a) if a.startswith("//") else a
                break

        hub = r.get("hub") or "Pune"
        parts = [p.strip() for p in hub.split(",") if p.strip()]
        locality = parts[1] if len(parts) >= 2 else parts[0]

        owners = r.get("no_of_owners")
        owner_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(owners, f"{owners}th" if owners else None)

        url = r.get("permanent_url") or ""
        if url.startswith("/"):
            url = "https://www.spinny.com" + url

        return {
            "source": "spinny",
            "external_id": str(r.get("id")),
            "source_url": url or None,
            "title": " ".join(str(x) for x in
                               [r.get("make_year"), r.get("make"), r.get("model"), r.get("variant")] if x),
            "make": r.get("make"),
            "model": r.get("model"),
            "variant": r.get("variant"),
            "year": r.get("make_year"),
            "km": int(r["mileage"]) if r.get("mileage") else None,
            "fuel": (r.get("fuel_type") or "").title() or None,
            "transmission": (r.get("transmission") or "").title() or None,
            "owners": owner_label,
            "location": locality,
            "seller_type": "dealer",
            "listed_price": int(r["price"]) if r.get("price") else None,
            "image_url": img,
        }
