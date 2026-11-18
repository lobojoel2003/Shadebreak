"""Regression tests for issues found in code review before 1.0.0."""

from datetime import datetime, time, timedelta

import pytest
import responses

from crews.models import Assignment, CheckIn, Crew, Experience, JobSite, WorkDay, Worker
from crews.services.buddies import pair_buddies
from crews.services.planning import ensure_workday, heat_days, plan_workday
from crews.services.sample import load_sample_forecast
from messaging.backends import SMSError, locmem
from messaging.delivery import deliver, send_now
from messaging.escalation import escalate_missed
from messaging.inbound import classify, handle_inbound
from messaging.models import Message

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "body",
    [
        "Yes he needs help",
        "Si, necesita ayuda",
        "ok he is not ok, help",
        "Stop, he collapsed, help",
        "Alto, se siente mal",
        "no esta bien",
        "1 but she fainted",
    ],
)
def test_any_sign_of_trouble_means_help(body):
    assert classify(body) == "help"


def test_stop_is_still_honored():
    assert classify("STOP") == "stop"
    assert classify("stop texting me") == "stop"
    assert classify("ok") == "ok"
    assert classify("no") == "unknown"  # ambiguous: ask again, and escalate if nobody answers


def at(site, hh, mm=0, day=PHOENIX_DAY):
    return datetime.combine(day, time(hh, mm), tzinfo=site.tz)


def test_worker_is_not_scheduled_before_their_start_date(site, make_worker, hot_day):
    later = make_worker(
        "Starts Friday", experience=Experience.NEW, start_date=PHOENIX_DAY + timedelta(days=2)
    )
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    assert not workday.assignments.filter(worker=later).exists()
    # Even if added earlier by hand, days before the start date never count as heat days.
    Assignment.objects.create(workday=workday, worker=later)
    plan_workday(workday, now=at(site, 4), notify=False)
    assert not workday.assignments.filter(worker=later).exists()
    assert heat_days(later, PHOENIX_DAY + timedelta(days=2)) == []


def test_new_worker_added_today_joins_todays_plan(logged_in, site, hot_day, make_worker):
    make_worker("Vera")
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    logged_in.post(
        "/crew/new/",
        {
            "name": "Nina New",
            "language": "en",
            "experience": "new",
            "start_date": PHOENIX_DAY.isoformat(),
            "site": site.pk,
        },
    )
    nina = Worker.objects.get(name="Nina New")
    assignment = Assignment.objects.get(workday=workday, worker=nina)
    assert assignment.acclimatization_day == 1 and assignment.exposure_percent == 20
    logged_in.post(f"/crew/{nina.pk}/deactivate/")
    assert not Assignment.objects.filter(workday=workday, worker=nina).exists()


def test_adding_someone_to_a_day_before_their_start_date_moves_it(logged_in, site, make_worker):
    later = make_worker("Later", start_date=PHOENIX_DAY + timedelta(days=5), site=None)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    logged_in.post(f"/days/{workday.pk}/add-worker/", {"worker": later.pk})
    later.refresh_from_db()
    assert later.start_date == PHOENIX_DAY
    assert workday.assignments.filter(worker=later).exists()


def test_new_workers_are_watched_by_experienced_ones_even_when_outnumbered(site, make_worker):
    workday = WorkDay.objects.create(
        site=site, date=PHOENIX_DAY, start_time=site.shift_start, end_time=site.shift_end
    )
    v1, v2 = make_worker("V1"), make_worker("V2")
    v1.buddy, v2.buddy = v2, v1
    v1.save()
    v2.save()
    rows = [Assignment.objects.create(workday=workday, worker=w) for w in (v1, v2)]
    rows += [
        Assignment.objects.create(workday=workday, worker=make_worker(n), first_week=True)
        for n in ("N1", "N2")
    ]
    pair_buddies(rows)
    assert rows[0].buddy_id == v2.pk and rows[1].buddy_id == v1.pk
    watchers = {rows[2].buddy_id, rows[3].buddy_id}
    assert watchers == {v1.pk, v2.pk}  # one experienced worker each, not each other


def test_one_text_per_buddy_when_watching_two_people(site, hot_day, make_worker, frozen_clock):
    vet = make_worker("Vera")
    workday = WorkDay.objects.create(
        site=site, date=PHOENIX_DAY, start_time=site.shift_start, end_time=site.shift_end
    )
    for name in ("N1", "N2"):
        rookie = make_worker(name, experience=Experience.NEW, start_date=PHOENIX_DAY)
        Assignment.objects.create(workday=workday, worker=rookie, buddy=vet, buddy_manual=True)
    Assignment.objects.create(workday=workday, worker=vet)
    plan_workday(workday, now=at(site, 4))
    prompts = Message.objects.filter(kind=Message.Kind.CHECKIN, to_number=vet.phone).order_by("send_at")
    first = prompts.first()
    assert first.checkins.count() == 2
    assert "N1 and N2" in first.body and "Reply 1 if all are OK" in first.body
    assert prompts.filter(send_at=first.send_at).count() == 1
    deliver(first, now=first.send_at)
    frozen_clock.move_to(first.send_at + timedelta(minutes=2))
    result = handle_inbound(vet.phone, "1")
    assert result.action == "checkin_ok"
    assert set(CheckIn.objects.filter(prompts=first).values_list("status", flat=True)) == {"ok"}


def test_reply_alerts_the_crew_the_checkin_belongs_to(site, hot_day, make_worker, crew, frozen_clock, user):
    other_crew = Crew.objects.create(name="Other crew", lead_phone="+16025550999", timezone="America/Phoenix")
    buddy = make_worker("Shared Phone")
    Worker.objects.create(crew=other_crew, name="Same person elsewhere", phone=buddy.phone, sms_opt_in=True)
    rookie = make_worker("Rookie", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    Assignment.objects.filter(workday=workday, worker=rookie).update(buddy=buddy, buddy_manual=True)
    plan_workday(workday, now=at(site, 4))
    prompt = (
        Message.objects.filter(kind=Message.Kind.CHECKIN, to_number=buddy.phone).order_by("send_at").first()
    )
    deliver(prompt, now=prompt.send_at)
    frozen_clock.move_to(prompt.send_at + timedelta(minutes=2))
    result = handle_inbound(buddy.phone, "2")
    assert result.crew_id == crew.pk
    alert = Message.objects.get(kind=Message.Kind.ESCALATION)
    assert alert.to_number == crew.lead_phone and alert.crew == crew
    inbound = Message.objects.get(direction=Message.Direction.INBOUND)
    assert inbound.crew == crew


def test_crew_lead_stop_is_honored(crew, frozen_clock):
    result = handle_inbound(crew.lead_phone, "STOP")
    assert result.action == "opted_out"
    crew.refresh_from_db()
    assert crew.lead_opted_out
    alert = send_now(crew=crew, kind=Message.Kind.ESCALATION, to_number=crew.lead_phone, body="x")
    assert alert.status == Message.Status.EXPIRED
    handle_inbound(crew.lead_phone, "START")
    crew.refresh_from_db()
    assert not crew.lead_opted_out


def test_changing_the_lead_phone_clears_a_stop(logged_in, crew):
    crew.lead_opted_out = True
    crew.save()
    logged_in.post(
        "/settings/",
        {
            "name": crew.name,
            "timezone": crew.timezone,
            "language": "en",
            "emergency_number": "911",
            "lead_phone": "6025550199",
            "sms_enabled": "on",
        },
    )
    crew.refresh_from_db()
    assert crew.lead_phone == "+16025550199" and not crew.lead_opted_out


def test_unexpected_backend_errors_do_not_leave_texts_stuck(crew, monkeypatch):
    def explode(self, to, body):
        raise RuntimeError("provider returned HTML")

    monkeypatch.setattr("messaging.backends.locmem.LocmemBackend.send", explode)
    message = send_now(crew=crew, kind=Message.Kind.ESCALATION, to_number="+16025550111", body="x")
    assert message.status == Message.Status.FAILED and "provider returned HTML" in message.error


@responses.activate
def test_twilio_success_without_json_body(settings):
    from messaging.backends import get_backend

    settings.TWILIO_ACCOUNT_SID = "AC123"
    settings.TWILIO_AUTH_TOKEN = "secret"
    settings.SHADEBREAK_SMS_FROM = "+16025550000"
    responses.post(
        "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json", body="<html>ok</html>", status=201
    )
    assert get_backend("messaging.backends.twilio.TwilioBackend").send("+1602", "x").provider_id == ""


def test_refresh_redirect_stays_on_site(logged_in, site, monkeypatch):
    monkeypatch.setattr("crews.views.refresh_site_forecast", lambda site, client=None: 0)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    response = logged_in.post(f"/days/{workday.pk}/refresh/", {"next": "https://evil.example/phish"})
    assert response["Location"] == "/"
    response = logged_in.post(f"/days/{workday.pk}/refresh/", {"next": f"/days/{workday.pk}/"})
    assert response["Location"] == f"/days/{workday.pk}/"


def test_clothing_change_rerates_stored_hours(logged_in, site, hot_day):
    before = site.forecasts.order_by("start").first().risk
    data = {
        "name": site.name,
        "address": site.address,
        "latitude": str(site.latitude),
        "longitude": str(site.longitude),
        "exposure": site.exposure,
        "workload": site.workload,
        "clothing": "vapor_barrier",
        "shift_start": "06:00",
        "shift_end": "14:30",
        "weekdays": list(site.weekdays),
        "active": "on",
    }
    assert logged_in.post(f"/sites/{site.pk}/", data).status_code == 302
    site.refresh_from_db()
    assert site.forecasts.order_by("start").first().risk > before


def test_missed_escalation_then_late_reply_still_updates_lead(site, hot_day, make_worker, crew, frozen_clock):
    buddy = make_worker("Luis")
    make_worker("Ana", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=at(site, 4))
    prompt = (
        Message.objects.filter(kind=Message.Kind.CHECKIN, to_number=buddy.phone).order_by("send_at").first()
    )
    deliver(prompt, now=prompt.send_at)
    frozen_clock.move_to(prompt.send_at + timedelta(minutes=20))
    assert escalate_missed() == 1
    handle_inbound(buddy.phone, "1")
    bodies = list(Message.objects.filter(kind=Message.Kind.ESCALATION).values_list("body", flat=True))
    assert any("no reply" in b for b in bodies) and any("is OK" in b for b in bodies)
    assert locmem.outbox


def test_site_in_another_crew_cannot_be_scheduled(client, django_user_model, site):
    intruder = django_user_model.objects.create_user("intruder2", password="x-long-password-1")
    Crew.objects.create(name="Other").leads.add(intruder)
    client.force_login(intruder)
    assert client.post(f"/sites/{site.pk}/schedule/", {"date": "2026-07-18"}).status_code == 404
    assert not JobSite.objects.filter(pk=site.pk, workdays__date="2026-07-18").exists()


def test_sample_forecast_for_a_new_site(crew):
    from decimal import Decimal

    site = JobSite.objects.create(
        crew=crew, name="Fresh", latitude=Decimal("33.4"), longitude=Decimal("-112.0")
    )
    assert load_sample_forecast(site, PHOENIX_DAY) == 48
    assert SMSError
