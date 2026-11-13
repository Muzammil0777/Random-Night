"""Venue dashboard + monthly invoice CSV (task 8). Venues pay per checked-in guest (one VenueVisit each);
routed guests who never checked in (no-shows) are shown but never billed."""
import csv
import io
import re
from datetime import date

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth import IST, _aware, first_name, today_ist
from app.models import CheckIn, Experience, PlanStop, Ticket, User, VenueVisit
from app.nights import DbDep
from app.staff import StaffDep

router = APIRouter(prefix="/api/staff", tags=["billing"])
MonthQ = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, default this month (IST)")


def month_range(month: str | None) -> tuple[str, date, date]:
    first = date.fromisoformat(f"{month}-01") if month else today_ist().replace(day=1)
    nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    return first.strftime("%Y-%m"), first, nxt


class NightRow(BaseModel):
    date: date
    routed: int      # distinct guests with a booked stop here that night
    checked_in: int  # billable guests


class Dashboard(BaseModel):
    venue: str
    month: str
    rate_inr: int    # current rate; each guest is billed at the rate when they checked in
    nights: list[NightRow]
    billable_guests: int
    total_inr: int


@router.get("/dashboard")
def dashboard(key: StaffDep, db: DbDep, month: str | None = MonthQ) -> Dashboard:
    label, first, nxt = month_range(month)
    routed = dict(db.execute(
        select(Ticket.night_date, func.count(func.distinct(Ticket.user_id))).join(PlanStop).join(Experience)
        .where(Experience.venue_id == key.venue_id, Ticket.night_date >= first, Ticket.night_date < nxt)
        .group_by(Ticket.night_date)).all())
    visits = db.scalars(select(VenueVisit).where(VenueVisit.venue_id == key.venue_id,
                                                 VenueVisit.night_date >= first, VenueVisit.night_date < nxt)).all()
    checked: dict[date, int] = {}
    for v in visits:
        checked[v.night_date] = checked.get(v.night_date, 0) + 1
    nights = [NightRow(date=d, routed=routed.get(d, 0), checked_in=checked.get(d, 0))
              for d in sorted(routed.keys() | checked.keys())]
    return Dashboard(venue=key.venue.name, month=label, rate_inr=key.venue.cpa_rate_inr, nights=nights,
                     billable_guests=len(visits), total_inr=sum(v.rate_inr for v in visits))


def _cell(value):
    """Spreadsheet-safe: a guest name like '=HYPERLINK(...)' must not run as a formula in Excel/Sheets."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/invoice.csv")
def invoice_csv(key: StaffDep, db: DbDep, month: str | None = MonthQ) -> Response:
    label, first, nxt = month_range(month)
    rows = db.execute(
        select(VenueVisit, CheckIn, User.name, Experience.title)
        .join(CheckIn, CheckIn.id == VenueVisit.checkin_id).join(User, User.id == VenueVisit.user_id)
        .join(PlanStop, PlanStop.id == CheckIn.plan_stop_id).join(Experience, Experience.id == PlanStop.experience_id)
        .where(VenueVisit.venue_id == key.venue_id, VenueVisit.night_date >= first, VenueVisit.night_date < nxt)
        .order_by(VenueVisit.night_date, CheckIn.at)).all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Random Night invoice: {key.venue.name}, {label}"])
    w.writerow(["night", "checked_in_at_ist", "guest", "stop", "entered_by", "rate_inr"])
    for visit, checkin, name, title in rows:
        w.writerow([_cell(x) for x in (visit.night_date.isoformat(),
                                       _aware(checkin.at).astimezone(IST).strftime("%Y-%m-%d %H:%M"),
                                       first_name(name), title, checkin.entered_by, visit.rate_inr)])
    w.writerow(["TOTAL", "", f"{len(rows)} guests", "", "", sum(v.rate_inr for v, *_ in rows)])
    slug = re.sub(r"[^a-z0-9]+", "-", key.venue.name.lower()).strip("-")
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="random-night-{slug}-{label}.csv"'})
