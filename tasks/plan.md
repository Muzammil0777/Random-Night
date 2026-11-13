# Plan: Random Night MVP (Hyderabad)

**Complexity:** Medium-Large (~3–4 weeks, 1 dev)
**Status:** WAITING FOR CONFIRMATION. No code written yet.
**Research:** [research/marketing-research.md](../research/marketing-research.md)

## 1. Requirements restated
A user in Hyderabad picks four inputs: **area, budget (₹1K/₹2K/₹5K+), time (2h/4h/all night) and vibe (party/food/chill/surprise)**, plus a **company mode**. The app returns a **timed multi-stop night**, for example 9:00 meet group → 10:30 live music → 11:45 social challenge → 12:30 finale. Users going solo, or looking for new people, get **matched into groups of 4–6**. They check in at each stop and rate the night afterwards.

**Money.** Users pay Random Night nothing; they pay the venues directly for what they consume. **Venues pay per checked-in guest.** A venue that pays a higher rate gets more routing, **but only among venues that already fit** the user's inputs and pass the rating floor. Partner venues are **labelled** in the plan. **Under-21s are never routed to licensed venues.**

**Done =** the deck's 4-weekend loop: 50–100 users, 10–20 experiences, 5–10 venues, real check-ins and generated invoices.

## 2. Features (MVP vs later)

| MVP (build now) | Later (only when the loop is proven) |
|---|---|
| Signup (email magic link), date of birth, ID check by admin before the first 21+ night | Phone OTP, DigiLocker/Aadhaar e-KYC |
| 4 inputs + company mode: **solo-join-group, my friends, new people** | **Dating mode**. It carries the highest safety risk, so it ships last. |
| Rule-based generator over a hand-curated experience catalogue | ML personalisation ("I'm free tonight" from past nights) |
| **Weekly "Random Friday" drop**: join by Thursday, groups formed Thursday night | On-demand matching any night |
| Booking + **6-digit check-in code** that venue staff enter | QR scan with the camera |
| Ratings for the night and each stop, report/block user | Reputation scores, auto-moderation |
| Safety: share the live plan with a contact, SOS button (call + WhatsApp location) | In-app live tracking |
| **Venue dashboard:** routed vs checked-in guests, rate, monthly invoice CSV | Self-serve bidding, online payment collection |
| Admin panel = `sqladmin` over the same DB | Custom admin UI |
| Mobile-first **React web app (PWA)**: no app-store wait | React Native app |
| Partner label, rating floor and age gate enforced in the generator | Sponsored themed nights, brand sponsorship |

## 3. Architecture (deliberately boring)
- **Backend:** FastAPI + **Postgres on Neon** from day one, so there's no SQLite→Postgres migration later. SQLAlchemy models; `sqladmin` for the admin panel. Plain FastAPI + `DATABASE_URL`, nothing host-specific, so the app can move hosts by changing env vars.
- **Frontend:** one Vite + React app with route groups `/` (user) and `/venue` (venue staff). `/admin` is served by sqladmin.
- **Deploy:** Vercel (see "Hosting & distribution" below).
- **No payment gateway.** Venues get a monthly CSV/PDF invoice and pay by UPI or bank transfer.

### Hosting & distribution (minimal cost, grow later)
**Stage 1: building + free founding-venue weekends (₹0/month + domain)**
- **Vercel Hobby (free):** hosts the React build plus FastAPI as Python functions, and deploys on every `git push`. Set the function region to Singapore (`sin1`), next to the Neon DB: one hop from Hyderabad beats several DB round trips per request.
- **Neon Free:** Postgres with 1 GB storage and 100 compute-hours/month per project, in the Singapore region (Mumbai isn't confirmed). The DB sleeps when idle, so the first request after a quiet spell is a bit slower.
- **Weekly matching job:** Vercel Cron calls `/api/jobs/match` on Thursday night.
- **Login emails:** Resend or Brevo free tier.
- **Domain:** a `.in` costs ~₹500–900/year; DNS via Vercel or Cloudflare (free).

**Stage 2: before the first paid venue invoice (~$20/month ≈ ₹1,700)**
- Vercel Hobby is **non-commercial only**, so charging venues requires **Vercel Pro ($20/month per member)**.
- Cheaper alternative if ₹1,700 is too much: keep Neon and the frontend, and move only the FastAPI app to a ~$5 India VPS or Cloud Run. It's the same code, with a new `DATABASE_URL` and API URL.

**Not using Antideploy (for now):** it's an AI deploy service with a free tier, but pricing is "contact us" and it's new and unproven. That's fine to try on a side project, but don't put venue billing on it until it has a track record.

**How people get it:** a **PWA**, not an app store. They open the link (Instagram bio, a QR on a venue table tent, WhatsApp) and tap **"Install"** on Android Chrome or **Share → Add to Home Screen** on iPhone. It gets an icon and fullscreen like an app, with no store fees or review wait, and updates land instantly. Push notifications work on Android, and on iOS 16.4+ once the app is added to the Home Screen.

**When to grow (trigger, then move):**

| Trigger | Move |
|---|---|
| Start charging venues | Vercel Pro ($20/month), or move the API to a ~$5 VPS |
| Neon storage near 1 GB or compute hours run out | Neon Launch (paid, usage-based) |
| Slow API from India (DB round-trips to Singapore) | Move the DB and API to the same region, or a Mumbai Postgres |
| Users ask "is it on the Play Store?" | Wrap the PWA as a TWA via PWABuilder. One-time $25 Google Play fee, but a new personal developer account must run a 14-day closed test with 12+ testers first. |
| Need iOS App Store presence | React Native/Expo app ($99/year Apple). Apple often rejects thin web wrappers. |
| Photos/media grow | Move uploads to Cloudflare R2 |

### Data model
- `users`(id, email, name, dob, id_verified, gender_opt, emergency_contact)
- `venues`(id, name, area, licensed, closes_at, rating_avg, cpa_rate_inr, is_partner, active)
- `experiences`(id, venue_id, kind[meet/music/challenge/food/finale], vibes, price_per_head, duration_min, min_age)
- `nights`(id, date, area)
- `groups`(id, night_id)
- `group_members`(group_id, user_id)
- `plans`(id, user_id|group_id, night_id, inputs_json)
- `plan_stops`(plan_id, experience_id, starts_at, is_partner, code)
- `checkins`(plan_stop_id, user_id, venue_id, at, entered_by)
- `ratings`(user_id, plan_stop_id, stars, text)
- `reports`(reporter_id, reported_id, reason)

Invoices are a query (`checkins × cpa_rate` per venue per month), not a table.

### Generator rules (a pure function, and the heart of the business)
1. **Hard filter.** A stop stays in the candidate set only if all of these hold:
   - its area is the user's area or a neighbouring one;
   - the stops' `price_per_head` values add up to within the budget;
   - it fits inside the time window **and** before `closes_at` (1 AM on Fri/Sat);
   - its vibe matches;
   - `min_age ≤ user age`, where any **licensed venue means 21**;
   - the venue is `active` with `rating_avg ≥ floor`.
2. **Score** each remaining candidate as `fit_score` (vibe match, distance between stops, rating) + `bid_weight × cpa_rate`. **The bid weight is capped**, so payment can only reorder venues that already fit. It can never pull in a venue that failed the filter.
3. **Assemble** the stops in slot order (meet → main → challenge → finale) and set `is_partner` so the plan shows the label.
4. **Fallback:** if no partner plan fits, return the best non-partner plan. If nothing fits at all, say "no night available". Never return a broken plan.

## 4. Tasks (one task = one commit)

| # | Task | Validate |
|---|---|---|
| 1 | Scaffold FastAPI + Postgres (Neon) models + seed script (founding venues and experiences from a CSV) | `pytest` smoke test passes, `uvicorn` boots |
| 2 | Auth (magic link) + profile + date-of-birth age calc + admin ID-verify flag | **Real tests:** login, token expiry, age calc at the 21st-birthday boundary |
| 3 | `sqladmin` panel for venues, experiences and users | Manually add a venue in the admin |
| 4 | **Generator** (pure function) | **Real tests:** an under-21 never gets a licensed venue; a paying venue outside the area or vibe is never chosen; a higher bid wins only between equal-fit venues; closing time and budget are respected; partner flag is set |
| 5 | Plan UI: 4 inputs + company mode → timeline with "Partner venue" labels. Login page: strip `?token=` from the URL immediately (`history.replaceState`), set `Referrer-Policy: no-referrer`, and decide session storage (prefer httpOnly cookie, same origin on Vercel) | Click through on a phone viewport |
| 6 | Random Friday drop + group matching. A batch job buckets users by area, vibe, budget and age band into groups of 4–6, with optional women-only groups. | **Tests:** group sizes are 4–6; no under-21s in licensed-night groups; leftovers are handled |
| 7 | Booking + check-in codes + venue staff page | **Tests:** a code works once, only at the right venue, only on that night |
| 8 | Venue dashboard + monthly invoice CSV | **Tests:** invoice total = checked-in guests × rate; no-shows are not billed |
| 9 | Ratings + report/block + auto-pause for venues below the rating floor | **Tests:** a venue under the floor is excluded from the next generation |
| 10 | Safety: share plan with a contact, SOS button | Manual test on a phone |
| 11a | Deploy-ready backend: Alembic baseline (create_all only for local SQLite); `vercel.json` with Services (frontend `frontend/`, FastAPI `backend/`; `/api/*` and `/admin*` to FastAPI, everything else to the SPA incl. `/venue`), region `sin1` next to Neon, weekly cron `GET /api/jobs/match` Thu 18:00 UTC (23:30 IST) with `CRON_SECRET`; fail fast at boot in prod if any of `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`, `CRON_SECRET`, `RESEND_API_KEY`, `EMAIL_FROM` is missing/weak; DB-backed rate limits (per-IP `/api/auth/request`, per-IP `/admin/login`, wrong codes per venue key on `/api/staff/checkin`); admin cookie `https_only`; security headers | **Tests:** migrations build the same schema as the models; prod boot refuses missing secrets; each limit returns 429 past its cap |
| 11b | Landing page + waitlist with referral bump; PWA manifest + install prompt | Installs on Android and iPhone |
| 11c | First deploy (with you, on your Vercel account): link the repo, set env vars, run `alembic upgrade head` on Neon production, seed real venues, smoke-test | Live HTTPS URL works; a cron run creates groups |

**Order matters.** Tasks 1 → 2 → 4 → 7 → 8 are the money path. Tasks 3, 5, 6, 9 and 10 build on that path.

## 5. Risks

| Risk | Level | Mitigation |
|---|---|---|
| Cold start: not enough people per Friday to form groups | **High** | One weekly drop, one area cluster. The "bring your friends" mode works with zero matching. |
| Safety incident (strangers, alcohol, late night) | **High** | ID-verified users, public venues only, share plan + SOS, report/block, women-only groups, no dating mode in the MVP |
| Paid routing degrades night quality | **High** | Capped bid weight, rating floor with auto-pause, fit filter first. Covered by the task 4 tests. |
| Legal: disguised ads, under-21s in pubs | Medium | Partner label always shown. The age gate is enforced in the generator, not just the UI. |
| Venue billing disputes | Medium | Venues pay only for check-ins their own staff entered, and see each check-in live. |
| Personal data (DPDP Act 2023) | Medium | Don't store ID images: the admin verifies, and only `id_verified=true` is stored. Keep profile fields minimal. |
| Free tiers change, or Vercel Hobby's non-commercial rule | Medium | Keep code host-agnostic (env vars only). Budget $20/month for Vercel Pro from the first paid invoice. |

## 6. Open decisions for you
1. **Dating mode:** defer it until after the pilot (recommended), or include it now?
2. **Platform:** a web PWA first (recommended; ships in days), or React Native from day one?
3. **Price per checked-in guest:** talk to 5–10 venues before setting a number.

**WAITING FOR CONFIRMATION:** proceed with this plan? (yes / modify / different approach)
