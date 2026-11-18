"""Acclimatization: a gradual start for new and returning workers.

More than 70% of workers who die of heat die in their first week. NIOSH
recommends limiting time in the heat while the body adapts:

* New workers: no more than 20% of the usual time in the heat on day 1 and
  no more than 20% more on each following day (20, 40, 60, 80, 100%).
* Workers with previous experience: 50% on day 1, 60% on day 2, 80% on day 3
  and 100% on day 4.

Acclimatization fades with time away from the heat, so a worker whose last
hot day was more than ``gap_days`` ago starts the returning ramp again. Only
days that actually reached the Caution level count as heat days.

Source: NIOSH Criteria for a Recommended Standard: Occupational Exposure to
Heat and Hot Environments (DHHS/NIOSH 2016-106), Chapter 4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

NEW_WORKER_RAMP: tuple[int, ...] = (20, 40, 60, 80, 100)
RETURNING_WORKER_RAMP: tuple[int, ...] = (50, 60, 80, 100)
DEFAULT_GAP_DAYS = 7


class Experience(StrEnum):
    NEW = "new"  # new to hot outdoor work
    RETURNING = "returning"  # experienced, but new to this crew or back after time away
    ACCLIMATIZED = "acclimatized"  # already working in the heat


@dataclass(frozen=True)
class AcclimatizationStatus:
    exposure_percent: int
    day: int | None = None  # day of the ramp to be worked today (1-based)
    ramp: tuple[int, ...] = ()

    @property
    def acclimatizing(self) -> bool:
        return self.day is not None and self.exposure_percent < 100

    @property
    def ramp_length(self) -> int:
        return len(self.ramp)

    @property
    def schedule(self) -> str | None:
        if not self.ramp:
            return None
        return "new" if self.ramp == NEW_WORKER_RAMP else "returning"


def acclimatization_status(
    experience: Experience | str,
    heat_days: Iterable[date],
    today: date,
    gap_days: int = DEFAULT_GAP_DAYS,
) -> AcclimatizationStatus:
    """Where a worker is on their ramp today.

    ``heat_days`` are earlier dates the worker worked in Caution-level heat or
    above. Dates on or after ``today`` are ignored.
    """
    experience = Experience(experience)
    ramp: tuple[int, ...] | None
    if experience is Experience.NEW:
        ramp, day = NEW_WORKER_RAMP, 1
    elif experience is Experience.RETURNING:
        ramp, day = RETURNING_WORKER_RAMP, 1
    else:
        ramp, day = None, 0
    ever_acclimatized = experience is Experience.ACCLIMATIZED
    previous: date | None = None

    def lose_acclimatization() -> tuple[tuple[int, ...], int]:
        # Someone who never finished the new-worker ramp starts it over.
        return (RETURNING_WORKER_RAMP if ever_acclimatized else NEW_WORKER_RAMP), 1

    for current in sorted({d for d in heat_days if d < today}):
        if previous is not None and (current - previous).days > gap_days:
            ramp, day = lose_acclimatization()
        if ramp is not None:
            day += 1
            if day > len(ramp):
                ramp, day = None, 0
                ever_acclimatized = True
        previous = current

    if previous is not None and (today - previous).days > gap_days:
        ramp, day = lose_acclimatization()

    if ramp is None:
        return AcclimatizationStatus(exposure_percent=100)
    return AcclimatizationStatus(exposure_percent=ramp[day - 1], day=day, ramp=ramp)


def is_first_week(start_date: date | None, today: date) -> bool:
    """True during the first seven calendar days on the job."""
    return start_date is not None and 0 <= (today - start_date).days < 7


def floor_to_quarter_hour(delta: timedelta) -> timedelta:
    minutes = int(delta.total_seconds() // 60)
    return timedelta(minutes=minutes - minutes % 15)


def heat_budget(hot_minutes: int, percent: int) -> int:
    """Minutes of heat exposure allowed, floored to 15 minutes."""
    allowed = hot_minutes * percent // 100
    return allowed - allowed % 15


__all__ = [
    "DEFAULT_GAP_DAYS",
    "NEW_WORKER_RAMP",
    "RETURNING_WORKER_RAMP",
    "AcclimatizationStatus",
    "Experience",
    "acclimatization_status",
    "floor_to_quarter_hour",
    "heat_budget",
    "is_first_week",
]
