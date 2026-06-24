# NaughtyScrape ☕

A Django + htmx + Alpine.js + Tailwind tool that scrapes **Google Maps for coffee
shops worldwide** using the **Google Places API (New)**, enriches them with emails
scraped from their websites, and manages them as a B2B lead pipeline for selling
[clickcollect.coffee](https://clickcollect.coffee).

> Internal lead-gen tool. It has email/password auth with roles, but is not
> hardened for public production use.

## What it does

- **Search** Google Places (New) `searchText` for any query across a list of
  locations (one search per location, up to 60 results each), run in the
  background with a live progress + activity log.
- **Auto-expand** (optional): run many coffee-related query variants per location
  to get well past Google's ~60-results-per-query cap (deduped by Place ID).
- **Enrich** leads by visiting each business website and extracting emails and
  social links (Google never returns emails).
- **Pipeline**: dedupe by Google Place ID, status tracking
  (new → contacted → qualified → won/lost), notes, rich filtering, and CSV export.
- **Auth & roles**: custom user model with **email as the login** (no username),
  email/password auth. **Admins** can search, enrich, and manage the team;
  **Viewers** can browse leads/jobs, edit status/notes, and export, but can't run
  searches/enrichment or manage users.

## Stack

| Concern        | Choice                                   |
|----------------|------------------------------------------|
| Backend        | Django 6 (Python 3.14)                   |
| DB             | PostgreSQL (via `psycopg` 3)             |
| Front-end      | htmx + Alpine.js + Tailwind CSS          |
| Places data    | Google Places API (New) — `searchText`   |
| Config         | `python-dotenv` (`.env`)                 |

## Setup

```bash
# 1. Python deps
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 2. Front-end (Tailwind) — only needed if you change templates/styles
npm install
npm run build          # or: npm run watch

# 3. Configure .env (already present) — add your Google key:
#    GOOGLE_MAPS_API_KEY=...
#    (Enable "Places API (New)" in Google Cloud first.)

# 4. Database
./.venv/bin/python manage.py migrate

# 5. Create your first admin (email + password — no username)
./.venv/bin/python manage.py createsuperuser            # interactive: prompts email + password
#   or non-interactively / scripted:
#   DJANGO_SUPERUSER_PASSWORD=yourpassword ./.venv/bin/python manage.py createsuperuser --email you@example.com --noinput
#   or the idempotent helper (updates if the user already exists):
#   ./.venv/bin/python manage.py bootstrap_admin --email you@example.com --password yourpassword

# 6. Run
./.venv/bin/python manage.py runserver
```

> `createsuperuser` is overridden to ask for **email + password only** — there is
> no classic Django username (the email is the login).

Open http://localhost:8000 and sign in. Add more users (admin or viewer) from
the **Team** page. New users default to **viewer**.

### Background worker

Jobs (searches + enrichment) run in the background.

- **Default (DEBUG):** an in-process worker thread starts with `runserver`, so
  you only need one terminal. You'll see `☕ NaughtyScrape in-process job worker started.`
- **Heavy batch crawls:** set `RUN_INPROCESS_WORKER=False` in `.env` and run a
  dedicated worker in its own terminal:

  ```bash
  ./.venv/bin/python manage.py runworker            # poll forever
  ./.venv/bin/python manage.py runworker --once     # drain queue and exit
  ```

## Production static files

For production deployments, use the production settings module and collect static
assets before starting Gunicorn:

```bash
DJANGO_SETTINGS_MODULE=app.settings.production ./.venv/bin/python manage.py collectstatic --noinput
```

`app.settings.production` serves static assets through WhiteNoise using
compressed manifest storage, so missing or stale static files should be fixed by
rerunning `collectstatic` during deploy.

## How searching works (important)

- Google caps a single query at **~60 results** (3 pages of 20). To cover the
  world you provide **many locations** — the search form has a one-click
  "🌍 Fill world cities" button to seed a starter list, which you can edit.
- Each location + page is a **billed Google API call**. The field mask requests
  phone + website, which is the higher-cost SKU tier — fine for lead gen, but
  worth knowing before running thousands of cities.

## `.env` keys

| Key                     | Purpose                                            |
|-------------------------|----------------------------------------------------|
| `GOOGLE_MAPS_API_KEY`   | Places API (New) key (required to run searches)    |
| `DB_*`                  | Postgres connection                                |
| `PLACES_DEFAULT_LANGUAGE` / `PLACES_DEFAULT_REGION` | default search locale     |
| `SCRAPE_REQUEST_DELAY`  | polite delay (s) between outbound requests         |
| `SCRAPE_HTTP_TIMEOUT`   | outbound HTTP timeout (s)                          |
| `RUN_INPROCESS_WORKER`  | start the worker thread inside `runserver`         |

## Project layout

```
app/                 Django project (settings package: base + development)
scraper/
  models.py          User (email login + role) + Business (lead) + CrawlJob
  services/
    places.py        Places API (New) client
    enrichment.py    website email/social scraper
    crawler.py       job orchestration + upsert
  worker.py          background worker (thread + claim loop)
  management/commands/runworker.py
  views.py · urls.py · templates/ · templatetags/
templates/base.html
static/               Tailwind source + built CSS
```
