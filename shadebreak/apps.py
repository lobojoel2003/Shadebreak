from django.apps import AppConfig


class ShadebreakConfig(AppConfig):
    """Registers the project package so its templates, static files and
    translations ship inside the wheel."""

    name = "shadebreak"
    verbose_name = "Shadebreak"
