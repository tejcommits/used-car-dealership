from ..base import BaseScraper
from ._helpers import to_int, year_from


class OlxScraper(BaseScraper):
    name = "olx"
    label = "OLX Pune"
    expected_min = 5

    def list_urls(self):
        return ["https://www.olx.in/pune_g4058659/cars_c84"]

    def parse(self, html, url):
        soup = self.soup(html)
        rows = []
        for card in soup.select("li[data-aut-id='itemBox']"):
            try:
                link = card.select_one("a")
                href = link.get("href") if link else None
                title = card.select_one("[data-aut-id='itemTitle']")
                price = card.select_one("[data-aut-id='itemPrice']")
                detail = card.select_one("[data-aut-id='itemDetails']")
                img = card.select_one("img")
                rows.append({
                    "external_id": href.rstrip("/").split("-")[-1] if href else None,
                    "source_url": ("https://www.olx.in" + href) if href and href.startswith("/") else href,
                    "title": title.get_text(strip=True) if title else None,
                    "listed_price": to_int(price.get_text() if price else None),
                    "year": year_from((title.get_text() if title else "")),
                    "km": to_int(detail.get_text() if detail else None),
                    "location": "Pune",
                    "seller_type": "individual",
                    "image_url": img.get("src") if img else None,
                })
            except Exception:
                continue
        return rows
