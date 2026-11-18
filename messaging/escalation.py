"""Escalate buddy check-ins that nobody answered."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from crews.models import CheckIn

from . import compose
from .delivery import send_now
from .models import Message

LOOKBACK = timedelta(hours=6)


def escalate_missed(now: datetime | None = None) -> int:
    now = now or timezone.now()
    grace = timedelta(minutes=settings.SHADEBREAK_CHECKIN_GRACE_MINUTES)
    overdue = CheckIn.objects.filter(
        status=CheckIn.Status.PENDING, due_at__lte=now - grace, due_at__gte=now - LOOKBACK
    ).select_related("worker", "buddy", "workday__site__crew")
    count = 0
    for checkin in overdue:
        claimed = CheckIn.objects.filter(pk=checkin.pk, status=CheckIn.Status.PENDING).update(
            status=CheckIn.Status.MISSED, escalated_at=now
        )
        if not claimed:
            continue
        count += 1
        crew = checkin.workday.site.crew
        if crew.sms_enabled and crew.lead_phone:
            send_now(
                crew=crew,
                workday=checkin.workday,
                checkin=checkin,
                kind=Message.Kind.ESCALATION,
                to_number=crew.lead_phone,
                body=compose.missed_checkin_alert(checkin),
                language=crew.language,
            )
    return count
