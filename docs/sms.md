# Text messages

Workers never install anything. Shadebreak texts them in their language and
reads their replies.

## What gets sent

| Text | To | When |
| --- | --- | --- |
| Morning briefing | Each worker who opted in, and the crew lead | 30 minutes before the shift |
| Break reminder | Each worker | When their break starts (new workers' longer breaks start earlier) |
| Water reminder | Each worker | Top of each hour at High heat or above without a break |
| Buddy check-in | The worker's buddy (or the crew lead if they have none) | Every 1–2 hours by heat level |
| Alert | Crew lead | A buddy replies `2`, a worker texts `help`, or a check-in goes unanswered |

Only people marked **agreed to get text messages** receive texts. Reminders
that would arrive more than 30 minutes late are skipped rather than sent.

## Replies

| Reply | Meaning |
| --- | --- |
| `1`, `ok`, `sí`, `bien` | The person checked on is OK |
| `2`, `help`, `ayuda` | They need help: the crew lead is alerted right away |
| `STOP`, `alto` | Stop all texts to this number |
| `START` | Turn texts back on |
| anything else | A short help message |

A worker who texts `help` without a pending check-in also triggers an urgent
alert to the crew lead, with their number.

## Twilio

```dotenv
SHADEBREAK_SMS_BACKEND=messaging.backends.twilio.TwilioBackend
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_MESSAGING_SERVICE_SID=MG...     # or SHADEBREAK_SMS_FROM=+1...
SHADEBREAK_PUBLIC_URL=https://shadebreak.example.com
```

In the Twilio console, set the number's (or messaging service's) incoming
message webhook to `https://shadebreak.example.com/sms/twilio/` (HTTP POST).
Every request is checked against Twilio's `X-Twilio-Signature`; replies go back
in the TwiML response. U.S. numbers need A2P 10DLC registration for business
texting.

## A local or self-hosted gateway

```dotenv
SHADEBREAK_SMS_BACKEND=messaging.backends.gateway.GatewayBackend
SHADEBREAK_SMS_GATEWAY_URL=https://gateway.example/send
SHADEBREAK_SMS_GATEWAY_TOKEN=outbound-secret
SHADEBREAK_SMS_INBOUND_TOKEN=inbound-secret
```

Outbound texts are sent as `POST {"to": "+1...", "body": "...", "from": "..."}`
with `Authorization: Bearer <SHADEBREAK_SMS_GATEWAY_TOKEN>`. Point the
gateway's incoming-message webhook at `/sms/gateway/` with
`Authorization: Bearer <SHADEBREAK_SMS_INBOUND_TOKEN>` (or `?token=`). It
accepts JSON or form data with `from` and `body` (`phone`, `message` and
`text` also work). Add `?reply=inline` if your gateway sends the `reply` field
of the JSON response itself.

To support a gateway with a different payload, subclass
`messaging.backends.gateway.GatewayBackend` and override `payload()`, or write
a backend with a `send(to, body)` method and point `SHADEBREAK_SMS_BACKEND`
at it.

## Cost: keeping Spanish texts cheap

SMS bills by segment. One character outside the GSM-7 alphabet (`á`, `í`,
`ó`, `ú`, `°`) switches a whole text to UCS-2, cutting a segment from 160 to
70 characters. With `SHADEBREAK_SMS_FOLD_ACCENTS=1` (the default) those
characters are replaced before sending, while `ñ`, `é`, `ü`, `¿` and `¡`,
which GSM-7 has, are kept. The app and the message log always show the
original text.
