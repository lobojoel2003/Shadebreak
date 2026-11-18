from __future__ import annotations

import json
from hmac import compare_digest
from xml.sax.saxutils import escape

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .backends.twilio import valid_twilio_signature
from .delivery import send_now
from .inbound import handle_inbound, record_reply
from .models import Message
from .text import fold_to_gsm


def _fold(text: str) -> str:
    return fold_to_gsm(text) if settings.SHADEBREAK_SMS_FOLD_ACCENTS else text


@csrf_exempt
@require_POST
def twilio_inbound(request):
    """Twilio incoming-message webhook. Replies with TwiML."""
    params = request.POST.dict()
    url = (
        settings.SHADEBREAK_PUBLIC_URL + request.get_full_path()
        if settings.SHADEBREAK_PUBLIC_URL
        else request.build_absolute_uri()
    )
    signature = request.headers.get("X-Twilio-Signature", "")
    if not valid_twilio_signature(settings.TWILIO_AUTH_TOKEN, url, params, signature):
        return HttpResponseForbidden("Invalid signature")
    sender = params.get("From", "")
    result = handle_inbound(sender, params.get("Body", ""))
    body = ""
    if result.reply:
        record_reply(result, sender, result.crew_id, sent=True)
        body = f"<Message>{escape(_fold(result.reply))}</Message>"
    return HttpResponse(
        f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', content_type="text/xml"
    )


@csrf_exempt
@require_POST
def gateway_inbound(request):
    """Incoming texts from a generic HTTP gateway.

    Authenticate with ``Authorization: Bearer <SHADEBREAK_SMS_INBOUND_TOKEN>``
    (or ``?token=``). Accepts JSON or form data with ``from`` and ``body``
    (``message`` and ``text`` also work). The reply is sent as a new text
    unless ``?reply=inline``, in which case it is only returned in the JSON.
    """
    expected = settings.SHADEBREAK_SMS_INBOUND_TOKEN
    header = request.headers.get("Authorization", "")
    supplied = (
        header.removeprefix("Bearer ").strip()
        if header.startswith("Bearer ")
        else request.GET.get("token", "")
    )
    if not expected or not compare_digest(supplied.encode(), expected.encode()):
        return HttpResponseForbidden("Invalid token")
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return HttpResponseBadRequest("Invalid JSON")
    else:
        data = request.POST.dict()
    sender = str(data.get("from") or data.get("From") or data.get("phone") or data.get("sender") or "")
    text = str(data.get("body") or data.get("Body") or data.get("message") or data.get("text") or "")
    if not sender:
        return HttpResponseBadRequest("Missing sender")
    result = handle_inbound(sender, text)
    if result.reply and request.GET.get("reply") != "inline":
        send_now(
            crew_id=result.crew_id,
            kind=Message.Kind.REPLY,
            to_number=sender,
            body=result.reply,
            language=result.language,
        )
    return JsonResponse(
        {"ok": True, "action": result.action, "reply": _fold(result.reply) if result.reply else None}
    )


@login_required
def message_log(request):
    crew = getattr(request, "crew", None)
    if crew is None:
        return redirect("onboarding")
    messages = (
        Message.objects.filter(crew=crew)
        .select_related("worker", "workday__site")
        .annotate(moment=Coalesce("sent_at", "send_at", "created_at"))
    )
    person = None
    if request.GET.get("worker", "").isdigit():
        person = crew.workers.filter(pk=request.GET["worker"]).first()
    if person is not None:
        messages = messages.filter(Q(worker=person) | Q(to_number=person.phone) | Q(from_number=person.phone))
    kind = request.GET.get("kind", "")
    if kind in Message.Kind.values:
        messages = messages.filter(kind=kind)
    status = request.GET.get("status", "")
    if status in Message.Status.values:
        messages = messages.filter(status=status)
    # A person's thread reads like a chat (oldest first); the full log shows newest first.
    ordering = ("moment", "pk") if person else ("-moment", "-pk")
    page = Paginator(messages.order_by(*ordering), 50).get_page(request.GET.get("page"))
    template = (
        "messaging/_message_rows.html" if request.htmx and request.GET.get("page") else "messaging/log.html"
    )
    return render(
        request,
        template,
        {
            "page": page,
            "kinds": Message.Kind.choices,
            "kind": kind,
            "status": status,
            "person": person,
            "people": crew.workers.filter(active=True).exclude(phone=""),
            "nav": "messages",
        },
    )
