import json

import pytest
import responses

from messaging.backends import SMSError, get_backend
from messaging.backends.twilio import twilio_signature, valid_twilio_signature

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"


@pytest.fixture
def twilio(settings):
    settings.TWILIO_ACCOUNT_SID = "AC123"
    settings.TWILIO_AUTH_TOKEN = "secret"
    settings.SHADEBREAK_SMS_FROM = "+16025550000"
    return get_backend("messaging.backends.twilio.TwilioBackend")


@responses.activate
def test_twilio_send(twilio):
    responses.post(TWILIO_URL, json={"sid": "SM1"}, status=201)
    assert twilio.send("+16025550111", "hola").provider_id == "SM1"
    body = responses.calls[0].request.body
    assert "From=%2B16025550000" in body and "Body=hola" in body


@responses.activate
def test_twilio_messaging_service(settings, twilio):
    settings.TWILIO_MESSAGING_SERVICE_SID = "MG1"
    backend = get_backend("messaging.backends.twilio.TwilioBackend")
    responses.post(TWILIO_URL, json={"sid": "SM2"}, status=201)
    backend.send("+16025550111", "x")
    assert "MessagingServiceSid=MG1" in responses.calls[0].request.body


@responses.activate
def test_twilio_errors(twilio):
    responses.post(TWILIO_URL, json={"message": "The 'To' number is not valid."}, status=400)
    with pytest.raises(SMSError, match="not valid"):
        twilio.send("+1", "x")


def test_twilio_requires_sender(settings):
    settings.TWILIO_ACCOUNT_SID = "AC123"
    settings.TWILIO_AUTH_TOKEN = "secret"
    settings.SHADEBREAK_SMS_FROM = ""
    settings.TWILIO_MESSAGING_SERVICE_SID = ""
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured):
        get_backend("messaging.backends.twilio.TwilioBackend")


def test_twilio_signature_follows_the_documented_algorithm():
    # Twilio: HMAC-SHA1 over the full URL followed by each POST parameter
    # name and value, sorted by name, base64 encoded.
    import base64
    import hashlib
    import hmac

    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    url = "https://example.com/myapp.php?foo=1&bar=2"
    payload = (
        url
        + "CallSidCA1234567890ABCDE"
        + "Caller+12349013030"
        + "Digits1234"
        + "From+12349013030"
        + "To+18005551212"
    )
    expected = base64.b64encode(hmac.new(b"12345", payload.encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature("12345", url, params) == expected
    assert valid_twilio_signature("12345", url, params, expected)
    assert not valid_twilio_signature("12345", url, params, "nope")
    assert not valid_twilio_signature("", url, params, "x")


@responses.activate
def test_gateway_send(settings):
    settings.SHADEBREAK_SMS_GATEWAY_URL = "https://gateway.example/send"
    settings.SHADEBREAK_SMS_GATEWAY_TOKEN = "tok"
    settings.SHADEBREAK_SMS_FROM = "+16025550000"
    responses.post("https://gateway.example/send", json={"id": 42})
    result = get_backend("messaging.backends.gateway.GatewayBackend").send("+16025550111", "hi")
    assert result.provider_id == "42"
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok"
    assert json.loads(request.body) == {"to": "+16025550111", "body": "hi", "from": "+16025550000"}


@responses.activate
def test_gateway_errors(settings):
    import requests

    settings.SHADEBREAK_SMS_GATEWAY_URL = "https://gateway.example/send"
    backend = get_backend("messaging.backends.gateway.GatewayBackend")
    responses.post("https://gateway.example/send", status=502, body="bad gateway")
    with pytest.raises(SMSError, match="502"):
        backend.send("+1", "x")
    responses.replace(responses.POST, "https://gateway.example/send", body=requests.ConnectionError("down"))
    with pytest.raises(SMSError):
        backend.send("+1", "x")
    responses.replace(responses.POST, "https://gateway.example/send", body="ok", status=200)
    assert backend.send("+1", "x").provider_id == ""
