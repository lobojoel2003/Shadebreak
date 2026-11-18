from __future__ import annotations

from django.http import Http404, HttpRequest

from ..models import Crew

SESSION_KEY = "shadebreak_crew_id"


def current_crew(request: HttpRequest) -> Crew | None:
    user = request.user
    if not user.is_authenticated:
        return None
    crews = Crew.objects.filter(leads=user)
    crew_id = request.session.get(SESSION_KEY)
    crew = crews.filter(pk=crew_id).first() if crew_id else None
    return crew or crews.order_by("pk").first()


def require_crew(request: HttpRequest) -> Crew:
    crew = getattr(request, "crew", None)
    if crew is None:
        raise Http404("No crew")
    return crew
