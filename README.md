# Random Night

**You choose the vibe. We create the night.**

Random Night builds a curated night out in Hyderabad. Pick an area, a budget (₹1K / ₹2K / ₹5K+), how long (2 h, 4 h, all night) and a vibe (party, food, chill, surprise), and get a timed night of 2–4 stops. Go solo, bring friends, or join **Random Friday** to be matched into a group of 4–6.

It's free for guests. Venues pay Random Night per guest who actually checks in.

**Live:** https://random-night-lemon.vercel.app

## What it does

| For | Feature |
|---|---|
| Guests | Sign in with Google (or an email login link), plan and book a night, a 6-digit check-in code per stop, ratings, report/block, share-plan and SOS (112, emergency contact, location on WhatsApp) |
| Random Friday | Weekly sign-up, matched Thursday night into groups of 4–6 by area, vibe, budget and age; optional women-only groups |
| Venue staff | `/venue`: check guests in by code; dashboard of routed vs checked-in guests; monthly invoice CSV |
| Admin | `/admin`: venues, experiences, ID checks, door keys, billable visits, reports, waitlist |
| Launch | Landing page, waitlist with a referral bump, installable app (PWA) |

### Rules the code enforces (and tests cover)

- Nobody under 21 is routed to a licensed venue. 21+ also needs an ID check by staff.
- What a venue pays only reorders venues that already fit the guest's area, budget, time, vibe and the 3.5 rating floor.
- Every paying venue is labelled **Partner venue**.
- Venues are billed only for guests who checked in: once per guest, per venue, per night, at the rate in force at check-in.

## Tech

- **Frontend:** Vite + React (`frontend/`), a mobile-first PWA
- **Backend:** FastAPI + SQLAlchemy 2.0 on Python 3.12 (`backend/`), sqladmin for `/admin`
- **Database:** Postgres on [Neon](https://neon.tech) (Singapore), schema managed with Alembic
- **Hosting:** [Vercel](https://vercel.com) Services: one project serves the SPA and the FastAPI function (region `sin1`), plus a weekly cron for Random Friday matching
- **Email:** [Resend](https://resend.com) for login links

## Run it locally (Windows, Git Bash)

Backend:

```bash
cd backend
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env    # fill in ADMIN_PASSWORD, SECRET_KEY; optional GOOGLE_CLIENT_ID
DATABASE_URL=sqlite:///./dev.db .venv/Scripts/python -m app.seed
DATABASE_URL=sqlite:///./dev.db .venv/Scripts/python -m uvicorn app.main:app --reload
```

Frontend (in a second terminal, with the backend on :8000):

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173
```

Without a Resend key, the email login link is printed in the backend terminal. For the Google button locally, put `VITE_GOOGLE_CLIENT_ID=...` in `frontend/.env.local`.

## Tests

```bash
cd backend
TEST_DATABASE_URL= .venv/Scripts/python -m pytest -q    # in-memory SQLite, ~10 s
.venv/Scripts/python -m pytest -q                       # real Postgres on the Neon "test" branch, ~10 min
```

The Postgres run wipes the `test` branch, so never run two at the same time.

## Deploying

Pushing to `main` deploys to production on Vercel. One-time setup:

- **Production env vars:** `APP_URL`, `DATABASE_URL` (Neon pooled), `SECRET_KEY`, `ADMIN_PASSWORD`, `CRON_SECRET`, `RESEND_API_KEY`, `EMAIL_FROM`, `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`. The app refuses to start if any of them is missing or too weak.
- **Schema changes:** run migrations from your machine against the direct Neon URL, before the code that needs them goes live:

  ```bash
  cd backend && .venv/Scripts/alembic upgrade head    # uses DATABASE_URL_UNPOOLED from ../.env.local
  ```

- **Door staff keys:** `.venv/Scripts/python -m app.staff "Venue name" "Front door"` (the key is shown once; turn it off in `/admin`).

## Project layout

```
backend/app/       FastAPI app: auth, generator, bookings, matching, staff check-in, billing, feedback, waitlist
backend/migrations Alembic migrations
backend/seed/      sample venues and experiences (CSV)
backend/tests/     pytest suite, one file per task
frontend/src/      React app (App.jsx: guests; Staff.jsx: /venue)
tasks/plan.md      build plan, one task per commit
research/          go-to-market research
vercel.json        Vercel Services, routing, region, cron
```
