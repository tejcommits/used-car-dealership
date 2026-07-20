"""Scraper health: detect a broken source and raise an alert.

This is the lean version of "self-healing" that fits the budget. The system
watches every source and tells you the moment one stops returning data, so a
break is caught in hours instead of being discovered weeks later with a gap in
the data. The actual fix is done by hand (with help), not auto-deployed,
because at this price a wrong auto-fix that silently feeds bad data is worse
than a scraper that is visibly down.

notify() currently logs to the console. Swap the body for an email or a
WhatsApp message when you want alerts to reach a phone.
"""


def check_health(db):
    """Return the rows for any source that is actually broken.

    'paused' is a deliberate, known-off source (e.g. OLX pending a residential
    proxy) — not a break, so it doesn't raise an alert.
    """
    rows = db.execute("SELECT * FROM scraper_health").fetchall()
    return [r for r in rows if r["status"] not in ("ok", "paused")]


def report_broken(db):
    broken = check_health(db)
    for r in broken:
        notify(
            f"[scraper alert] {r['source']} is {r['status']}: {r['message']} "
            f"(found {r['items_found']}, expected at least {r['expected_min']})"
        )
    return broken


def notify(message):
    print(message)
