"""The written heat plan, rendered to PDF with WeasyPrint."""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from heat.acclimatization import NEW_WORKER_RAMP, RETURNING_WORKER_RAMP
from shadebreak.version import version_string

from .models import Crew, WorkDay
from .services.dashboard import build_site_day

TRIGGERS = [
    (
        "low",
        _("Low"),
        _("Below 80°F"),
        _("Below 80°F"),
        _("Water, shade and rest available all shift. Watch new workers."),
    ),
    (
        "caution",
        _("Caution"),
        "80–89°F",
        "80–84°F",
        _(
            "Cool water within reach: 1 cup every 15–20 minutes. Shade for every rest. Rest whenever "
            "needed. New workers on reduced hours."
        ),
    ),
    (
        "high",
        _("High"),
        "90–102°F",
        "85–87°F",
        _(
            "At least a 15-minute rest in shade every 2 hours. Buddy check-ins every 2 hours. "
            "Talk about heat at the start of the shift."
        ),
    ),
    (
        "very-high",
        _("Very high"),
        "103–114°F",
        "88–89°F",
        _("Follow the work/rest schedule. Hourly buddy check-ins. Move heavy work to the coolest hours."),
    ),
    (
        "extreme",
        _("Extreme"),
        _("115°F and up"),
        _("90°F and up"),
        _(
            "Stop heavy work unless it cannot wait. Light work only, with long rests in shade "
            "and constant watch."
        ),
    ),
]


def plan_context(crew: Crew, day: date, language: str, request=None) -> dict:
    workdays = WorkDay.objects.filter(site__crew=crew, site__active=True, date=day).select_related("site")
    site_days = [build_site_day(workday) for workday in workdays]
    return {
        "crew": crew,
        "day": day,
        "language": language,
        "site_days": site_days,
        "workers": crew.workers.filter(active=True).select_related("buddy", "site"),
        "triggers": TRIGGERS,
        "new_ramp": NEW_WORKER_RAMP,
        "returning_ramp": RETURNING_WORKER_RAMP,
        "generated_at": timezone.now().astimezone(crew.tz),
        "version_string": version_string(),
        "logo_path": _logo_uri(),
    }


def _logo_uri() -> str:
    from pathlib import Path

    found = finders.find("shadebreak/img/logo.svg")
    return Path(found).as_uri() if found else ""


def render_plan_html(crew: Crew, day: date, language: str, request=None) -> str:
    with translation.override(language), timezone.override(crew.tz):
        return render_to_string("crews/plan/heat_plan.html", plan_context(crew, day, language, request))


def render_plan_pdf(crew: Crew, day: date, language: str, request=None) -> bytes:
    from weasyprint import HTML  # imported lazily: it is heavy

    html = render_plan_html(crew, day, language, request)
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
