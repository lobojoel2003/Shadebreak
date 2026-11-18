"""A generic HTTP SMS gateway.

Sends ``POST {"to": "+1...", "body": "..."}`` as JSON to
``SHADEBREAK_SMS_GATEWAY_URL`` with ``Authorization: Bearer
SHADEBREAK_SMS_GATEWAY_TOKEN`` when a token is set. Many self-hosted gateways
(an Android phone running a gateway app, Jasmin, Kannel behind a small
adapter) can accept this, or subclass and override :meth:`payload`.

Incoming texts are accepted at ``/sms/gateway/`` (see ``messaging.views``).
"""

from __future__ import annotations

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend, SendResult, SMSError


class GatewayBackend(BaseBackend):
    def __init__(self) -> None:
        super().__init__()
        self.url = settings.SHADEBREAK_SMS_GATEWAY_URL
        self.token = settings.SHADEBREAK_SMS_GATEWAY_TOKEN
        if not self.url:
            raise ImproperlyConfigured("Set SHADEBREAK_SMS_GATEWAY_URL.")

    def payload(self, to: str, body: str) -> dict:
        data = {"to": to, "body": body}
        if self.from_number:
            data["from"] = self.from_number
        return data

    def send(self, to: str, body: str) -> SendResult:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = requests.post(self.url, json=self.payload(to, body), headers=headers, timeout=15)
        except requests.RequestException as exc:
            raise SMSError(str(exc)) from exc
        if response.status_code >= 400:
            raise SMSError(f"Gateway {response.status_code}: {response.text[:200]}")
        try:
            provider_id = str(response.json().get("id", ""))
        except ValueError:
            provider_id = ""
        return SendResult(provider_id=provider_id[:64])
