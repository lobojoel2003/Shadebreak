import pytest
import responses
from django.core.management import call_command
from django.core.management.base import CommandError

from crews.models import Crew, HourlyForecast, WorkDay
from crews.tasks import refresh_all_sites, refresh_site
from messaging.models import Message
from messaging.tasks import escalate_missed_checkins, send_due_messages
from shadebreak import __version__
from shadebreak.version import build_info, version_string

from .conftest import load_fixture

pytestmark = pytest.mark.django_db


@responses.activate
def test_refresh_all_sites_task(site, make_worker):
    make_worker("Vera")
    site.nws_grid_id = ""
    site.save()
    responses.get("https://api.weather.gov/points/33.4484,-112.0740", json=load_fixture("nws_points.json"))
    responses.get("https://api.weather.gov/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    refresh_all_sites.delay()
    assert HourlyForecast.objects.filter(site=site).count() == 24
    assert WorkDay.objects.filter(site=site).count() == 2


@responses.activate
def test_refresh_site_survives_nws_errors(site, make_worker, settings):
    make_worker("Vera")
    site.nws_grid_id, site.nws_grid_x, site.nws_grid_y = "PSR", 159, 57
    site.save()
    responses.get("https://api.weather.gov/gridpoints/PSR/159,57", status=400, body="no")
    refresh_site(site.pk)
    assert WorkDay.objects.filter(site=site).exists()
    refresh_site(999999)  # unknown site is ignored


def test_message_tasks():
    assert send_due_messages() == 0
    assert escalate_missed_checkins() == 0


def test_seed_demo_command():
    call_command("seed_demo", password="demo-pass-123", date="2026-07-15", clock="10:20")
    crew = Crew.objects.get(name__startswith="Desert Bloom")
    assert crew.sites.count() == 2 and crew.workers.count() == 7
    assert Message.objects.filter(crew=crew, status=Message.Status.SENT).exists()
    assert Message.objects.filter(crew=crew, direction=Message.Direction.INBOUND).exists()
    # Running it again replaces the demo crew.
    call_command("seed_demo", password="demo-pass-123", date="2026-07-15", clock="10:20")
    assert Crew.objects.filter(name__startswith="Desert Bloom").count() == 1
    with pytest.raises(CommandError):
        call_command("seed_demo", password="x", clock="ten")


def test_version_info(monkeypatch):
    build_info.cache_clear()
    monkeypatch.setenv("SHADEBREAK_BUILD_NUMBER", "42")
    monkeypatch.setenv("SHADEBREAK_GIT_SHA", "0123456789abcdef")
    try:
        assert build_info() == {"version": __version__, "build": "42", "commit": "0123456", "date": ""}
        assert version_string() == f"v{__version__} · build 42 · 0123456"
    finally:
        monkeypatch.undo()
        build_info.cache_clear()
    assert build_info()["build"] == "dev"
