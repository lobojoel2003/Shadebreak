"""Fetch NWS forecasts for job sites and turn them into rated hours."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from heat.indices import WBGTInput, heat_index_f, station_pressure_hpa, wbgt_series_c
from heat.risk import hourly_risk
from heat.solar import estimate_sunlight
from heat.units import c_to_f
from nws import ForecastHour, NWSClient, NWSError, NWSLocationError

from ..models import Exposure, HourlyForecast, JobSite

logger = logging.getLogger(__name__)

KEEP_HISTORY = timedelta(days=60)


def nws_client() -> NWSClient:
    return NWSClient(user_agent=settings.SHADEBREAK_NWS_USER_AGENT)


def rate_hours(
    site: JobSite,
    hours: Iterable[ForecastHour],
    source: str = HourlyForecast.Source.NWS,
) -> list[HourlyForecast]:
    """Compute heat index, WBGT and risk for each forecast hour at a site."""
    hours = list(hours)
    if not hours:
        return []
    lat, lon = float(site.latitude), float(site.longitude)
    suns = [estimate_sunlight(lat, lon, h.start + timedelta(minutes=30), h.sky_cover) for h in hours]
    inputs = [
        WBGTInput(temp_c=h.temp_c, rh=h.relative_humidity, wind_ms=h.wind_ms, sun=sun)
        for h, sun in zip(hours, suns, strict=True)
    ]
    pressure = station_pressure_hpa(site.elevation_m)
    in_sun = wbgt_series_c(inputs, pressure)
    in_shade = wbgt_series_c(inputs, pressure, shade=True)
    fetched_at = timezone.now()

    rows = []
    for hour, sun, sun_wbgt, shade_wbgt in zip(hours, suns, in_sun, in_shade, strict=True):
        wbgt_source = "estimated"
        if site.exposure == Exposure.SHADE:
            wbgt = shade_wbgt
        elif site.exposure == Exposure.PARTIAL:
            wbgt = (sun_wbgt + shade_wbgt) / 2
        elif hour.nws_wbgt_c is not None:
            wbgt, wbgt_source = hour.nws_wbgt_c, "nws"
        else:
            wbgt = sun_wbgt
        hi = heat_index_f(c_to_f(hour.temp_c), hour.relative_humidity)
        rows.append(
            HourlyForecast(
                site=site,
                start=hour.start,
                temperature_c=hour.temp_c,
                dewpoint_c=hour.dewpoint_c,
                relative_humidity=hour.relative_humidity,
                wind_speed_ms=hour.wind_ms,
                sky_cover=hour.sky_cover,
                precip_probability=hour.precip_probability,
                solar_wm2=round(sun.ghi, 1),
                heat_index_f=round(hi, 1),
                wbgt_c=round(wbgt, 2),
                wbgt_shade_c=round(shade_wbgt, 2),
                wbgt_source=wbgt_source,
                risk=int(hourly_risk(hi, wbgt, site.clothing_adjustment_c)),
                source=source,
                fetched_at=fetched_at,
            )
        )
    return rows


def store_hours(site: JobSite, rows: list[HourlyForecast]) -> int:
    if not rows:
        return 0
    HourlyForecast.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["site", "start"],
        update_fields=[
            "temperature_c",
            "dewpoint_c",
            "relative_humidity",
            "wind_speed_ms",
            "sky_cover",
            "precip_probability",
            "solar_wm2",
            "heat_index_f",
            "wbgt_c",
            "wbgt_shade_c",
            "wbgt_source",
            "risk",
            "source",
            "fetched_at",
        ],
    )
    # Keep two months of history before the oldest hour just stored (relative
    # to the data, so loading an older sample day never deletes itself).
    cutoff = min(timezone.now(), min(row.start for row in rows)) - KEEP_HISTORY
    HourlyForecast.objects.filter(site=site, start__lt=cutoff).delete()
    return len(rows)


def refresh_site_forecast(site: JobSite, client: NWSClient | None = None) -> int:
    """Pull the latest NWS grid forecast for ``site``. Returns hours stored.

    Errors are recorded on the site (shown on the dashboard) and re-raised.
    """
    client = client or nws_client()
    lat, lon = float(site.latitude), float(site.longitude)
    try:
        if not site.has_grid:
            _locate(site, client, lat, lon)
        try:
            grid = client.gridpoint(site.nws_grid_id, site.nws_grid_x, site.nws_grid_y)
        except NWSLocationError:
            # NWS occasionally re-grids an office; look the point up again once.
            _locate(site, client, lat, lon)
            grid = client.gridpoint(site.nws_grid_id, site.nws_grid_x, site.nws_grid_y)
    except NWSError as exc:
        site.forecast_error = str(exc)[:255]
        site.save(update_fields=["forecast_error"])
        logger.warning("Forecast refresh failed for site %s: %s", site.pk, exc)
        raise

    if grid.elevation_m is not None:
        site.elevation_m = grid.elevation_m
    cutoff = timezone.now() - timedelta(hours=24)
    stored = store_hours(site, rate_hours(site, [h for h in grid.hours if h.start >= cutoff]))
    site.forecast_updated_at = timezone.now()
    site.forecast_error = ""
    site.save(
        update_fields=[
            "elevation_m",
            "forecast_updated_at",
            "forecast_error",
            "timezone",
            "nws_grid_id",
            "nws_grid_x",
            "nws_grid_y",
            "nws_place",
        ]
    )
    return stored


def _locate(site: JobSite, client: NWSClient, lat: float, lon: float) -> None:
    point = client.point(lat, lon)
    site.nws_grid_id = point.grid_id
    site.nws_grid_x = point.grid_x
    site.nws_grid_y = point.grid_y
    site.nws_place = point.place
    if point.time_zone:
        site.timezone = point.time_zone


def rerate_site(site: JobSite) -> int:
    """Recompute WBGT and risk for stored hours after site settings change."""
    hours = [
        ForecastHour(
            start=f.start,
            temp_c=f.temperature_c,
            dewpoint_c=f.dewpoint_c,
            relative_humidity=f.relative_humidity,
            wind_ms=f.wind_speed_ms,
            sky_cover=f.sky_cover,
            precip_probability=f.precip_probability,
            nws_wbgt_c=f.wbgt_c if f.wbgt_source == "nws" else None,
        )
        for f in site.forecasts.all()
    ]
    sources = {f.start: f.source for f in site.forecasts.all()}
    rows = rate_hours(site, hours)
    for row in rows:
        row.source = sources.get(row.start, HourlyForecast.Source.NWS)
    return store_hours(site, rows)
