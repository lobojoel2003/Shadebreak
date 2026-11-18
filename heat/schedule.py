"""Turn hourly conditions into a day plan: breaks, check-ins and reduced hours.

All times are timezone-aware datetimes. Hours are forecast hours (each covers
``start`` to ``start + 1 hour``); the shift is cut into one-hour blocks from
its start and each block uses the forecast at its midpoint.

Rules, in order:

1. Below Caution, no extra breaks are scheduled (water and shade must still
   be available).
2. Once WBGT itself (plus the clothing adjustment) reaches the Caution line
   of 80 F, the ACGIH work/rest table sets the rest per hour for the site's
   workload: the TLV for the crew, the stricter Action Limit for workers who
   are still acclimatizing. The table is WBGT-based, so a humid dawn that
   trips Caution only on heat index does not trigger it.
3. From High up (heat index 90 F, the 2024 proposed OSHA rule's high-heat
   trigger), nobody goes more than two hours without a 15-minute rest.
4. Where even 45 minutes of rest an hour is not enough, the block is a
   *stop*: that pace of work should not happen then.

Breaks sit at the end of each block, so a crew works 45 minutes and rests 15.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .acclimatization import heat_budget
from .risk import STOP_WORK, Risk, Workload, rest_minutes_per_hour, risk_from_wbgt_c

HOUR = timedelta(hours=1)
QUARTER = timedelta(minutes=15)
TWO_HOUR_RULE_MINUTES = 120
TWO_HOUR_RULE_REST = 15


@dataclass(frozen=True)
class Hour:
    start: datetime
    risk: Risk
    wbgt_c: float
    heat_index_f: float


@dataclass(frozen=True)
class PlannedBreak:
    end: datetime
    minutes: int  # rest for acclimatized workers (0 = none for them)
    new_worker_minutes: int  # rest for workers still acclimatizing
    reason: str  # "work_rest", "two_hour", "new_workers" or "stop"
    risk: Risk
    wbgt_c: float
    heat_index_f: float
    stop: bool = False  # crew-wide stop
    new_worker_stop: bool = False

    @property
    def start(self) -> datetime:
        return self.end - timedelta(minutes=self.minutes)

    @property
    def new_worker_start(self) -> datetime:
        return self.end - timedelta(minutes=self.new_worker_minutes)


def conditions_at(hours: Sequence[Hour], moment: datetime) -> Hour | None:
    for hour in hours:
        if hour.start <= moment < hour.start + HOUR:
            return hour
    return None


def shift_blocks(shift_start: datetime, shift_end: datetime) -> list[tuple[datetime, datetime]]:
    blocks = []
    cursor = shift_start
    while cursor < shift_end:
        end = min(cursor + HOUR, shift_end)
        blocks.append((cursor, end))
        cursor = end
    return blocks


def _scaled(rest: int, block_minutes: int) -> int:
    """Scale an hourly rest requirement to a short final block (5-minute steps)."""
    if rest >= STOP_WORK:
        return block_minutes
    if block_minutes >= 60:
        return rest
    scaled = rest * block_minutes / 60
    return int(5 * round(scaled / 5))


def plan_breaks(
    hours: Sequence[Hour],
    shift_start: datetime,
    shift_end: datetime,
    workload: Workload | str,
    clothing_adjustment_c: float = 0.0,
) -> list[PlannedBreak]:
    breaks: list[PlannedBreak] = []
    since_rest = {"crew": 0, "new": 0}
    for block_start, block_end in shift_blocks(shift_start, shift_end):
        length = int((block_end - block_start).total_seconds() // 60)
        hour = conditions_at(hours, block_start + (block_end - block_start) / 2)
        if hour is None or hour.risk < Risk.CAUTION:
            since_rest["crew"] += length
            since_rest["new"] += length
            continue

        if risk_from_wbgt_c(hour.wbgt_c + clothing_adjustment_c) >= Risk.CAUTION:
            rest = {
                "crew": rest_minutes_per_hour(hour.wbgt_c, workload, True, clothing_adjustment_c),
                "new": rest_minutes_per_hour(hour.wbgt_c, workload, False, clothing_adjustment_c),
            }
        else:
            rest = {"crew": 0, "new": 0}
        stop = {key: value >= STOP_WORK for key, value in rest.items()}
        reason = {key: ("stop" if stop[key] else "work_rest") for key in rest}
        for key in rest:
            rest[key] = _scaled(rest[key], length)
            if (
                hour.risk >= Risk.HIGH
                and rest[key] < TWO_HOUR_RULE_REST
                and since_rest[key] + length >= TWO_HOUR_RULE_MINUTES
                and block_end < shift_end
            ):
                rest[key] = TWO_HOUR_RULE_REST
                reason[key] = "two_hour"
            if rest[key] >= TWO_HOUR_RULE_REST:
                since_rest[key] = 0
            else:
                since_rest[key] += length - rest[key]

        rest["new"] = max(rest["new"], rest["crew"])
        if rest["crew"] == 0 and rest["new"] == 0:
            continue
        crew_reason = reason["crew"] if rest["crew"] else "new_workers"
        breaks.append(
            PlannedBreak(
                end=block_end,
                minutes=rest["crew"],
                new_worker_minutes=rest["new"],
                reason=crew_reason,
                risk=hour.risk,
                wbgt_c=hour.wbgt_c,
                heat_index_f=hour.heat_index_f,
                stop=stop["crew"],
                new_worker_stop=stop["new"] or stop["crew"],
            )
        )
    return breaks


def plan_checkins(
    hours: Sequence[Hour],
    start: datetime,
    end: datetime,
    first_week: bool = False,
) -> list[datetime]:
    """Times a buddy should check on a worker.

    Every hour at Very high or above, every two hours at High, and every hour
    from Caution up for someone in their first week or still acclimatizing.
    """
    times: list[datetime] = []
    last: datetime | None = None
    mark = start + HOUR
    while mark < end:
        hour = conditions_at(hours, mark - HOUR / 2)
        interval: timedelta | None = None
        if hour is not None:
            if hour.risk >= Risk.VERY_HIGH or (first_week and hour.risk >= Risk.CAUTION):
                interval = HOUR
            elif hour.risk >= Risk.HIGH:
                interval = 2 * HOUR
        if interval is not None and (last is None or mark - last >= interval):
            times.append(mark)
            last = mark
        mark += HOUR
    return times


def exposure_end(
    hours: Sequence[Hour],
    shift_start: datetime,
    shift_end: datetime,
    percent: int,
) -> datetime:
    """When a worker on ``percent`` of normal heat exposure should stop.

    Only time at Caution or above counts against the budget, so a new worker
    can still work a cool morning in full. The budget is floored to 15 minutes.
    """
    if percent >= 100:
        return shift_end
    steps = []
    cursor = shift_start
    while cursor < shift_end:
        hour = conditions_at(hours, cursor + QUARTER / 2)
        steps.append((cursor, hour is not None and hour.risk >= Risk.CAUTION))
        cursor += QUARTER
    hot_minutes = 15 * sum(1 for _, hot in steps if hot)
    if hot_minutes == 0:
        return shift_end
    budget = heat_budget(hot_minutes, percent)
    used = 0
    for moment, hot in steps:
        if hot:
            if used >= budget:
                return moment
            used += 15
    return shift_end


def peak_hour(hours: Sequence[Hour], start: datetime, end: datetime) -> Hour | None:
    in_shift = [h for h in hours if h.start + HOUR > start and h.start < end]
    if not in_shift:
        return None
    return max(in_shift, key=lambda h: (h.risk, h.wbgt_c, h.heat_index_f))
