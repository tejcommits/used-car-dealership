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


def _int_or_none(val):
    try:
        return int(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


@bp.route("/find-car", methods=["GET", "POST"])
def find_car():
    """A general lead form: the customer describes the car they want and the
    dealer goes and sources it. Unlike an enquiry, this is not tied to a vehicle
    already in stock."""
    db = get_db()
    if request.method == "POST":
        f = request.form
        name = (f.get("name") or "").strip()
        phone = (f.get("phone") or "").strip()
        if not name or not phone:
            flash("Add your name and a phone number so we can call you back.", "error")
            return redirect(url_for("public.find_car"))
        db.execute(
            """INSERT INTO leads
                 (name, phone, city, budget, make, model, fuel, transmission,
                  year_min, timeline, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, phone, (f.get("city") or "").strip(),
             _int_or_none(f.get("budget")), (f.get("make") or "").strip(),
             (f.get("model") or "").strip(), (f.get("fuel") or "").strip(),
             (f.get("transmission") or "").strip(), _int_or_none(f.get("year_min")),
             (f.get("timeline") or "").strip(), (f.get("notes") or "").strip(), now()),
        )
        db.commit()
        flash("Got it. We'll start the hunt and call you back soon.", "find_car_ok")
        return redirect(url_for("public.find_car"))

    makes = [r["make"] for r in db.execute(
        "SELECT DISTINCT make FROM vehicles WHERE make IS NOT NULL AND make != '' ORDER BY make"
    ).fetchall()]
    return render_template("public/find_car.html", makes=makes)


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
