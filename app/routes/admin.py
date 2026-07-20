"""Admin panel: the dealer's private workspace.

Four areas:
  Deals      - scraped listings from across the Pune sites, his hunting ground
  Inventory  - vehicles he has bought and published to the public site
  Enquiries  - customer leads from the public site
  Scrapers   - health of each source, plus a button to scrape now
"""
import os
import uuid
import json
import sqlite3
import threading
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash, abort,
    current_app, jsonify,
)
from werkzeug.utils import secure_filename
from ..db import get_db, now, photos_for

bp = Blueprint("admin", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == current_app.config["ADMIN_PASSWORD"]:
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin.deals"))
        flash("Wrong password.", "error")
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("public.home"))


@bp.route("/")
@login_required
def deals():
    db = get_db()
    a = request.args
    f = {k: a.get(k, "").strip() for k in
         ("q", "make", "source", "fuel", "area", "sort", "min_year", "max_km", "max_price")}

    sql = "SELECT * FROM vehicles WHERE status='scraped' AND delisted_at IS NULL"
    params = []
    if f["q"]:
        # every word in the search must appear somewhere (make/model/variant/colour/area/title)
        for word in f["q"].split():
            sql += (" AND (title LIKE ? OR make LIKE ? OR model LIKE ? OR variant LIKE ? "
                    "OR color LIKE ? OR location LIKE ?)")
            params += [f"%{word}%"] * 6
    if f["make"]:
        sql += " AND make=?"; params.append(f["make"])
    if f["source"]:
        sql += " AND source=?"; params.append(f["source"])
    if f["fuel"]:
        sql += " AND fuel=?"; params.append(f["fuel"])
    if f["area"]:
        sql += " AND location=?"; params.append(f["area"])
    if f["min_year"].isdigit():
        sql += " AND year >= ?"; params.append(int(f["min_year"]))
    if f["max_km"].isdigit():
        sql += " AND km IS NOT NULL AND km <= ?"; params.append(int(f["max_km"]))
    if f["max_price"].isdigit():
        sql += " AND listed_price <= ?"; params.append(int(f["max_price"]))
    sql += " ORDER BY " + {
        "price_asc": "listed_price ASC", "price_desc": "listed_price DESC",
        "year_desc": "year DESC", "year_asc": "year ASC",
        "km_asc": "km ASC",
        "newest": "fresh DESC, scraped_at DESC", "oldest": "scraped_at ASC",
    }.get(f["sort"], "fresh DESC, listed_price ASC")

    deals = db.execute(sql, params).fetchall()

    def distinct(col):
        return [r[0] for r in db.execute(
            f"SELECT DISTINCT {col} FROM vehicles WHERE status='scraped' AND delisted_at IS NULL "
            f"AND {col} IS NOT NULL AND {col} != '' ORDER BY {col}").fetchall()]

    b = db.execute("SELECT MIN(listed_price), MAX(listed_price), MIN(year), MAX(year) "
                   "FROM vehicles WHERE status='scraped' AND delisted_at IS NULL").fetchone()
    bounds = {"pmin": b[0] or 0, "pmax": b[1] or 2000000,
              "ymin": b[2] or 2008, "ymax": b[3] or 2026}

    return render_template("admin/deals.html", deals=deals,
                           makes=distinct("make"), sources=distinct("source"),
                           fuels=distinct("fuel"), areas=distinct("location"),
                           bounds=bounds, filters=f, stats=_stats(db))


@bp.route("/deal/<int:vid>")
@login_required
def deal(vid):
    db = get_db()
    v = db.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        abort(404)
    return render_template("admin/deal.html", v=v)


@bp.route("/deal/<int:vid>/publish", methods=["POST"])
@login_required
def publish(vid):
    db = get_db()
    f = request.form
    db.execute(
        """UPDATE vehicles SET
             make=?, model=?, variant=?, year=?, km=?, fuel=?, transmission=?, owners=?,
             location=?, buy_price=?, as_is_price=?, fixed_price=?, work_required=?,
             description=?, featured=?, status='published', published_at=?
           WHERE id=?""",
        (f.get("make"), f.get("model"), f.get("variant"),
         _int(f.get("year")), _int(f.get("km")), f.get("fuel"), f.get("transmission"),
         f.get("owners"), f.get("location"),
         _int(f.get("buy_price")), _int(f.get("as_is_price")), _int(f.get("fixed_price")),
         f.get("work_required"), f.get("description"),
         1 if f.get("featured") else 0, now(), vid),
    )
    n = _save_photos(db, vid, request.files.getlist("photos"))
    db.commit()
    if n:
        flash(f"Published with {n} photo{'s' if n != 1 else ''}.", "success")
        return redirect(url_for("admin.inventory"))
    flash("Published. Add photos so buyers can see the car.", "success")
    return redirect(url_for("admin.photos", vid=vid))


@bp.route("/inventory")
@login_required
def inventory():
    db = get_db()
    vehicles = db.execute(
        "SELECT * FROM vehicles WHERE status IN ('published','sold') ORDER BY status, published_at DESC"
    ).fetchall()
    ids = [v["id"] for v in vehicles]
    from ..db import cover_photos
    covers = cover_photos(db, ids)
    counts = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in db.execute(
            f"SELECT vehicle_id, COUNT(*) AS c FROM vehicle_photos WHERE vehicle_id IN ({marks}) GROUP BY vehicle_id",
            ids,
        ).fetchall():
            counts[r["vehicle_id"]] = r["c"]
    return render_template("admin/inventory.html", vehicles=vehicles, stats=_stats(db),
                           covers=covers, counts=counts)


@bp.route("/vehicle/<int:vid>/status", methods=["POST"])
@login_required
def set_status(vid):
    new = request.form.get("status")
    if new not in ("published", "sold", "hidden", "scraped"):
        abort(400)
    db = get_db()
    db.execute("UPDATE vehicles SET status=? WHERE id=?", (new, vid))
    db.commit()
    flash(f"Marked as {new}.", "success")
    return redirect(request.referrer or url_for("admin.inventory"))


@bp.route("/enquiries")
@login_required
def enquiries():
    db = get_db()
    rows = db.execute(
        """SELECT e.*, v.title FROM enquiries e
           LEFT JOIN vehicles v ON v.id = e.vehicle_id
           ORDER BY e.created_at DESC"""
    ).fetchall()
    return render_template("admin/enquiries.html", enquiries=rows, stats=_stats(db))


@bp.route("/enquiry/<int:eid>/handled", methods=["POST"])
@login_required
def mark_handled(eid):
    db = get_db()
    db.execute("UPDATE enquiries SET handled=1 WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("admin.enquiries"))


@bp.route("/leads")
@login_required
def leads():
    db = get_db()
    rows = db.execute("SELECT * FROM leads ORDER BY handled, created_at DESC").fetchall()
    return render_template("admin/leads.html", leads=rows, stats=_stats(db))


@bp.route("/lead/<int:lid>/handled", methods=["POST"])
@login_required
def lead_handled(lid):
    db = get_db()
    db.execute("UPDATE leads SET handled=1 WHERE id=?", (lid,))
    db.commit()
    return redirect(url_for("admin.leads"))


@bp.route("/trends")
@login_required
def trends():
    db = get_db()

    # What's in demand, read from live Pune supply across every source.
    # Listing volume per model is the best free proxy for demand; pair it with
    # asking price and how new the stock is. (No public per-city sales feed
    # exists, so supply + price is the honest, defensible signal.)
    top_models = db.execute(
        """SELECT make || ' ' || model AS name, COUNT(*) AS listings,
                  CAST(AVG(listed_price) AS INT) AS avg_price, MIN(year) AS oldest, MAX(year) AS newest
           FROM vehicles WHERE listed_price IS NOT NULL AND model IS NOT NULL
           GROUP BY make, model HAVING listings >= 2
           ORDER BY listings DESC LIMIT 12"""
    ).fetchall()

    top_makes = db.execute(
        """SELECT make, COUNT(*) AS listings FROM vehicles WHERE make IS NOT NULL
           GROUP BY make ORDER BY listings DESC LIMIT 8"""
    ).fetchall()

    fuel_rows = db.execute(
        """SELECT COALESCE(NULLIF(fuel,''),'Other') AS fuel, COUNT(*) AS c
           FROM vehicles GROUP BY fuel ORDER BY c DESC"""
    ).fetchall()

    year_rows = db.execute(
        """SELECT year, COUNT(*) AS c FROM vehicles
           WHERE year IS NOT NULL AND year >= 2008 GROUP BY year ORDER BY year"""
    ).fetchall()

    source_rows = db.execute(
        "SELECT source, COUNT(*) AS c FROM vehicles GROUP BY source ORDER BY c DESC"
    ).fetchall()

    # price bands (computed in Python so the buckets read nicely)
    bands = [("Under ₹3L", 0, 300000), ("₹3–5L", 300000, 500000), ("₹5–8L", 500000, 800000),
             ("₹8–12L", 800000, 1200000), ("₹12L+", 1200000, 10**9)]
    prices = [r["listed_price"] for r in db.execute(
        "SELECT listed_price FROM vehicles WHERE listed_price IS NOT NULL").fetchall()]
    price_bands = [{"label": lab, "c": sum(1 for p in prices if lo <= p < hi)} for lab, lo, hi in bands]

    prices_sorted = sorted(prices)
    median = prices_sorted[len(prices_sorted) // 2] if prices_sorted else 0

    data = {
        "top_models": [dict(r) for r in top_models],
        "top_makes": [dict(r) for r in top_makes],
        "fuel": [dict(r) for r in fuel_rows],
        "years": [dict(r) for r in year_rows],
        "sources": [dict(r) for r in source_rows],
        "price_bands": price_bands,
        "total": len(prices),
        "median": median,
        "distinct_models": len(top_models),
    }
    return render_template("admin/trends.html", d=data, stats=_stats(db))


@bp.route("/scrapers")
@login_required
def scrapers():
    db = get_db()
    health = db.execute("SELECT * FROM scraper_health ORDER BY status DESC, source").fetchall()

    # Feed the Scrape dialog real makes/models so they become typo-proof dropdowns.
    rows = db.execute(
        "SELECT DISTINCT make, model FROM vehicles WHERE make IS NOT NULL AND model IS NOT NULL ORDER BY make, model"
    ).fetchall()
    makes = sorted({r["make"] for r in rows})
    models_by_make = {}
    for r in rows:
        models_by_make.setdefault(r["make"], [])
        if r["model"] not in models_by_make[r["make"]]:
            models_by_make[r["make"]].append(r["model"])

    from ..scrapers.apify_client import credits, has_token
    apify = {"connected": has_token(), "credits": credits()}

    return render_template("admin/scrapers.html", health=health, stats=_stats(db),
                           makes=makes, models_by_make=models_by_make, apify=apify)


@bp.route("/deals/cleanup", methods=["POST"])
@login_required
def cleanup_deals():
    """Cross-check the deals against their sources and clear out the gone ones.

    This ONLY cleans up — it never adds new listings. Each source is re-checked
    (check_only), a deal still present on its source is marked seen, one that's
    sold or delisted is hidden from Deals, and anything hidden for a week or more
    is removed for good. Runs synchronously — a manual, occasional admin action.
    """
    from ..scrapers.sources import ALL_SOURCES
    from ..db import sweep_delisted

    db = get_db()
    start_ts = now()
    # check_only: fetch to see what's still live, but don't upsert any new cars.
    filters = {"check_only": True, "max_per_source": 60}
    for cls in ALL_SOURCES:
        try:
            cls().run(db, filters)
        except Exception:
            pass  # a broken source shouldn't block the rest; health already records it

    hidden, purged = sweep_delisted(db, [cls.name for cls in ALL_SOURCES], start_ts)
    bits = []
    if hidden:
        bits.append(f"{hidden} no longer on their source (hidden from Deals)")
    if purged:
        bits.append(f"{purged} removed for good (hidden 7+ days)")
    flash("Cleaned up deals. " + ("; ".join(bits) if bits else "Nothing to clear, everything's current."), "success")
    return redirect(url_for("admin.deals"))


@bp.route("/scrapers/run", methods=["POST"])
@login_required
def run_scrapers():
    """Start a scrape in the background and return a job id. The dialog polls
    /scrapers/status/<id> for live progress so the request never blocks."""
    from ..scrapers.sources import ALL_SOURCES
    f = request.form

    filters = {}
    if f.get("make", "").strip():
        filters["make"] = f["make"].strip()
    if f.get("model", "").strip():
        filters["model"] = f["model"].strip()
    if f.get("fuel", "").strip():
        filters["fuel"] = f["fuel"].strip()
    for key in ("min_year", "max_year", "max_km", "min_price", "max_price", "max_per_source"):
        v = _int(f.get(key))
        if v is not None:
            filters[key] = v
    filters.setdefault("max_per_source", 60)

    job_id = uuid.uuid4().hex
    db = get_db()
    db.execute("INSERT INTO scrape_jobs (id, status, total_sources, done_sources, new_listings, started_at) "
               "VALUES (?,?,?,?,?,?)", (job_id, "running", len(ALL_SOURCES), 0, 0, now()))
    db.commit()

    db_path = current_app.config["DATABASE"]
    threading.Thread(target=_scrape_worker, args=(db_path, job_id, filters), daemon=True).start()
    return jsonify({"job_id": job_id})


@bp.route("/scrapers/status/<job_id>")
@login_required
def scrape_status(job_id):
    r = get_db().execute("SELECT * FROM scrape_jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        abort(404)
    return jsonify({
        "status": r["status"], "done": r["done_sources"], "total": r["total_sources"],
        "current": r["current"], "new": r["new_listings"],
        "summary": json.loads(r["summary"] or "[]"),
    })


def _scrape_worker(db_path, job_id, filters):
    """Runs in a background thread with its own DB connection.

    A thread can't reuse the request's connection, so it opens a fresh one.
    In production that must be Postgres (Neon) — the same store the job row and
    scraped vehicles live in — not a throwaway local SQLite file.
    """
    from ..scrapers.sources import ALL_SOURCES
    from ..db import USING_PG, connect_worker

    if USING_PG:
        conn = connect_worker()
    else:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 8000")

    def count():
        return conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='scraped'").fetchone()[0]

    # clear last scrape's NEW tags; only this run's new inserts will be flagged
    conn.execute("UPDATE vehicles SET fresh=0")
    conn.commit()

    summary, total_new = [], 0
    try:
        for i, cls in enumerate(ALL_SOURCES):
            s = cls()
            conn.execute("UPDATE scrape_jobs SET current=?, done_sources=? WHERE id=?", (s.label, i, job_id))
            conn.commit()
            before = count()
            try:
                _, ok, err = s.run(conn, filters)
            except Exception as exc:
                ok, err = False, f"{type(exc).__name__}: {exc}"
            new = max(0, count() - before)
            total_new += new
            summary.append({"source": s.label, "new": new, "ok": bool(ok), "error": err})
            conn.execute("UPDATE scrape_jobs SET done_sources=?, new_listings=?, summary=? WHERE id=?",
                         (i + 1, total_new, json.dumps(summary), job_id))
            conn.commit()
        conn.execute("UPDATE scrape_jobs SET status='done', current=NULL, finished_at=? WHERE id=?",
                     (now(), job_id))
        conn.commit()
    except Exception as exc:
        conn.execute("UPDATE scrape_jobs SET status='error', summary=? WHERE id=?",
                     (json.dumps([{"source": "—", "error": str(exc)}]), job_id))
        conn.commit()
    finally:
        conn.close()


def _stats(db):
    def one(sql):
        return db.execute(sql).fetchone()[0]
    return {
        "deals": one("SELECT COUNT(*) FROM vehicles WHERE status='scraped' AND delisted_at IS NULL"),
        "published": one("SELECT COUNT(*) FROM vehicles WHERE status='published'"),
        "sold": one("SELECT COUNT(*) FROM vehicles WHERE status='sold'"),
        "enquiries": one("SELECT COUNT(*) FROM enquiries WHERE handled=0"),
        "leads": one("SELECT COUNT(*) FROM leads WHERE handled=0"),
        "broken": one("SELECT COUNT(*) FROM scraper_health WHERE status!='ok'"),
    }


def _int(val):
    try:
        return int(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _save_photos(db, vehicle_id, files):
    """Save uploaded image files for a vehicle. Returns how many were saved."""
    folder = current_app.config["UPLOAD_FOLDER"]
    allowed = current_app.config["ALLOWED_IMAGE_EXTS"]
    os.makedirs(folder, exist_ok=True)

    start = db.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM vehicle_photos WHERE vehicle_id=?",
        (vehicle_id,),
    ).fetchone()["n"]

    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in allowed:
            continue
        fname = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(folder, fname))
        db.execute(
            "INSERT INTO vehicle_photos (vehicle_id, filename, position, created_at) VALUES (?,?,?,?)",
            (vehicle_id, fname, start + saved, now()),
        )
        saved += 1
    return saved


@bp.route("/vehicle/<int:vid>/photos")
@login_required
def photos(vid):
    db = get_db()
    v = db.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        abort(404)
    return render_template("admin/photos.html", v=v, photos=photos_for(db, vid), stats=_stats(db))


@bp.route("/vehicle/<int:vid>/photos/upload", methods=["POST"])
@login_required
def upload_photos(vid):
    db = get_db()
    if not db.execute("SELECT id FROM vehicles WHERE id=?", (vid,)).fetchone():
        abort(404)
    n = _save_photos(db, vid, request.files.getlist("photos"))
    db.commit()
    flash(f"Added {n} photo{'s' if n != 1 else ''}." if n else "No valid images were uploaded.",
          "success" if n else "error")
    return redirect(url_for("admin.photos", vid=vid))


@bp.route("/photo/<int:pid>/delete", methods=["POST"])
@login_required
def delete_photo(pid):
    db = get_db()
    row = db.execute("SELECT * FROM vehicle_photos WHERE id=?", (pid,)).fetchone()
    if not row:
        abort(404)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], row["filename"])
    if os.path.exists(path):
        os.remove(path)
    db.execute("DELETE FROM vehicle_photos WHERE id=?", (pid,))
    db.commit()
    flash("Photo removed.", "success")
    return redirect(url_for("admin.photos", vid=row["vehicle_id"]))
