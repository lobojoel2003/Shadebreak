import json

import pytest

from messaging.backends.twilio import twilio_signature
from messaging.models import Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def twilio_settings(settings):
    settings.TWILIO_AUTH_TOKEN = "secret"
    settings.SHADEBREAK_PUBLIC_URL = ""
    return settings


def test_twilio_rejects_bad_signature(client, twilio_settings):
    response = client.post(
        "/sms/twilio/", {"From": "+16025550111", "Body": "1"}, HTTP_X_TWILIO_SIGNATURE="bad"
    )
    assert response.status_code == 403


def test_twilio_accepts_signed_request_and_replies_with_twiml(client, twilio_settings, make_worker):
    worker = make_worker("Ana", language="es")
    params = {"From": worker.phone, "Body": "STOP", "MessageSid": "SM1"}
    signature = twilio_signature("secret", "http://testserver/sms/twilio/", params)
    response = client.post("/sms/twilio/", params, HTTP_X_TWILIO_SIGNATURE=signature)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/xml"
    body = response.content.decode()
    assert body.startswith('<?xml version="1.0" encoding="UTF-8"?><Response><Message>')
    assert "START" in body
    assert Message.objects.filter(kind=Message.Kind.REPLY, to_number=worker.phone).exists()


def test_twilio_uses_public_url_for_signature(client, twilio_settings, make_worker):
    twilio_settings.SHADEBREAK_PUBLIC_URL = "https://shade.example.com"
    worker = make_worker("Ana")
    params = {"From": worker.phone, "Body": "?"}
    signature = twilio_signature("secret", "https://shade.example.com/sms/twilio/", params)
    assert client.post("/sms/twilio/", params, HTTP_X_TWILIO_SIGNATURE=signature).status_code == 200


def test_twilio_unknown_sender_gets_empty_response(client, twilio_settings):
    params = {"From": "+19995550000", "Body": "hi"}
    signature = twilio_signature("secret", "http://testserver/sms/twilio/", params)
    response = client.post("/sms/twilio/", params, HTTP_X_TWILIO_SIGNATURE=signature)
    assert response.content.decode().endswith("<Response></Response>")


@pytest.fixture
def gateway_settings(settings):
    settings.SHADEBREAK_SMS_INBOUND_TOKEN = "in-token"
    return settings


def test_gateway_requires_token(client, gateway_settings):
    assert client.post("/sms/gateway/", {"from": "+1", "body": "1"}).status_code == 403
    gateway_settings.SHADEBREAK_SMS_INBOUND_TOKEN = ""
    assert client.post("/sms/gateway/?token=", {"from": "+1", "body": "1"}).status_code == 403


def test_gateway_json_and_reply_out_of_band(client, gateway_settings, make_worker):
    worker = make_worker("Jake")
    response = client.post(
        "/sms/gateway/",
        data=json.dumps({"from": worker.phone, "message": "info"}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer in-token",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] and data["action"] == "info"
    reply = Message.objects.get(kind=Message.Kind.REPLY)
    assert reply.status == Message.Status.SENT and reply.to_number == worker.phone


def test_gateway_form_inline_reply(client, gateway_settings, make_worker):
    worker = make_worker("Jake")
    response = client.post(
        "/sms/gateway/?token=in-token&reply=inline", {"phone": worker.phone, "text": "stop"}
    )
    assert response.json()["action"] == "opted_out"
    assert not Message.objects.filter(kind=Message.Kind.REPLY).exists()


def test_gateway_bad_requests(client, gateway_settings):
    auth = {"HTTP_AUTHORIZATION": "Bearer in-token"}
    assert client.post("/sms/gateway/", data="{", content_type="application/json", **auth).status_code == 400
    assert client.post("/sms/gateway/", {"body": "1"}, **auth).status_code == 400
    assert client.get("/sms/gateway/", **auth).status_code == 405
