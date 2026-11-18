"""Handle texts that workers and crew leads send back."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from crews.models import CheckIn, Crew, Worker
from crews.phones import normalize_phone

from . import compose
from .delivery import send_now
from .models import Message

OK_WORDS = {
    "1",
    "ok",
    "okay",
    "k",
    "yes",
    "y",
    "good",
    "fine",
    "si",
    "bien",
    "bueno",
    "todo bien",
    "esta bien",
}
HELP_WORDS = {
    "2",
    "help",
    "ayuda",
    "sos",
    "mal",
    "sick",
    "enfermo",
    "enferma",
    "emergency",
    "emergencia",
    "911",
}
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "alto", "parar", "baja"}
START_WORDS = {"start", "unstop", "inicio", "alta", "comenzar"}
INFO_WORDS = {"info", "?", "menu"}
PROMPT_WINDOW = timedelta(hours=3)


@dataclass
class InboundResult:
    reply: str | None
    language: str = "en"
    action: str = "none"
    checkins: list[CheckIn] = field(default_factory=list)
    crew_id: int | None = None


def classify(body: str) -> str:
    text = unicodedata.normalize("NFKD", body or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9?\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "unknown"
    first = text.split(" ")[0]
    for word in (text, first):
        if word in STOP_WORDS:
            return "stop"
        if word in START_WORDS:
            return "start"
        if word in HELP_WORDS:
            return "help"
        if word in OK_WORDS:
            return "ok"
        if word in INFO_WORDS:
            return "info"
    return "unknown"


@transaction.atomic
def handle_inbound(from_number: str, body: str, now: datetime | None = None) -> InboundResult:
    now = now or timezone.now()
    try:
        number = normalize_phone(from_number)
    except Exception:
        number = (from_number or "").strip()
    workers = list(Worker.objects.filter(phone=number, active=True).select_related("crew"))
    lead_crews = list(Crew.objects.filter(lead_phone=number)) if number else []
    worker = workers[0] if workers else None
    crew = worker.crew if worker else (lead_crews[0] if lead_crews else None)
    language = worker.language if worker else (crew.language if crew else "en")

    Message.objects.create(
        crew=crew,
        worker=worker,
        direction=Message.Direction.INBOUND,
        kind=Message.Kind.INBOUND,
        from_number=number,
        body=(body or "")[:1600],
        language=language,
        status=Message.Status.RECEIVED,
        sent_at=now,
    )
    if crew is None:
        return InboundResult(reply=None, action="unknown_sender")
    result = _respond(number, body, worker, crew, language, now)
    result.crew_id = crew.pk
    return result


def _respond(
    number: str, body: str, worker: Worker | None, crew: Crew, language: str, now: datetime
) -> InboundResult:
    intent = classify(body)
    if intent == "stop":
        Worker.objects.filter(phone=number).update(sms_opt_in=False)
        return InboundResult(reply=compose.opted_out(language), language=language, action="opted_out")
    if intent == "start":
        Worker.objects.filter(phone=number).update(sms_opt_in=True)
        return InboundResult(reply=compose.opted_in(language), language=language, action="opted_in")

    open_checkins = _prompted_checkins(number, now)
    if intent in ("ok", "help") and open_checkins:
        return _answer_checkins(open_checkins, intent, worker, crew, language, body, now)
    if intent == "help" and worker is not None:
        workday = worker.workdays.filter(date=now.astimezone(crew.tz).date()).select_related("site").first()
        site = workday.site if workday else None
        _alert_lead(crew, compose.help_alert(crew, worker, None, site), workday)
        return InboundResult(
            reply=compose.ack_self_help(language, crew.emergency_number),
            language=language,
            action="self_help",
        )
    return InboundResult(
        reply=compose.help_text(language, crew.emergency_number), language=language, action="info"
    )


def _prompted_checkins(number: str, now: datetime) -> list[CheckIn]:
    ids = (
        Message.objects.filter(
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.CHECKIN,
            to_number=number,
            status=Message.Status.SENT,
            sent_at__gte=now - PROMPT_WINDOW,
            checkin__isnull=False,
        )
        .values_list("checkin_id", flat=True)
        .distinct()
    )
    return list(
        CheckIn.objects.filter(pk__in=list(ids), status__in=[CheckIn.Status.PENDING, CheckIn.Status.MISSED])
        .select_related("worker", "buddy", "workday__site__crew")
        .order_by("due_at")
    )


def _answer_checkins(checkins, intent, responder, crew, language, body, now) -> InboundResult:
    names = []
    for checkin in checkins:
        was_missed = checkin.status == CheckIn.Status.MISSED
        checkin.status = CheckIn.Status.OK if intent == "ok" else CheckIn.Status.HELP
        checkin.responded_at = now
        checkin.response = (body or "")[:160]
        checkin.save(update_fields=["status", "responded_at", "response"])
        names.append(checkin.worker.name)
        if intent == "help":
            _alert_lead(
                crew,
                compose.help_alert(crew, checkin.worker, responder, checkin.workday.site),
                checkin.workday,
                checkin,
            )
        elif was_missed:
            _alert_lead(crew, compose.ok_update(crew, checkin.worker, responder), checkin.workday, checkin)
    if intent == "ok":
        return InboundResult(compose.ack_ok(language, names), language, "checkin_ok", checkins)
    return InboundResult(
        compose.ack_help(language, names, crew.emergency_number), language, "checkin_help", checkins
    )


def _alert_lead(crew: Crew, body: str, workday=None, checkin=None) -> None:
    if not crew.lead_phone:
        return
    send_now(
        crew=crew,
        workday=workday,
        checkin=checkin,
        kind=Message.Kind.ESCALATION,
        to_number=crew.lead_phone,
        body=body,
        language=crew.language,
    )


def record_reply(
    result: InboundResult, to_number: str, crew_id: int | None, sent: bool, provider_id: str = ""
) -> Message:
    return Message.objects.create(
        crew_id=crew_id,
        kind=Message.Kind.REPLY,
        to_number=to_number,
        body=result.reply or "",
        language=result.language,
        status=Message.Status.SENT if sent else Message.Status.QUEUED,
        send_at=timezone.now(),
        sent_at=timezone.now() if sent else None,
        provider_id=provider_id,
    )
