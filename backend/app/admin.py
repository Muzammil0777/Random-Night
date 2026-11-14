"""Admin panel at /admin (sqladmin): venues, experiences, and ID checks on users."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from wtforms import FloatField
from wtforms.validators import NumberRange, Optional

from app import ratelimit, staff
from app.auth import today_ist
from app.db import SessionLocal, engine
from app.models import Experience, Report, User, Venue, VenueKey, VenueVisit, WaitlistEntry

MIN_ADMIN_PASSWORD = 12
MAX_ADMIN_FAILS, ADMIN_FAIL_WINDOW = 5, timedelta(minutes=15)  # per IP
MAX_ADMIN_FAILS_ALL = 50  # across all IPs per window: rotating IPs doesn't buy more guesses


class PasswordAuth(AuthenticationBackend):
    """One shared admin password from ADMIN_PASSWORD. Unset or too short = nobody can log in."""
    session_maker = SessionLocal  # tests point this at their own database

    async def login(self, request: Request) -> bool:
        expected = os.environ.get("ADMIN_PASSWORD", "")
        given = str((await request.form()).get("password", ""))
        keys = [f"admin-ip:{ip}"] if (ip := ratelimit.client_ip(request)) else []
        with self.session_maker() as db:
            if ratelimit.count(db, "admin-all", ADMIN_FAIL_WINDOW) >= MAX_ADMIN_FAILS_ALL or any(
                    ratelimit.count(db, k, ADMIN_FAIL_WINDOW) >= MAX_ADMIN_FAILS for k in keys):
                db.commit()
                return False  # locked out for the window, even with the right password
            # Compare bytes: compare_digest raises on non-ASCII str.
            ok = len(expected) >= MIN_ADMIN_PASSWORD and secrets.compare_digest(given.encode(), expected.encode())
            if ok:
                db.commit()
                request.session["admin"] = True
            else:
                for k in [*keys, "admin-all"]:
                    ratelimit.record(db, k)
        return ok

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


class VenueAdmin(ModelView, model=Venue):
    column_list = [Venue.id, Venue.name, Venue.area, Venue.licensed, Venue.is_partner,
                   Venue.cpa_rate_inr, Venue.rating_avg, Venue.active]
    column_searchable_list = [Venue.name, Venue.area]
    # rating_avg comes from guest ratings (task 9). Admins may set it to un-pause a venue below the 3.5 floor;
    # it's recomputed from the latest raters at the next rating.
    form_overrides = {"rating_avg": FloatField}  # sqladmin has no default field for Double
    form_args = {"rating_avg": {"validators": [Optional(), NumberRange(min=0, max=5)]}}
    can_delete = False  # check-ins and invoices point at venues: untick "active" instead

    @action(name="create-door-key", label="Create door key",
            confirmation_message="Create a new door key for this venue? It is shown only once.")
    async def create_door_key(self, request: Request):
        """Task 12: same as `python -m app.staff`, from the admin. The key page is never cached."""
        pks = [p for p in request.query_params.get("pks", "").split(",") if p]
        if len(pks) != 1 or not pks[0].isdigit():
            return PlainTextResponse("Tick exactly one venue, then choose Actions > Create door key.", status_code=400)
        with self.session_maker() as db:
            venue = db.get(Venue, int(pks[0]))
            if venue is None:
                return PlainTextResponse("No such venue.", status_code=404)
            label = f"Door key {today_ist():%d %b}"
            key, name = staff.create_key(db, venue.name, label), venue.name
        response = await self.templates.TemplateResponse(request, "door_key.html", {
            "venue": name, "label": label, "key": key, "site": os.environ.get("APP_URL", "")})
        response.headers["Cache-Control"] = "no-store"
        return response


class ExperienceAdmin(ModelView, model=Experience):
    column_list = [Experience.id, Experience.title, Experience.venue, Experience.kind, Experience.vibes,
                   Experience.price_per_head_inr, Experience.duration_min, Experience.min_age]
    column_searchable_list = [Experience.title]
    can_delete = False  # plans point at experiences


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.name, User.dob, User.id_verified, User.created_at]
    column_searchable_list = [User.email, User.name]
    form_columns = [User.id_verified]  # admins only confirm a physical ID check; identity and DOB stay as signed up
    can_create = False
    can_delete = False


class VenueKeyAdmin(ModelView, model=VenueKey):
    name_plural = "Venue keys"
    column_list = [VenueKey.id, VenueKey.venue, VenueKey.label, VenueKey.active, VenueKey.created_at]
    form_columns = [VenueKey.label, VenueKey.active]  # create keys from Venues > Actions; here rename or turn off
    can_create = False
    can_delete = False


class VenueVisitAdmin(ModelView, model=VenueVisit):
    """Billable guests across all venues; filter by venue and export CSV here. Read-only: invoices come from these."""
    name_plural = "Billable visits"
    column_list = [VenueVisit.night_date, VenueVisit.venue, VenueVisit.user_id, VenueVisit.rate_inr,
                   VenueVisit.checkin_id]
    column_default_sort = [(VenueVisit.night_date, True)]
    can_create = False
    can_edit = False
    can_delete = False


class ReportAdmin(ModelView, model=Report):
    """Safety reports from group members (the reporter has also blocked them). Read-only: act on the user."""
    column_list = [Report.created_at, Report.reporter_id, Report.reported_id, Report.reason]
    column_default_sort = [(Report.created_at, True)]
    can_create = False
    can_edit = False
    can_delete = False


class WaitlistAdmin(ModelView, model=WaitlistEntry):
    """Launch list. Invite in the order the app shows people (most referrals first, then earliest); export CSV here."""
    name_plural = "Waitlist"
    column_list = [WaitlistEntry.id, WaitlistEntry.email, WaitlistEntry.area, WaitlistEntry.referred_by_id,
                   WaitlistEntry.created_at]
    column_searchable_list = [WaitlistEntry.email]
    can_create = False
    can_edit = False


admin: Admin | None = None


def mount_admin(app) -> Admin:
    global admin
    # SECRET_KEY signs the admin session cookie. Without it a random key is used, so admin logins reset on restart.
    secret = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    https = os.environ.get("APP_URL", "").startswith("https://")
    backend = PasswordAuth(secret_key=secret, https_only=https, same_site="strict")  # admin cookie never over http
    admin = Admin(app, engine, authentication_backend=backend, title="Random Night admin",
                  templates_dir=str(Path(__file__).parent / "templates"))  # always-dark base + door-key page
    for view in (VenueAdmin, ExperienceAdmin, UserAdmin, VenueKeyAdmin, VenueVisitAdmin, ReportAdmin, WaitlistAdmin):
        admin.add_view(view)
    return admin
