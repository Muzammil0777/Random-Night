"""Admin panel at /admin (sqladmin): venues, experiences, and ID checks on users."""
import os
import secrets

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.db import engine
from app.models import Experience, User, Venue, VenueKey, VenueVisit

MIN_ADMIN_PASSWORD = 12


class PasswordAuth(AuthenticationBackend):
    """One shared admin password from ADMIN_PASSWORD. Unset or too short = nobody can log in."""

    async def login(self, request: Request) -> bool:
        expected = os.environ.get("ADMIN_PASSWORD", "")
        given = str((await request.form()).get("password", ""))
        # Compare bytes: compare_digest raises on non-ASCII str.
        ok = len(expected) >= MIN_ADMIN_PASSWORD and secrets.compare_digest(given.encode(), expected.encode())
        if ok:
            request.session["admin"] = True
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
    form_excluded_columns = [Venue.rating_avg]  # comes from guest ratings (task 9), never typed in
    can_delete = False  # check-ins and invoices point at venues: untick "active" instead


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
    form_columns = [VenueKey.active]  # keys are created with `python -m app.staff` (shown once); here you only revoke
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


admin: Admin | None = None


def mount_admin(app) -> Admin:
    global admin
    # SECRET_KEY signs the admin session cookie. Without it a random key is used, so admin logins reset on restart.
    secret = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    admin = Admin(app, engine, authentication_backend=PasswordAuth(secret_key=secret), title="Random Night admin")
    for view in (VenueAdmin, ExperienceAdmin, UserAdmin, VenueKeyAdmin, VenueVisitAdmin):
        admin.add_view(view)
    return admin
