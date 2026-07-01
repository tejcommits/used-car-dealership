"""SQLite access layer.

We use plain sqlite3, no ORM. At this scale a single file database is the
right call: zero running cost, trivial backups (copy one file), and easy for
a freelancer to inherit. If volume ever outgrows it, the schema moves to
Postgres without changing the route code much.
"""
import sqlite3
from datetime import datetime, timedelta
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,          -- which site it came from, or 'manual'
    source_url    TEXT,
    external_id   TEXT,                   -- the listing id on the source site
    title         TEXT,
    make          TEXT,
    model         TEXT,
    variant       TEXT,
    year          INTEGER,
    km            INTEGER,
    fuel          TEXT,
    transmission  TEXT,
    owners        TEXT,
    location      TEXT,
    seller_type   TEXT,
    listed_price  INTEGER,                -- asking price found on the source
    image_url     TEXT,
    status        TEXT NOT NULL DEFAULT 'scraped',  -- scraped|published|sold|hidden

    -- filled in by the dealer when he buys and publishes a vehicle
    buy_price     INTEGER,                -- what he paid (private, never public)
    as_is_price   INTEGER,                -- public price, take it as-is
    fixed_price   INTEGER,                -- public price, he gets the work done
    work_required TEXT,                   -- honest note on what needs fixing
    description   TEXT,

    featured      INTEGER DEFAULT 0,
    fresh         INTEGER DEFAULT 0,     -- newly added in the most recent scrape
    color         TEXT,
    scraped_at    TEXT,
    published_at  TEXT,
    last_seen_at  TEXT,                  -- stamped whenever an unfiltered scrape still finds it
    delisted_at   TEXT,                  -- set when an unfiltered scrape no longer finds it
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS enquiries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id    INTEGER,
    name          TEXT,
    phone         TEXT,
    message       TEXT,
    option_chosen TEXT,                   -- as_is | fixed
    created_at    TEXT,
    handled       INTEGER DEFAULT 0,
    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
);

CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT,
    phone         TEXT,
    city          TEXT,
    budget        INTEGER,                -- target spend in rupees
    make          TEXT,                   -- preferred brand, blank if open
    model         TEXT,                   -- optional specifics, free text
    fuel          TEXT,
    transmission  TEXT,
    year_min      INTEGER,                -- 'not older than'
    timeline      TEXT,                   -- week | month | exploring
    notes         TEXT,
    created_at    TEXT,
    handled       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scraper_health (
    source       TEXT PRIMARY KEY,
    last_run     TEXT,
    last_ok_at   TEXT,
    status       TEXT,                    -- ok | broken | never
    items_found  INTEGER DEFAULT 0,
    expected_min INTEGER DEFAULT 0,
    message      TEXT
);

CREATE TABLE IF NOT EXISTS vehicle_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL,
    filename    TEXT NOT NULL,          -- stored under static/uploads/
    position    INTEGER DEFAULT 0,      -- lower shows first; 0 is the cover
    created_at  TEXT,
    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT,                  -- running | done | error
    total_sources INTEGER,
    done_sources  INTEGER DEFAULT 0,
    current       TEXT,
    new_listings  INTEGER DEFAULT 0,
    summary       TEXT,                  -- JSON list of per-source results
    started_at    TEXT,
    finished_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status);
CREATE INDEX IF NOT EXISTS idx_vehicles_makemodel ON vehicles(make, model);
CREATE INDEX IF NOT EXISTS idx_photos_vehicle ON vehicle_photos(vehicle_id, position);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 8000")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they do not exist. Safe to run repeatedly."""
    db = sqlite3.connect(current_app.config["DATABASE"])
    db.executescript(SCHEMA)
    # migrate older databases that predate the 'fresh' column
    cols = [r[1] for r in db.execute("PRAGMA table_info(vehicles)").fetchall()]
    if "fresh" not in cols:
        db.execute("ALTER TABLE vehicles ADD COLUMN fresh INTEGER DEFAULT 0")
    if "color" not in cols:
        db.execute("ALTER TABLE vehicles ADD COLUMN color TEXT")
    if "last_seen_at" not in cols:
        db.execute("ALTER TABLE vehicles ADD COLUMN last_seen_at TEXT")
    if "delisted_at" not in cols:
        db.execute("ALTER TABLE vehicles ADD COLUMN delisted_at TEXT")
    db.commit()
    db.close()


_COLORS = ["white", "black", "silver", "grey", "gray", "red", "blue", "brown",
           "maroon", "green", "gold", "golden", "orange", "yellow", "beige", "bronze", "purple"]


def extract_color(text):
    """Pull a colour word out of a title/description, if present."""
    if not text:
        return None
    t = str(text).lower()
    for c in _COLORS:
        if c in t:
            return "Grey" if c in ("grey", "gray") else c.capitalize()
    return None


def now():
    return datetime.now().isoformat(timespec="seconds")


def photos_for(db, vehicle_id):
    """Return the uploaded photo rows for one vehicle, cover first."""
    return db.execute(
        "SELECT * FROM vehicle_photos WHERE vehicle_id=? ORDER BY position, id",
        (vehicle_id,),
    ).fetchall()


def cover_photos(db, vehicle_ids):
    """Map each vehicle id to its cover photo filename (or absent if none).

    One query for a whole list, so card grids do not fan out into N queries.
    """
    if not vehicle_ids:
        return {}
    marks = ",".join("?" * len(vehicle_ids))
    rows = db.execute(
        f"""SELECT vehicle_id, filename FROM vehicle_photos
            WHERE vehicle_id IN ({marks})
            ORDER BY vehicle_id, position, id""",
        list(vehicle_ids),
    ).fetchall()
    cover = {}
    for r in rows:
        cover.setdefault(r["vehicle_id"], r["filename"])  # first row wins
    return cover


def upsert_vehicle(db, row):
    """Insert a scraped listing, or update price/image if we have seen it before.

    Keyed on (source, external_id) so re-running a scraper does not create
    duplicates of the same listing. A vehicle the dealer has already published
    is never knocked back to 'scraped' by a later scrape.
    """
    existing = db.execute(
        "SELECT id, status FROM vehicles WHERE source=? AND external_id=?",
        (row["source"], row["external_id"]),
    ).fetchone()

    if existing:
        db.execute(
            "UPDATE vehicles SET listed_price=?, image_url=?, title=? WHERE id=?",
            (row.get("listed_price"), row.get("image_url"), row.get("title"), existing["id"]),
        )
        return existing["id"]

    cols = [
        "source", "source_url", "external_id", "title", "make", "model",
        "variant", "year", "km", "fuel", "transmission", "owners", "location",
        "seller_type", "listed_price", "image_url", "scraped_at",
    ]
    values = [row.get(c) for c in cols]
    values[cols.index("scraped_at")] = now()
    # newly inserted listings are flagged 'fresh' so the deals page can tag them NEW;
    # capture colour (from the source if given, else from the title) for search
    color = row.get("color") or extract_color(row.get("title"))
    cols = cols + ["fresh", "color"]
    values = values + [1, color]
    placeholders = ",".join("?" * len(cols))
    cur = db.execute(
        f"INSERT INTO vehicles ({','.join(cols)}) VALUES ({placeholders})", values
    )
    return cur.lastrowid


def stamp_seen(db, source, external_ids):
    """Mark scraped listings as still present on the source site.

    Called with every external_id found in a scraper's raw fetch (before the
    dealer's save filters/cap are applied), so a narrow "Scrape now" filter
    never makes an untouched listing look delisted. Un-delists anything that
    reappears.
    """
    ids = [str(x) for x in external_ids if x]
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    db.execute(
        f"""UPDATE vehicles SET last_seen_at=?, delisted_at=NULL
            WHERE source=? AND status='scraped' AND external_id IN ({marks})""",
        [now(), source] + ids,
    )


def sweep_delisted(db, sources, cutoff_before):
    """Soft-hide scraped listings a full sweep didn't find, and purge
    listings that have been soft-hidden for a week or more.

    `cutoff_before` is the timestamp the sweep started at: anything from
    `sources` not stamped by stamp_seen() since then is gone from its site.
    Returns (soft_hidden, purged) counts.
    """
    if not sources:
        return 0, 0
    marks = ",".join("?" * len(sources))
    cur = db.execute(
        f"""UPDATE vehicles SET delisted_at=?
            WHERE status='scraped' AND delisted_at IS NULL AND source IN ({marks})
              AND (last_seen_at IS NULL OR last_seen_at < ?)""",
        [now(), *sources, cutoff_before],
    )
    hidden = cur.rowcount

    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    cur = db.execute(
        "DELETE FROM vehicles WHERE status='scraped' AND delisted_at IS NOT NULL AND delisted_at <= ?",
        (week_ago,),
    )
    purged = cur.rowcount
    db.commit()
    return hidden, purged
