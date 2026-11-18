"""Pluggable SMS backends.

Set ``SHADEBREAK_SMS_BACKEND`` to a dotted path. Built in:

* ``messaging.backends.console.ConsoleBackend`` - prints texts to the log (default).
* ``messaging.backends.locmem.LocmemBackend`` - keeps texts in memory (tests).
* ``messaging.backends.twilio.TwilioBackend`` - Twilio's REST API.
* ``messaging.backends.gateway.GatewayBackend`` - any HTTP SMS gateway, such as
  an Android phone running a gateway app or a self-hosted Jasmin/Kannel box.

Write your own by subclassing :class:`messaging.backends.base.BaseBackend`.
"""

from django.conf import settings
from django.utils.module_loading import import_string

from .base import BaseBackend, SendResult, SMSError


def get_backend(path: str | None = None) -> BaseBackend:
    backend_class = import_string(path or settings.SHADEBREAK_SMS_BACKEND)
    return backend_class()


__all__ = ["BaseBackend", "SMSError", "SendResult", "get_backend"]
