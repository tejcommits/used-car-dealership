"""Database access layer — SQLite locally, Postgres in production.

Plain SQL, no ORM. When DATABASE_URL is set (Render/Neon) we talk to Postgres;
otherwise we fall back to a local SQLite file. The route and scraper code is
written once against a small sqlite-style surface (`?` placeholders, rows you
can index by name *or* position, `.lastrowid`, `.rowcount`) and a thin adapter
below makes Postgres honour that same surface — so nothing outside this file
has to know which engine is live.

Why Postgres in prod: Render's filesystem is ephemeral, so a SQLite file gets
wiped on every deploy/restart, taking scraped deals and customer leads with it.
A managed Postgres (Neon free tier) persists across deploys.
"""
import os
import re
import sqlite3
from datetime import datetime, timedelta
from flask import current_app, g

# Postgres when a connection URL is present (Render/Neon), else local SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL")
USING_PG = bool(DATABASE_URL)

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


# --- Postgres compatibility shim ---------------------------------------------
# The app is written in the sqlite dialect. These helpers let the exact same
# calls run on Postgres, so no route/scraper/seed code needs an engine branch.

def _qmarks_to_pg(sql):
    """Rewrite sqlite `?` placeholders to Postgres `%s`.

    Safe here because none of our SQL contains `?` or literal `%` anywhere but
    as a bind placeholder (verified across the codebase).
    """
    return sql.replace("?", "%s")


def _split_statements(script):
    """Split a multi-statement DDL script into individual statements.

    psycopg runs one command per execute(); sqlite's executescript() does not.
    We strip `-- ...` line comments first, because a comment can itself contain
    a semicolon (e.g. "-- lower shows first; 0 is the cover"), which would
    otherwise split a statement mid-comment. Our schema has no string literals
    containing `--` or `;`, so this is safe.
    """
    no_comments = re.sub(r"--[^\n]*", "", script)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


class _PgRow:
    """A result row indexable by column name or position, like sqlite3.Row.

    Also supports `in`, `.get()`, `.keys()` and `dict(row)`, which the app and
    Jinja templates rely on.
    """
    __slots__ = ("_cols", "_vals", "_map")

    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = vals
        self._map = None

    def _mapping(self):
        if self._map is None:
            self._map = dict(zip(self._cols, self._vals))
        return self._map

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._mapping()[key]

    def __contains__(self, key):
        return key in self._mapping()

    def get(self, key, default=None):
        return self._mapping().get(key, default)

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


def _pg_row_factory(cursor):
    cols = [d.name for d in (cursor.description or [])]
    return lambda values: _PgRow(cols, values)


class _PgConn:
    """Wraps a psycopg connection to speak the sqlite-style surface the app uses."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        q = _qmarks_to_pg(sql)
        # Only pass params when there are any, so paramless SQL never triggers
        # psycopg's `%` interpolation.
        return self._raw.execute(q, params) if params else self._raw.execute(q)

    def executescript(self, script):
        for stmt in _split_statements(script):
            self._raw.execute(stmt)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def _connect_pg():
    import psycopg
    raw = psycopg.connect(DATABASE_URL)
    raw.row_factory = _pg_row_factory
    return _PgConn(raw)


# -----------------------------------------------------------------------------


def get_db():
    if "db" not in g:
        if USING_PG:
            g.db = _connect_pg()
        else:
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
    if USING_PG:
        # Fresh Postgres schemas get every column from SCHEMA, so no ALTER
        # migration is needed. AUTOINCREMENT -> SERIAL is the only dialect gap.
        db = _connect_pg()
        db.executescript(SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"))
        db.commit()
        db.close()
        return

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
        if existing["status"] == "scraped":
            # Still in the dealer's hunting list — refresh every scraped field so
            # a corrected/updated source listing overwrites a stale first read.
            color = row.get("color") or extract_color(row.get("title"))
            db.execute(
                """UPDATE vehicles SET title=?, make=?, model=?, variant=?, year=?, km=?,
                     fuel=?, transmission=?, owners=?, location=?, seller_type=?,
                     listed_price=?, image_url=?, color=? WHERE id=?""",
                (row.get("title"), row.get("make"), row.get("model"), row.get("variant"),
                 row.get("year"), row.get("km"), row.get("fuel"), row.get("transmission"),
                 row.get("owners"), row.get("location"), row.get("seller_type"),
                 row.get("listed_price"), row.get("image_url"), color, existing["id"]),
            )
        else:
            # Already published/sold — the dealer owns those fields now. Only the
            # source's asking price and photo get refreshed, never his edits.
            db.execute(
                "UPDATE vehicles SET listed_price=?, image_url=? WHERE id=?",
                (row.get("listed_price"), row.get("image_url"), existing["id"]),
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
    insert = f"INSERT INTO vehicles ({','.join(cols)}) VALUES ({placeholders})"
    if USING_PG:
        # Postgres has no lastrowid; ask for the new id back.
        return db.execute(insert + " RETURNING id", values).fetchone()[0]
    return db.execute(insert, values).lastrowid


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
