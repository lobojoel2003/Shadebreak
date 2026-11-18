"""Serve the demo crew with the clock pinned to a summer morning.

Used to take the README screenshots, so they always show the same day:

    python scripts/demo_server.py --at 2026-07-15T10:20 --port 8765

It creates a throwaway SQLite database, runs migrations, loads the demo crew
(sample forecast, no network needed) and serves the app with static files.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", default="2026-07-15T10:20", help="Local Phoenix time to pin the clock to")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--password", default="demo-pass-123")
    args = parser.parse_args()

    local = datetime.fromisoformat(args.at).replace(tzinfo=ZoneInfo("America/Phoenix"))
    database = Path(tempfile.mkdtemp(prefix="shadebreak-demo-")) / "demo.sqlite3"
    os.environ.update(
        {
            "DJANGO_SETTINGS_MODULE": "shadebreak.settings",
            "DATABASE_URL": f"sqlite:///{database}",
            "DJANGO_DEBUG": "1",
            "SHADEBREAK_SMS_BACKEND": "messaging.backends.locmem.LocmemBackend",
        }
    )

    from freezegun import freeze_time

    freezer = freeze_time(local, tick=True)
    freezer.start()

    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", verbosity=0)
    call_command(
        "seed_demo",
        password=args.password,
        date=local.date().isoformat(),
        clock=local.strftime("%H:%M"),
    )

    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.servers.basehttp import run
    from django.core.wsgi import get_wsgi_application

    print(f"Serving demo at http://127.0.0.1:{args.port}/ (clock pinned to {local.isoformat()})", flush=True)
    run("127.0.0.1", args.port, StaticFilesHandler(get_wsgi_application()), threading=True)


if __name__ == "__main__":
    main()
