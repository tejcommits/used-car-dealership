from ..base import BaseScraper
from ._helpers import to_int, year_from


class TeamBhpScraper(BaseScraper):
    name = "teambhp"
    label = "Team-BHP Classifieds"
    expected_min = 3

    def list_urls(self):
        return ["https://www.team-bhp.com/used-cars/pune"]

    def parse(self, html, url):
        soup = self.soup(html)
        rows = []
        for card in soup.select(".classified-listing, .listing-row"):
            try:
                link = card.select_one("a")
                href = link.get("href") if link else None
                title = card.select_one("h3, .listing-title")
                price = card.select_one("[class*='price']")
                img = card.select_one("img")
                rows.append({
                    "external_id": href.rstrip("/").split("/")[-1] if href else None,
                    "source_url": href,
                    "title": title.get_text(strip=True) if title else None,
                    "listed_price": to_int(price.get_text() if price else None),
                    "year": year_from((title.get_text() if title else "")),
                    "location": "Pune",
                    "seller_type": "individual",
                    "image_url": img.get("src") if img else None,
                })
            except Exception:
                continue
        return rows
