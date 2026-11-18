import math

import pytest

from heat.indices import (
    WBGTInput,
    dewpoint_from_rh,
    heat_index_f,
    relative_humidity,
    station_pressure_hpa,
    wbgt_c,
    wbgt_series_c,
)
from heat.solar import SolarEstimate
from heat.units import c_to_f, f_to_c, kmh_to_ms, knots_to_ms, mph_to_ms, ms_to_mph


def test_unit_round_trips():
    assert c_to_f(100) == 212
    assert f_to_c(32) == 0
    assert math.isclose(f_to_c(c_to_f(31.4)), 31.4)
    assert math.isclose(kmh_to_ms(36), 10)
    assert math.isclose(ms_to_mph(mph_to_ms(12)), 12)
    assert math.isclose(knots_to_ms(1), 0.514444)


@pytest.mark.parametrize(
    ("temp_f", "rh", "expected"),
    [
        # Values from the NWS heat index chart.
        (90, 50, 95),
        (96, 60, 116),
        (100, 40, 109),
        (86, 90, 105),
        (80, 40, 80),
        (104, 55, 137),
    ],
)
def test_heat_index_matches_nws_chart(temp_f, rh, expected):
    assert round(heat_index_f(temp_f, rh)) == pytest.approx(expected, abs=1)


def test_heat_index_low_temperatures_use_simple_formula():
    assert heat_index_f(70, 50) == pytest.approx(69.4, abs=0.5)


def test_heat_index_dry_and_humid_adjustments():
    # Low humidity adjustment lowers the regression value.
    assert heat_index_f(100, 10) < 100
    # High humidity adjustment between 80 and 87 F raises it.
    assert heat_index_f(84, 95) > heat_index_f(84, 85)


def test_relative_humidity_and_dewpoint_are_inverse():
    rh = relative_humidity(35.0, 20.0)
    assert 40 < rh < 45
    assert dewpoint_from_rh(35.0, rh) == pytest.approx(20.0, abs=0.05)
    assert relative_humidity(30, 30) == 100


def test_station_pressure():
    assert station_pressure_hpa(None) == pytest.approx(1013.25)
    assert station_pressure_hpa(1600) == pytest.approx(835, abs=5)


SUNNY = SolarEstimate(cos_zenith=0.9, ghi=900.0, direct_fraction=0.85)
NIGHT = SolarEstimate(cos_zenith=-0.2, ghi=0.0, direct_fraction=0.0)


def test_wbgt_hot_dry_desert_afternoon():
    value = c_to_f(wbgt_c(43, 10, 3, SUNNY, pressure_hpa=975))
    assert 84 < value < 90


def test_wbgt_hot_humid_sun_is_extreme():
    assert c_to_f(wbgt_c(35, 55, 2, SUNNY)) > 90


def test_shade_and_night_are_cooler_than_sun():
    sun = wbgt_c(35, 55, 2, SUNNY)
    shade = wbgt_c(35, 55, 2, SUNNY, shade=True)
    night = wbgt_c(35, 55, 2, NIGHT)
    assert shade < sun - 3
    assert night == pytest.approx(shade, abs=0.5)


def test_wbgt_rises_with_humidity_and_falls_with_wind():
    assert wbgt_c(35, 70, 2, SUNNY) > wbgt_c(35, 30, 2, SUNNY)
    assert wbgt_c(35, 50, 6, SUNNY) < wbgt_c(35, 50, 0.5, SUNNY)


def test_wbgt_series_handles_empty_and_many():
    assert wbgt_series_c([]) == []
    rows = [WBGTInput(30 + i, 40, 2, SUNNY) for i in range(5)]
    values = wbgt_series_c(rows)
    assert values == sorted(values)


def test_wbgt_falls_back_when_solver_fails(monkeypatch):
    import numpy as np

    import heat.indices as indices

    monkeypatch.setattr(
        indices.thermofeel, "calculate_wbgt_liljegren", lambda *args, **kwargs: np.array([np.nan])
    )
    value = indices.wbgt_c(32, 50, 2, SUNNY)
    assert 25 < value < 35
