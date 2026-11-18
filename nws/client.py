"""National Weather Service API client.

Shadebreak uses two endpoints:

* ``/points/{lat},{lon}`` maps a location to a forecast office grid square
  and its time zone. This rarely changes, so callers cache it.
* ``/gridpoints/{office}/{x},{y}`` returns the raw hourly forecast grids
  (temperature, dew point, humidity, wind and sky cover) in SI units, each
  value tagged with an ISO 8601 interval such as
  ``2026-07-01T18:00:00+00:00/PT3H``.

The API is free and needs no key, but asks every client to send a
User-Agent that identifies the application and a way to contact its operator.
See https://www.weather.gov/documentation/services-web-api
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from heat.indices import dewpoint_from_rh, relative_humidity
from heat.units import f_to_c, kmh_to_ms, knots_to_ms, mph_to_ms

logger = logging.getLogger(__name__)

BASE_URL = "https://api.weather.gov"
HOUR = timedelta(hours=1)
_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class NWSError(Exception):
    """The NWS API could not be reached or returned something unusable."""


class NWSLocationError(NWSError):
    """The location is outside NWS forecast coverage."""


@dataclass(frozen=True)
class Point:
    grid_id: str
    grid_x: int
    grid_y: int
    time_zone: str
    city: str = ""
    state: str = ""

    @property
    def place(self) -> str:
        return ", ".join(part for part in (self.city, self.state) if part)


@dataclass(frozen=True)
class ForecastHour:
    start: datetime  # UTC, on the hour
    temp_c: float
    dewpoint_c: float
    relative_humidity: float
    wind_ms: float
    sky_cover: float | None
    precip_probability: float | None = None
    nws_wbgt_c: float | None = None


@dataclass(frozen=True)
class GridForecast:
    updated: datetime | None
    elevation_m: float | None
    hours: list[ForecastHour] = field(default_factory=list)


def parse_iso_duration(text: str) -> timedelta:
    match = _DURATION.match(text)
    if not match or text in ("P", "PT"):
        raise ValueError(f"Unsupported ISO 8601 duration: {text!r}")
    parts = {key: int(value) for key, value in match.groupdict().items() if value}
    return timedelta(**parts)


def parse_valid_time(text: str) -> tuple[datetime, timedelta]:
    start_text, _, duration_text = text.partition("/")
    start = datetime.fromisoformat(start_text).astimezone(UTC)
    return start, parse_iso_duration(duration_text or "PT1H")


def _to_celsius(value: float, unit: str) -> float:
    if unit.endswith("degF"):
        return f_to_c(value)
    if unit.endswith("K"):
        return value - 273.15
    return value


def _to_ms(value: float, unit: str) -> float:
    if unit.endswith("km_h-1"):
        return kmh_to_ms(value)
    if unit.endswith("mi_h-1") or unit.endswith("mph"):
        return mph_to_ms(value)
    if unit.endswith("kn") or unit.endswith("kt"):
        return knots_to_ms(value)
    return value


def _hourly_values(layer: dict[str, Any] | None, convert=None) -> dict[datetime, float]:
    """Expand an NWS grid layer into ``{hour_start: value}``."""
    if not layer:
        return {}
    unit = layer.get("uom", "")
    expanded: dict[datetime, float] = {}
    for item in layer.get("values", []):
        value = item.get("value")
        if value is None:
            continue
        try:
            start, duration = parse_valid_time(item["validTime"])
        except (KeyError, ValueError):
            logger.warning("Skipping NWS value with bad validTime: %r", item)
            continue
        number = float(convert(value, unit)) if convert else float(value)
        hour = start.replace(minute=0, second=0, microsecond=0)
        end = start + duration
        while hour < end:
            expanded[hour] = number
            hour += HOUR
    return expanded


def parse_point(data: dict[str, Any]) -> Point:
    props = data.get("properties") or {}
    try:
        grid_id = props["gridId"]
        grid_x = int(props["gridX"])
        grid_y = int(props["gridY"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NWSError("NWS points response is missing grid information") from exc
    relative = ((props.get("relativeLocation") or {}).get("properties")) or {}
    return Point(
        grid_id=grid_id,
        grid_x=grid_x,
        grid_y=grid_y,
        time_zone=props.get("timeZone") or "",
        city=relative.get("city", ""),
        state=relative.get("state", ""),
    )


def parse_gridpoint(data: dict[str, Any]) -> GridForecast:
    props = data.get("properties") or {}
    temps = _hourly_values(props.get("temperature"), _to_celsius)
    dewpoints = _hourly_values(props.get("dewpoint"), _to_celsius)
    humidity = _hourly_values(props.get("relativeHumidity"))
    wind = _hourly_values(props.get("windSpeed"), _to_ms)
    sky = _hourly_values(props.get("skyCover"))
    pop = _hourly_values(props.get("probabilityOfPrecipitation"))
    wbgt = _hourly_values(props.get("wetBulbGlobeTemperature"), _to_celsius)

    hours: list[ForecastHour] = []
    for start in sorted(temps):
        temp_c = temps[start]
        if start in dewpoints:
            dew_c = dewpoints[start]
            rh = humidity.get(start, relative_humidity(temp_c, dew_c))
        elif start in humidity:
            rh = humidity[start]
            dew_c = dewpoint_from_rh(temp_c, rh)
        else:
            continue  # without humidity we cannot judge heat stress
        hours.append(
            ForecastHour(
                start=start,
                temp_c=round(temp_c, 2),
                dewpoint_c=round(dew_c, 2),
                relative_humidity=round(rh, 1),
                # Calm is rare outdoors; missing wind is treated as light air.
                wind_ms=round(wind.get(start, 1.0), 2),
                sky_cover=sky.get(start),
                precip_probability=pop.get(start),
                nws_wbgt_c=wbgt.get(start),
            )
        )

    elevation = (props.get("elevation") or {}).get("value")
    updated_text = props.get("updateTime")
    updated = datetime.fromisoformat(updated_text).astimezone(UTC) if updated_text else None
    return GridForecast(
        updated=updated,
        elevation_m=float(elevation) if elevation is not None else None,
        hours=hours,
    )


class NWSClient:
    def __init__(
        self,
        user_agent: str,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        retries: int = 3,
        backoff: float = 1.0,
        base_url: str = BASE_URL,
    ) -> None:
        if not user_agent:
            raise ValueError("The NWS API requires a User-Agent that identifies your app")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/geo+json"})
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 404:
                    raise NWSLocationError(_problem_detail(response) or "Location not found")
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        last_error = exc
                elif response.status_code in (429, 500, 502, 503, 504):
                    # The NWS API is known for brief 500/503 hiccups; retry those.
                    last_error = NWSError(f"{response.status_code}: {_problem_detail(response)}")
                else:
                    raise NWSError(f"{response.status_code}: {_problem_detail(response)}")
            if attempt + 1 < self.retries:
                time.sleep(self.backoff * (2**attempt))
        raise NWSError(f"NWS request failed for {path}: {last_error}")

    def point(self, latitude: float, longitude: float) -> Point:
        # The API wants at most four decimal places and redirects otherwise.
        return parse_point(self._get(f"/points/{latitude:.4f},{longitude:.4f}"))

    def gridpoint(self, grid_id: str, grid_x: int, grid_y: int) -> GridForecast:
        return parse_gridpoint(self._get(f"/gridpoints/{grid_id}/{grid_x},{grid_y}"))


def _problem_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    return body.get("detail") or body.get("title") or ""
