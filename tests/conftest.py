from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone
from freezegun import freeze_time

from crews.models import Crew, Experience, Exposure, JobSite, Worker, Workload
from crews.services.sample import load_sample_forecast
from messaging.backends import locmem

FIXTURES = Path(__file__).parent / "fixtures"
PHOENIX_DAY = date(2026, 7, 15)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def frozen_clock():
    """Tests run at 3:00 AM in Phoenix on a summer day unless they move the clock."""
    with freeze_time("2026-07-15T10:00:00Z") as frozen:
        yield frozen


@pytest.fixture(autouse=True)
def _clean_outbox():
    locmem.outbox.clear()
    locmem.fail_numbers.clear()
    yield
    locmem.outbox.clear()
    locmem.fail_numbers.clear()


@pytest.fixture(autouse=True)
def _english(settings):
    settings.LANGUAGE_CODE = "en"
    settings.SHADEBREAK_SMS_BACKEND = "messaging.backends.locmem.LocmemBackend"
    settings.SHADEBREAK_GEOCODER = ""


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="lead", password="a-strong-pass-123")


@pytest.fixture
def crew(user):
    crew = Crew.objects.create(
        name="Test Crew",
        timezone="America/Phoenix",
        lead_name="Pat Lead",
        lead_phone="+16025550100",
    )
    crew.leads.add(user)
    return crew


@pytest.fixture
def site(crew):
    return JobSite.objects.create(
        crew=crew,
        name="Desert Park",
        address="Phoenix, AZ",
        latitude=Decimal("33.4484"),
        longitude=Decimal("-112.0740"),
        exposure=Exposure.SUN,
        workload=Workload.MODERATE,
        shift_start=time(6, 0),
        shift_end=time(14, 30),
        weekdays="0123456",
        timezone="America/Phoenix",
        elevation_m=331,
    )


@pytest.fixture
def make_worker(crew, site):
    counter = {"n": 0}

    def make(name: str, **kwargs) -> Worker:
        counter["n"] += 1
        defaults = {
            "crew": crew,
            "phone": f"+1602555{counter['n']:04d}",
            "language": "en",
            "experience": Experience.ACCLIMATIZED,
            "start_date": PHOENIX_DAY - timedelta(days=365),
            "site": site,
            "sms_opt_in": True,
        }
        defaults.update(kwargs)
        return Worker.objects.create(name=name, **defaults)

    return make


@pytest.fixture
def hot_day(site):
    """A sample hot forecast for PHOENIX_DAY (and the next day)."""
    load_sample_forecast(site, PHOENIX_DAY)
    return PHOENIX_DAY


@pytest.fixture
def early_morning():
    return datetime.combine(PHOENIX_DAY, time(4, 0), tzinfo=timezone.get_fixed_timezone(-7 * 60))


@pytest.fixture
def logged_in(client, user, crew):
    client.force_login(user)
    return client
