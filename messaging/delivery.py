"""Send queued texts through the configured backend."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .backends import BaseBackend, SMSError, get_backend
from .models import Message
from .text import fold_to_gsm

logger = logging.getLogger(__name__)

# A reminder that would arrive this late is more confusing than helpful.
STALE_AFTER = timedelta(minutes=30)
NEVER_STALE = {Message.Kind.ESCALATION, Message.Kind.REPLY}


def deliver(message: Message, backend: BaseBackend | None = None, now: datetime | None = None) -> Message:
    now = now or timezone.now()
    if not Message.objects.filter(pk=message.pk, status=Message.Status.QUEUED).update(
        status=Message.Status.SENDING
    ):
        message.refresh_from_db()
        return message  # someone else is sending (or sent) it

    def finish(status: str, **fields) -> Message:
        fields["status"] = status
        Message.objects.filter(pk=message.pk).update(**fields)
        for key, value in fields.items():
            setattr(message, key, value)
        return message

    if message.kind not in NEVER_STALE and message.send_at and message.send_at < now - STALE_AFTER:
        return finish(Message.Status.EXPIRED, error="Too late to be useful")
    if message.worker_id and not message.worker.can_text and message.kind != Message.Kind.REPLY:
        return finish(Message.Status.EXPIRED, error="Worker is not opted in to texts")
    if message.crew_id and not message.crew.sms_enabled:
        return finish(Message.Status.EXPIRED, error="Texts are turned off for this crew")
    if not message.to_number:
        return finish(Message.Status.FAILED, error="No phone number")

    body = fold_to_gsm(message.body) if settings.SHADEBREAK_SMS_FOLD_ACCENTS else message.body
    try:
        result = (backend or get_backend()).send(message.to_number, body)
    except SMSError as exc:
        logger.warning("SMS %s to %s failed: %s", message.pk, message.to_number, exc)
        return finish(Message.Status.FAILED, error=str(exc)[:255], sent_at=now)
    return finish(Message.Status.SENT, provider_id=result.provider_id[:64], sent_at=now, error="")


def send_now(**fields) -> Message:
    """Create and immediately deliver a text (used for urgent alerts)."""
    now = timezone.now()
    message = Message.objects.create(status=Message.Status.QUEUED, send_at=now, **fields)
    return deliver(message, now=now)


def send_due(now: datetime | None = None, limit: int = 500) -> int:
    now = now or timezone.now()
    due = list(
        Message.objects.filter(status=Message.Status.QUEUED, send_at__lte=now)
        .select_related("worker", "crew")
        .order_by("send_at")[:limit]
    )
    if not due:
        return 0
    backend = get_backend()
    for message in due:
        deliver(message, backend=backend, now=now)
    return len(due)
