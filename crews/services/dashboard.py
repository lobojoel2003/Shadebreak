"""Shape a work day into what the crew lead's morning screen shows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.utils import timezone

from heat.units import c_to_f

from ..models import Assignment, Break, CheckIn, HourlyForecast, RiskLevel, WorkDay

RISK_SLUGS = {0: "low", 1: "caution", 2: "high", 3: "very-high", 4: "extreme"}
STALE_AFTER = timedelta(hours=3)


@dataclass
class HourCell:
    start: datetime
    risk: int
    wbgt_f: int
    heat_index_f: int
    temp_f: int
    in_shift: bool
    has_break: bool
    has_stop: bool
    is_peak: bool
    is_now: bool

    @property
    def slug(self) -> str:
        return RISK_SLUGS[self.risk]

    @property
    def label(self) -> str:
        return str(RiskLevel(self.risk).label)


@dataclass
class StopWindow:
    start: datetime
    end: datetime
    new_workers_only: bool


@dataclass
class CrewRow:
    assignment: Assignment
    checkins: list[CheckIn] = field(default_factory=list)

    @property
    def worker(self):
        return self.assignment.worker


@dataclass
class SiteDay:
    workday: WorkDay
    forecasts: list[HourlyForecast]
    cells: list[HourCell]
    breaks: list[Break]
    stops: list[StopWindow]
    rows: list[CrewRow]
    source: str | None
    updated_at: datetime | None
    stale: bool
    open_checkins: int
    help_checkins: int

    @property
    def site(self):
        return self.workday.site

    @property
    def peak_slug(self) -> str:
        return (
            RISK_SLUGS.get(self.workday.peak_risk, "unknown")
            if self.workday.peak_risk is not None
            else "unknown"
        )

    @property
    def has_forecast(self) -> bool:
        return bool(self.cells)

    @property
    def new_worker_count(self) -> int:
        return sum(1 for row in self.rows if row.assignment.present and row.assignment.needs_extra_care)

    @property
    def present_count(self) -> int:
        return sum(1 for row in self.rows if row.assignment.present)


def build_site_day(workday: WorkDay, now: datetime | None = None) -> SiteDay:
    now = now or timezone.now()
    start, end = workday.shift_start, workday.shift_end
    forecasts = list(
        HourlyForecast.objects.filter(
            site=workday.site, start__gte=start - timedelta(hours=1), start__lt=end + timedelta(hours=1)
        )
    )
    breaks = list(workday.breaks.all())
    break_hours = {
        (b.end - timedelta(minutes=max(b.minutes, b.new_worker_minutes))).replace(minute=0) for b in breaks
    }
    stop_hours = {(b.end - timedelta(minutes=1)).replace(minute=0) for b in breaks if b.stop}

    cells = [
        HourCell(
            start=f.start,
            risk=f.risk,
            wbgt_f=round(c_to_f(f.wbgt_c)),
            heat_index_f=round(f.heat_index_f),
            temp_f=round(f.temperature_f),
            in_shift=f.start + timedelta(hours=1) > start and f.start < end,
            has_break=_hour_key(f.start) in {_hour_key(h) for h in break_hours},
            has_stop=_hour_key(f.start) in {_hour_key(h) for h in stop_hours},
            is_peak=workday.peak_at == f.start,
            is_now=f.start <= now < f.start + timedelta(hours=1),
        )
        for f in forecasts
    ]

    checkins = list(workday.checkins.select_related("buddy").order_by("due_at"))
    by_worker: dict[int, list[CheckIn]] = {}
    for checkin in checkins:
        by_worker.setdefault(checkin.worker_id, []).append(checkin)
    assignments = sorted(
        workday.assignments.select_related("worker", "buddy"),
        key=lambda a: (not a.present, not a.needs_extra_care, a.worker.name.lower()),
    )
    rows = [CrewRow(assignment=a, checkins=by_worker.get(a.worker_id, [])) for a in assignments]

    latest = max(forecasts, key=lambda f: f.fetched_at) if forecasts else None
    updated_at = workday.site.forecast_updated_at or (latest.fetched_at if latest else None)
    source = latest.source if latest else None
    return SiteDay(
        workday=workday,
        forecasts=forecasts,
        cells=cells,
        breaks=breaks,
        stops=_stop_windows(breaks),
        rows=rows,
        source=source,
        updated_at=updated_at,
        stale=bool(source == HourlyForecast.Source.NWS and updated_at and now - updated_at > STALE_AFTER),
        open_checkins=sum(1 for c in checkins if c.status == CheckIn.Status.PENDING and c.due_at <= now),
        help_checkins=sum(1 for c in checkins if c.status in (CheckIn.Status.HELP, CheckIn.Status.MISSED)),
    )


def _hour_key(moment: datetime) -> tuple:
    utc = moment.astimezone(UTC)
    return (utc.year, utc.month, utc.day, utc.hour)


def _stop_windows(breaks: list[Break]) -> list[StopWindow]:
    windows: list[StopWindow] = []
    for brk in breaks:
        if not brk.new_worker_stop:
            continue
        crew_stop = brk.stop
        start = brk.end - timedelta(minutes=brk.new_worker_minutes)
        if windows and windows[-1].end == start and windows[-1].new_workers_only == (not crew_stop):
            windows[-1].end = brk.end
        else:
            windows.append(StopWindow(start=start, end=brk.end, new_workers_only=not crew_stop))
    return windows
