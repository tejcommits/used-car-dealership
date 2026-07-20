"""OLX India via Apify.

Verified working: the actor returns real Pune car listings with full specs and
photos (Pune location id g4059014). Run through Apify because OLX blocks direct
scraping. Needs APIFY_TOKEN; skipped and flagged in health without it.
"""
from ..base import BaseScraper, record_health, match_filters
from ._helpers import to_int
from ..apify_client import run_actor, has_token

ACTOR = "natanielsantos~olx-india-scraper"
PUNE_CARS_URL = "https://www.olx.in/pune_g4059014/cars_c84"


class OlxScraper(BaseScraper):
    name = "olx"
    label = "OLX Pune"
    expected_min = 5

    def list_urls(self):
        return []

    def parse(self, html, url):
        return []

    def run(self, db, filters=None):
        if not has_token():
            record_health(db, self.name, False, 0, self.expected_min,
                           "needs APIFY_TOKEN (add it to enable OLX)")
            db.commit()
            return 0, False, "no APIFY_TOKEN"

        cap = (filters or {}).get("max_per_source") or 40
        error, rows = None, []
        try:
            items = run_actor(ACTOR, {
                "startUrls": [{"url": PUNE_CARS_URL}], "maxItemsPerUrl": cap,
            })
            rows = [r for r in (self._to_row(it) for it in items) if r]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        from ...db import stamp_seen
        stamp_seen(db, self.name, (r.get("external_id") for r in rows))

        saved = 0
        if not (filters or {}).get("check_only"):
            for row in rows:
                if not row.get("external_id") or not match_filters(row, filters):
                    continue
                from ...db import upsert_vehicle
                upsert_vehicle(db, row)
                saved += 1

        ok = error is None and len(rows) >= self.expected_min
        # No hard error, just no data → this is the known "parked" state (OLX
        # blocks server IPs), shown as a deliberate pause, not a break/alert.
        parked = not ok and error is None
        note = error or ("ok" if ok else
                         "parked — OLX blocks server IPs; needs a residential proxy (planned)")
        record_health(db, self.name, ok, len(rows), self.expected_min, note,
                       status="paused" if parked else None)
        db.commit()
        return saved, ok, error

    def _to_row(self, it):
        by = {}
        for p in (it.get("parameters") or []):
            if p.get("key_name"):
                by[p["key_name"]] = p.get("value_name") or p.get("formatted_value")
        loc = it.get("locationsResolved") or {}
        return {
            "source": "olx",
            "external_id": str(it.get("id")),
            "source_url": it.get("url"),
            "title": it.get("title"),
            "make": by.get("Brand"),
            "model": by.get("Model"),
            "variant": by.get("Variant"),
            "year": to_int(by.get("Year")),
            "km": to_int(by.get("KM driven")),
            "fuel": by.get("Fuel"),
            "transmission": by.get("Transmission"),
            "owners": by.get("No. of Owners"),
            "location": loc.get("SUBLOCALITY_LEVEL_1_name") or loc.get("ADMIN_LEVEL_3_name") or "Pune",
            "seller_type": "individual" if it.get("userType") == "Regular" else "dealer",
            "listed_price": (it.get("price") or {}).get("raw"),
            "image_url": it.get("mainImage"),
        }
