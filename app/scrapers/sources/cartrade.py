"""CarTrade Pune — direct HTML scrape of the live used-cars listing page.

CarTrade (same group as CarWale) renders its Pune used-car listings server-side
at /second-hand/pune/, reachable with a plain request — no Apify, no proxy. The
old approach rendered a now-dead URL through Apify datacenter-proxy IPs that
CarTrade blocks; that's why it reported "blocked by the source". This fetches
the live page directly and parses the cards, exactly like the CarDekho scraper.
"""
import re

from ..base import BaseScraper
from ._helpers import to_int, split_name

LISTING_URL = "https://www.cartrade.com/second-hand/pune/"
# /second-hand/pune/<make-model-slug>/<listing-id>/?dc=0
_HREF = re.compile(r"^/second-hand/pune/[a-z0-9-]+/([a-z0-9]{6,})")
_FUELS = ("Diesel", "Petrol", "CNG", "Electric", "Hybrid", "LPG")


class CarTradeScraper(BaseScraper):
    name = "cartrade"
    label = "CarTrade Pune"
    expected_min = 10

    def list_urls(self):
        return [LISTING_URL]

    def parse(self, html, url):
        soup = self.soup(html)
        rows, seen = [], set()
        for a in soup.find_all("a", href=_HREF):
            href = a.get("href", "")
            m = _HREF.match(href)
            ext = m.group(1)
            if ext in seen:
                continue
            text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            ym = re.search(r"((?:19|20)\d{2})\s+(.+?)\s+₹", text)
            if not ym:
                continue
            year = int(ym.group(1))
            name = ym.group(2).strip()
            make, model, variant = split_name(f"{year} {name}")
            pm = re.search(r"₹\s*([\d.,]+)\s*(crore|cr|lakh|l)?", text, re.I)
            price = to_int(f"{pm.group(1)} {pm.group(2) or ''}") if pm else None
            if not (price and make):
                continue
            km_m = re.search(r"([\d,]+)\s*KMs?", text, re.I)
            km = to_int(km_m.group(1)) if km_m else None
            fuel = next((f for f in _FUELS if re.search(rf"\b{f}\b", text, re.I)), None)

            # the real car photo lives on a nearby <img> with 'vimages' in its src
            img, card = None, a
            for _ in range(4):
                card = card.parent
                if card is None:
                    break
                pic = (card.find("img", src=re.compile("vimages"))
                       or card.find("img", attrs={"data-src": re.compile("vimages")}))
                if pic:
                    img = pic.get("src") or pic.get("data-src")
                    break

            seen.add(ext)
            rows.append({
                "source": "cartrade",
                "external_id": ext,
                "source_url": "https://www.cartrade.com" + href.split("?")[0],
                "title": f"{year} {name}"[:120],
                "make": make, "model": model, "variant": variant,
                "year": year, "km": km, "fuel": fuel,
                "location": "Pune", "seller_type": "dealer",
                "listed_price": price, "image_url": img,
            })
        return rows
