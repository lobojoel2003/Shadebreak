from __future__ import annotations

import contextlib
import logging

from celery import shared_task
from django.conf import settings

from nws import NWSError

from .models import JobSite
from .services.forecasts import refresh_site_forecast
from .services.planning import plan_site_days

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def refresh_site(site_id: int) -> None:
    site = JobSite.objects.select_related("crew").filter(pk=site_id, active=True).first()
    if site is None:
        return
    with contextlib.suppress(NWSError):  # errors are recorded on the site; plan with what we have
        refresh_site_forecast(site)
    plan_site_days(site, days=settings.SHADEBREAK_FORECAST_DAYS)


@shared_task(ignore_result=True)
def refresh_all_sites() -> None:
    """Hourly: pull forecasts for every active site and re-plan its days."""
    site_ids = list(JobSite.objects.filter(active=True).values_list("pk", flat=True))
    for index, site_id in enumerate(site_ids):
        # Spread requests out a little; NWS asks clients to be gentle.
        refresh_site.apply_async(args=[site_id], countdown=min(index * 2, 600))
    logger.info("Queued forecast refresh for %d sites", len(site_ids))
