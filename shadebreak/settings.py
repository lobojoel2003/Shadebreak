"""Django settings for Shadebreak.

Everything that changes between environments is read from environment
variables; see ``.env.example`` for the full list.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from . import __version__

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


TESTING = env_bool("SHADEBREAK_TESTING", "pytest" in sys.modules or sys.argv[1:2] == ["test"])
DEBUG = env_bool("DJANGO_DEBUG", False)
PRODUCTION = env("SHADEBREAK_ENV", "development") == "production"

_DEV_SECRET = "django-insecure-shadebreak-development-key-change-me"  # noqa: S105
SECRET_KEY = env("DJANGO_SECRET_KEY") or _DEV_SECRET
if PRODUCTION and SECRET_KEY == _DEV_SECRET:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when SHADEBREAK_ENV=production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
if TESTING:
    ALLOWED_HOSTS.append("testserver")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "shadebreak",
    "crews",
    "messaging",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "crews.middleware.CrewMiddleware",
]

ROOT_URLCONF = "shadebreak.urls"
WSGI_APPLICATION = "shadebreak.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "shadebreak.context_processors.shadebreak",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DJANGO_DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Internationalization: English and Spanish from the start.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("es", _("Spanish"))]
LOCALE_PATHS = [BASE_DIR / "shadebreak" / "locale"]
FORMAT_MODULE_PATH = ["shadebreak.formats"]
USE_I18N = True
TIME_ZONE = "UTC"
USE_TZ = True
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Security. Turn these on behind HTTPS (the Docker image does by default).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("DJANGO_BEHIND_PROXY") else None
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", PRODUCTION)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # crew leads stay signed in on their phone

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"weasyprint": {"level": "ERROR"}, "fontTools": {"level": "ERROR"}},
}

# Celery: Redis broker, beat schedule for forecasts, plans and reminders.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", env("REDIS_URL", "redis://localhost:6379/0"))
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", TESTING)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "UTC"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "refresh-forecasts-and-plans": {
        "task": "crews.tasks.refresh_all_sites",
        "schedule": crontab(minute="7"),  # NWS grids update roughly hourly
    },
    "send-due-messages": {
        "task": "messaging.tasks.send_due_messages",
        "schedule": 60.0,
    },
    "escalate-missed-check-ins": {
        "task": "messaging.tasks.escalate_missed_checkins",
        "schedule": 120.0,
    },
}

# Shadebreak
SHADEBREAK_VERSION = __version__
SHADEBREAK_NWS_USER_AGENT = env(
    "SHADEBREAK_NWS_USER_AGENT",
    f"Shadebreak/{__version__} (+https://github.com/lobojoel2003/shadebreak)",
)
SHADEBREAK_GEOCODER = env("SHADEBREAK_GEOCODER", "census")  # "census" or "" to disable
SHADEBREAK_ALLOW_SIGNUP = env_bool("SHADEBREAK_ALLOW_SIGNUP", True)
SHADEBREAK_PUBLIC_URL = env("SHADEBREAK_PUBLIC_URL").rstrip("/")
SHADEBREAK_ACCLIMATIZATION_GAP_DAYS = env_int("SHADEBREAK_ACCLIMATIZATION_GAP_DAYS", 7)
SHADEBREAK_CHECKIN_GRACE_MINUTES = env_int("SHADEBREAK_CHECKIN_GRACE_MINUTES", 15)
SHADEBREAK_BRIEFING_LEAD_MINUTES = env_int("SHADEBREAK_BRIEFING_LEAD_MINUTES", 30)
SHADEBREAK_FORECAST_DAYS = env_int("SHADEBREAK_FORECAST_DAYS", 2)

# SMS: a dotted path to a backend class. Built in: console, locmem, twilio, gateway.
SHADEBREAK_SMS_BACKEND = env(
    "SHADEBREAK_SMS_BACKEND",
    "messaging.backends.locmem.LocmemBackend" if TESTING else "messaging.backends.console.ConsoleBackend",
)
SHADEBREAK_SMS_FROM = env("SHADEBREAK_SMS_FROM")
SHADEBREAK_SMS_FOLD_ACCENTS = env_bool("SHADEBREAK_SMS_FOLD_ACCENTS", True)
SHADEBREAK_SMS_INBOUND_TOKEN = env("SHADEBREAK_SMS_INBOUND_TOKEN")
SHADEBREAK_SMS_GATEWAY_URL = env("SHADEBREAK_SMS_GATEWAY_URL")
SHADEBREAK_SMS_GATEWAY_TOKEN = env("SHADEBREAK_SMS_GATEWAY_TOKEN")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = env("TWILIO_MESSAGING_SERVICE_SID")
