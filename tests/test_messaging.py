from datetime import datetime, time, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured

from crews.models import Assignment, CheckIn, Experience, Workload
from crews.services.planning import ensure_workday, plan_workday
from messaging import compose
from messaging.backends import SMSError, get_backend, locmem
from messaging.delivery import deliver, send_due, send_now
from messaging.models import Message
from messaging.text import fold_to_gsm, is_gsm, segments

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


def at(site, hh, mm=0):
    return datetime.combine(PHOENIX_DAY, time(hh, mm), tzinfo=site.tz)


@pytest.fixture
def planned(site, hot_day, make_worker):
    site.workload = Workload.HEAVY
    site.save()
    vet = make_worker("Luis Ortega", language="es")
    rookie = make_worker("Ana Torres", language="es", experience=Experience.NEW, start_date=PHOENIX_DAY)
    other = make_worker("Jake Miller")
    quiet = make_worker("No Texts", sms_opt_in=False)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=at(site, 4))
    return {"workday": workday, "vet": vet, "rookie": rookie, "other": other, "quiet": quiet}


def test_gsm_folding_keeps_spanish_readable():
    text = "Tome agua ahora, aunque no tenga sed. Día 2 · 88°F – ¿Está bien? Mañana"
    folded = fold_to_gsm(text)
    assert folded == "Tome agua ahora, aunque no tenga sed. Dia 2 - 88F - ¿Está bien? Mañana".replace(
        "Está", "Esta"
    )
    assert is_gsm(folded)
    assert segments("a" * 160) == 1
    assert segments("a" * 161) == 2
    assert segments("á" * 70) == 1 and segments("á" * 71) == 2
    assert segments("{" * 80) == 1 and segments("{" * 81) == 2


def test_schedule_creates_the_days_texts(planned):
    workday = planned["workday"]
    kinds = set(Message.objects.filter(workday=workday).values_list("kind", flat=True))
    assert {"briefing", "break", "checkin"} <= kinds
    assert not Message.objects.filter(worker=planned["quiet"]).exists()
    briefings = Message.objects.filter(workday=workday, kind=Message.Kind.BRIEFING)
    # One per texting worker plus the crew lead, 30 minutes before the shift.
    assert briefings.count() == 4
    assert {m.send_at for m in briefings} == {workday.shift_start - timedelta(minutes=30)}
    lead = briefings.get(to_number=planned["workday"].site.crew.lead_phone)
    assert "Ana Torres (day 1, until" in lead.body
    rookie_breaks = Message.objects.filter(worker=planned["rookie"], kind=Message.Kind.BREAK)
    rookie_end = Assignment.objects.get(worker=planned["rookie"]).planned_end
    assert all(m.send_at < rookie_end for m in rookie_breaks)


def test_rookie_briefing_explains_reduced_hours(planned):
    a = Assignment.objects.select_related("worker", "buddy", "workday__site__crew").get(
        worker=planned["other"]
    )
    text = compose.briefing(a, list(a.workday.breaks.all()))
    assert text.startswith("Shadebreak - Desert Park")
    assert "Drink 1 cup of water every 15-20 min" in text
    assert "Emergency: call 911." in text
    rookie = Assignment.objects.select_related("worker", "buddy", "workday__site__crew").get(
        worker=planned["rookie"]
    )
    rookie.worker.language = "en"
    text = compose.briefing(rookie, list(rookie.workday.breaks.all()))
    assert "day 1 of 5 of your heat ramp" in text
    assert "Your buddy:" in text


def test_replanning_replaces_unsent_texts_only(planned):
    workday = planned["workday"]
    first = Message.objects.filter(workday=workday).order_by("send_at").first()
    deliver(first, now=first.send_at)
    total = Message.objects.filter(workday=workday).count()
    plan_workday(workday, now=first.send_at + timedelta(minutes=1))
    assert Message.objects.filter(pk=first.pk, status=Message.Status.SENT).exists()
    # The already-briefed numbers are not briefed twice.
    assert Message.objects.filter(workday=workday, kind="briefing", to_number=first.to_number).count() == 1
    assert Message.objects.filter(workday=workday).count() <= total


def test_send_due_sends_and_expires(planned, frozen_clock):
    workday = planned["workday"]
    frozen_clock.move_to(workday.shift_start - timedelta(minutes=29))
    sent = send_due()
    assert sent >= 4
    assert len(locmem.outbox) == sent
    # Accents are folded before sending.
    assert all(is_gsm(m["body"]) for m in locmem.outbox)
    # A reminder that is hours late is skipped, not sent.
    stale = (
        Message.objects.filter(status=Message.Status.QUEUED, kind=Message.Kind.BREAK)
        .order_by("send_at")
        .first()
    )
    frozen_clock.move_to(stale.send_at + timedelta(hours=2))
    deliver(stale)
    stale.refresh_from_db()
    assert stale.status == Message.Status.EXPIRED


def test_deliver_respects_opt_out_and_failures(planned, crew):
    message = Message.objects.filter(worker=planned["vet"], status="queued").first()
    planned["vet"].sms_opt_in = False
    planned["vet"].save()
    deliver(message, now=message.send_at)
    assert Message.objects.get(pk=message.pk).status == Message.Status.EXPIRED

    locmem.fail_numbers.add(crew.lead_phone)
    failed = send_now(crew=crew, kind=Message.Kind.ESCALATION, to_number=crew.lead_phone, body="hi")
    assert failed.status == Message.Status.FAILED and "Simulated" in failed.error

    no_number = send_now(crew=crew, kind=Message.Kind.ESCALATION, to_number="", body="hi")
    assert no_number.status == Message.Status.FAILED

    crew.sms_enabled = False
    crew.save()
    off = send_now(crew=crew, kind=Message.Kind.ESCALATION, to_number="+16025550199", body="hi")
    assert off.status == Message.Status.EXPIRED


def test_deliver_does_not_double_send(planned):
    message = Message.objects.filter(status="queued").first()
    deliver(message, now=message.send_at)
    deliver(message, now=message.send_at)
    assert len(locmem.outbox) == 1


def test_sms_disabled_crew_gets_no_schedule(site, hot_day, make_worker, crew):
    crew.sms_enabled = False
    crew.save()
    make_worker("A")
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=at(site, 4))
    assert not Message.objects.exists()


def test_checkin_prompts_go_to_lead_when_no_buddy(site, hot_day, make_worker, crew):
    make_worker("Solo", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=at(site, 4))
    prompts = Message.objects.filter(kind=Message.Kind.CHECKIN)
    assert prompts.exists()
    assert set(prompts.values_list("to_number", flat=True)) == {crew.lead_phone}
    assert "has no buddy on site" in prompts.first().body


def test_water_reminders_skip_hours_with_breaks(planned):
    for message in Message.objects.filter(kind=Message.Kind.WATER):
        breaks = Message.objects.filter(kind=Message.Kind.BREAK, to_number=message.to_number)
        assert all(abs(b.send_at - message.send_at) > timedelta(minutes=20) for b in breaks)


def test_backends(settings):
    assert get_backend().__class__.__name__ == "LocmemBackend"
    with pytest.raises(ImproperlyConfigured):
        get_backend("messaging.backends.twilio.TwilioBackend")
    with pytest.raises(ImproperlyConfigured):
        get_backend("messaging.backends.gateway.GatewayBackend")
    console = get_backend("messaging.backends.console.ConsoleBackend")
    assert console.send("+16025550100", "hello").provider_id.startswith("console-")
    with pytest.raises(SMSError):
        locmem.fail_numbers.add("+1")
        get_backend().send("+1", "x")


def test_checkin_model_helpers(planned):
    checkin = CheckIn.objects.first()
    assert checkin.is_open
    assert str(checkin).startswith("Check on")
