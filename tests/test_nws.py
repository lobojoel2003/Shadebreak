from datetime import UTC, datetime, timedelta

import pytest
import responses

from nws import NWSClient, NWSError, NWSLocationError, parse_gridpoint, parse_iso_duration, parse_point
from nws.client import parse_valid_time

from .conftest import load_fixture

BASE = "https://api.weather.gov"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PT1H", timedelta(hours=1)),
        ("PT3H", timedelta(hours=3)),
        ("P1D", timedelta(days=1)),
        ("P1DT6H", timedelta(days=1, hours=6)),
        ("PT30M", timedelta(minutes=30)),
        ("P7DT14H", timedelta(days=7, hours=14)),
    ],
)
def test_parse_iso_duration(text, expected):
    assert parse_iso_duration(text) == expected


@pytest.mark.parametrize("bad", ["", "P", "PT", "1H", "P1W"])
def test_parse_iso_duration_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_iso_duration(bad)


def test_parse_valid_time_normalizes_to_utc():
    start, duration = parse_valid_time("2026-07-15T05:00:00-07:00/PT2H")
    assert start == datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert duration == timedelta(hours=2)


def test_parse_point():
    point = parse_point(load_fixture("nws_points.json"))
    assert (point.grid_id, point.grid_x, point.grid_y) == ("PSR", 159, 57)
    assert point.time_zone == "America/Phoenix"
    assert point.place == "Phoenix, AZ"


def test_parse_point_without_grid():
    with pytest.raises(NWSError):
        parse_point({"properties": {}})


def test_parse_gridpoint_expands_intervals():
    grid = parse_gridpoint(load_fixture("nws_gridpoints.json"))
    assert grid.elevation_m == pytest.approx(331.96, abs=0.01)
    assert grid.updated == datetime(2026, 7, 15, 5, 12, 41, tzinfo=UTC)
    assert len(grid.hours) == 24
    first = grid.hours[0]
    assert first.start == datetime(2026, 7, 15, 7, tzinfo=UTC)
    assert first.temp_c == 31
    assert first.dewpoint_c == 8.3
    assert first.relative_humidity == 22  # NWS humidity wins over the computed one
    assert first.wind_ms == pytest.approx(1.54, abs=0.01)  # 5.556 km/h
    assert first.sky_cover == 3
    assert first.precip_probability == 0
    assert first.nws_wbgt_c is None
    afternoon = next(h for h in grid.hours if h.start.hour == 22)
    assert afternoon.temp_c == 43
    assert afternoon.sky_cover == 24


def test_parse_gridpoint_converts_fahrenheit_and_mph_and_skips_missing_humidity():
    data = {
        "properties": {
            "temperature": {
                "uom": "wmoUnit:degF",
                "values": [
                    {"validTime": "2026-07-15T18:00:00+00:00/PT2H", "value": 100},
                    {"validTime": "2026-07-15T20:00:00+00:00/PT1H", "value": None},
                    {"validTime": "garbage", "value": 99},
                ],
            },
            "relativeHumidity": {
                "uom": "wmoUnit:percent",
                "values": [{"validTime": "2026-07-15T18:00:00+00:00/PT1H", "value": 30}],
            },
            "windSpeed": {
                "uom": "wmoUnit:mi_h-1",
                "values": [{"validTime": "2026-07-15T18:00:00+00:00/PT2H", "value": 10}],
            },
            "wetBulbGlobeTemperature": {
                "uom": "wmoUnit:degF",
                "values": [{"validTime": "2026-07-15T18:00:00+00:00/PT1H", "value": 86}],
            },
        }
    }
    grid = parse_gridpoint(data)
    assert len(grid.hours) == 1  # the 19:00 hour has no humidity or dew point
    hour = grid.hours[0]
    assert hour.temp_c == pytest.approx(37.78, abs=0.01)
    assert hour.wind_ms == pytest.approx(4.47, abs=0.01)
    assert hour.nws_wbgt_c == pytest.approx(30.0, abs=0.01)
    assert grid.updated is None and grid.elevation_m is None


def test_client_requires_user_agent():
    with pytest.raises(ValueError):
        NWSClient(user_agent="")


@responses.activate
def test_client_point_and_gridpoint():
    responses.get(f"{BASE}/points/33.4484,-112.0740", json=load_fixture("nws_points.json"))
    responses.get(f"{BASE}/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    client = NWSClient(user_agent="test-agent", backoff=0)
    point = client.point(33.44841, -112.07399)
    grid = client.gridpoint(point.grid_id, point.grid_x, point.grid_y)
    assert len(grid.hours) == 24
    assert responses.calls[0].request.headers["User-Agent"] == "test-agent"


@responses.activate
def test_client_retries_server_errors():
    url = f"{BASE}/gridpoints/PSR/159,57"
    responses.get(url, status=500, json={"title": "Unexpected Problem"})
    responses.get(url, json=load_fixture("nws_gridpoints.json"))
    grid = NWSClient(user_agent="t", backoff=0).gridpoint("PSR", 159, 57)
    assert len(grid.hours) == 24
    assert len(responses.calls) == 2


@responses.activate
def test_client_gives_up_after_retries():
    responses.get(f"{BASE}/gridpoints/PSR/1,1", status=503, json={"detail": "Gridpoint data not available"})
    with pytest.raises(NWSError, match="not available"):
        NWSClient(user_agent="t", backoff=0, retries=2).gridpoint("PSR", 1, 1)


@responses.activate
def test_client_location_errors():
    responses.get(
        f"{BASE}/points/48.8566,2.3522", status=404, json={"detail": "Data Unavailable For Requested Point"}
    )
    with pytest.raises(NWSLocationError, match="Unavailable"):
        NWSClient(user_agent="t", backoff=0).point(48.8566, 2.3522)


@responses.activate
def test_client_other_client_errors_are_not_retried():
    responses.get(f"{BASE}/points/1.0000,1.0000", status=400, body="bad request")
    with pytest.raises(NWSError):
        NWSClient(user_agent="t", backoff=0).point(1, 1)
    assert len(responses.calls) == 1


@responses.activate
def test_client_handles_connection_errors_and_bad_json():
    import requests

    url = f"{BASE}/gridpoints/PSR/2,2"
    responses.get(url, body=requests.ConnectionError("down"))
    responses.get(url, body="not json", status=200)
    with pytest.raises(NWSError):
        NWSClient(user_agent="t", backoff=0, retries=2).gridpoint("PSR", 2, 2)
