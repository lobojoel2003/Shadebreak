from datetime import UTC, datetime

import pytest
import responses

from crews.models import Exposure, HourlyForecast, RiskLevel
from crews.services.forecasts import rate_hours, refresh_site_forecast, rerate_site
from nws import ForecastHour, NWSClient, NWSError

from .conftest import load_fixture

pytestmark = pytest.mark.django_db
BASE = "https://api.weather.gov"


def client():
    return NWSClient(user_agent="test", backoff=0)


@responses.activate
def test_refresh_site_forecast_caches_grid_and_stores_hours(site):
    site.nws_grid_id = ""
    site.timezone = ""
    site.save()
    responses.get(f"{BASE}/points/33.4484,-112.0740", json=load_fixture("nws_points.json"))
    responses.get(f"{BASE}/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    from freezegun import freeze_time

    with freeze_time("2026-07-15T12:00:00Z"):
        stored = refresh_site_forecast(site, client())
    site.refresh_from_db()
    assert stored == 24
    assert (site.nws_grid_id, site.nws_grid_x, site.nws_grid_y) == ("PSR", 159, 57)
    assert site.timezone == "America/Phoenix"
    assert site.nws_place == "Phoenix, AZ"
    assert site.forecast_error == ""
    hottest = HourlyForecast.objects.filter(site=site).order_by("-wbgt_c").first()
    assert hottest.source == "nws"
    assert hottest.risk >= RiskLevel.HIGH
    assert 84 < hottest.wbgt_f < 95
    night = HourlyForecast.objects.get(site=site, start=datetime(2026, 7, 15, 10, tzinfo=UTC))
    assert night.solar_wm2 == 0
    assert night.wbgt_c == pytest.approx(night.wbgt_shade_c, abs=0.6)


@responses.activate
def test_refresh_is_an_upsert(site):
    site.nws_grid_id, site.nws_grid_x, site.nws_grid_y = "PSR", 159, 57
    site.save()
    responses.get(f"{BASE}/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    from freezegun import freeze_time

    with freeze_time("2026-07-15T12:00:00Z"):
        refresh_site_forecast(site, client())
        refresh_site_forecast(site, client())
    assert HourlyForecast.objects.filter(site=site).count() == 24
    assert len(responses.calls) == 2  # no /points lookup when the grid is cached


@responses.activate
def test_refresh_relocates_after_regrid(site):
    site.nws_grid_id, site.nws_grid_x, site.nws_grid_y = "OLD", 1, 1
    site.save()
    responses.get(f"{BASE}/gridpoints/OLD/1,1", status=404, json={"detail": "Not found"})
    responses.get(f"{BASE}/points/33.4484,-112.0740", json=load_fixture("nws_points.json"))
    responses.get(f"{BASE}/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    from freezegun import freeze_time

    with freeze_time("2026-07-15T12:00:00Z"):
        assert refresh_site_forecast(site, client()) == 24
    site.refresh_from_db()
    assert site.nws_grid_id == "PSR"


@responses.activate
def test_refresh_records_errors(site):
    site.nws_grid_id = ""
    site.save()
    responses.get(f"{BASE}/points/33.4484,-112.0740", status=500, json={"title": "Unexpected Problem"})
    with pytest.raises(NWSError):
        refresh_site_forecast(site, NWSClient(user_agent="t", backoff=0, retries=1))
    site.refresh_from_db()
    assert "Unexpected Problem" in site.forecast_error


def noon_hour(**overrides):
    values = {
        "start": datetime(2026, 7, 15, 19, tzinfo=UTC),
        "temp_c": 36.0,
        "dewpoint_c": 20.0,
        "relative_humidity": 42.0,
        "wind_ms": 2.0,
        "sky_cover": 0.0,
    }
    values.update(overrides)
    return ForecastHour(**values)


def test_exposure_changes_wbgt(site):
    site.exposure = Exposure.SUN
    sun = rate_hours(site, [noon_hour()])[0]
    site.exposure = Exposure.PARTIAL
    partial = rate_hours(site, [noon_hour()])[0]
    site.exposure = Exposure.SHADE
    shade = rate_hours(site, [noon_hour()])[0]
    assert sun.wbgt_c > partial.wbgt_c > shade.wbgt_c
    assert shade.wbgt_c == shade.wbgt_shade_c


def test_nws_wbgt_is_preferred_in_full_sun(site):
    row = rate_hours(site, [noon_hour(nws_wbgt_c=31.5)])[0]
    assert row.wbgt_c == 31.5
    assert row.wbgt_source == "nws"
    assert rate_hours(site, []) == []


def test_rerate_after_exposure_change(site, hot_day):
    before = HourlyForecast.objects.filter(site=site).order_by("-wbgt_c").first().wbgt_c
    site.exposure = Exposure.SHADE
    site.save()
    assert rerate_site(site) > 0
    after = HourlyForecast.objects.filter(site=site).order_by("-wbgt_c").first()
    assert after.wbgt_c < before
    assert after.source == "sample"


def test_old_history_is_pruned_but_new_batches_are_kept(site, frozen_clock):
    from datetime import timedelta

    from crews.services.forecasts import store_hours

    old = rate_hours(site, [noon_hour(start=datetime(2026, 4, 1, 19, tzinfo=UTC))])
    store_hours(site, old)
    assert HourlyForecast.objects.filter(site=site).count() == 1
    store_hours(site, rate_hours(site, [noon_hour()]))
    assert HourlyForecast.objects.filter(site=site).count() == 1  # April is > 60 days before July
    # Loading an old sample day long after the fact keeps it.
    frozen_clock.move_to(datetime(2026, 11, 18, tzinfo=UTC))
    store_hours(
        site, rate_hours(site, [noon_hour(start=datetime(2026, 7, 15, 19, tzinfo=UTC) - timedelta(days=1))])
    )
    assert HourlyForecast.objects.filter(site=site).count() == 2
