from ..base import BaseScraper
from ._helpers import to_int, year_from


class FacebookScraper(BaseScraper):
    """Facebook Marketplace.

    The hardest source: content loads via JavaScript and the site blocks plain
    requests aggressively. A working version needs a headless browser
    (Playwright) and usually residential proxies. This module is the plain
    request version; expect it to flip to 'broken' until upgraded, which is
    exactly what the health monitor is for. Budget a small proxy plan when you
    decide this source is worth the upkeep.
    """
    name = "facebook"
    label = "FB Marketplace Pune"
    expected_min = 3

    def list_urls(self):
        return ["https://www.facebook.com/marketplace/pune/vehicles"]

    def parse(self, html, url):
        soup = self.soup(html)
        rows = []
        for card in soup.select("a[href*='/marketplace/item/']"):
            try:
                href = card.get("href")
                title = card.get_text(" ", strip=True)
                img = card.select_one("img")
                rows.append({
                    "external_id": href.split("/item/")[-1].split("/")[0] if href else None,
                    "source_url": ("https://www.facebook.com" + href) if href and href.startswith("/") else href,
                    "title": title or None,
                    "listed_price": to_int(title),
                    "year": year_from(title),
                    "location": "Pune",
                    "seller_type": "individual",
                    "image_url": img.get("src") if img else None,
                })
            except Exception:
                continue
        return rows
