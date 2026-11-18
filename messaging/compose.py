"""The words of every text Shadebreak sends, in English and Spanish.

Each function renders in the recipient's language. Keep texts short and
plain: they are read on a job site, in the sun, on a small screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from django.utils import formats, translation
from django.utils.translation import gettext as _

from crews.models import Assignment, Break, CheckIn, Crew, JobSite, RiskLevel, WorkDay, Worker
from heat.units import c_to_f

MAX_LISTED_BREAKS = 6


def clock(moment: datetime, site: JobSite) -> str:
    return formats.time_format(moment.astimezone(site.tz), "TIME_FORMAT")


def day_label(workday: WorkDay) -> str:
    return formats.date_format(workday.date, "SHORT_DATE_FORMAT")


def risk_name(level: int | None) -> str:
    if level is None:
        return _("unknown")
    return str(RiskLevel(level).label)


def workload_name(workload: str) -> str:
    names = {
        "light": _("light"),
        "moderate": _("moderate"),
        "heavy": _("heavy"),
        "very_heavy": _("very heavy"),
    }
    return names.get(workload, workload)


def _breaks_for(assignment: Assignment, breaks: Sequence[Break]) -> list[tuple[datetime, int, bool]]:
    """(start, minutes, stop) for the breaks this worker takes."""
    result = []
    finish = assignment.planned_end or assignment.workday.shift_end
    for brk in breaks:
        minutes = brk.new_worker_minutes if assignment.acclimatizing else brk.minutes
        stop = brk.new_worker_stop if assignment.acclimatizing else brk.stop
        start = brk.end - timedelta(minutes=minutes)
        if minutes and start < finish:
            result.append((start, minutes, stop))
    return result


def _break_list(items: list[tuple[datetime, int, bool]], site: JobSite) -> str:
    parts = []
    for start, minutes, stop in items[:MAX_LISTED_BREAKS]:
        if stop:
            parts.append(_("%(time)s stop") % {"time": clock(start, site)})
        else:
            parts.append(_("%(time)s %(minutes)s min") % {"time": clock(start, site), "minutes": minutes})
    text = "; ".join(parts)
    if len(items) > MAX_LISTED_BREAKS:
        text += " " + _("(+%(count)s more)") % {"count": len(items) - MAX_LISTED_BREAKS}
    return text


def briefing(assignment: Assignment, breaks: Sequence[Break]) -> str:
    workday = assignment.workday
    site = workday.site
    crew = site.crew
    worker = assignment.worker
    with translation.override(worker.language):
        parts = []
        if workday.peak_risk is not None and workday.peak_risk >= RiskLevel.CAUTION:
            parts.append(
                _("Shadebreak - %(site)s, %(day)s: heat %(risk)s (peak %(wbgt)s°F WBGT at %(time)s).")
                % {
                    "site": site.name,
                    "day": day_label(workday),
                    "risk": risk_name(workday.peak_risk).upper(),
                    "wbgt": round(c_to_f(workday.peak_wbgt_c)),
                    "time": clock(workday.peak_at, site),
                }
            )
            mine = _breaks_for(assignment, breaks)
            if mine:
                parts.append(_("Rest in shade: %(breaks)s.") % {"breaks": _break_list(mine, site)})
            parts.append(_("Drink 1 cup of water every 15-20 min, even if not thirsty."))
            if (
                assignment.acclimatizing
                and assignment.planned_end
                and assignment.planned_end < workday.shift_end
            ):
                parts.append(
                    _(
                        "You are on day %(day)s of %(days)s of your heat ramp: work in the heat "
                        "until %(time)s, then shade or cool tasks."
                    )
                    % {
                        "day": assignment.acclimatization_day,
                        "days": assignment.acclimatization_days,
                        "time": clock(assignment.planned_end, site),
                    }
                )
            elif assignment.first_week:
                parts.append(_("First week on the crew: tell your lead right away if you feel sick."))
        else:
            parts.append(
                _("Shadebreak - %(site)s, %(day)s: heat %(risk)s. Keep water and shade close.")
                % {"site": site.name, "day": day_label(workday), "risk": risk_name(workday.peak_risk).upper()}
            )
        if assignment.buddy_id:
            parts.append(_("Your buddy: %(name)s.") % {"name": assignment.buddy.name})
        parts.append(_("Emergency: call %(number)s.") % {"number": crew.emergency_number})
        parts.append(_("Reply STOP to end texts."))
        return " ".join(parts)


def lead_briefing(workday: WorkDay) -> str:
    site = workday.site
    crew = site.crew
    with translation.override(crew.language):
        if workday.peak_risk is None:
            return _("Shadebreak %(day)s - %(site)s: no forecast yet. Open the app to check.") % {
                "day": day_label(workday),
                "site": site.name,
            }
        parts = [
            _(
                "Shadebreak %(day)s - %(site)s: heat %(risk)s, peak %(wbgt)s°F WBGT / "
                "heat index %(hi)s°F at %(time)s."
            )
            % {
                "day": day_label(workday),
                "site": site.name,
                "risk": risk_name(workday.peak_risk).upper(),
                "wbgt": round(c_to_f(workday.peak_wbgt_c)),
                "hi": round(workday.peak_heat_index_f),
                "time": clock(workday.peak_at, site),
            }
        ]
        crew_breaks = [(b.start, b.minutes, b.stop) for b in workday.breaks.all() if b.minutes]
        if crew_breaks:
            parts.append(_("Crew breaks: %(breaks)s.") % {"breaks": _break_list(crew_breaks, site)})
        assignments = [a for a in workday.assignments.select_related("worker", "buddy") if a.present]
        ramping = [a for a in assignments if a.needs_extra_care]
        if ramping:
            names = []
            for a in ramping:
                if a.acclimatizing and a.planned_end and a.planned_end < workday.shift_end:
                    names.append(
                        _("%(name)s (day %(day)s, until %(time)s)")
                        % {
                            "name": a.worker.name,
                            "day": a.acclimatization_day,
                            "time": clock(a.planned_end, site),
                        }
                    )
                else:
                    names.append(a.worker.name)
            parts.append(_("New or ramping up: %(names)s.") % {"names": ", ".join(names)})
        pairs = _pairs(assignments)
        if pairs:
            parts.append(_("Buddies: %(pairs)s.") % {"pairs": ", ".join(pairs)})
        return " ".join(parts)


def _pairs(assignments: Sequence[Assignment]) -> list[str]:
    seen: set[int] = set()
    pairs = []
    for a in assignments:
        if a.worker_id in seen or not a.buddy_id:
            continue
        seen.add(a.worker_id)
        if any(b.worker_id == a.buddy_id and b.buddy_id == a.worker_id for b in assignments):
            seen.add(a.buddy_id)
            pairs.append(f"{a.worker.first_name}+{a.buddy.first_name}")
        else:
            pairs.append(f"{a.buddy.first_name}>{a.worker.first_name}")
    return pairs


def break_reminder(assignment: Assignment, minutes: int, until: datetime, stop: bool) -> str:
    site = assignment.workday.site
    with translation.override(assignment.worker.language):
        if stop:
            return _(
                "Shadebreak: too hot for %(workload)s work until %(time)s. Stop or switch to light "
                "tasks in the shade. Drink water."
            ) % {"workload": workload_name(site.workload), "time": clock(until, site)}
        return _("Shadebreak: rest break now, %(minutes)s min in the shade until %(time)s. Drink water.") % {
            "minutes": minutes,
            "time": clock(until, site),
        }


def water_reminder(worker: Worker, risk: int) -> str:
    with translation.override(worker.language):
        return _("Shadebreak: water check. Drink a cup now, even if you are not thirsty. Heat: %(risk)s.") % {
            "risk": risk_name(risk)
        }


def checkin_prompt(checkins: Sequence[CheckIn], language: str, to_lead: bool) -> str:
    """Ask a buddy (or the crew lead) to look at one or more workers now."""
    if isinstance(checkins, CheckIn):
        checkins = [checkins]
    crew = checkins[0].workday.site.crew
    names = [c.worker.name for c in checkins]
    with translation.override(language):
        listed = _join_names(names)
        if to_lead:
            return _(
                "Shadebreak check-in: %(worker)s has no buddy on site. Check on them now. "
                "Reply 1 if OK, 2 if they need help."
            ) % {"worker": listed}
        if len(names) > 1:
            return _(
                "Shadebreak check-in: look at %(workers)s now. Reply 1 if all are OK, "
                "2 if anyone needs help. Danger signs: confusion, slurred speech, fainting, "
                "hot dry skin - call %(number)s."
            ) % {"workers": listed, "number": crew.emergency_number}
        return _(
            "Shadebreak check-in: look at %(worker)s now. Reply 1 if OK, 2 if they need help. "
            "Danger signs: confusion, slurred speech, fainting, hot dry skin - call %(number)s."
        ) % {"worker": listed, "number": crew.emergency_number}


def _join_names(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return _("%(names)s and %(last)s") % {"names": ", ".join(names[:-1]), "last": names[-1]}


def missed_checkin_alert(checkin: CheckIn) -> str:
    site = checkin.workday.site
    with translation.override(site.crew.language):
        asked = checkin.buddy.name if checkin.buddy_id else _("you")
        return _(
            "Shadebreak ALERT: no reply to the %(time)s check-in on %(worker)s at %(site)s "
            "(asked: %(buddy)s). Check on %(worker)s now."
        ) % {
            "time": clock(checkin.due_at, site),
            "worker": checkin.worker.name,
            "site": site.name,
            "buddy": asked,
        }


def help_alert(crew: Crew, worker: Worker, reporter: Worker | None, site: JobSite | None) -> str:
    with translation.override(crew.language):
        place = site.name if site else crew.name
        if reporter is None or reporter.pk == worker.pk:
            return _(
                "Shadebreak URGENT: %(worker)s texted for help at %(site)s. Call them now: %(phone)s. "
                "If confused, fainting or not sweating: call %(number)s."
            ) % {
                "worker": worker.name,
                "site": place,
                "phone": worker.phone_display,
                "number": crew.emergency_number,
            }
        return _(
            "Shadebreak URGENT: %(reporter)s says %(worker)s needs help at %(site)s. Go now. If confused, "
            "fainting or not sweating: call %(number)s and cool them with cold water or ice."
        ) % {"reporter": reporter.name, "worker": worker.name, "site": place, "number": crew.emergency_number}


def ok_update(crew: Crew, worker: Worker, reporter: Worker | None) -> str:
    with translation.override(crew.language):
        return _("Shadebreak update: %(reporter)s says %(worker)s is OK.") % {
            "reporter": reporter.name if reporter else _("Someone"),
            "worker": worker.name,
        }


def ack_ok(language: str, names: Sequence[str]) -> str:
    with translation.override(language):
        return _("Thanks. Logged: %(names)s OK.") % {"names": ", ".join(names)}


def ack_help(language: str, names: Sequence[str], emergency: str) -> str:
    with translation.override(language):
        return _(
            "Alert sent to your crew lead. Stay with %(names)s, get to shade and cool off with water. "
            "Call %(number)s for confusion, fainting or vomiting."
        ) % {"names": ", ".join(names), "number": emergency}


def ack_self_help(language: str, emergency: str) -> str:
    with translation.override(language):
        return _(
            "Alert sent to your crew lead. Stop work, get to shade and drink water. "
            "If you feel confused or faint, call %(number)s."
        ) % {"number": emergency}


def opted_out(language: str) -> str:
    with translation.override(language):
        return _("Shadebreak: you will not get more texts. Reply START to turn them back on.")


def opted_in(language: str) -> str:
    with translation.override(language):
        return _("Shadebreak: texts are on. Reply STOP to turn them off.")


def help_text(language: str, emergency: str) -> str:
    with translation.override(language):
        return _(
            "Shadebreak heat-safety texts. Reply 1 = OK, 2 = needs help, STOP = end texts. "
            "Emergency: call %(number)s."
        ) % {"number": emergency}
