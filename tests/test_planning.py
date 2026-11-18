from datetime import datetime, time, timedelta

import pytest
from freezegun import freeze_time

from crews.models import Assignment, Break, CheckIn, Experience, RiskLevel, WorkDay, Workload
from crews.services.planning import (
    ensure_scheduled_workdays,
    ensure_workday,
    heat_days,
    plan_site_days,
    plan_workday,
)
from crews.services.sample import diurnal_temperature, load_sample_forecast

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


def local(site, hh, mm=0, day=PHOENIX_DAY):
    return datetime.combine(day, time(hh, mm), tzinfo=site.tz)


def test_diurnal_curve_shape():
    assert diurnal_temperature(5.5, 20, 40) == pytest.approx(20)
    assert diurnal_temperature(16, 20, 40) == pytest.approx(40)
    assert 20 < diurnal_temperature(23, 20, 40) < 40


def test_ensure_workday_adds_regulars(site, make_worker):
    regular = make_worker("Rae")
    make_worker("Inactive", active=False)
    workday, created = ensure_workday(site, PHOENIX_DAY)
    assert created
    assert list(workday.workers.all()) == [regular]
    assert ensure_workday(site, PHOENIX_DAY) == (workday, False)
    assert workday.shift_start == local(site, 6)
    assert workday.shift_end == local(site, 14, 30)


def test_ensure_scheduled_workdays_respects_weekdays(site):
    site.weekdays = "01234"
    site.save()
    saturday = PHOENIX_DAY + timedelta(days=(5 - PHOENIX_DAY.weekday()) % 7)
    assert ensure_scheduled_workdays(site, saturday) is None
    assert ensure_scheduled_workdays(site, PHOENIX_DAY) is not None
    site.active = False
    assert ensure_scheduled_workdays(site, PHOENIX_DAY) is None


def test_night_shift_crosses_midnight(site):
    workday = WorkDay.objects.create(site=site, date=PHOENIX_DAY, start_time=time(20), end_time=time(4))
    assert workday.shift_end - workday.shift_start == timedelta(hours=8)


def test_plan_workday_builds_breaks_ramp_and_checkins(site, hot_day, make_worker):
    site.workload = Workload.HEAVY
    site.save()
    veteran = make_worker("Vera Veteran")
    rookie = make_worker("Rico Rookie", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=local(site, 4))

    workday.refresh_from_db()
    assert workday.peak_risk >= RiskLevel.HIGH
    assert workday.peak_wbgt_f > 82
    assert workday.is_heat_day
    assert Break.objects.filter(workday=workday).exists()

    a_rookie = Assignment.objects.get(workday=workday, worker=rookie)
    a_vet = Assignment.objects.get(workday=workday, worker=veteran)
    assert a_rookie.first_week and a_rookie.acclimatizing
    assert (a_rookie.acclimatization_day, a_rookie.acclimatization_days, a_rookie.exposure_percent) == (
        1,
        5,
        20,
    )
    assert a_rookie.planned_end < workday.shift_end
    assert a_rookie.reduced_today
    assert a_rookie.ramp_steps == ["today", "", "", "", ""]
    assert a_vet.exposure_percent == 100 and a_vet.planned_end == workday.shift_end
    assert a_rookie.buddy == veteran and a_vet.buddy == rookie

    rookie_checks = CheckIn.objects.filter(workday=workday, worker=rookie)
    assert rookie_checks.exists()
    assert all(c.due_at <= a_rookie.planned_end for c in rookie_checks)
    assert all(c.buddy == veteran for c in rookie_checks)


def test_replanning_keeps_answered_checkins(site, hot_day, make_worker):
    make_worker("A")
    make_worker("B", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=local(site, 4), notify=False)
    first = workday.checkins.order_by("due_at").first()
    first.status = CheckIn.Status.OK
    first.save()
    count = workday.checkins.count()
    plan_workday(workday, now=first.due_at + timedelta(minutes=5), notify=False)
    assert workday.checkins.filter(pk=first.pk, status=CheckIn.Status.OK).exists()
    assert workday.checkins.count() == count


def test_heat_days_drive_the_ramp(site, make_worker):
    load_sample_forecast(site, PHOENIX_DAY - timedelta(days=2), days=3)
    rookie = make_worker("Ana", experience=Experience.NEW, start_date=PHOENIX_DAY - timedelta(days=2))
    for offset in (2, 1):
        day = PHOENIX_DAY - timedelta(days=offset)
        workday, _ = ensure_workday(site, day)
        plan_workday(workday, now=local(site, 4, day=day), notify=False)
    assert len(heat_days(rookie, PHOENIX_DAY)) == 2
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=local(site, 4), notify=False)
    a = Assignment.objects.get(workday=workday, worker=rookie)
    assert (a.acclimatization_day, a.exposure_percent) == (3, 60)


def test_absent_days_do_not_count(site, make_worker):
    load_sample_forecast(site, PHOENIX_DAY - timedelta(days=1), days=2)
    rookie = make_worker("Ana", experience=Experience.NEW)
    yesterday = PHOENIX_DAY - timedelta(days=1)
    workday, _ = ensure_workday(site, yesterday)
    plan_workday(workday, now=local(site, 4, day=yesterday), notify=False)
    Assignment.objects.filter(worker=rookie).update(status=Assignment.Status.ABSENT)
    assert heat_days(rookie, PHOENIX_DAY) == []


def test_exposure_override(site, hot_day, make_worker):
    rookie = make_worker("R", experience=Experience.NEW)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    Assignment.objects.filter(worker=rookie).update(exposure_override=100)
    plan_workday(workday, now=local(site, 4), notify=False)
    a = Assignment.objects.get(worker=rookie)
    assert a.exposure_percent == 100 and a.planned_end == workday.shift_end


def test_plan_without_forecast(site, make_worker):
    make_worker("A")
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=local(site, 4))
    workday.refresh_from_db()
    assert workday.peak_risk is None
    assert not workday.breaks.exists()
    assert workday.planned_at is not None


def test_plan_site_days(site, make_worker):
    make_worker("A")
    load_sample_forecast(site, PHOENIX_DAY)
    with freeze_time("2026-07-15T11:00:00Z"):
        planned = plan_site_days(site, days=2)
    assert [w.date for w in planned] == [PHOENIX_DAY, PHOENIX_DAY + timedelta(days=1)]
