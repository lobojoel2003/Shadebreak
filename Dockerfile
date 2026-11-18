# syntax=docker/dockerfile:1.7
# Shadebreak production image: Django + Gunicorn, Celery worker and beat.
FROM python:3.15-slim

ARG VERSION=dev
ARG BUILD_NUMBER=dev
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="Shadebreak" \
      org.opencontainers.image.description="Heat-illness prevention for small outdoor crews" \
      org.opencontainers.image.url="https://github.com/lobojoel2003/shadebreak" \
      org.opencontainers.image.source="https://github.com/lobojoel2003/shadebreak" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      io.shadebreak.build-number="${BUILD_NUMBER}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=shadebreak.settings \
    SHADEBREAK_ENV=production \
    SHADEBREAK_BUILD_NUMBER=${BUILD_NUMBER} \
    SHADEBREAK_GIT_SHA=${GIT_SHA} \
    SHADEBREAK_BUILD_DATE=${BUILD_DATE} \
    PORT=8000

# WeasyPrint needs Pango and HarfBuzz; DejaVu covers English and Spanish.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only-not-secret python manage.py collectstatic --noinput --verbosity 0 \
    && useradd --create-home --uid 10001 shadebreak \
    && chown -R shadebreak:shadebreak /app

USER shadebreak
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["python", "docker/healthcheck.py"]
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
