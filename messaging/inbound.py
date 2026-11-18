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
    "hurt",
    "herido",
    "herida",
    "collapsed",
    "fainted",
    "desmayo",
    "desmayado",
    "desmayada",
}
# Phrases that turn an "ok" or "bien" into the opposite.
HELP_PHRASES = ("not ok", "not okay", "not good", "no ok", "no esta bien", "no estoy bien", "no bien")
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
    worker_id: int | None = None


def classify(body: str) -> str:
    """What a reply means. Safety first: any sign of trouble anywhere in the
    text means "help", even after a "yes", "ok" or "stop"."""
    text = unicodedata.normalize("NFKD", body or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9?\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "unknown"
    # Carrier keywords are whole-message commands.
    if text in STOP_WORDS:
        return "stop"
    if text in START_WORDS:
        return "start"
    tokens = text.split(" ")
    if any(token in HELP_WORDS for token in tokens) or any(f" {p} " in f" {text} " for p in HELP_PHRASES):
        return "help"
    first = tokens[0]
    if first in STOP_WORDS:
        return "stop"
    if first in START_WORDS:
        return "start"
    if text in OK_WORDS or first in OK_WORDS:
        return "ok"
    if text in INFO_WORDS or first in INFO_WORDS:
        return "info"
    return "unknown"


@transaction.atomic
def handle_inbound(from_number: str, body: str, now: datetime | None = None) -> InboundResult:
    now = now or timezone.now()
    try:
        number = normalize_phone(from_number)
    except Exception:
        number = (from_number or "").strip()
    workers = list(Worker.objects.filter(phone=number, active=True).select_related("crew")) if number else []
    lead_crews = list(Crew.objects.filter(lead_phone=number)) if number else []
    crew = _conversation_crew(number, workers, lead_crews)
    worker = next((w for w in workers if crew and w.crew_id == crew.pk), None)
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
    result.worker_id = worker.pk if worker else None
    return result


def _conversation_crew(number: str, workers: list[Worker], lead_crews: list[Crew]) -> Crew | None:
    """The crew this number is talking to. One phone can belong to people on
    more than one crew, so prefer the crew that texted it most recently."""
    crews = {w.crew_id: w.crew for w in workers} | {c.pk: c for c in lead_crews}
    if not crews:
        return None
    recent = (
        Message.objects.filter(
            direction=Message.Direction.OUTBOUND, to_number=number, crew_id__in=list(crews)
        )
        .exclude(sent_at=None)
        .order_by("-sent_at")
        .values_list("crew_id", flat=True)
        .first()
    )
    return crews.get(recent) or next(iter(crews.values()))


def _respond(
    number: str, body: str, worker: Worker | None, crew: Crew, language: str, now: datetime
) -> InboundResult:
    intent = classify(body)
    if intent == "stop":
        Worker.objects.filter(phone=number).update(sms_opt_in=False)
        Crew.objects.filter(lead_phone=number).update(lead_opted_out=True)
        return InboundResult(reply=compose.opted_out(language), language=language, action="opted_out")
    if intent == "start":
        Worker.objects.filter(phone=number).update(sms_opt_in=True)
        Crew.objects.filter(lead_phone=number).update(lead_opted_out=False)
        return InboundResult(reply=compose.opted_in(language), language=language, action="opted_in")

    open_checkins = _prompted_checkins(number, now)
    if intent in ("ok", "help") and open_checkins:
        return _answer_checkins(open_checkins, intent, number, language, body, now)
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
    """Open check-ins this number was asked about in the last few hours.

    Rows are locked so a reply and the escalation task never both act on the
    same check-in (the second one sees the first one's result).
    """
    prompts = Message.objects.filter(
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.CHECKIN,
        to_number=number,
        status=Message.Status.SENT,
        sent_at__gte=now - PROMPT_WINDOW,
    ).values_list("pk", flat=True)
    ids = list(CheckIn.objects.filter(prompts__in=list(prompts)).values_list("pk", flat=True).distinct())
    return list(
        CheckIn.objects.select_for_update(of=("self",))
        .filter(pk__in=ids, status__in=[CheckIn.Status.PENDING, CheckIn.Status.MISSED])
        .select_related("worker", "buddy", "workday__site__crew")
        .order_by("due_at")
    )


def _answer_checkins(checkins, intent, number, language, body, now) -> InboundResult:
    names = []
    for checkin in checkins:
        crew = checkin.workday.site.crew
        responder = Worker.objects.filter(crew=crew, phone=number).first()
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
    emergency = checkins[0].workday.site.crew.emergency_number
    if intent == "ok":
        return InboundResult(compose.ack_ok(language, names), language, "checkin_ok", checkins)
    return InboundResult(compose.ack_help(language, names, emergency), language, "checkin_help", checkins)


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
        worker_id=result.worker_id,
        kind=Message.Kind.REPLY,
        to_number=to_number,
        body=result.reply or "",
        language=result.language,
        status=Message.Status.SENT if sent else Message.Status.QUEUED,
        send_at=timezone.now(),
        sent_at=timezone.now() if sent else None,
        provider_id=provider_id,
    )
