"""Seed the database from a snapshot of real scraped listings.

app/seed_data.json holds a real pull from the Pune sources (Spinny, CarWale,
CarDekho) — actual cars with their actual photos, plus a handful already
published to the public site. This runs once on first start so a fresh deploy
shows real inventory immediately, without waiting on a live scrape.

To refresh with live data later, use the "Scrape now" button in the admin or
run: venv/bin/python -m app.scrapers.run
Re-seed from the snapshot with: venv/bin/flask --app run seed
"""
import json
from pathlib import Path

from .db import now, USING_PG

SNAPSHOT = Path(__file__).resolve().parent / "seed_data.json"


def seed(db, force=False):
    count = db.execute("SELECT COUNT(*) AS c FROM vehicles").fetchone()["c"]
    if count and not force:
        return 0
    if force:
        db.execute("DELETE FROM vehicle_photos")
        db.execute("DELETE FROM vehicles")

    if not SNAPSHOT.exists():
        return 0
    data = json.loads(SNAPSHOT.read_text())

    vehicles = data.get("vehicles", [])
    if vehicles:
        cols = [c for c in vehicles[0].keys()]
        placeholders = ",".join("?" * len(cols))
        for v in vehicles:
            db.execute(
                f"INSERT INTO vehicles ({','.join(cols)}) VALUES ({placeholders})",
                [v.get(c) for c in cols],
            )

    if USING_PG:
        health_sql = """INSERT INTO scraper_health
               (source,last_run,last_ok_at,status,items_found,expected_min,message)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (source) DO UPDATE SET
                 last_run=EXCLUDED.last_run, last_ok_at=EXCLUDED.last_ok_at,
                 status=EXCLUDED.status, items_found=EXCLUDED.items_found,
                 expected_min=EXCLUDED.expected_min, message=EXCLUDED.message"""
    else:
        health_sql = """INSERT OR REPLACE INTO scraper_health
               (source,last_run,last_ok_at,status,items_found,expected_min,message)
               VALUES (?,?,?,?,?,?,?)"""
    for h in data.get("health", []):
        db.execute(
            health_sql,
            (h.get("source"), h.get("last_run") or now(), h.get("last_ok_at"),
             h.get("status"), h.get("items_found"), h.get("expected_min"), h.get("message")),
        )

    db.commit()
    return len(vehicles)
