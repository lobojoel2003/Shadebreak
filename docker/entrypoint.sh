#!/bin/sh
# Start one Shadebreak process: web (default), worker, beat, or a manage.py command.
set -e

case "${1:-web}" in
  web)
    if [ "${SHADEBREAK_MIGRATE_ON_START:-1}" = "1" ]; then
      python manage.py migrate --noinput
    fi
    exec gunicorn shadebreak.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
      --access-logfile -
    ;;
  worker)
    exec celery -A shadebreak worker --loglevel "${CELERY_LOG_LEVEL:-info}" --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A shadebreak beat --loglevel "${CELERY_LOG_LEVEL:-info}" --schedule /tmp/celerybeat-schedule
    ;;
  manage)
    shift
    exec python manage.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
