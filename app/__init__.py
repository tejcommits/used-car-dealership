"""Flask application factory."""
from flask import Flask

from config import Config
from . import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.teardown_appcontext(db.close_db)

    with app.app_context():
        db.init_db()
        from .seed import seed
        conn = db.get_db()
        seed(conn)

    # CLI: `venv/bin/flask --app run seed --force` to reset sample data
    @app.cli.command("seed")
    def seed_cmd():
        from .seed import seed
        n = seed(db.get_db(), force=True)
        print(f"Seeded {n} vehicles.")

    from .routes.public import bp as public_bp
    from .routes.admin import bp as admin_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.template_filter("inr")
    def inr(value):
        """Format a rupee amount the Indian way: 5,45,000 -> ?5.45 L."""
        if value is None or value == "":
            return "-"
        try:
            n = int(value)
        except (TypeError, ValueError):
            return value
        if n >= 100000:
            return f"₹{n / 100000:.2f}".rstrip("0").rstrip(".") + " L"
        # Indian grouping for smaller numbers
        s = str(n)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            import re as _re
            head = _re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
            s = head + "," + tail
        return "₹" + s

    @app.template_filter("ago")
    def ago(value):
        """Turn an ISO timestamp into '2d ago', '5h ago', 'just now'."""
        if not value:
            return "-"
        from datetime import datetime
        try:
            t = datetime.fromisoformat(str(value))
        except ValueError:
            return "-"
        secs = (datetime.now() - t).total_seconds()
        if secs < 90:
            return "just now"
        if secs < 3600:
            return f"{int(secs // 60)}m ago"
        if secs < 86400:
            return f"{int(secs // 3600)}h ago"
        days = int(secs // 86400)
        return "1 day ago" if days == 1 else f"{days} days ago"

    @app.template_filter("km")
    def km(value):
        if value is None or value == "":
            return "-"
        try:
            return f"{int(value):,} km"
        except (TypeError, ValueError):
            return value

    # Make a few values available to every template.
    # Cache-bust static assets: stamp links with the CSS file's mtime, so a
    # changed stylesheet is always re-fetched instead of served stale.
    import os
    _css = os.path.join(app.static_folder, "css", "style.css")
    try:
        asset_v = str(int(os.path.getmtime(_css)))
    except OSError:
        asset_v = "1"

    @app.context_processor
    def inject_globals():
        return {
            "business_name": app.config["BUSINESS_NAME"],
            "whatsapp_number": app.config["WHATSAPP_NUMBER"],
            "asset_v": asset_v,
        }

    # Optional in-process scheduler. On a real server prefer cron.
    if app.config["RUN_SCHEDULER"]:
        _start_scheduler(app)

    return app


def _start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from .scrapers.run import run_all

    scheduler = BackgroundScheduler(daemon=True)
    hours = app.config["SCRAPE_INTERVAL_HOURS"]

    def job():
        with app.app_context():
            run_all()

    scheduler.add_job(job, "interval", hours=hours, id="scrape_all")
    scheduler.start()
