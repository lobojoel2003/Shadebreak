import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shadebreak.settings")

app = Celery("shadebreak")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
