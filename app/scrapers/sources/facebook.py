"""Facebook Marketplace via Apify.

Verified working: the crowdpull Facebook Marketplace actor returns real Pune
car listings (no login). We run it through Apify, normalise the freeform
titles into our schema, and drop obvious junk (rental/self-drive ads, prices
too low to be a real car).

Needs APIFY_TOKEN. Without it this source is skipped and flagged in health.
"""
import re

from ..base import BaseScraper, record_health, match_filters
from ._helpers import to_int, year_from, split_name
from ..apify_client import run_actor, has_token

ACTOR = "crowdpull~facebook-marketplace-scraper"

KNOWN_MAKES = [
    "Maruti Suzuki", "Maruti", "Hyundai", "Honda", "Tata", "Mahindra", "Toyota",
    "Volkswagen", "Skoda", "Ford", "Renault", "Nissan", "Kia", "MG", "Volvo",
    "BMW", "Mercedes", "Audi", "Jeep", "Fiat", "Chevrolet", "Datsun", "Jaguar",
    "Land Rover", "Mini", "Citroen",
]
JUNK = re.compile(r"self[\s-]?drive|for rent|rental|on rent|taxi|driver", re.I)


class FacebookScraper(BaseScraper):
    name = "facebook"
    label = "FB Marketplace Pune"
    expected_min = 5

    def list_urls(self):
        return []

    def parse(self, html, url):
        return []

    def run(self, db, filters=None):
        if not has_token():
            record_health(db, self.name, False, 0, self.expected_min,
                           "needs APIFY_TOKEN (add it to enable Facebook)")
            db.commit()
            return 0, False, "no APIFY_TOKEN"

        cap = (filters or {}).get("max_per_source") or 40
        error, rows = None, []
        try:
            items = run_actor(ACTOR, {
                "location": "Pune", "searchQuery": "car",
                "maxListings": cap, "includeDetails": False,
            })
            rows = [r for r in (self._to_row(it) for it in items) if r]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        saved = 0
        for row in rows:
            if not row.get("external_id") or not match_filters(row, filters):
                continue
            from ...db import upsert_vehicle
            upsert_vehicle(db, row)
            saved += 1

        ok = error is None and len(rows) >= self.expected_min
        record_health(db, self.name, ok, len(rows), self.expected_min,
                       error or ("ok" if ok else "returned fewer rows than expected"))
        db.commit()
        return saved, ok, error

    def _to_row(self, it):
        title = (it.get("title") or "").strip().replace("\n", " ")
        if not title or JUNK.search(title):
            return None
        price = to_int(it.get("priceFormatted") or it.get("price"))
        if not price or price < 50000:   # below this it's not a real car sale
            return None
        make = next((m for m in KNOWN_MAKES if m.lower() in title.lower()), None)
        _, model, _ = split_name(re.sub(r"^.*?(?=" + (make or "") + ")", "", title)) if make else (None, None, None)
        return {
            "source": "facebook",
            "external_id": str(it.get("listingId")),
            "source_url": it.get("listingUrl"),
            "title": title[:120],
            "make": make,
            "model": model,
            "variant": None,
            "year": year_from(title),
            "fuel": _fuel(title),
            "location": (it.get("location") or "Pune").split(",")[0],
            "seller_type": "individual",
            "listed_price": price,
            "image_url": it.get("imageUrl"),
        }


def _fuel(text):
    t = text.lower()
    if "diesel" in t:
        return "Diesel"
    if "cng" in t:
        return "Cng"
    if "electric" in t or " ev " in t or t.endswith(" ev"):
        return "Electric"
    if "petrol" in t:
        return "Petrol"
    return None
