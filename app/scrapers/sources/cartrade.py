"""CarTrade Pune via Apify's browser renderer (apify/web-scraper).

Verified working: renders the Pune listing page and extracts real cars with
photos. CarTrade is a JS site, so we render it rather than parse raw HTML.
Needs APIFY_TOKEN. Without it this source is skipped and flagged.
"""
import re

from ..base import BaseScraper, record_health, match_filters
from ._helpers import to_int, split_name
from ..apify_client import run_actor, has_token

ACTOR = "apify~web-scraper"
URL = "https://www.cartrade.com/buy-used-cars/pune/c/"

PAGE_FUNCTION = (
    "async function pageFunction(context){"
    " const $=context.jQuery; await new Promise(r=>setTimeout(r,9000));"
    " const items=[]; const seen=new Set();"
    " $('img').each(function(){"
    "  let src=$(this).attr('src')||$(this).attr('data-src')||'';"
    "  if(!/vimages/i.test(src)) return;"
    "  let card=$(this).closest('a,li,div');"
    "  for(let k=0;k<4 && card.length;k++){ if(/(₹|Lakh|Cr)/i.test(card.text()||'')) break; card=card.parent(); }"
    "  let text=(card.text()||'').replace(/\\s+/g,' ').trim();"
    "  if(!/(₹|Lakh|Cr)/i.test(text)) return; text=text.slice(0,170);"
    "  if(seen.has(text)) return; seen.add(text);"
    "  let a=card.find(\"a[href*='used']\").attr('href')||'';"
    "  items.push({text, img:src, href:a});"
    " });"
    " return { items };"
    "}"
)


class CarTradeScraper(BaseScraper):
    name = "cartrade"
    label = "CarTrade Pune"
    expected_min = 10

    def list_urls(self):
        return []

    def parse(self, html, url):
        return []

    def run(self, db, filters=None):
        if not has_token():
            record_health(db, self.name, False, 0, self.expected_min,
                           "needs APIFY_TOKEN (add it to enable CarTrade)")
            db.commit()
            return 0, False, "no APIFY_TOKEN"

        error, rows = None, []
        try:
            pages = run_actor(ACTOR, {
                "runMode": "PRODUCTION", "startUrls": [{"url": URL}], "linkSelector": "",
                "proxyConfiguration": {"useApifyProxy": True}, "injectJQuery": True,
                "maxPagesPerCrawl": 1, "maxScrollHeightPixels": 10000,
                "pageFunctionTimeoutSecs": 80, "pageLoadTimeoutSecs": 80,
                "pageFunction": PAGE_FUNCTION,
            }, timeout=150)
            for pg in pages:
                for it in (pg.get("items") or []):
                    row = parse_cartrade(it)
                    if row:
                        rows.append(row)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        cap = (filters or {}).get("max_per_source") or 40
        saved = 0
        for row in rows:
            if not row.get("external_id") or not match_filters(row, filters):
                continue
            from ...db import upsert_vehicle
            upsert_vehicle(db, row)
            saved += 1
            if saved >= cap:
                break

        ok = error is None and len(rows) >= self.expected_min
        record_health(db, self.name, ok, len(rows), self.expected_min,
                       error or ("ok" if ok else "returned fewer rows than expected"))
        db.commit()
        return saved, ok, error


def parse_cartrade(it):
    text = re.sub(r"^(facebook|email|twitter|whatsapp|sponsored|featured|assured|share)+", "",
                  (it.get("text") or ""), flags=re.I).strip()
    ym = re.search(r"((?:19|20)\d{2})\s+(.+?)\s+₹", text)
    year = int(ym.group(1)) if ym else None
    name = ym.group(2).strip() if ym else None
    make, model, variant = split_name(f"{year} {name}" if name else text)

    pm = re.search(r"₹\s*([\d.,]+)\s*(crore|cr|lakh|l)?", text, re.I)
    price = to_int(f"{pm.group(1)} {pm.group(2) or ''}") if pm else None
    km_m = re.search(r"([\d,]+)\s*KMs?", text, re.I)
    km = to_int(km_m.group(1)) if km_m else None
    fuel = next((f for f in ("Diesel", "Petrol", "Cng", "Electric") if f.lower() in text.lower()), None)

    img = it.get("img") or ""
    idm = re.search(r"vimages/\d+/(\d+)", img)
    href = it.get("href") or ""
    if not (price and make):
        return None
    return {
        "source": "cartrade",
        "external_id": idm.group(1) if idm else (img[-18:] or None),
        "source_url": ("https://www.cartrade.com" + href) if href.startswith("/") else (href or URL),
        "title": f"{year or ''} {name or ''}".strip() or text[:80],
        "make": make, "model": model, "variant": variant,
        "year": year, "km": km, "fuel": fuel,
        "location": "Pune", "seller_type": "dealer",
        "listed_price": price, "image_url": img,
    }
