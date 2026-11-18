from celery import shared_task

from .delivery import send_due
from .escalation import escalate_missed


@shared_task(ignore_result=True)
def send_due_messages() -> int:
    """Every minute: send texts whose time has come."""
    return send_due()


@shared_task(ignore_result=True)
def escalate_missed_checkins() -> int:
    """Every two minutes: alert the crew lead about unanswered check-ins."""
    return escalate_missed()
