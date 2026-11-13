# Random Night

Hyderabad-first app that builds a curated night out (area, budget, time, vibe + company mode) and matches solo users into groups of 4–6. It's free for users; venues pay per checked-in guest.

- Plan: `tasks/plan.md` (one task = one commit, in table order)
- Research: `research/marketing-research.md`

## Stack
- Backend: `backend/`, FastAPI (sync routes + sync SQLAlchemy 2.0), Python **3.12** (matches Vercel; don't use the system 3.15).
- DB: Postgres on **Neon** (project `cold-unit-37714956`, Singapore). `neon env pull` writes `DATABASE_URL` (pooled, for the app) and `DATABASE_URL_UNPOOLED` (direct, for migrations) to the repo-root `.env.local`. `backend/.env` holds `TEST_DATABASE_URL` (Neon branch `test`, where tests drop all tables). Both files are gitignored. With no `.env.local` the app falls back to SQLite, so **use only portable column types** (no PG arrays/enums; use `JSON`, `String`, `Integer`).
- Auth (`app/auth.py`): magic link + bearer session, both stored hashed. Env: `RESEND_API_KEY`, `EMAIL_FROM`, `APP_URL`. Without `RESEND_API_KEY` the link is logged **only** when `APP_URL` is localhost (default); otherwise the request returns 503. Use `can_enter_licensed(user, night_date)` for every 21+ decision, never a raw DOB check.
- Schema changes: `create_all` only adds missing tables; it never alters existing ones. Keep changes additive until Alembic lands (before the first Vercel deploy).
- Neon config: `neon.ts` (Postgres only; branch `test` exempt from auto-expiry). Apply with `neon deploy`.
- Money is stored as whole rupees in `Integer` columns (`*_inr`), never floats.
- Frontend (from task 5): Vite + React PWA in `frontend/`.
- Hosting: Vercel (Hobby while building; **Pro before the first paid venue invoice**, because Hobby is non-commercial only) + Neon. Keep code host-agnostic: env vars only.

## Commands (Git Bash, run from `backend/`)
```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
TEST_DATABASE_URL= .venv/Scripts/python -m pytest -q   # fast loop: in-memory SQLite
.venv/Scripts/python -m pytest -q                      # real Postgres: Neon "test" branch (~2 min, before commits)
.venv/Scripts/python -m app.seed                       # seeds the branch in DATABASE_URL (Neon production)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## Rules that must never break (enforce in code and cover with tests)
- Never route a user under 21 to a licensed venue.
- Paid rank (`cpa_rate_inr`) only reorders venues that already pass the fit filter (area, budget, time, vibe, rating floor, active).
- Every paid venue is shown with a "Partner" label (CCPA dark-patterns guidelines, ASCI).
- Bill only checked-in guests; one check-in per user per stop.

## Use ECC skills throughout development
Invoke the matching ECC skill via the Skill tool **before** doing that kind of work:

| When | ECC skill |
|---|---|
| Planning a task or feature | `ecc:plan` |
| FastAPI routes, deps, schemas | `ecc:fastapi-patterns`, then `ecc:fastapi-review` after the change |
| Models, constraints, migrations (Alembic before first prod deploy) | `ecc:postgres-patterns`, `ecc:database-migrations`, review with the `ecc:database-reviewer` agent |
| Writing tests | `ecc:python-testing`; `ecc:tdd-workflow` only when TDD is explicitly asked for |
| API shape / endpoint naming | `ecc:api-design` |
| Auth, check-in codes, billing, user data | `ecc:security-review` |
| React / PWA frontend | `ecc:react-patterns`, `ecc:frontend-patterns`, `ecc:accessibility`; review with `ecc:react-review` |
| Build errors | `ecc:build-fix` (React: `ecc:react-build`) |
| Before each commit | `ecc:verification-loop`, `ecc:code-review` |
| Deploying (Vercel + Neon) | `ecc:deployment-patterns` |
| Landing page / SEO / launch marketing | `ecc:seo`, `ecc:marketing-campaign` |
| End-to-end user flows | `ecc:e2e-testing` |

Keep it lean (ponytail): minimal diffs, no speculative abstractions. Write real tests for anything touching records, billing/exports, age gating or login.
