"""Risk levels and work/rest limits.

Shadebreak rates each hour on five levels and takes the higher of two scales,
so a hot, humid morning (heat index) and a clear, still afternoon (WBGT) both
register:

========== ============================ ==========================
Level      Heat index (F)               WBGT (F)
========== ============================ ==========================
Low        below 80                     below 80
Caution    80 to 89                     80 to 84.9
High       90 to 102                    85 to 87.9
Very high  103 to 114                   88 to 89.9
Extreme    115 and above                90 and above
========== ============================ ==========================

The 80 F and 90 F heat-index lines are the "initial" and "high" heat triggers
in OSHA's 2024 proposed heat rule; 103 F is the NWS "danger" line; 115 F is
where the OSHA-NIOSH Heat Safety Tool showed "very high to extreme". The WBGT
lines are the categories used by NWS WBGT forecasts.

Work/rest is the ACGIH TLV (acclimatized workers) and Action Limit
(unacclimatized workers) screening table for WBGT, as reproduced in the OSHA
Technical Manual, Section III, Chapter 4. A clothing adjustment value is added
to WBGT before the lookup.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from .units import c_to_f


class Risk(IntEnum):
    LOW = 0
    CAUTION = 1
    HIGH = 2
    VERY_HIGH = 3
    EXTREME = 4

    @property
    def slug(self) -> str:
        return self.name.lower().replace("_", "-")


class Workload(StrEnum):
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    VERY_HEAVY = "very_heavy"


class Clothing(StrEnum):
    STANDARD = "standard"
    DOUBLE_LAYER = "double"
    POLYOLEFIN = "polyolefin"
    VAPOR_BARRIER = "vapor_barrier"


# ACGIH clothing adjustment values, degrees C added to WBGT.
CLOTHING_ADJUSTMENT_C: dict[Clothing, float] = {
    Clothing.STANDARD: 0.0,
    Clothing.DOUBLE_LAYER: 3.0,
    Clothing.POLYOLEFIN: 1.0,
    Clothing.VAPOR_BARRIER: 11.0,
}

HEAT_INDEX_THRESHOLDS_F: tuple[tuple[float, Risk], ...] = (
    (115.0, Risk.EXTREME),
    (103.0, Risk.VERY_HIGH),
    (90.0, Risk.HIGH),
    (80.0, Risk.CAUTION),
)

WBGT_THRESHOLDS_F: tuple[tuple[float, Risk], ...] = (
    (90.0, Risk.EXTREME),
    (88.0, Risk.VERY_HIGH),
    (85.0, Risk.HIGH),
    (80.0, Risk.CAUTION),
)

# Rows are work allocations 75-100%, 50-75%, 25-50% and 0-25% of each hour.
# ``None`` means ACGIH gives no value because the strain is too high for that
# much work. Values in degrees C WBGT.
TLV_C: dict[Workload, tuple[float | None, ...]] = {
    Workload.LIGHT: (31.0, 31.0, 32.0, 32.5),
    Workload.MODERATE: (28.0, 29.0, 30.0, 31.5),
    Workload.HEAVY: (None, 27.5, 29.0, 30.5),
    Workload.VERY_HEAVY: (None, None, 28.0, 30.0),
}
ACTION_LIMIT_C: dict[Workload, tuple[float | None, ...]] = {
    Workload.LIGHT: (28.0, 28.5, 29.5, 30.0),
    Workload.MODERATE: (25.0, 26.0, 27.0, 29.0),
    Workload.HEAVY: (None, 24.0, 25.5, 28.0),
    Workload.VERY_HEAVY: (None, None, 24.5, 27.0),
}
# Minimum rest per hour for each of those rows.
REST_MINUTES_BY_ROW = (0, 15, 30, 45)
STOP_WORK = 60  # beyond the table: the work should not be done at this pace


def _level(value: float, thresholds: tuple[tuple[float, Risk], ...]) -> Risk:
    for threshold, level in thresholds:
        if value >= threshold:
            return level
    return Risk.LOW


def risk_from_heat_index(heat_index_f: float) -> Risk:
    return _level(heat_index_f, HEAT_INDEX_THRESHOLDS_F)


def risk_from_wbgt_c(wbgt_c: float) -> Risk:
    return _level(c_to_f(wbgt_c), WBGT_THRESHOLDS_F)


def hourly_risk(heat_index_f: float, wbgt_c: float) -> Risk:
    """The higher of the heat-index and WBGT levels."""
    return max(risk_from_heat_index(heat_index_f), risk_from_wbgt_c(wbgt_c))


def rest_minutes_per_hour(
    wbgt_c: float,
    workload: Workload | str,
    acclimatized: bool,
    clothing_adjustment_c: float = 0.0,
) -> int:
    """Minutes of rest each hour needed to stay under the ACGIH limit.

    Returns 0, 15, 30 or 45, or :data:`STOP_WORK` (60) when even 15 minutes
    of work an hour would exceed the limit.
    """
    table = TLV_C if acclimatized else ACTION_LIMIT_C
    limits = table[Workload(workload)]
    effective = wbgt_c + clothing_adjustment_c
    for limit, rest in zip(limits, REST_MINUTES_BY_ROW, strict=True):
        if limit is not None and effective <= limit:
            return rest
    return STOP_WORK


def lighter(workload: Workload | str) -> Workload | None:
    """The next lighter workload, used to suggest an alternative to stopping."""
    order = list(Workload)
    index = order.index(Workload(workload))
    return order[index - 1] if index > 0 else None
