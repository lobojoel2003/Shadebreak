from datetime import datetime, time, timedelta

import pytest

from crews.models import CheckIn, Experience, Worker
from crews.services.planning import ensure_workday, plan_workday
from messaging.backends import locmem
from messaging.delivery import deliver
from messaging.escalation import escalate_missed
from messaging.inbound import classify, handle_inbound
from messaging.models import Message

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("body", "intent"),
    [
        ("1", "ok"),
        (" OK! ", "ok"),
        ("Sí", "ok"),
        ("todo bien", "ok"),
        ("2", "help"),
        ("AYUDA", "help"),
        ("help me", "help"),
        ("STOP", "stop"),
        ("Alto", "stop"),
        ("start", "start"),
        ("?", "info"),
        ("what time is lunch", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify(body, intent):
    assert classify(body) == intent


@pytest.fixture
def prompted(site, hot_day, make_worker):
    """A planned day where the first check-in prompt has been sent."""
    buddy = make_worker("Luis", language="es")
    rookie = make_worker("Ana", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=datetime.combine(PHOENIX_DAY, time(4), tzinfo=site.tz))
    prompt = (
        Message.objects.filter(kind=Message.Kind.CHECKIN, to_number=buddy.phone).order_by("send_at").first()
    )
    deliver(prompt, now=prompt.send_at)
    return {"buddy": buddy, "rookie": rookie, "prompt": prompt, "checkin": prompt.checkin}


def test_buddy_says_ok(prompted, frozen_clock):
    frozen_clock.move_to(prompted["prompt"].send_at + timedelta(minutes=2))
    result = handle_inbound(prompted["buddy"].phone, "1")
    checkin = CheckIn.objects.get(pk=prompted["checkin"].pk)
    assert checkin.status == CheckIn.Status.OK
    assert checkin.response == "1"
    assert result.action == "checkin_ok"
    assert result.language == "es"
    assert "Ana" in result.reply
    assert Message.objects.filter(direction="in", worker=prompted["buddy"]).exists()


def test_buddy_says_help_alerts_lead(prompted, frozen_clock, crew):
    frozen_clock.move_to(prompted["prompt"].send_at + timedelta(minutes=2))
    result = handle_inbound("(602) 555-" + prompted["buddy"].phone[-4:], "2")
    assert CheckIn.objects.get(pk=prompted["checkin"].pk).status == CheckIn.Status.HELP
    assert result.action == "checkin_help"
    alert = Message.objects.get(kind=Message.Kind.ESCALATION)
    assert alert.to_number == crew.lead_phone and alert.status == Message.Status.SENT
    assert "URGENT" in alert.body and "Luis says Ana needs help" in alert.body
    assert locmem.outbox[-1]["to"] == crew.lead_phone


def test_missed_checkin_escalates_then_late_ok_updates_lead(prompted, frozen_clock, crew):
    checkin = prompted["checkin"]
    frozen_clock.move_to(checkin.due_at + timedelta(minutes=16))
    assert escalate_missed() == 1
    assert escalate_missed() == 0  # only once
    checkin.refresh_from_db()
    assert checkin.status == CheckIn.Status.MISSED and checkin.escalated_at
    alert = Message.objects.get(kind=Message.Kind.ESCALATION)
    assert "no reply" in alert.body
    handle_inbound(prompted["buddy"].phone, "ok")
    checkin.refresh_from_db()
    assert checkin.status == CheckIn.Status.OK
    assert Message.objects.filter(kind=Message.Kind.ESCALATION).count() == 2
    assert "is OK" in Message.objects.filter(kind=Message.Kind.ESCALATION).order_by("-pk").first().body


def test_worker_texts_help_without_a_checkin(prompted, crew, frozen_clock):
    frozen_clock.move_to(datetime.combine(PHOENIX_DAY, time(9), tzinfo=crew.tz))
    result = handle_inbound(prompted["rookie"].phone, "help")
    assert result.action == "self_help"
    alert = Message.objects.get(kind=Message.Kind.ESCALATION)
    assert "Ana texted for help at Desert Park" in alert.body


def test_stop_and_start(prompted):
    phone = prompted["rookie"].phone
    assert handle_inbound(phone, "STOP").action == "opted_out"
    assert not Worker.objects.get(phone=phone).sms_opt_in
    assert handle_inbound(phone, "START").action == "opted_in"
    assert Worker.objects.get(phone=phone).sms_opt_in


def test_unknown_text_gets_help_and_unknown_sender_gets_nothing(prompted):
    result = handle_inbound(prompted["rookie"].phone, "when is lunch?")
    assert result.action == "info" and "Reply 1 = OK" in result.reply
    stranger = handle_inbound("+19995550000", "1")
    assert stranger.reply is None and stranger.action == "unknown_sender"
    assert handle_inbound("not a number", "1").action == "unknown_sender"


def test_lead_can_answer_prompts(site, hot_day, make_worker, crew, frozen_clock):
    make_worker("Solo", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday, now=datetime.combine(PHOENIX_DAY, time(4), tzinfo=site.tz))
    prompt = Message.objects.filter(kind=Message.Kind.CHECKIN).order_by("send_at").first()
    deliver(prompt, now=prompt.send_at)
    frozen_clock.move_to(prompt.send_at + timedelta(minutes=1))
    result = handle_inbound(crew.lead_phone, "1")
    assert result.action == "checkin_ok"
    assert result.crew_id == crew.pk
