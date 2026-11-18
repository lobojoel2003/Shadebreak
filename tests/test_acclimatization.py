from datetime import date, timedelta

import pytest

from heat.acclimatization import (
    NEW_WORKER_RAMP,
    RETURNING_WORKER_RAMP,
    acclimatization_status,
    heat_budget,
    is_first_week,
)

TODAY = date(2026, 7, 15)


def days_before(*offsets):
    return [TODAY - timedelta(days=o) for o in offsets]


def test_brand_new_worker_starts_at_20_percent():
    status = acclimatization_status("new", [], TODAY)
    assert (status.day, status.exposure_percent, status.ramp) == (1, 20, NEW_WORKER_RAMP)
    assert status.acclimatizing
    assert status.schedule == "new"


@pytest.mark.parametrize(("worked", "day", "percent"), [(1, 2, 40), (2, 3, 60), (3, 4, 80), (4, 5, 100)])
def test_new_worker_ramps_up_on_heat_days(worked, day, percent):
    status = acclimatization_status("new", days_before(*range(1, worked + 1)), TODAY)
    assert status.day == day
    assert status.exposure_percent == percent


def test_new_worker_is_acclimatized_after_the_ramp():
    status = acclimatization_status("new", days_before(1, 2, 3, 4, 5), TODAY)
    assert status.exposure_percent == 100
    assert status.day is None
    assert not status.acclimatizing


def test_returning_worker_ramp():
    assert acclimatization_status("returning", [], TODAY).exposure_percent == 50
    assert acclimatization_status("returning", days_before(1), TODAY).exposure_percent == 60
    status = acclimatization_status("returning", days_before(1, 2), TODAY)
    assert (status.day, status.exposure_percent, status.ramp_length) == (3, 80, 4)
    assert status.schedule == "returning"


def test_acclimatized_worker_without_history_is_full_time():
    assert acclimatization_status("acclimatized", [], TODAY).exposure_percent == 100


def test_time_away_restarts_the_returning_ramp():
    status = acclimatization_status("acclimatized", days_before(20, 21, 22), TODAY)
    assert (status.day, status.exposure_percent, status.ramp) == (1, 50, RETURNING_WORKER_RAMP)
    # After a short gap acclimatization holds.
    assert acclimatization_status("acclimatized", days_before(3), TODAY).exposure_percent == 100


def test_returning_ramp_progresses_after_gap():
    history = days_before(30, 31, 32, 1)  # old season, then one hot day yesterday
    status = acclimatization_status("acclimatized", history, TODAY)
    assert (status.day, status.exposure_percent) == (2, 60)


def test_new_worker_who_never_finished_restarts_new_ramp():
    status = acclimatization_status("new", days_before(20, 21), TODAY)
    assert (status.day, status.exposure_percent, status.ramp) == (1, 20, NEW_WORKER_RAMP)


def test_new_worker_who_finished_returns_on_returning_ramp():
    status = acclimatization_status("new", days_before(20, 21, 22, 23, 24), TODAY)
    assert status.ramp == RETURNING_WORKER_RAMP


def test_gap_is_configurable_and_future_days_ignored():
    assert acclimatization_status("acclimatized", days_before(10), TODAY, gap_days=14).exposure_percent == 100
    assert acclimatization_status("new", [TODAY, TODAY + timedelta(days=1)], TODAY).exposure_percent == 20


def test_first_week():
    assert is_first_week(TODAY, TODAY)
    assert is_first_week(TODAY - timedelta(days=6), TODAY)
    assert not is_first_week(TODAY - timedelta(days=7), TODAY)
    assert not is_first_week(None, TODAY)
    assert not is_first_week(TODAY + timedelta(days=1), TODAY)


def test_heat_budget_floors_to_quarter_hours():
    assert heat_budget(510, 20) == 90
    assert heat_budget(510, 40) == 195
    assert heat_budget(60, 20) == 0
