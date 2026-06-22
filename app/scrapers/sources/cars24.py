from ..base import BaseScraper
from ._helpers import to_int, year_from


class Cars24Scraper(BaseScraper):
    name = "cars24"
    label = "Cars24 Pune"
    expected_min = 5

    def list_urls(self):
        return ["https://www.cars24.com/buy-used-cars-pune/"]

    def parse(self, html, url):
        soup = self.soup(html)
        rows = []
        for card in soup.select("[data-testid='car-card'], .car-card"):
            try:
                link = card.select_one("a")
                href = link.get("href") if link else None
                title = card.select_one("h3, .car-name")
                price = card.select_one(".price, [class*='price']")
                img = card.select_one("img")
                rows.append({
                    "external_id": href.rstrip("/").split("/")[-1] if href else None,
                    "source_url": ("https://www.cars24.com" + href) if href and href.startswith("/") else href,
                    "title": title.get_text(strip=True) if title else None,
                    "listed_price": to_int(price.get_text() if price else None),
                    "year": year_from((title.get_text() if title else "")),
                    "location": "Pune",
                    "seller_type": "dealer",
                    "image_url": img.get("src") if img else None,
                })
            except Exception:
                continue
        return rows
