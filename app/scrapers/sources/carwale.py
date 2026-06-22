"""CarWale — listings from the page's embedded state.

CarWale ships the first pages of search results inside a window.__INITIAL_STATE__
JSON blob, with full specs and a real image URL per car. We read that directly,
which is more stable than scraping rendered HTML. If CarWale changes the state
shape, the health monitor flags it.
"""
import json
import re

from ..base import BaseScraper
from ._helpers import to_int

BASE = "https://www.carwale.com/used/cars-in-pune/"


class CarWaleScraper(BaseScraper):
    name = "carwale"
    label = "CarWale Pune"
    expected_min = 15
    pages = 4

    def list_urls(self):
        return [BASE] + [f"{BASE}?page={p}" for p in range(2, self.pages + 1)]

    def parse(self, html, url):
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{)", html)
        if not m:
            return []
        try:
            obj, _ = json.JSONDecoder().raw_decode(html[m.start(1):])
        except ValueError:
            return []

        stocks = (obj.get("usedSearch") or {}).get("stocks") or []
        rows = []
        for s in stocks:
            try:
                u = s.get("url") or ""
                rows.append({
                    "source": "carwale",
                    "external_id": str(s.get("profileId")),
                    "source_url": ("https://www.carwale.com" + u) if u.startswith("/") else u,
                    "title": s.get("carName") or
                             f"{s.get('makeYear','')} {s.get('makeName','')} {s.get('modelName','')}".strip(),
                    "make": s.get("makeName"),
                    "model": s.get("modelName"),
                    "variant": s.get("versionName"),
                    "year": s.get("makeYear"),
                    "km": s.get("kmNumeric") or to_int(s.get("km")),
                    "fuel": s.get("fuel"),
                    "transmission": s.get("transmission"),
                    "location": s.get("areaName") or s.get("cityName") or "Pune",
                    "seller_type": "dealer",
                    "listed_price": s.get("priceNumeric") or to_int(s.get("price")),
                    "image_url": s.get("imageUrl"),
                })
            except Exception:
                continue
        return rows
