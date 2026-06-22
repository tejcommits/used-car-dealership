"""Run every scraper once, then report any broken source.

From the project root:
    venv/bin/python -m app.scrapers.run

On a server, point a cron job at that command (e.g. twice a day). That keeps
scraping out of the web process, which is the clean way to run it.
"""
from .sources import ALL_SOURCES
from .health import report_broken


def run_all(db=None):
    from ..db import get_db

    if db is None:
        db = get_db()

    results = []
    for cls in ALL_SOURCES:
        scraper = cls()
        try:
            saved, ok, error = scraper.run(db)
        except Exception as exc:
            saved, ok, error = 0, False, f"{type(exc).__name__}: {exc}"
        results.append((scraper.label, saved, ok, error))

    report_broken(db)
    return results


def main():
    from app import create_app

    app = create_app()
    with app.app_context():
        results = run_all()
        print("\nScrape complete:")
        for label, saved, ok, error in results:
            flag = "OK    " if ok else "BROKEN"
            extra = f"  ({error})" if error and not ok else ""
            print(f"  {flag} {label}: {saved} items{extra}")


if __name__ == "__main__":
    main()
