"""Heat index and wet bulb globe temperature (WBGT).

*Heat index* follows the National Weather Service algorithm: the Steadman
simple formula below 80 F, otherwise the Rothfusz regression with the NWS
low- and high-humidity adjustments.

*WBGT* is estimated with the Liljegren et al. (2008) energy-balance model, as
implemented and validated in ECMWF's open source ``thermofeel`` library. It
needs air temperature, humidity, pressure, wind and sunlight; sunlight comes
from :mod:`heat.solar`. WBGT accounts for sun and wind, which is why it can
read well above what the heat index suggests on a clear afternoon.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import thermofeel

from .solar import SolarEstimate
from .units import c_to_f, f_to_c

STANDARD_PRESSURE_HPA = 1013.25


def relative_humidity(temp_c: float, dewpoint_c: float) -> float:
    """Relative humidity (%) from temperature and dew point (Magnus formula)."""
    a, b = 17.625, 243.04
    rh = 100.0 * math.exp(a * dewpoint_c / (b + dewpoint_c) - a * temp_c / (b + temp_c))
    return max(1.0, min(100.0, rh))


def dewpoint_from_rh(temp_c: float, rh: float) -> float:
    """Dew point (C) from temperature and relative humidity (Magnus formula)."""
    a, b = 17.625, 243.04
    rh = max(1.0, min(100.0, rh))
    gamma = math.log(rh / 100.0) + a * temp_c / (b + temp_c)
    return b * gamma / (a - gamma)


def heat_index_f(temp_f: float, rh: float) -> float:
    """NWS heat index in Fahrenheit.

    https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
    """
    t, r = temp_f, rh
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + r * 0.094)
    if (simple + t) / 2.0 < 80.0:
        return (simple + t) / 2.0
    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * r
        - 0.22475541 * t * r
        - 0.00683783 * t * t
        - 0.05481717 * r * r
        + 0.00122874 * t * t * r
        + 0.00085282 * t * r * r
        - 0.00000199 * t * t * r * r
    )
    if r < 13 and 80 <= t <= 112:
        hi -= ((13 - r) / 4.0) * math.sqrt((17 - abs(t - 95.0)) / 17.0)
    elif r > 85 and 80 <= t <= 87:
        hi += ((r - 85) / 10.0) * ((87 - t) / 5.0)
    return hi


def station_pressure_hpa(elevation_m: float | None) -> float:
    """Surface pressure from elevation with the standard-atmosphere formula."""
    if not elevation_m:
        return STANDARD_PRESSURE_HPA
    return STANDARD_PRESSURE_HPA * (1.0 - 2.25577e-5 * elevation_m) ** 5.25588


@dataclass(frozen=True)
class WBGTInput:
    temp_c: float
    rh: float
    wind_ms: float
    sun: SolarEstimate


def wbgt_series_c(
    rows: Sequence[WBGTInput],
    pressure_hpa: float = STANDARD_PRESSURE_HPA,
    shade: bool = False,
) -> list[float]:
    """Liljegren WBGT (C) for many hours at once.

    With ``shade=True`` the direct and diffuse sunlight are removed, which
    gives the WBGT a worker would feel resting in full shade.
    """
    if not rows:
        return []
    t_k = np.array([r.temp_c + 273.15 for r in rows], dtype=float)
    rh = np.array([r.rh for r in rows], dtype=float)
    va = np.array([max(0.0, r.wind_ms) for r in rows], dtype=float)
    cz = np.array([r.sun.cos_zenith for r in rows], dtype=float)
    if shade:
        ssrd = np.zeros(len(rows))
        fdir = np.zeros(len(rows))
    else:
        ssrd = np.array([r.sun.ghi for r in rows], dtype=float)
        fdir = np.array([r.sun.direct_fraction for r in rows], dtype=float)
    pressure = np.full(len(rows), pressure_hpa, dtype=float)
    with np.errstate(all="ignore"):
        result_k = thermofeel.calculate_wbgt_liljegren(t_k, rh, pressure, va, ssrd, fdir, cz)
        fallback_k = thermofeel.calculate_wbgt_simple(t_k, rh)
    values = []
    for value, fallback in zip(result_k, fallback_k, strict=True):
        # The iterative solver returns NaN if it does not converge; fall back to
        # the ACSM/BoM screening approximation so we never drop an hour.
        chosen = value if np.isfinite(value) else fallback
        values.append(round(float(chosen) - 273.15, 2))
    return values


def wbgt_c(
    temp_c: float,
    rh: float,
    wind_ms: float,
    sun: SolarEstimate,
    pressure_hpa: float = STANDARD_PRESSURE_HPA,
    shade: bool = False,
) -> float:
    """Liljegren WBGT (C) for a single hour."""
    return wbgt_series_c([WBGTInput(temp_c, rh, wind_ms, sun)], pressure_hpa, shade)[0]


__all__ = [
    "WBGTInput",
    "c_to_f",
    "dewpoint_from_rh",
    "f_to_c",
    "heat_index_f",
    "relative_humidity",
    "station_pressure_hpa",
    "wbgt_c",
    "wbgt_series_c",
]
