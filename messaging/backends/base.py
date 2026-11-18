from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


class SMSError(Exception):
    """The provider refused or failed to send the message."""


@dataclass(frozen=True)
class SendResult:
    provider_id: str = ""


class BaseBackend:
    #: Whether inbound replies should be answered with a separate outbound
    #: message (True) or are answered in the webhook response (False).
    replies_out_of_band = True

    def __init__(self) -> None:
        self.from_number = settings.SHADEBREAK_SMS_FROM

    def send(self, to: str, body: str) -> SendResult:  # pragma: no cover - interface
        raise NotImplementedError
