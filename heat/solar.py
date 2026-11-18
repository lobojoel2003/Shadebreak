"""Sun position and an estimate of sunlight reaching a job site.

The National Weather Service forecast gives sky cover but not solar
radiation, and sunlight is what makes WBGT in full sun much higher than the
heat index suggests. We estimate it in three steps, each a standard,
published model:

1. Solar zenith angle from the NOAA "General Solar Position Calculations"
   (Spencer, 1971 series for declination and the equation of time).
2. Clear-sky global horizontal irradiance from Haurwitz (1945).
3. Cloud reduction from Kasten & Czeplak (1980), then a split into direct
   and diffuse light with the Erbs et al. (1982) correlation.

The result is an estimate, not a measurement. It is deliberately simple and
errs toward more sun when the sky-cover forecast is missing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

SOLAR_CONSTANT = 1361.0  # W/m2, top of atmosphere


@dataclass(frozen=True)
class SolarEstimate:
    cos_zenith: float  # cosine of the solar zenith angle (<= 0 means night)
    ghi: float  # global horizontal irradiance, W/m2
    direct_fraction: float  # share of ghi that is direct beam, 0..1

    @property
    def is_daylight(self) -> bool:
        return self.cos_zenith > 0.0 and self.ghi > 0.0


def _fractional_year(when: datetime) -> float:
    when = when.astimezone(UTC)
    day_of_year = when.timetuple().tm_yday
    days_in_year = 366 if _is_leap(when.year) else 365
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    return 2.0 * math.pi / days_in_year * (day_of_year - 1 + (hour - 12.0) / 24.0)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def cos_zenith(latitude: float, longitude: float, when: datetime) -> float:
    """Cosine of the solar zenith angle at ``when`` (aware datetime).

    NOAA Global Monitoring Division, "General Solar Position Calculations".
    Longitude is positive east, so U.S. sites are negative.
    """
    if when.tzinfo is None:
        raise ValueError("cos_zenith needs a timezone-aware datetime")
    g = _fractional_year(when)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    utc = when.astimezone(UTC)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60.0
    true_solar_time = minutes + eqtime + 4.0 * longitude
    hour_angle = math.radians(true_solar_time / 4.0 - 180.0)
    lat = math.radians(latitude)
    value = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    return max(-1.0, min(1.0, value))


def extraterrestrial_horizontal(cos_z: float, when: datetime) -> float:
    """Top-of-atmosphere irradiance on a horizontal surface, W/m2."""
    if cos_z <= 0:
        return 0.0
    day_of_year = when.astimezone(UTC).timetuple().tm_yday
    eccentricity = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    return SOLAR_CONSTANT * eccentricity * cos_z


def clear_sky_ghi(cos_z: float) -> float:
    """Haurwitz (1945) clear-sky global horizontal irradiance, W/m2."""
    if cos_z <= 0.01:
        return 0.0
    return 1098.0 * cos_z * math.exp(-0.059 / cos_z)


def cloudy_ghi(clear_ghi: float, sky_cover_percent: float | None) -> float:
    """Kasten & Czeplak (1980) reduction of irradiance by cloud cover."""
    if sky_cover_percent is None:
        return clear_ghi  # unknown sky: assume full sun (conservative)
    cover = max(0.0, min(1.0, sky_cover_percent / 100.0))
    return clear_ghi * (1.0 - 0.75 * cover**3.4)


def erbs_diffuse_fraction(clearness_index: float) -> float:
    """Erbs, Klein & Duffie (1982) diffuse fraction of global irradiance."""
    kt = clearness_index
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    if kt <= 0.80:
        return 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
    return 0.165


def estimate_sunlight(
    latitude: float,
    longitude: float,
    when: datetime,
    sky_cover_percent: float | None,
) -> SolarEstimate:
    """Estimate sunlight at ``when`` for a site, from sky cover alone."""
    cz = cos_zenith(latitude, longitude, when)
    ghi = cloudy_ghi(clear_sky_ghi(cz), sky_cover_percent)
    if ghi <= 0:
        return SolarEstimate(cos_zenith=cz, ghi=0.0, direct_fraction=0.0)
    toa = extraterrestrial_horizontal(cz, when)
    kt = min(1.0, ghi / toa) if toa > 0 else 0.0
    direct = 1.0 - erbs_diffuse_fraction(kt)
    return SolarEstimate(cos_zenith=cz, ghi=ghi, direct_fraction=max(0.0, min(1.0, direct)))
