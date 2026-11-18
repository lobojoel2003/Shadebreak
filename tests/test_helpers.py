from decimal import Decimal

import pytest
import requests
import responses
from django.core.exceptions import ValidationError

from crews.models import Crew, validate_timezone, validate_weekdays
from crews.phones import display_phone, normalize_phone
from crews.services.geocode import CENSUS_URL, geocode
from heat.risk import Risk


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("602-555-0142", "+16025550142"),
        ("1 (602) 555 0142", "+16025550142"),
        ("+52 33 1234 5678", "+523312345678"),
        ("", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "+1234", "+1234567890123456"])
def test_normalize_phone_rejects(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


def test_display_phone():
    assert display_phone("+16025550142") == "(602) 555-0142"
    assert display_phone("+523312345678") == "+523312345678"
    assert display_phone("") == ""


def test_validators():
    validate_timezone("America/Phoenix")
    validate_weekdays("01234")
    for bad in ["Mars/Base", ""]:
        with pytest.raises(ValidationError):
            validate_timezone(bad)
    for bad in ["", "78", "001"]:
        with pytest.raises(ValidationError):
            validate_weekdays(bad)


@pytest.mark.django_db
def test_crew_clean_normalizes_phone():
    crew = Crew(name="x", lead_phone="602 555 0100")
    crew.clean()
    assert crew.lead_phone == "+16025550100"
    assert str(crew) == "x"


@responses.activate
def test_geocode_census(settings):
    settings.SHADEBREAK_GEOCODER = "census"
    responses.get(
        CENSUS_URL,
        json={"result": {"addressMatches": [{"coordinates": {"x": -112.030212, "y": 33.509187}}]}},
    )
    assert geocode("2400 E Camelback Rd, Phoenix, AZ") == (Decimal("33.5092"), Decimal("-112.0302"))
    responses.replace(responses.GET, CENSUS_URL, json={"result": {"addressMatches": []}})
    assert geocode("nowhere") is None
    responses.replace(responses.GET, CENSUS_URL, body=requests.ConnectionError("down"))
    assert geocode("anything") is None
    assert geocode("   ") is None
    settings.SHADEBREAK_GEOCODER = ""
    assert geocode("2400 E Camelback Rd") is None


def test_risk_enum():
    assert [r.slug for r in Risk] == ["low", "caution", "high", "very-high", "extreme"]
