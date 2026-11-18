"""Container health check: GET /healthz with a Host header Django accepts."""

import os
import sys
import urllib.request

hosts = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if h.strip()]
host = next((h.lstrip(".") for h in hosts if h != "*"), "localhost")
request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz",
    headers={"Host": host, "X-Forwarded-Proto": "https"},
)
try:
    with urllib.request.urlopen(request, timeout=4) as response:  # noqa: S310 - fixed local URL
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
