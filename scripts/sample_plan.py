"""Render the demo crew's heat plan to PDF (English and Spanish).

    python scripts/sample_plan.py --out dist/

Uses a throwaway SQLite database and the sample forecast, so it needs no
network access. CI attaches the result to each GitHub release.
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
    parser.add_argument("--at", default="2026-07-15T05:00")
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()

    local = datetime.fromisoformat(args.at).replace(tzinfo=ZoneInfo("America/Phoenix"))
    database = Path(tempfile.mkdtemp(prefix="shadebreak-plan-")) / "plan.sqlite3"
    os.environ.update(
        {
            "DJANGO_SETTINGS_MODULE": "shadebreak.settings",
            "DATABASE_URL": f"sqlite:///{database}",
            "SHADEBREAK_SMS_BACKEND": "messaging.backends.locmem.LocmemBackend",
        }
    )
    from freezegun import freeze_time

    with freeze_time(local):
        import django
        from django.core.management import call_command

        django.setup()
        call_command("migrate", verbosity=0)
        call_command("seed_demo", password="unused-demo-pass-1", date=local.date().isoformat(), clock="05:00")

        from crews.models import Crew
        from crews.plan import render_plan_pdf

        crew = Crew.objects.get(name__startswith="Desert Bloom")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for language in ("en", "es"):
            path = out / f"shadebreak-sample-heat-plan-{language}.pdf"
            path.write_bytes(render_plan_pdf(crew, local.date(), language))
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
