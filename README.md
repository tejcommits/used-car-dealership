# Used Car Dealership (AutoLux)

A two-sided platform for a used-vehicle dealer in Pune & Mumbai.

- **Admin (private):** a deal-finder fed by scrapers across the major Pune
  listing sites. Only the dealer sees these. He spots a good deal, buys the
  vehicle, then publishes it.
- **Public:** the dealer's shopfront. Customers only ever see vehicles he has
  bought, each with an honest note on what work it needs and two prices: take
  it as-is, or pay a bit more and he gets the work done first. They enquire by
  form or WhatsApp; the deal closes offline.

Scraped listings never reach the public side. The public site shows only the
dealer's own bought inventory. Keep that line and the scraping stays low-risk.

## Stack

Flask + SQLite, server-rendered with Jinja templates. No build step, no Node,
nothing to compile. It runs on the cheapest VPS you can rent and backs up by
copying one file (`autohub.db`).

## Run it locally

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python run.py
```

Open http://localhost:5055. The admin is at `/admin` (default password
`admin`). Sample Pune listings are seeded on first run so the site is full
before the live scrapers are tuned.

To reset the sample data: `venv/bin/flask --app run seed`.

## Configuration

Copy `.env.example` to `.env` and set:

- `ADMIN_PASSWORD` — change this before going live.
- `SECRET_KEY` — a long random string.
- `BUSINESS_NAME`, `WHATSAPP_NUMBER` — shown on the public site.

## Scrapers

Eight Pune sources live in `app/scrapers/sources/`. Their current status:

- **Spinny** — live, via its JSON API. Real cars, real photos, ~300 per pull.
- **CarWale** — live, read from the page's embedded state. Real cars and photos.
- **CarDekho** — live, parsed from the rendered listing cards (some cards
  lazy-load their photo, so image coverage is partial).
- **OLX, Cars24** — coded, but both hosts are blocked from the environment this
  was built in. They run from a normal server (Cars24 may need a proxy).
- **Quikr, Team-BHP, Facebook** — coded; need selector work / a headless browser
  + proxy. Facebook is the hardest and is expected to read as broken until then.

Each source knows which URLs to fetch and how to read a listing; the base class
handles requests and records health.

Run a scrape from the command line:

```bash
venv/bin/python -m app.scrapers.run
```

On a server, point a cron job at that command (twice a day is plenty). Keep
scraping out of the web process.

### When a scraper breaks

Sites change their markup, and the harder ones (OLX, Facebook) block plain
requests. The system watches every source and flips it to "broken" the moment
it stops returning data, so you find out in hours, not weeks. See the
**Scrapers** page in the admin. The alert currently prints to the console;
swap `notify()` in `app/scrapers/health.py` for an email or WhatsApp message
when you want it on a phone.

Facebook ships as the plain-request version and will read as broken until it
is upgraded to a headless browser with a proxy. That is expected, and it is
why the source list is a budget dial, not a fixed promise.

The selectors in each source module are written against the live pages but
will need a pass against the real sites when you deploy, since markup drifts.

## Deploy a shareable link

The code is on GitHub. To get a public URL anyone can open:

**Render (free, recommended).** This repo has a `render.yaml`, so on
[render.com](https://render.com) choose New > Blueprint and point it at this
repo. It installs, starts gunicorn, and gives you a `*.onrender.com` URL. Set
`ADMIN_PASSWORD` in the dashboard. The site comes up pre-loaded with the real
listings from `app/seed_data.json`. (Free instances sleep when idle and the
disk resets on redeploy, so uploaded photos there are not permanent — fine for
a demo, move to object storage for real use.)

**GitHub Codespaces.** Open the repo in a Codespace, run
`pip install -r requirements.txt && python run.py`, and forward the port as
public. Good for a quick look without a separate host.

Locally it runs the same way (see above).

## What this build covers

The Pune deal-finder, the public shopfront with as-is and fixed pricing, the
enquiry capture, and the scraper health monitor. No payments, no KYC, no
auction, no RTO. Those were parked on purpose.

## Layout

```
app/
  __init__.py        app factory, currency filter, optional scheduler
  db.py              SQLite schema and helpers
  seed.py            sample Pune listings
  routes/
    public.py        the shopfront
    admin.py         the dealer console
  scrapers/
    base.py          BaseScraper + health recording
    health.py        broken-source detection and alerts
    run.py           run every source once
    sources/         one module per site
  templates/         Jinja templates (public + admin)
  static/            CSS and a little JS
run.py               entry point
```
