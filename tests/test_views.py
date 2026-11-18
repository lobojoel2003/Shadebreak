from datetime import timedelta
from decimal import Decimal

import pytest
import responses

from crews.models import Assignment, CheckIn, Crew, Experience, JobSite, WorkDay, Worker
from crews.services.planning import ensure_workday, plan_workday

from .conftest import PHOENIX_DAY, load_fixture

pytestmark = pytest.mark.django_db


def test_pages_require_login(client):
    for url in ["/", "/crew/", "/sites/", "/messages/", "/plan/", "/settings/"]:
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith("/accounts/login/")


def test_login_page_and_signup(client, django_user_model):
    assert client.get("/accounts/login/").status_code == 200
    response = client.post(
        "/signup/",
        {
            "crew_name": "Sunrise Roofing",
            "lead_name": "Maria",
            "timezone": "America/Chicago",
            "username": "maria",
            "password1": "pa55-heat-plan!",
            "password2": "pa55-heat-plan!",
        },
    )
    assert response.status_code == 302 and response["Location"] == "/sites/new/"
    crew = Crew.objects.get(name="Sunrise Roofing")
    assert crew.leads.get().username == "maria"
    assert crew.timezone == "America/Chicago"


def test_signup_can_be_disabled(client, settings):
    settings.SHADEBREAK_ALLOW_SIGNUP = False
    assert client.get("/signup/").status_code == 404


def test_user_without_crew_goes_to_onboarding(client, django_user_model):
    user = django_user_model.objects.create_user("solo", password="x-long-password-1")
    client.force_login(user)
    assert client.get("/")["Location"] == "/welcome/"
    response = client.post(
        "/welcome/",
        {
            "name": "Solo Crew",
            "timezone": "America/Denver",
            "language": "es",
            "emergency_number": "911",
            "sms_enabled": "on",
        },
    )
    assert response.status_code == 302
    assert Crew.objects.get(name="Solo Crew").leads.filter(pk=user.pk).exists()
    assert client.get("/welcome/")["Location"] == "/"


def test_empty_dashboard_prompts_for_a_site(logged_in):
    response = logged_in.get("/")
    assert response.status_code == 200
    assert b"Add your first job site" in response.content


def test_dashboard_shows_the_morning_screen(logged_in, site, hot_day, make_worker):
    make_worker("Vera")
    make_worker("Rico", experience=Experience.NEW, start_date=PHOENIX_DAY)
    response = logged_in.get("/")
    html = response.content.decode()
    assert response.status_code == 200
    assert "Desert Park" in html
    assert 'class="strip"' in html
    assert "First week" in html and "Day 1 of 5" in html
    assert "In the heat until" in html
    assert "Sample forecast" in html
    assert WorkDay.objects.filter(site=site, date=PHOENIX_DAY).exists()


def test_dashboard_other_days_and_bad_dates(logged_in, site, hot_day):
    assert logged_in.get("/?date=2026-07-16").status_code == 200
    assert logged_in.get("/?date=not-a-date").status_code == 200
    site.weekdays = "6"
    site.save()
    monday = PHOENIX_DAY + timedelta(days=(7 - PHOENIX_DAY.weekday()) % 7 or 7)
    html = logged_in.get(f"/?date={monday.isoformat()}").content.decode()
    assert "Not working this day" in html


def test_dashboard_in_spanish(logged_in, site, hot_day, make_worker):
    make_worker("Rico", experience=Experience.NEW, start_date=PHOENIX_DAY)
    logged_in.post("/i18n/setlang/", {"language": "es", "next": "/"})
    html = logged_in.get("/").content.decode()
    assert 'lang="es"' in html
    assert "Primera semana" in html
    assert "Descansos" in html


@responses.activate
def test_refresh_button_returns_the_card(logged_in, site, make_worker):
    make_worker("Vera")
    site.nws_grid_id, site.nws_grid_x, site.nws_grid_y = "PSR", 159, 57
    site.save()
    responses.get("https://api.weather.gov/gridpoints/PSR/159,57", json=load_fixture("nws_gridpoints.json"))
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    response = logged_in.post(f"/days/{workday.pk}/refresh/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    html = response.content.decode()
    assert html.strip().startswith("<article")
    assert "NWS forecast updated" in html
    assert site.forecasts.count() == 24


@responses.activate
def test_refresh_failure_is_shown(logged_in, site):
    site.nws_grid_id, site.nws_grid_x, site.nws_grid_y = "PSR", 159, 57
    site.save()
    responses.get("https://api.weather.gov/gridpoints/PSR/159,57", status=503, json={"detail": "down"})
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    response = logged_in.post(f"/days/{workday.pk}/refresh/", follow=True)
    assert b"Could not reach the National Weather Service" in response.content


def test_workday_page_and_roster_changes(logged_in, site, hot_day, make_worker):
    vera = make_worker("Vera")
    rico = make_worker("Rico", experience=Experience.NEW, start_date=PHOENIX_DAY, site=None)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    response = logged_in.get(f"/days/{workday.pk}/")
    assert response.status_code == 200
    assert b"Hour by hour" in response.content

    logged_in.post(f"/days/{workday.pk}/add-worker/", {"worker": rico.pk})
    rico_assignment = Assignment.objects.get(workday=workday, worker=rico)
    assert rico_assignment.acclimatization_day == 1

    vera_assignment = Assignment.objects.get(workday=workday, worker=vera)
    prefix = f"a{vera_assignment.pk}"
    logged_in.post(
        f"/assignments/{vera_assignment.pk}/",
        {f"{prefix}-status": "absent", f"{prefix}-buddy": "", f"{prefix}-exposure_override": ""},
    )
    vera_assignment.refresh_from_db()
    assert vera_assignment.status == "absent"

    prefix = f"a{rico_assignment.pk}"
    logged_in.post(
        f"/assignments/{rico_assignment.pk}/",
        {f"{prefix}-status": "scheduled", f"{prefix}-buddy": "", f"{prefix}-exposure_override": "100"},
    )
    rico_assignment.refresh_from_db()
    assert rico_assignment.exposure_percent == 100

    response = logged_in.post(
        f"/assignments/{rico_assignment.pk}/",
        {f"{prefix}-status": "bogus", f"{prefix}-buddy": "", f"{prefix}-exposure_override": ""},
        follow=True,
    )
    assert b"Could not save" in response.content

    logged_in.post(f"/assignments/{rico_assignment.pk}/", {"remove": "1"})
    assert not Assignment.objects.filter(pk=rico_assignment.pk).exists()


def test_checkin_buttons(logged_in, site, hot_day, make_worker, frozen_clock):
    make_worker("Vera")
    make_worker("Rico", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday)
    checkin = CheckIn.objects.order_by("due_at").first()
    frozen_clock.move_to(checkin.due_at + timedelta(minutes=1))
    html = logged_in.get("/").content.decode()
    assert f'id="checkin-{checkin.pk}"' in html and 'value="ok"' in html
    response = logged_in.post(f"/checkins/{checkin.pk}/", {"status": "ok"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and b"chip--ok" in response.content
    checkin.refresh_from_db()
    assert checkin.status == "ok"
    response = logged_in.post(f"/checkins/{checkin.pk}/", {"status": "help"})
    assert response.status_code == 302


def test_worker_crud_keeps_buddies_mutual(logged_in, crew, site):
    assert logged_in.get("/crew/new/").status_code == 200
    response = logged_in.post(
        "/crew/new/",
        {
            "name": "Luis Ortega",
            "phone": "602-555-0111",
            "language": "es",
            "experience": "acclimatized",
            "start_date": "2025-04-01",
            "site": site.pk,
            "sms_opt_in": "on",
        },
    )
    assert response.status_code == 302
    luis = Worker.objects.get(name="Luis Ortega")
    assert luis.phone == "+16025550111"
    assert luis.active
    logged_in.post(
        "/crew/new/",
        {
            "name": "Ana Torres",
            "phone": "",
            "language": "es",
            "experience": "new",
            "start_date": "2026-07-15",
            "buddy": luis.pk,
        },
    )
    ana = Worker.objects.get(name="Ana Torres")
    luis.refresh_from_db()
    assert ana.buddy == luis and luis.buddy == ana

    response = logged_in.post(
        "/crew/new/",
        {
            "name": "Dup",
            "phone": "(602) 555-0111",
            "language": "en",
            "experience": "new",
            "start_date": "2026-07-15",
        },
    )
    assert b"already has this number" in response.content
    response = logged_in.post(
        "/crew/new/",
        {
            "name": "No phone",
            "language": "en",
            "experience": "new",
            "start_date": "2026-07-15",
            "sms_opt_in": "on",
        },
    )
    assert b"Add a mobile number" in response.content
    response = logged_in.post(
        "/crew/new/",
        {
            "name": "Bad phone",
            "phone": "12",
            "language": "en",
            "experience": "new",
            "start_date": "2026-07-15",
        },
    )
    assert b"10-digit" in response.content

    assert logged_in.get(f"/crew/{ana.pk}/").status_code == 200
    logged_in.post(
        f"/crew/{ana.pk}/",
        {
            "name": "Ana Torres",
            "language": "es",
            "experience": "new",
            "start_date": "2026-07-15",
            "active": "on",
        },
    )
    luis.refresh_from_db()
    assert luis.buddy is None

    logged_in.post(f"/crew/{luis.pk}/deactivate/")
    luis.refresh_from_db()
    assert not luis.active
    page = logged_in.get("/crew/").content.decode()
    assert "Inactive" in page and "(602) 555-0111" in page


def test_site_crud(logged_in, crew, settings, monkeypatch):
    from crews.services import geocode as geocode_module

    assert logged_in.get("/sites/new/").status_code == 200
    data = {
        "name": "Mesa Ballfields",
        "address": "",
        "latitude": "33.4152",
        "longitude": "-111.8315",
        "exposure": "partial",
        "workload": "moderate",
        "clothing": "standard",
        "shift_start": "06:00",
        "shift_end": "14:30",
        "weekdays": ["0", "1", "2", "3", "4"],
    }
    monkeypatch.setattr("crews.views.refresh_site_forecast", lambda site, client=None: 0)
    response = logged_in.post("/sites/new/", data)
    assert response.status_code == 302
    site = JobSite.objects.get(name="Mesa Ballfields")
    assert site.weekdays == "01234" and site.latitude == Decimal("33.4152")
    assert site.active

    response = logged_in.post("/sites/new/", {**data, "name": "Nowhere", "latitude": "", "longitude": ""})
    assert b"Enter an address or use your location" in response.content
    response = logged_in.post("/sites/new/", {**data, "name": "Half", "longitude": ""})
    assert b"Enter both latitude and longitude" in response.content

    settings.SHADEBREAK_GEOCODER = "census"
    monkeypatch.setattr(geocode_module, "geocode", lambda address: (Decimal("33.4"), Decimal("-112.0")))
    response = logged_in.post(
        "/sites/new/", {**data, "name": "By address", "address": "1 Main St", "latitude": "", "longitude": ""}
    )
    assert response.status_code == 302
    assert JobSite.objects.get(name="By address").latitude == Decimal("33.4")
    monkeypatch.setattr(geocode_module, "geocode", lambda address: None)
    response = logged_in.post(
        "/sites/new/", {**data, "name": "Lost", "address": "Nowhere", "latitude": "", "longitude": ""}
    )
    assert b"could not find that address" in response.content

    edit = {**data, "exposure": "shade", "shift_end": "13:00", "active": "on"}
    assert logged_in.post(f"/sites/{site.pk}/", edit).status_code == 302
    site.refresh_from_db()
    assert site.exposure == "shade"
    assert b"Mesa Ballfields" in logged_in.get("/sites/").content
    logged_in.post(f"/sites/{site.pk}/archive/")
    site.refresh_from_db()
    assert not site.active

    response = logged_in.post("/sites/new/", {**data, "name": "Same", "shift_end": "06:00"})
    assert b"must end at a different time" in response.content


def test_schedule_day_off(logged_in, site):
    site.weekdays = "0"
    site.save()
    response = logged_in.post(f"/sites/{site.pk}/schedule/", {"date": "2026-07-18"})
    workday = WorkDay.objects.get(site=site, date="2026-07-18")
    assert response["Location"] == f"/days/{workday.pk}/"


def test_settings_and_switch_crew(logged_in, crew, user):
    assert logged_in.get("/settings/").status_code == 200
    response = logged_in.post(
        "/settings/",
        {
            "name": "Renamed",
            "timezone": "America/Phoenix",
            "language": "es",
            "emergency_number": "911",
            "lead_phone": "6025550100",
        },
    )
    assert response.status_code == 302
    crew.refresh_from_db()
    assert crew.name == "Renamed" and crew.lead_phone == "+16025550100" and not crew.sms_enabled
    other = Crew.objects.create(name="Second crew")
    other.leads.add(user)
    assert b"Switch crew" in logged_in.get("/settings/").content
    logged_in.post("/switch-crew/", {"crew": other.pk})
    assert b"Second crew" in logged_in.get("/").content


def test_other_crews_data_is_hidden(client, django_user_model, site, hot_day, make_worker):
    worker = make_worker("Vera")
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    intruder = django_user_model.objects.create_user("intruder", password="x-long-password-1")
    Crew.objects.create(name="Other").leads.add(intruder)
    client.force_login(intruder)
    assert client.get(f"/days/{workday.pk}/").status_code == 404
    assert client.get(f"/crew/{worker.pk}/").status_code == 404
    assert client.get(f"/sites/{site.pk}/").status_code == 404
    assert client.post(f"/crew/{worker.pk}/deactivate/").status_code == 404


def test_message_log(logged_in, site, hot_day, make_worker):
    make_worker("Vera")
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday)
    page = logged_in.get("/messages/")
    assert page.status_code == 200 and b"Morning briefing" in page.content
    assert logged_in.get("/messages/?kind=briefing&status=queued").status_code == 200
    assert logged_in.get("/messages/?page=2", HTTP_HX_REQUEST="true").status_code == 200


def test_health_version_and_manifest(client):
    health = client.get("/healthz")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    version = client.get("/version").json()
    assert version["version"].count(".") == 2
    assert client.get("/manifest.webmanifest")["Content-Type"] == "application/manifest+json"


def test_404_page(logged_in):
    assert logged_in.get("/days/999999/").status_code == 404


def test_healthz_reports_database_errors(client, monkeypatch):
    from django.db import connection

    def broken_cursor():
        raise RuntimeError("database is down")

    monkeypatch.setattr(connection, "cursor", broken_cursor)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "detail": "database is down"}


def test_pages_use_the_crew_time_zone(logged_in, crew, site, hot_day, make_worker):
    from django.utils import timezone

    make_worker("Vera")
    crew.timezone = "America/New_York"
    crew.save()
    response = logged_in.get("/")
    assert response.context["crew"] == crew
    # Site times stay in the site's own zone (Phoenix), whatever the crew zone.
    assert "6:00 AM–2:30 PM" in response.content.decode()
    assert timezone.get_current_timezone_name() == "UTC"  # deactivated after the request


def test_footer_shows_version_and_build(logged_in, settings):
    from shadebreak import __version__

    html = logged_in.get("/").content.decode()
    assert f"v{__version__} · build dev" in html


def test_switching_to_someone_elses_crew_is_refused(logged_in, user):
    other = Crew.objects.create(name="Not mine")
    assert logged_in.post("/switch-crew/", {"crew": other.pk}).status_code == 404
    assert logged_in.get("/").context["crew"].name == "Test Crew"


def test_language_switch_persists_on_other_pages(logged_in):
    logged_in.post("/i18n/setlang/", {"language": "es", "next": "/crew/"})
    html = logged_in.get("/crew/").content.decode()
    assert "Cuadrilla" in html and "Agregar trabajador" in html
    logged_in.post("/i18n/setlang/", {"language": "en", "next": "/crew/"})
    assert "Add worker" in logged_in.get("/crew/").content.decode()
