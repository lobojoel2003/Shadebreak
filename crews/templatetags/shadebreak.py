from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from django import template
from django.utils import formats, timezone
from django.utils.translation import get_language

from crews.models import RiskLevel
from crews.phones import display_phone
from crews.services.dashboard import RISK_SLUGS
from heat.units import c_to_f

register = template.Library()


@register.filter
def risk_slug(level) -> str:
    if level is None or level == "":
        return "unknown"
    return RISK_SLUGS.get(int(level), "unknown")


@register.filter
def risk_label(level) -> str:
    if level is None or level == "":
        return ""
    return str(RiskLevel(int(level)).label)


@register.filter(name="f")
def fahrenheit(celsius) -> str:
    if celsius is None or celsius == "":
        return ""
    return str(round(c_to_f(float(celsius))))


def _tz(site):
    return site.tz if site is not None and hasattr(site, "tz") else timezone.get_current_timezone()


@register.filter
def local(moment: datetime | None, site=None) -> str:
    """Clock time in the site's time zone, in the active language's format."""
    if not moment:
        return ""
    return formats.time_format(moment.astimezone(_tz(site)), "TIME_FORMAT")


@register.simple_tag
def time_range(start: datetime, end: datetime, site=None) -> str:
    """'6:15–6:30 AM' rather than '6:15 AM–6:30 AM' when both share AM/PM."""
    first, second = local(start, site), local(end, site)
    first_parts, second_parts = first.rsplit(" ", 1), second.rsplit(" ", 1)
    if len(first_parts) == 2 and len(second_parts) == 2 and first_parts[1] == second_parts[1]:
        first = first_parts[0]
    return f"{first}–{second}"


@register.filter
def hour_number(moment: datetime, site=None) -> str:
    local_time = moment.astimezone(_tz(site))
    return str(local_time.hour % 12 or 12)


@register.filter
def meridiem(moment: datetime, site=None) -> str:
    return "AM" if moment.astimezone(_tz(site)).hour < 12 else "PM"


@register.filter
def phone(value: str) -> str:
    return display_phone(value)


@register.filter
def minutes_between(end: datetime, start: datetime) -> int:
    return int((end - start).total_seconds() // 60)


@register.simple_tag(takes_context=True)
def query(context, **params) -> str:
    request = context["request"]
    data = request.GET.copy()
    for key, value in params.items():
        if value in (None, ""):
            data.pop(key, None)
        else:
            data[key] = value
    return "?" + urlencode(data, doseq=True) if data else "?"


@register.simple_tag
def current_language() -> str:
    return get_language() or "en"
