"""Live Postgres smoke test for the AutoLux DB layer.

Run against a real Neon/Postgres URL BEFORE pointing production at it:

    DATABASE_URL='postgresql://...' venv/bin/python scripts/pg_smoketest.py

It exercises the exact code paths production uses — schema creation, seeding,
scraped-listing upsert (insert + update), lead insert, the delisted sweep, and
the admin stats queries — then prints a PASS/FAIL summary. Non-destructive to
any existing data only if the target DB is empty; use a throwaway DB.
"""
import os
import sys

if not os.environ.get("DATABASE_URL"):
    sys.exit("Set DATABASE_URL to a Postgres connection string first.")

from app import create_app
from app import db


def main():
    app = create_app()  # runs init_db() + seed() on Postgres
    with app.app_context():
        conn = db.get_db()
        assert db.USING_PG, "expected Postgres path"

        n = conn.execute("SELECT COUNT(*) AS c FROM vehicles").fetchone()["c"]
        print(f"[ok] seeded vehicles: {n}")
        assert n > 0

        # dual indexing + dict(row)
        r = conn.execute("SELECT id, make, model FROM vehicles LIMIT 1").fetchone()
        _ = dict(r)
        assert r[0] == r["id"]
        print("[ok] row indexing by name + position + dict()")

        # upsert insert then update returns same id
        vid = db.upsert_vehicle(conn, {
            "source": "smoketest", "external_id": "st-1", "title": "White Swift VXI",
            "make": "Maruti", "model": "Swift", "year": 2019, "km": 38000,
            "fuel": "Petrol", "owners": "1st", "location": "Pune", "listed_price": 550000,
        })
        assert isinstance(vid, int)
        vid2 = db.upsert_vehicle(conn, {
            "source": "smoketest", "external_id": "st-1", "title": "White Swift VXI",
            "make": "Maruti", "model": "Swift", "year": 2019, "km": 41000,
            "fuel": "Petrol", "owners": "1st", "location": "Pune", "listed_price": 535000,
        })
        assert vid == vid2, f"upsert should reuse id ({vid} != {vid2})"
        km = conn.execute("SELECT km FROM vehicles WHERE id=?", (vid,)).fetchone()["km"]
        assert km == 41000, f"upsert should refresh km, got {km}"
        conn.commit()
        print(f"[ok] upsert insert+update (id {vid}, km refreshed to {km})")

        # stamp_seen + sweep (delisted) with IN(...) params
        db.stamp_seen(conn, "smoketest", ["st-1"])
        conn.commit()
        hidden, purged = db.sweep_delisted(conn, ["smoketest"], db.now())
        print(f"[ok] sweep_delisted ran (hidden={hidden}, purged={purged})")

        # lead insert (the customer-facing form path)
        conn.execute(
            """INSERT INTO leads (name, phone, city, budget, make, timeline, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("Smoke Test", "9000000000", "Pune", 600000, "Maruti", "week", db.now()),
        )
        conn.commit()
        leads = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        assert leads >= 1
        print(f"[ok] lead insert (leads={leads})")

        # admin stats-style aggregate with alias + dict(row)
        rows = conn.execute(
            "SELECT make, COUNT(*) AS n FROM vehicles GROUP BY make ORDER BY n DESC LIMIT 3"
        ).fetchall()
        _ = [dict(x) for x in rows]
        print(f"[ok] grouped aggregate + dict rows: {[(x['make'], x['n']) for x in rows]}")

        # cleanup the smoketest vehicle so a reused DB stays clean
        conn.execute("DELETE FROM vehicles WHERE source='smoketest'")
        conn.execute("DELETE FROM leads WHERE phone='9000000000'")
        conn.commit()

    print("\nALL POSTGRES SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
