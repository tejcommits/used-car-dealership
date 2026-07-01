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

    def run(self, db, filters=None):
        """Fetch every listing URL, parse it, store the rows, record health.

        If `filters` is given, only listings matching them are stored — this is
        what the dealer's "Scrape now" dialog passes (make, year, km, price...).
        """
        from ..db import upsert_vehicle, stamp_seen  # local import to avoid a cycle

        rows, error = [], None
        try:
            for url in self.list_urls():
                html = self.fetch(url)
                rows.extend(self.parse(html, url))
                time.sleep(self.request_delay)
        except Exception as exc:  # network error, blocked, markup change
            error = f"{type(exc).__name__}: {exc}"

        # Every listing this fetch actually found is still live on the source,
        # regardless of the dealer's save filter — stamp that before filtering.
        stamp_seen(db, self.name, (r.get("external_id") for r in rows))

        cap = (filters or {}).get("max_per_source")
        saved = 0
        for row in rows:
            row.setdefault("source", self.name)
            if not row.get("external_id"):
                continue
            if not match_filters(row, filters):
                continue
            upsert_vehicle(db, row)
            saved += 1
            if cap and saved >= cap:
                break

        # Health reflects whether the SOURCE is reachable/parsing — judged on the
        # raw rows returned, not on how many passed the dealer's filter.
        fetched = len(rows)
        ok = error is None and fetched >= self.expected_min
        record_health(
            db,
            source=self.name,
            ok=ok,
            items_found=fetched,
            expected_min=self.expected_min,
            message=error or ("ok" if ok else "returned fewer rows than expected"),
        )
        db.commit()
        return saved, ok, error


def match_filters(row, filters):
    """Return True if a listing row passes the dealer's chosen filters.

    Unknown/missing values fail a filter that's set (e.g. if 'newer than 2016'
    is chosen and a listing has no year, it's left out rather than guessed in).
    """
    if not filters:
        return True

    make = filters.get("make")
    if make:
        rm = (row.get("make") or "").lower()
        rmodel = (row.get("model") or "").lower()
        if make.lower() not in rm and make.lower() not in rmodel:
            return False

    model = filters.get("model")
    if model and model.lower() not in (row.get("model") or "").lower():
        return False

    fuel = filters.get("fuel")
    if fuel and (row.get("fuel") or "").lower() != fuel.lower():
        return False

    def num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    year, km, price = num(row.get("year")), num(row.get("km")), num(row.get("listed_price"))

    if filters.get("min_year") is not None and (year is None or year < filters["min_year"]):
        return False
    if filters.get("max_year") is not None and (year is None or year > filters["max_year"]):
        return False
    if filters.get("max_km") is not None and (km is None or km > filters["max_km"]):
        return False
    if filters.get("min_price") is not None and (price is None or price < filters["min_price"]):
        return False
    if filters.get("max_price") is not None and (price is None or price > filters["max_price"]):
        return False
    return True


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
