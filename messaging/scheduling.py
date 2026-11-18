"""Queue a work day's texts: briefings, break and water reminders, check-ins.

Called by ``crews.services.planning.plan_workday`` whenever a plan changes.
Texts that have not gone out yet are rebuilt from the new plan; texts already
sent stay in the log.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings

from crews.models import Assignment, CheckIn, RiskLevel, WorkDay

from . import compose
from .models import Message

WATER_GAP = timedelta(minutes=20)


def schedule_workday(workday: WorkDay, now: datetime) -> int:
    site = workday.site
    crew = site.crew
    Message.objects.filter(workday=workday, status=Message.Status.QUEUED, send_at__gt=now).delete()
    if not crew.sms_enabled or workday.shift_end <= now:
        return 0

    briefed = set(
        Message.objects.filter(workday=workday, kind=Message.Kind.BRIEFING).values_list(
            "to_number", flat=True
        )
    )
    briefing_at = max(now, workday.shift_start - timedelta(minutes=settings.SHADEBREAK_BRIEFING_LEAD_MINUTES))
    breaks = list(workday.breaks.all())
    hot_marks = _hot_hour_marks(workday)
    assignments = list(
        workday.assignments.filter(status=Assignment.Status.SCHEDULED).select_related(
            "worker", "buddy", "workday"
        )
    )
    queue: list[Message] = []

    def add(kind, to_number, body, send_at, worker=None, checkin=None, language="en"):
        queue.append(
            Message(
                crew=crew,
                workday=workday,
                worker=worker,
                checkin=checkin,
                kind=kind,
                to_number=to_number,
                body=body,
                language=language,
                send_at=send_at,
            )
        )

    for a in assignments:
        worker = a.worker
        if not worker.can_text:
            continue
        if worker.phone not in briefed:
            add(
                Message.Kind.BRIEFING,
                worker.phone,
                compose.briefing(a, breaks),
                briefing_at,
                worker,
                language=worker.language,
            )
        finish = a.planned_end or workday.shift_end
        break_starts = []
        for start, minutes, until, stop in _worker_breaks(a, breaks):
            break_starts.append(start)
            if now < start < finish:
                add(
                    Message.Kind.BREAK,
                    worker.phone,
                    compose.break_reminder(a, minutes, until, stop),
                    start,
                    worker,
                    language=worker.language,
                )
        if crew.water_reminders:
            for mark, risk in hot_marks:
                if now < mark < finish and all(abs(mark - s) > WATER_GAP for s in break_starts):
                    add(
                        Message.Kind.WATER,
                        worker.phone,
                        compose.water_reminder(worker, risk),
                        mark,
                        worker,
                        language=worker.language,
                    )

    if crew.lead_phone and not crew.lead_opted_out and crew.lead_phone not in briefed:
        add(
            Message.Kind.BRIEFING,
            crew.lead_phone,
            compose.lead_briefing(workday),
            briefing_at,
            language=crew.language,
        )

    # One prompt per person and time, even when they watch more than one worker.
    groups: dict[tuple[str, datetime], dict] = {}
    for checkin in workday.checkins.filter(status=CheckIn.Status.PENDING, due_at__gt=now).select_related(
        "worker", "buddy"
    ):
        buddy = checkin.buddy
        if buddy is not None and buddy.can_text:
            to_number, recipient, language, to_lead = buddy.phone, buddy, buddy.language, False
        elif crew.lead_phone and not crew.lead_opted_out:
            to_number, recipient, language, to_lead = crew.lead_phone, None, crew.language, buddy is None
        else:
            continue
        group = groups.setdefault(
            (to_number, checkin.due_at),
            {"recipient": recipient, "language": language, "to_lead": to_lead, "checkins": []},
        )
        group["checkins"].append(checkin)
        group["to_lead"] = group["to_lead"] and buddy is None

    Message.objects.bulk_create(queue)
    for (to_number, due_at), group in groups.items():
        prompt = Message.objects.create(
            crew=crew,
            workday=workday,
            worker=group["recipient"],
            checkin=group["checkins"][0],
            kind=Message.Kind.CHECKIN,
            to_number=to_number,
            body=compose.checkin_prompt(group["checkins"], group["language"], to_lead=group["to_lead"]),
            language=group["language"],
            send_at=due_at,
        )
        prompt.checkins.set(group["checkins"])
    return len(queue) + len(groups)


def _worker_breaks(assignment: Assignment, breaks):
    """Yield (start, minutes, until, stop), merging back-to-back stop blocks."""
    merged: list[list] = []
    for brk in breaks:
        minutes = brk.new_worker_minutes if assignment.acclimatizing else brk.minutes
        stop = brk.new_worker_stop if assignment.acclimatizing else brk.stop
        if not minutes:
            continue
        start = brk.end - timedelta(minutes=minutes)
        if merged and stop and merged[-1][3] and merged[-1][2] == start:
            merged[-1][2] = brk.end
            merged[-1][1] += minutes
            continue
        merged.append([start, minutes, brk.end, stop])
    return [tuple(item) for item in merged]


def _hot_hour_marks(workday: WorkDay) -> list[tuple[datetime, int]]:
    marks = []
    for row in workday.site.forecasts.filter(
        start__gte=workday.shift_start, start__lt=workday.shift_end, risk__gte=RiskLevel.HIGH
    ):
        if row.start > workday.shift_start:
            marks.append((row.start, row.risk))
    return marks
