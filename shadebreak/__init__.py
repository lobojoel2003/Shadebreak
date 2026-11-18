"""Shadebreak: heat-illness prevention for small outdoor crews."""

__version__ = "1.0.0"

from .celery import app as celery_app

__all__ = ["__version__", "celery_app"]
