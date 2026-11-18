import logging
import uuid

from .base import BaseBackend, SendResult

logger = logging.getLogger("shadebreak.sms")


class ConsoleBackend(BaseBackend):
    """Writes each text to the log instead of sending it. Safe for development."""

    def send(self, to: str, body: str) -> SendResult:
        logger.info("SMS to %s: %s", to, body)
        return SendResult(provider_id=f"console-{uuid.uuid4().hex[:12]}")
