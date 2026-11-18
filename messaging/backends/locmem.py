import uuid

from .base import BaseBackend, SendResult, SMSError

outbox: list[dict[str, str]] = []
fail_numbers: set[str] = set()


class LocmemBackend(BaseBackend):
    """Stores texts in ``messaging.backends.locmem.outbox`` for tests."""

    def send(self, to: str, body: str) -> SendResult:
        if to in fail_numbers:
            raise SMSError(f"Simulated failure sending to {to}")
        provider_id = f"locmem-{uuid.uuid4().hex[:12]}"
        outbox.append({"to": to, "body": body, "id": provider_id})
        return SendResult(provider_id=provider_id)
