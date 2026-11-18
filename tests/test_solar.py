from datetime import UTC, datetime

import pytest

from heat.solar import (
    clear_sky_ghi,
    cloudy_ghi,
    cos_zenith,
    erbs_diffuse_fraction,
    estimate_sunlight,
    extraterrestrial_horizontal,
)


def test_cos_zenith_needs_aware_datetime():
    with pytest.raises(ValueError):
        cos_zenith(33.4, -112.0, datetime(2026, 7, 15, 12))


def test_sun_nearly_overhead_at_phoenix_solar_noon_in_june():
    # Phoenix solar noon in late June is about 19:30 UTC; the sun is ~10 degrees off zenith.
    cz = cos_zenith(33.45, -112.07, datetime(2026, 6, 21, 19, 30, tzinfo=UTC))
    assert cz == pytest.approx(0.985, abs=0.01)


def test_sun_below_horizon_at_night():
    assert cos_zenith(33.45, -112.07, datetime(2026, 7, 15, 9, 0, tzinfo=UTC)) < 0


def test_equator_equinox_noon_is_overhead():
    assert cos_zenith(0.0, 0.0, datetime(2026, 3, 20, 12, 7, tzinfo=UTC)) == pytest.approx(1.0, abs=0.01)


def test_clear_sky_and_clouds():
    assert clear_sky_ghi(0) == 0
    assert 950 < clear_sky_ghi(1.0) < 1050
    assert cloudy_ghi(1000, 0) == 1000
    assert cloudy_ghi(1000, 100) == pytest.approx(250)
    assert cloudy_ghi(1000, None) == 1000
    assert cloudy_ghi(1000, 50) > cloudy_ghi(1000, 90)


def test_erbs_diffuse_fraction_regimes():
    assert erbs_diffuse_fraction(0.1) == pytest.approx(0.991)
    assert erbs_diffuse_fraction(0.9) == pytest.approx(0.165)
    assert 0.1 < erbs_diffuse_fraction(0.7) < 0.4


def test_estimate_sunlight_day_and_night():
    noon = estimate_sunlight(33.45, -112.07, datetime(2026, 7, 15, 19, 30, tzinfo=UTC), 0)
    assert noon.is_daylight
    assert noon.ghi > 900
    assert 0.6 < noon.direct_fraction < 0.9
    night = estimate_sunlight(33.45, -112.07, datetime(2026, 7, 15, 9, 0, tzinfo=UTC), 0)
    assert not night.is_daylight
    assert night.ghi == 0 and night.direct_fraction == 0
    assert extraterrestrial_horizontal(-0.1, datetime(2026, 7, 15, tzinfo=UTC)) == 0


def test_overcast_cuts_sunlight():
    clear = estimate_sunlight(33.45, -112.07, datetime(2026, 7, 15, 19, 30, tzinfo=UTC), 0)
    cloudy = estimate_sunlight(33.45, -112.07, datetime(2026, 7, 15, 19, 30, tzinfo=UTC), 100)
    assert cloudy.ghi < clear.ghi / 3
    assert cloudy.direct_fraction < clear.direct_fraction
