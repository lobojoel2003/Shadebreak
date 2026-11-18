"""Turn a street address into coordinates with the free U.S. Census geocoder."""

from __future__ import annotations

import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def geocode(address: str) -> tuple[Decimal, Decimal] | None:
    if not address.strip() or settings.SHADEBREAK_GEOCODER != "census":
        return None
    try:
        response = requests.get(
            CENSUS_URL,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            headers={"User-Agent": settings.SHADEBREAK_NWS_USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        matches = response.json()["result"]["addressMatches"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.info("Geocoding failed for %r: %s", address, exc)
        return None
    if not matches:
        return None
    coords = matches[0]["coordinates"]
    return Decimal(str(round(coords["y"], 4))), Decimal(str(round(coords["x"], 4)))
