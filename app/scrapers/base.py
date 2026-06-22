"""Base scraper.

Every source is a subclass that knows two things: which URLs to fetch, and
how to turn a page of HTML into a list of vehicle rows. The base class handles
the parts that are the same everywhere: making the request politely, catching
failures, and reporting its own health so the self-heal layer can spot a
broken scraper the moment it stops returning data.

NOTE ON LIVE SITES: the CSS selectors in each source module are written
against the public listing pages, but sites change their markup often. When a
source breaks, its parse() returns too few rows, health flips to 'broken', and
you get alerted. See app/scrapers/health.py.
"""
import time
import requests
from bs4 import BeautifulSoup

from ..db import now

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


class BaseScraper:
    name = "base"          # short id, used as the key in scraper_health
    label = "Base"         # human label shown in the admin
    expected_min = 3       # fewer rows than this on a run = treat as broken
    request_delay = 1.5    # seconds between requests, be polite

    def list_urls(self):
        """Return the listing-page URLs to fetch. Override in subclass."""
        raise NotImplementedError

    def parse(self, html, url):
        """Turn one page of HTML into a list of vehicle dicts. Override."""
        raise NotImplementedError

    # --- shared machinery below, no need to override ---

    def fetch(self, url):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text

    def soup(self, html):
        return BeautifulSoup(html, "lxml")

    def run(self, db):
        """Fetch every listing URL, parse it, store the rows, record health."""
        from ..db import upsert_vehicle  # local import to avoid a cycle

        rows, error = [], None
        try:
            for url in self.list_urls():
                html = self.fetch(url)
                rows.extend(self.parse(html, url))
                time.sleep(self.request_delay)
        except Exception as exc:  # network error, blocked, markup change
            error = f"{type(exc).__name__}: {exc}"

        saved = 0
        for row in rows:
            row.setdefault("source", self.name)
            if not row.get("external_id"):
                continue
            upsert_vehicle(db, row)
            saved += 1

        ok = error is None and saved >= self.expected_min
        record_health(
            db,
            source=self.name,
            ok=ok,
            items_found=saved,
            expected_min=self.expected_min,
            message=error or ("ok" if ok else "returned fewer rows than expected"),
        )
        db.commit()
        return saved, ok, error


def record_health(db, source, ok, items_found, expected_min, message):
    ts = now()
    existing = db.execute(
        "SELECT source, last_ok_at FROM scraper_health WHERE source=?", (source,)
    ).fetchone()
    last_ok = ts if ok else (existing["last_ok_at"] if existing else None)
    status = "ok" if ok else "broken"
    if existing:
        db.execute(
            "UPDATE scraper_health SET last_run=?, last_ok_at=?, status=?, "
            "items_found=?, expected_min=?, message=? WHERE source=?",
            (ts, last_ok, status, items_found, expected_min, message, source),
        )
    else:
        db.execute(
            "INSERT INTO scraper_health (source, last_run, last_ok_at, status, "
            "items_found, expected_min, message) VALUES (?,?,?,?,?,?,?)",
            (source, ts, last_ok, status, items_found, expected_min, message),
        )
