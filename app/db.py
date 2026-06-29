"""SQLite access layer.

We use plain sqlite3, no ORM. At this scale a single file database is the
right call: zero running cost, trivial backups (copy one file), and easy for
a freelancer to inherit. If volume ever outgrows it, the schema moves to
Postgres without changing the route code much.
"""
import sqlite3
from datetime import datetime
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
    scraped_at    TEXT,
    published_at  TEXT,
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
    db.commit()
    db.close()


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
    # newly inserted listings are flagged 'fresh' so the deals page can tag them NEW
    cols = cols + ["fresh"]
    values = values + [1]
    placeholders = ",".join("?" * len(cols))
    cur = db.execute(
        f"INSERT INTO vehicles ({','.join(cols)}) VALUES ({placeholders})", values
    )
    return cur.lastrowid
