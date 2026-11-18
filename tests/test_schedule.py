from datetime import UTC, datetime, timedelta

from heat.risk import Risk, Workload
from heat.schedule import (
    Hour,
    conditions_at,
    exposure_end,
    peak_hour,
    plan_breaks,
    plan_checkins,
    shift_blocks,
)
from heat.units import f_to_c

START = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)  # 6:00 AM in Phoenix
H = timedelta(hours=1)


def hours(levels, wbgt_f=None, hi=95.0):
    """Build forecast hours from a list of risk levels (and optional WBGT F)."""
    result = []
    for index, level in enumerate(levels):
        wbgt = wbgt_f[index] if wbgt_f else {0: 75, 1: 82, 2: 86, 3: 89, 4: 92}[level]
        result.append(Hour(start=START + index * H, risk=Risk(level), wbgt_c=f_to_c(wbgt), heat_index_f=hi))
    return result


def test_shift_blocks_include_a_short_final_block():
    blocks = shift_blocks(START, START + timedelta(hours=2, minutes=30))
    assert [int((b - a).total_seconds() // 60) for a, b in blocks] == [60, 60, 30]


def test_conditions_at():
    forecast = hours([0, 1])
    assert conditions_at(forecast, START + timedelta(minutes=90)).risk == Risk.CAUTION
    assert conditions_at(forecast, START + 3 * H) is None


def test_no_breaks_on_a_low_day():
    assert plan_breaks(hours([0] * 8), START, START + 8 * H, Workload.HEAVY) == []


def test_two_hour_rule_at_high_heat_when_table_needs_nothing():
    # Light work at WBGT 86 F (30 C) is under the TLV, but heat index is high.
    forecast = hours([2] * 8, wbgt_f=[86] * 8)
    breaks = plan_breaks(forecast, START, START + 8 * H, Workload.LIGHT)
    crew = [b for b in breaks if b.minutes]
    assert [b.end - START for b in crew] == [2 * H, 4 * H, 6 * H]
    assert all(b.minutes == 15 and b.reason == "two_hour" for b in crew)
    assert crew[0].start == START + 2 * H - timedelta(minutes=15)


def test_two_hour_rule_skipped_at_end_of_shift():
    forecast = hours([2] * 2, wbgt_f=[86, 86])
    breaks = plan_breaks(forecast, START, START + 2 * H, Workload.LIGHT)
    assert all(b.minutes == 0 for b in breaks)  # only the stricter new-worker limit applies


def test_work_rest_table_applies_for_heavy_work():
    forecast = hours([3] * 3, wbgt_f=[84.5, 84.5, 84.5])  # 29.2 C
    breaks = plan_breaks(forecast, START, START + 3 * H, Workload.HEAVY)
    assert [b.minutes for b in breaks] == [45, 45, 45]
    assert all(b.new_worker_stop and not b.stop for b in breaks)


def test_table_waits_for_wbgt_caution_even_if_heat_index_is_caution():
    forecast = hours([1] * 3, wbgt_f=[70, 70, 70], hi=82)
    assert plan_breaks(forecast, START, START + 3 * H, Workload.HEAVY) == []


def test_clothing_adjustment_can_trigger_the_table():
    forecast = hours([1] * 2, wbgt_f=[75, 75], hi=82)  # 23.9 C
    assert plan_breaks(forecast, START, START + 2 * H, Workload.MODERATE) == []
    breaks = plan_breaks(forecast, START, START + 2 * H, Workload.MODERATE, clothing_adjustment_c=11)
    assert breaks and all(b.stop for b in breaks)


def test_stop_when_beyond_the_table():
    forecast = hours([4] * 2, wbgt_f=[95, 95])
    breaks = plan_breaks(forecast, START, START + 2 * H, Workload.MODERATE)
    assert all(b.stop and b.minutes == 60 and b.reason == "stop" for b in breaks)


def test_new_workers_can_need_rest_when_crew_does_not():
    forecast = hours([1] * 2, wbgt_f=[80.5, 80.5])  # 26.9 C, moderate
    breaks = plan_breaks(forecast, START, START + 2 * H, Workload.MODERATE)
    assert breaks and all(b.minutes == 0 and b.new_worker_minutes == 30 for b in breaks)
    assert breaks[0].reason == "new_workers"
    assert breaks[0].new_worker_start == breaks[0].end - timedelta(minutes=30)


def test_partial_block_rest_is_scaled():
    forecast = hours([3, 3], wbgt_f=[84.5, 84.5])
    breaks = plan_breaks(forecast, START, START + timedelta(minutes=90), Workload.HEAVY)
    assert breaks[-1].minutes == 20  # 45 min/h over a 30-minute block, rounded to 5


def test_checkins_by_risk():
    assert plan_checkins(hours([0] * 6), START, START + 6 * H) == []
    high = plan_checkins(hours([2] * 6), START, START + 6 * H)
    assert [t - START for t in high] == [1 * H, 3 * H, 5 * H]
    very_high = plan_checkins(hours([3] * 4), START, START + 4 * H)
    assert len(very_high) == 3
    first_week = plan_checkins(hours([1] * 4), START, START + 4 * H, first_week=True)
    assert len(first_week) == 3
    assert plan_checkins(hours([1] * 4), START, START + 4 * H) == []


def test_exposure_end_counts_only_hot_time():
    forecast = hours([0, 0, 1, 1, 1, 1, 1, 1])  # cool first two hours, then 6 hot hours
    end = exposure_end(forecast, START, START + 8 * H, 20)
    # 20% of 360 hot minutes = 72 -> 60 minutes of heat after 2 cool hours.
    assert end == START + 3 * H
    assert exposure_end(forecast, START, START + 8 * H, 100) == START + 8 * H
    assert exposure_end(hours([0] * 8), START, START + 8 * H, 20) == START + 8 * H


def test_exposure_end_with_tiny_budget_stops_at_first_hot_moment():
    forecast = hours([0, 1])
    assert exposure_end(forecast, START, START + 2 * H, 20) == START + H


def test_peak_hour():
    forecast = hours([1, 3, 2], wbgt_f=[82, 89, 87])
    assert peak_hour(forecast, START, START + 3 * H).risk == Risk.VERY_HIGH
    assert peak_hour([], START, START + H) is None
