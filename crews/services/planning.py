"""Build each work day's plan from the forecast.

``plan_workday`` is idempotent: it is re-run whenever the forecast changes.
It rebuilds breaks, reduced hours and buddy pairs, keeps check-ins that
already happened, and asks the messaging app to reschedule texts that have
not gone out yet.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from heat.acclimatization import acclimatization_status, is_first_week
from heat.risk import Risk
from heat.schedule import Hour, exposure_end, peak_hour, plan_breaks, plan_checkins

from ..models import Assignment, Break, CheckIn, JobSite, RiskLevel, WorkDay, Worker
from .buddies import pair_buddies


def ensure_workday(site: JobSite, day: date) -> tuple[WorkDay, bool]:
    """Get or create the work day, adding the site's regular workers."""
    workday, created = WorkDay.objects.get_or_create(
        site=site,
        date=day,
        defaults={"start_time": site.shift_start, "end_time": site.shift_end},
    )
    if created:
        regulars = site.regulars.filter(active=True, start_date__lte=day)
        Assignment.objects.bulk_create([Assignment(workday=workday, worker=w) for w in regulars])
    return workday, created


def sync_regular(worker: Worker, today: date) -> None:
    """Put an active worker on their usual site's upcoming days, and take an
    inactive one off them. Past days are history and stay as they were."""
    if not worker.active:
        Assignment.objects.filter(worker=worker, workday__date__gte=today).delete()
        return
    if worker.site_id is None:
        return
    first_day = max(today, worker.start_date) if worker.start_date else today
    for workday in WorkDay.objects.filter(site_id=worker.site_id, date__gte=first_day):
        Assignment.objects.get_or_create(workday=workday, worker=worker)


def ensure_scheduled_workdays(site: JobSite, day: date) -> WorkDay | None:
    """Create the day's plan if the site works that weekday."""
    if not site.active:
        return None
    existing = WorkDay.objects.filter(site=site, date=day).first()
    if existing:
        return existing
    if not site.works_on(day):
        return None
    workday, _ = ensure_workday(site, day)
    return workday


def forecast_hours(workday: WorkDay) -> list[Hour]:
    start, end = workday.shift_start, workday.shift_end
    rows = workday.site.forecasts.filter(
        start__gte=start - timedelta(hours=3), start__lt=end + timedelta(hours=3)
    )
    return [
        Hour(start=r.start, risk=Risk(r.risk), wbgt_c=r.wbgt_c, heat_index_f=r.heat_index_f) for r in rows
    ]


def heat_days(worker: Worker, before: date) -> list[date]:
    return list(
        Assignment.objects.filter(
            worker=worker,
            workday__date__lt=before,
            workday__date__gte=worker.start_date,
            workday__peak_risk__gte=RiskLevel.CAUTION,
        )
        .exclude(status=Assignment.Status.ABSENT)
        .values_list("workday__date", flat=True)
    )


@transaction.atomic
def plan_workday(workday: WorkDay, now: datetime | None = None, notify: bool = True) -> WorkDay:
    now = now or timezone.now()
    site = workday.site
    hours = forecast_hours(workday)
    start, end = workday.shift_start, workday.shift_end

    peak = peak_hour(hours, start, end)
    workday.peak_risk = int(peak.risk) if peak else None
    workday.peak_wbgt_c = peak.wbgt_c if peak else None
    workday.peak_heat_index_f = peak.heat_index_f if peak else None
    workday.peak_at = peak.start if peak else None

    workday.breaks.all().delete()
    Break.objects.bulk_create(
        Break(
            workday=workday,
            end=b.end,
            minutes=b.minutes,
            new_worker_minutes=b.new_worker_minutes,
            reason=b.reason,
            risk=int(b.risk),
            wbgt_c=b.wbgt_c,
            heat_index_f=b.heat_index_f,
            stop=b.stop,
            new_worker_stop=b.new_worker_stop,
        )
        for b in plan_breaks(hours, start, end, site.workload, site.clothing_adjustment_c)
    )

    assignments = list(workday.assignments.select_related("worker"))
    not_started = [a.pk for a in assignments if a.worker.start_date and a.worker.start_date > workday.date]
    if not_started:  # a start date moved later after the day was set up
        Assignment.objects.filter(pk__in=not_started).delete()
        assignments = [a for a in assignments if a.pk not in not_started]
    gap = settings.SHADEBREAK_ACCLIMATIZATION_GAP_DAYS
    for a in assignments:
        status = acclimatization_status(
            a.worker.experience, heat_days(a.worker, workday.date), workday.date, gap
        )
        a.first_week = is_first_week(a.worker.start_date, workday.date)
        a.acclimatization_day = status.day
        a.acclimatization_days = status.ramp_length or None
        a.exposure_percent = (
            a.exposure_override if a.exposure_override is not None else status.exposure_percent
        )
        a.planned_end = exposure_end(hours, start, end, a.exposure_percent) if hours else end
    pair_buddies(assignments)
    Assignment.objects.bulk_update(
        assignments,
        [
            "first_week",
            "acclimatization_day",
            "acclimatization_days",
            "exposure_percent",
            "planned_end",
            "buddy",
            "buddy_manual",
        ],
    )

    _plan_checkins(workday, assignments, hours, now)

    workday.planned_at = now
    workday.save(update_fields=["peak_risk", "peak_wbgt_c", "peak_heat_index_f", "peak_at", "planned_at"])

    if notify:
        from messaging.scheduling import schedule_workday

        schedule_workday(workday, now)
    return workday


def _plan_checkins(workday: WorkDay, assignments: list[Assignment], hours: list[Hour], now: datetime) -> None:
    workday.checkins.filter(status=CheckIn.Status.PENDING, due_at__gt=now).delete()
    kept = set(workday.checkins.values_list("worker_id", "due_at"))
    new = []
    for a in assignments:
        if not a.present:
            continue
        finish = a.planned_end or workday.shift_end
        for due in plan_checkins(hours, workday.shift_start, finish, first_week=a.needs_extra_care):
            if due > now and (a.worker_id, due) not in kept:
                new.append(CheckIn(workday=workday, worker=a.worker, buddy_id=a.buddy_id, due_at=due))
    CheckIn.objects.bulk_create(new)


def plan_site_days(site: JobSite, days: int = 2, now: datetime | None = None) -> list[WorkDay]:
    """Create and plan today's and upcoming work days for a site."""
    now = now or timezone.now()
    today = now.astimezone(site.tz).date()
    planned = []
    for offset in range(days):
        workday = ensure_scheduled_workdays(site, today + timedelta(days=offset))
        if workday:
            planned.append(plan_workday(workday, now=now))
    return planned
