"""A realistic sample forecast for demos and tests.

It follows the shape of a hot, clear summer day in the desert Southwest:
coolest just before sunrise, hottest mid-afternoon, a light afternoon breeze
and a few clouds late in the day. Hours are stored with source "sample" and
the dashboard labels them, so they are never mistaken for a real forecast.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta

from heat.indices import relative_humidity
from nws import ForecastHour

from ..models import HourlyForecast, JobSite
from .forecasts import rate_hours, store_hours

COOLEST_HOUR = 5.5
HOTTEST_HOUR = 16.0


def diurnal_temperature(hour: float, low_c: float, high_c: float) -> float:
    """Temperature at local ``hour`` (0-24) on a clear day."""
    rise = HOTTEST_HOUR - COOLEST_HOUR
    if COOLEST_HOUR <= hour <= HOTTEST_HOUR:
        share = (1 - math.cos(math.pi * (hour - COOLEST_HOUR) / rise)) / 2
        return low_c + (high_c - low_c) * share
    fall = 24 - rise
    since_peak = (hour - HOTTEST_HOUR) % 24
    share = (1 - math.cos(math.pi * since_peak / fall)) / 2
    return high_c - (high_c - low_c) * share


def sample_hours(
    site: JobSite,
    day: date,
    low_c: float = 29.0,
    high_c: float = 42.5,
    dewpoint_c: float = 9.0,
    days: int = 2,
) -> list[ForecastHour]:
    midnight = datetime.combine(day, time(0, 0), tzinfo=site.tz)
    hours = []
    for offset in range(24 * days):
        local = midnight + timedelta(hours=offset)
        hour = local.hour + 0.5
        temp = round(diurnal_temperature(hour, low_c, high_c), 1)
        wind = 1.5 + 2.0 * max(0.0, math.sin(math.pi * (hour - 9) / 12))
        hours.append(
            ForecastHour(
                start=local.astimezone(UTC),
                temp_c=temp,
                dewpoint_c=dewpoint_c,
                relative_humidity=round(relative_humidity(temp, dewpoint_c), 1),
                wind_ms=round(wind, 1),
                sky_cover=5.0 if hour < 15 else 25.0,
                precip_probability=0.0,
            )
        )
    return hours


def load_sample_forecast(site: JobSite, day: date, **kwargs) -> int:
    rows = rate_hours(site, sample_hours(site, day, **kwargs), source=HourlyForecast.Source.SAMPLE)
    return store_hours(site, rows)
