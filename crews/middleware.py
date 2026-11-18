from django.utils import timezone

from .services.access import current_crew


class CrewMiddleware:
    """Attach the signed-in lead's crew and show times in the crew's zone."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.crew = current_crew(request)
        if request.crew is not None:
            timezone.activate(request.crew.tz)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
