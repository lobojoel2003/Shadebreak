from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CrewsConfig(AppConfig):
    name = "crews"
    verbose_name = _("Crews and job sites")
