"""Public-facing site: the dealer's shopfront.

Customers only ever see vehicles the dealer has bought and published. Scraped
listings never reach this side.
"""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from ..db import get_db, now, photos_for, cover_photos

bp = Blueprint("public", __name__)


@bp.route("/")
def home():
    db = get_db()
    make = request.args.get("make", "").strip()
    fuel = request.args.get("fuel", "").strip()
    max_price = request.args.get("max_price", "").strip()
    q = request.args.get("q", "").strip()

    sql = "SELECT * FROM vehicles WHERE status='published'"
    params = []
    if make:
        sql += " AND make = ?"
        params.append(make)
    if fuel:
        sql += " AND fuel = ?"
        params.append(fuel)
    if max_price.isdigit():
        sql += " AND as_is_price <= ?"
        params.append(int(max_price))
    if q:
        sql += " AND (title LIKE ? OR model LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY featured DESC, published_at DESC"

    vehicles = db.execute(sql, params).fetchall()
    covers = cover_photos(db, [v["id"] for v in vehicles])
    makes = [r["make"] for r in db.execute(
        "SELECT DISTINCT make FROM vehicles WHERE status='published' ORDER BY make"
    ).fetchall()]
    return render_template("public/home.html", vehicles=vehicles, makes=makes, covers=covers,
                           filters={"make": make, "fuel": fuel, "max_price": max_price, "q": q})


@bp.route("/vehicle/<int:vid>")
def vehicle(vid):
    db = get_db()
    v = db.execute(
        "SELECT * FROM vehicles WHERE id=? AND status='published'", (vid,)
    ).fetchone()
    if not v:
        abort(404)
    return render_template("public/vehicle.html", v=v, photos=photos_for(db, vid))


@bp.route("/vehicle/<int:vid>/enquire", methods=["POST"])
def enquire(vid):
    db = get_db()
    v = db.execute(
        "SELECT id FROM vehicles WHERE id=? AND status='published'", (vid,)
    ).fetchone()
    if not v:
        abort(404)
    db.execute(
        """INSERT INTO enquiries (vehicle_id, name, phone, message, option_chosen, created_at)
           VALUES (?,?,?,?,?,?)""",
        (vid, request.form.get("name"), request.form.get("phone"),
         request.form.get("message"), request.form.get("option_chosen"), now()),
    )
    db.commit()
    flash("Thanks. Your enquiry is in, the dealer will call you back shortly.", "success")
    return redirect(url_for("public.vehicle", vid=vid))
