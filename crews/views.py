from __future__ import annotations

from datetime import date, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from nws import NWSClient, NWSError
from shadebreak.version import build_info

from .forms import AssignmentForm, CrewForm, SignupForm, SiteForm, WorkerForm
from .models import Assignment, CheckIn, Crew, JobSite, WorkDay, Worker
from .services.access import SESSION_KEY
from .services.dashboard import build_site_day
from .services.forecasts import refresh_site_forecast, rerate_site
from .services.planning import ensure_scheduled_workdays, ensure_workday, plan_site_days, plan_workday


def crew_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.crew is None:
            return redirect("onboarding")
        return view(request, *args, **kwargs)

    return wrapper


def interactive_client() -> NWSClient:
    """A client that gives up quickly so a button press never hangs."""
    return NWSClient(settings.SHADEBREAK_NWS_USER_AGENT, timeout=8, retries=2, backoff=0.5)


def _day_from(request, crew: Crew) -> date:
    text = request.GET.get("date") or request.POST.get("date")
    if text:
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    return crew.today()


def _refresh(request, site: JobSite) -> bool:
    try:
        refresh_site_forecast(site, interactive_client())
    except NWSError as exc:
        messages.warning(
            request, _("Could not reach the National Weather Service: %(error)s") % {"error": exc}
        )
        return False
    return True


# Dashboard ---------------------------------------------------------------


@crew_required
def dashboard(request):
    crew = request.crew
    day = _day_from(request, crew)
    today = crew.today()
    sites = list(crew.sites.filter(active=True))
    site_days, off_sites = [], []
    for site in sites:
        workday = ensure_scheduled_workdays(site, day)
        if workday is None:
            off_sites.append(site)
            continue
        if workday.planned_at is None or (
            day >= today and site.forecast_updated_at and workday.planned_at < site.forecast_updated_at
        ):
            plan_workday(workday)
        site_days.append(build_site_day(workday))
    return render(
        request,
        "crews/dashboard.html",
        {
            "day": day,
            "is_today": day == today,
            "previous_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
            "site_days": site_days,
            "off_sites": off_sites,
            "has_sites": bool(sites),
            "has_workers": crew.workers.filter(active=True).exists(),
            "nav": "today",
        },
    )


def _workday_for(request, pk: int) -> WorkDay:
    return get_object_or_404(WorkDay.objects.select_related("site__crew"), pk=pk, site__crew=request.crew)


def _card_response(request, workday: WorkDay):
    workday.refresh_from_db()
    context = {"sd": build_site_day(workday), "detail": request.POST.get("detail") == "1"}
    return render(request, "crews/_site_card.html", context)


@crew_required
def workday_detail(request, pk: int):
    workday = _workday_for(request, pk)
    if workday.planned_at is None:
        plan_workday(workday)
    assigned = workday.assignments.values_list("worker_id", flat=True)
    return render(
        request,
        "crews/workday.html",
        {
            "sd": build_site_day(workday),
            "detail": True,
            "available": request.crew.workers.filter(active=True).exclude(pk__in=assigned),
            "forms": [
                (a, AssignmentForm(instance=a, prefix=f"a{a.pk}"))
                for a in workday.assignments.select_related("worker", "buddy")
            ],
            "nav": "today",
        },
    )


@crew_required
@require_POST
def workday_refresh(request, pk: int):
    workday = _workday_for(request, pk)
    if _refresh(request, workday.site):
        plan_site_days(workday.site, days=settings.SHADEBREAK_FORECAST_DAYS)
    plan_workday(workday)
    if request.htmx:
        return _card_response(request, workday)
    return redirect(request.POST.get("next") or "dashboard")


@crew_required
@require_POST
def workday_add_worker(request, pk: int):
    workday = _workday_for(request, pk)
    worker = get_object_or_404(Worker, pk=request.POST.get("worker"), crew=request.crew)
    Assignment.objects.get_or_create(workday=workday, worker=worker)
    plan_workday(workday)
    messages.success(request, _("%(name)s added to the day.") % {"name": worker.name})
    return redirect(workday)


@crew_required
@require_POST
def assignment_update(request, pk: int):
    assignment = get_object_or_404(
        Assignment.objects.select_related("workday__site__crew", "worker"),
        pk=pk,
        workday__site__crew=request.crew,
    )
    if request.POST.get("remove") == "1":
        workday = assignment.workday
        assignment.delete()
        plan_workday(workday)
        return redirect(workday)
    form = AssignmentForm(request.POST, instance=assignment, prefix=f"a{assignment.pk}")
    if form.is_valid():
        form.save()
        plan_workday(assignment.workday)
        messages.success(request, _("Saved changes for %(name)s.") % {"name": assignment.worker.name})
    else:
        messages.error(request, _("Could not save: %(errors)s") % {"errors": form.errors.as_text()})
    return redirect(assignment.workday)


@crew_required
@require_POST
def checkin_update(request, pk: int):
    checkin = get_object_or_404(
        CheckIn.objects.select_related("workday__site__crew", "worker"),
        pk=pk,
        workday__site__crew=request.crew,
    )
    status = request.POST.get("status")
    if status in (CheckIn.Status.OK, CheckIn.Status.HELP):
        checkin.status = status
        checkin.responded_at = timezone.now()
        checkin.response = _("Marked in the app")
        checkin.save(update_fields=["status", "responded_at", "response"])
    if request.htmx:
        return render(request, "crews/_checkin.html", {"checkin": checkin, "site": checkin.workday.site})
    return redirect(checkin.workday)


# Workers -------------------------------------------------------------------


@crew_required
def worker_list(request):
    crew = request.crew
    today = crew.today()
    workers = crew.workers.select_related("site", "buddy").order_by("-active", "name")
    todays = {
        a.worker_id: a
        for a in Assignment.objects.filter(workday__site__crew=crew, workday__date=today).select_related(
            "workday__site"
        )
    }
    rows = [(w, todays.get(w.pk)) for w in workers]
    return render(request, "crews/workers.html", {"rows": rows, "today": today, "nav": "crew"})


@crew_required
def worker_form(request, pk: int | None = None):
    crew = request.crew
    worker = get_object_or_404(Worker, pk=pk, crew=crew) if pk else None
    form = WorkerForm(request.POST or None, instance=worker, crew=crew)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        _replan_upcoming(crew)
        messages.success(request, _("Saved %(name)s.") % {"name": saved.name})
        return redirect("worker_list")
    return render(request, "crews/worker_form.html", {"form": form, "worker": worker, "nav": "crew"})


@crew_required
@require_POST
def worker_deactivate(request, pk: int):
    worker = get_object_or_404(Worker, pk=pk, crew=request.crew)
    worker.active = False
    worker.save(update_fields=["active"])
    Worker.objects.filter(buddy=worker).update(buddy=None)
    messages.success(request, _("%(name)s is no longer on the active crew.") % {"name": worker.name})
    return redirect("worker_list")


# Sites ---------------------------------------------------------------------


@crew_required
def site_list(request):
    sites = request.crew.sites.annotate(regular_count=Count("regulars", filter=Q(regulars__active=True)))
    return render(request, "crews/sites.html", {"sites": sites.order_by("-active", "name"), "nav": "sites"})


@crew_required
def site_form(request, pk: int | None = None):
    crew = request.crew
    site = get_object_or_404(JobSite, pk=pk, crew=crew) if pk else None
    before = (site.exposure, site.latitude, site.longitude) if site else None
    form = SiteForm(request.POST or None, instance=site, crew=crew)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        moved = before is None or (before[1], before[2]) != (saved.latitude, saved.longitude)
        if moved:
            saved.forecasts.all().delete()
            _refresh(request, saved)
        elif before[0] != saved.exposure:
            rerate_site(saved)
        for workday in saved.workdays.filter(date__gte=crew.today()):
            workday.start_time, workday.end_time = saved.shift_start, saved.shift_end
            workday.save(update_fields=["start_time", "end_time"])
        plan_site_days(saved, days=settings.SHADEBREAK_FORECAST_DAYS)
        messages.success(request, _("Saved %(name)s.") % {"name": saved.name})
        return redirect("site_list")
    return render(request, "crews/site_form.html", {"form": form, "site": site, "nav": "sites"})


@crew_required
@require_POST
def site_deactivate(request, pk: int):
    site = get_object_or_404(JobSite, pk=pk, crew=request.crew)
    site.active = False
    site.save(update_fields=["active"])
    messages.success(request, _("%(name)s is archived.") % {"name": site.name})
    return redirect("site_list")


@crew_required
@require_POST
def site_schedule_day(request, pk: int):
    site = get_object_or_404(JobSite, pk=pk, crew=request.crew)
    day = _day_from(request, request.crew)
    workday, _created = ensure_workday(site, day)
    plan_workday(workday)
    return redirect(workday)


def _replan_upcoming(crew: Crew) -> None:
    for workday in WorkDay.objects.filter(site__crew=crew, date__gte=crew.today()):
        plan_workday(workday)


# Crew settings, signup -----------------------------------------------------


@crew_required
def crew_settings(request):
    form = CrewForm(request.POST or None, instance=request.crew)
    if request.method == "POST" and form.is_valid():
        form.save()
        _replan_upcoming(request.crew)
        messages.success(request, _("Crew settings saved."))
        return redirect("crew_settings")
    return render(request, "crews/settings.html", {"form": form, "nav": "settings"})


@login_required
@require_POST
def switch_crew(request):
    crew = get_object_or_404(Crew, pk=request.POST.get("crew"), leads=request.user)
    request.session[SESSION_KEY] = crew.pk
    return redirect("dashboard")


def signup(request):
    if not settings.SHADEBREAK_ALLOW_SIGNUP:
        raise Http404
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, _("Welcome! Add your first job site to get today's heat plan."))
        return redirect("site_create")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def onboarding(request):
    if request.crew is not None:
        return redirect("dashboard")
    form = CrewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        crew = form.save()
        crew.leads.add(request.user)
        return redirect("site_create")
    return render(request, "crews/onboarding.html", {"form": form})


# Heat plan -----------------------------------------------------------------


@crew_required
def heat_plan(request):
    from .plan import plan_context, render_plan_pdf

    crew = request.crew
    day = _day_from(request, crew)
    language = request.GET.get("lang") or crew.language
    if language not in dict(settings.LANGUAGES):
        language = crew.language
    for site in crew.sites.filter(active=True):
        workday = ensure_scheduled_workdays(site, day)
        if workday and workday.planned_at is None:
            plan_workday(workday)
    if request.GET.get("format") == "html":
        with translation.override(language):
            return render(request, "crews/plan/heat_plan.html", plan_context(crew, day, language, request))
    pdf = render_plan_pdf(crew, day, language, request)
    response = HttpResponse(pdf, content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="shadebreak-heat-plan-{day.isoformat()}-{language}.pdf"'
    )
    return response


@crew_required
def plan_page(request):
    crew = request.crew
    return render(request, "crews/plan_page.html", {"day": _day_from(request, crew), "nav": "plan"})


# Operations ----------------------------------------------------------------


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        return JsonResponse({"status": "error", "detail": str(exc)}, status=503)
    return JsonResponse({"status": "ok", **build_info()})


def version(request):
    return JsonResponse(build_info())
