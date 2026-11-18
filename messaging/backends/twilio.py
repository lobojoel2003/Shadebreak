"""Twilio Programmable Messaging over its REST API (no SDK needed).

Settings: ``TWILIO_ACCOUNT_SID``, ``TWILIO_AUTH_TOKEN`` and either
``TWILIO_MESSAGING_SERVICE_SID`` or ``SHADEBREAK_SMS_FROM``. Point the number's
incoming-message webhook at ``https://<your host>/sms/twilio/``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend, SendResult, SMSError

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioBackend(BaseBackend):
    replies_out_of_band = False  # replies go back in the TwiML response

    def __init__(self) -> None:
        super().__init__()
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.messaging_service_sid = settings.TWILIO_MESSAGING_SERVICE_SID
        if not (self.account_sid and self.auth_token):
            raise ImproperlyConfigured("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
        if not (self.messaging_service_sid or self.from_number):
            raise ImproperlyConfigured("Set TWILIO_MESSAGING_SERVICE_SID or SHADEBREAK_SMS_FROM.")

    def send(self, to: str, body: str) -> SendResult:
        data = {"To": to, "Body": body}
        if self.messaging_service_sid:
            data["MessagingServiceSid"] = self.messaging_service_sid
        else:
            data["From"] = self.from_number
        try:
            response = requests.post(
                API.format(sid=self.account_sid),
                data=data,
                auth=(self.account_sid, self.auth_token),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise SMSError(str(exc)) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", "")
            except ValueError:
                detail = response.text[:200]
            raise SMSError(f"Twilio {response.status_code}: {detail}")
        return SendResult(provider_id=response.json().get("sid", ""))


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Compute Twilio's X-Twilio-Signature for a form-encoded webhook."""
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    if not (auth_token and signature):
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)
