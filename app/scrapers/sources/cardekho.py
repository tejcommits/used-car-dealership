"""CarDekho — server-rendered listing pages.

CarDekho renders its used-car cards into the HTML (no API needed), each with a
real photo on its CDN. We read the card class, title, price, and image. If
CarDekho restyles the page, the card selector breaks and the health monitor
flags it — which is the whole point of the monitor.
"""
import re

from ..base import BaseScraper
from ._helpers import to_int, year_from, split_name

BASE = "https://www.cardekho.com/used-cars+in+pune"


class CarDekhoScraper(BaseScraper):
    name = "cardekho"
    label = "CarDekho Pune"
    expected_min = 15
    pages = 4

    def list_urls(self):
        return [BASE] + [f"{BASE}?pageNo={p}" for p in range(2, self.pages + 1)]

    def parse(self, html, url):
        soup = self.soup(html)
        rows = []
        for c in soup.select(".NewUcExCard"):
            try:
                a = c.select_one("h3.title a")
                if not a:
                    continue
                title = a.get("title") or a.get_text(" ", strip=True)
                href = a.get("href", "")
                mid = re.search(r"adId=(\d+)", href) or re.search(r"_([0-9a-f]{8,})", href)

                img = c.select_one(".singleImage img")
                src = ""
                if img:
                    src = img.get("src") or img.get("data-src") or ""
                    if "spacer" in src:
                        src = img.get("data-src") or ""

                pr = c.select_one(".Price")
                make, model, variant = split_name(title)
                rows.append({
                    "source": "cardekho",
                    "external_id": (mid.group(1) if mid else href[-16:]) or None,
                    "source_url": ("https://www.cardekho.com" + href) if href.startswith("/") else href,
                    "title": title,
                    "make": make, "model": model, "variant": variant,
                    "year": year_from(title),
                    "location": "Pune",
                    "seller_type": "dealer",
                    "listed_price": to_int(pr.get_text() if pr else None),
                    "image_url": src or None,
                })
            except Exception:
                continue
        return rows
