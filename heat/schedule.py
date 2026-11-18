"""Turn hourly conditions into a day plan: breaks, check-ins and reduced hours.

All times are timezone-aware datetimes; arithmetic is done in UTC so a shift
that crosses a daylight-saving change still gets real hours. Hours are
forecast hours (each covers ``start`` to ``start + 1 hour``); the shift is cut
into one-hour blocks from its start and each block uses the forecast at its
midpoint.

Rules:

1. The ACGIH work/rest table sets the rest each hour for the site's workload,
   using WBGT plus the clothing adjustment: the TLV for acclimatized workers,
   the stricter Action Limit for workers still acclimatizing. Below the limit
   for continuous work, no rest is required (water and shade must still be
   close, and anyone may rest at any time).
2. From High up (heat index 90 F, the 2024 proposed OSHA rule's high-heat
   trigger), nobody works more than two hours without a 15-minute rest. Time
   worked earlier in the shift counts, so the first such rest can come as
   soon as High heat begins.
3. Where even 45 minutes of rest an hour is not enough, the block is a
   *stop*: that pace of work should not happen then.

Work/rest breaks sit at the end of each block, so a crew works 45 minutes and
rests 15. Two-hour rests sit wherever the two hours run out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    moment = _utc(moment)
    for hour in hours:
        if hour.start <= moment < hour.start + HOUR:
            return hour
    return None


def shift_blocks(shift_start: datetime, shift_end: datetime) -> list[tuple[datetime, datetime]]:
    blocks = []
    shift_start, shift_end = _utc(shift_start), _utc(shift_end)
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


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def plan_breaks(
    hours: Sequence[Hour],
    shift_start: datetime,
    shift_end: datetime,
    workload: Workload | str,
    clothing_adjustment_c: float = 0.0,
) -> list[PlannedBreak]:
    shift_start, shift_end = _utc(shift_start), _utc(shift_end)
    breaks: list[PlannedBreak] = []
    tracks = ("crew", "new")
    since_rest = dict.fromkeys(tracks, 0)  # minutes worked since the last rest of 15+ minutes
    for block_start, block_end in shift_blocks(shift_start, shift_end):
        length = _minutes(block_end - block_start)
        hour = conditions_at(hours, block_start + (block_end - block_start) / 2)
        if hour is None:
            for track in tracks:
                since_rest[track] += length
            continue

        acclimatized = {"crew": True, "new": False}
        table = {
            track: rest_minutes_per_hour(hour.wbgt_c, workload, acclimatized[track], clothing_adjustment_c)
            for track in tracks
        }
        stop = {track: table[track] >= STOP_WORK for track in tracks}
        rest = {track: _scaled(table[track], length) for track in tracks}
        rest["new"] = max(rest["new"], rest["crew"])
        stop["new"] = stop["new"] or stop["crew"]
        high = max(hour.risk, risk_from_wbgt_c(hour.wbgt_c + clothing_adjustment_c)) >= Risk.HIGH

        # Two-hour rule: a 15-minute rest before anyone passes two hours of work.
        two_hour_end: dict[str, datetime] = {}
        for track in tracks:
            if not high or rest[track] >= TWO_HOUR_RULE_REST:
                continue
            if since_rest[track] + length - rest[track] < TWO_HOUR_RULE_MINUTES:
                continue
            latest = block_start + timedelta(minutes=max(0, TWO_HOUR_RULE_MINUTES - since_rest[track]))
            rest_start = max(block_start, min(latest, block_end - timedelta(minutes=TWO_HOUR_RULE_REST)))
            rest_end = rest_start + timedelta(minutes=TWO_HOUR_RULE_REST)
            if rest_end < shift_end:  # a rest at the very end of the shift is just going home
                two_hour_end[track] = rest_end

        def add(end, crew_minutes, new_minutes, reason, crew_stop=False, new_stop=False, _hour=hour):
            for existing in breaks:
                if existing.end == end:
                    breaks.remove(existing)
                    crew_minutes = max(crew_minutes, existing.minutes)
                    new_minutes = max(new_minutes, existing.new_worker_minutes)
                    crew_stop, new_stop = crew_stop or existing.stop, new_stop or existing.new_worker_stop
                    reason = existing.reason if existing.minutes >= crew_minutes else reason
                    break
            breaks.append(
                PlannedBreak(
                    end=end,
                    minutes=crew_minutes,
                    new_worker_minutes=max(new_minutes, crew_minutes),
                    reason=reason,
                    risk=_hour.risk,
                    wbgt_c=_hour.wbgt_c,
                    heat_index_f=_hour.heat_index_f,
                    stop=crew_stop,
                    new_worker_stop=new_stop,
                )
            )

        if rest["crew"]:
            add(
                block_end,
                rest["crew"],
                rest["new"],
                "stop" if stop["crew"] else "work_rest",
                stop["crew"],
                stop["new"],
            )
        elif rest["new"]:
            add(block_end, 0, rest["new"], "new_workers", False, stop["new"])
        if "crew" in two_hour_end:
            # Everyone rests together; new workers take this rest too.
            add(two_hour_end["crew"], TWO_HOUR_RULE_REST, TWO_HOUR_RULE_REST, "two_hour")
        if "new" in two_hour_end and (
            "crew" not in two_hour_end or two_hour_end["new"] < two_hour_end["crew"]
        ):
            # New workers reach two hours first (a crew rest that comes first covers them).
            add(two_hour_end["new"], 0, TWO_HOUR_RULE_REST, "two_hour")

        for track in tracks:
            minutes_key = "minutes" if track == "crew" else "new_worker_minutes"
            rests = [
                b
                for b in breaks
                if block_start < b.end <= block_end and getattr(b, minutes_key) >= TWO_HOUR_RULE_REST
            ]
            if rests:
                since_rest[track] = _minutes(block_end - max(b.end for b in rests))
            else:
                small = sum(getattr(b, minutes_key) for b in breaks if block_start < b.end <= block_end)
                since_rest[track] += length - small
    breaks.sort(key=lambda b: b.end)
    return breaks


def _checkin_interval(hour: Hour | None, first_week: bool) -> timedelta | None:
    if hour is None:
        return None
    if hour.risk >= Risk.VERY_HIGH or (first_week and hour.risk >= Risk.CAUTION):
        return HOUR
    if hour.risk >= Risk.HIGH:
        return 2 * HOUR
    return None


def plan_checkins(
    hours: Sequence[Hour],
    start: datetime,
    end: datetime,
    first_week: bool = False,
) -> list[datetime]:
    """Times a buddy should check on a worker between ``start`` and ``end``.

    Every hour at Very high or above, every two hours at High, and every hour
    from Caution up for someone in their first week or still acclimatizing.
    There is also a check when the worker comes off the heat (``end``) if the
    last stretch was hot and the previous check was at least 30 minutes ago.
    """
    start, end = _utc(start), _utc(end)
    times: list[datetime] = []
    last: datetime | None = None
    mark = start + HOUR
    while mark < end:
        interval = _checkin_interval(conditions_at(hours, mark - HOUR / 2), first_week)
        if interval is not None and (last is None or mark - last >= interval):
            times.append(mark)
            last = mark
        mark += HOUR
    final_hour = conditions_at(hours, end - timedelta(minutes=1))
    if (
        end > start
        and _checkin_interval(final_hour, first_week) is not None
        and (last is None or end - last >= timedelta(minutes=30))
    ):
        times.append(end)
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
    shift_start, shift_end = _utc(shift_start), _utc(shift_end)
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
    start, end = _utc(start), _utc(end)
    in_shift = [h for h in hours if h.start + HOUR > start and h.start < end]
    if not in_shift:
        return None
    return max(in_shift, key=lambda h: (h.risk, h.wbgt_c, h.heat_index_f))
