# Security policy

Shadebreak stores workers' names and phone numbers and sends texts on a
crew's behalf, so security reports are taken seriously.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x (latest minor) | Yes |
| Older | No; please upgrade |

## Reporting a vulnerability

Please **do not** open a public issue. Report it privately through
[GitHub security advisories](https://github.com/lobojoel2003/Shadebreak/security/advisories/new).
Include the version (page footer or `/version`), what an attacker could do,
and steps to reproduce. You should get an acknowledgement within a few days.

## Hardening checklist for operators

* Set a long random `DJANGO_SECRET_KEY` and keep `.env` out of version control.
* Serve over HTTPS with `DJANGO_BEHIND_PROXY=1`, `DJANGO_SECURE_SSL_REDIRECT=1`
  and `DJANGO_HSTS_SECONDS` set.
* Set `SHADEBREAK_ALLOW_SIGNUP=0` once your crews are set up.
* Use long random values for `SHADEBREAK_SMS_INBOUND_TOKEN` and keep your
  Twilio auth token secret; Twilio webhooks are signature-checked.
* Back up the database; it holds phone numbers and check-in history.
