# Deploying Shadebreak

Shadebreak runs as four processes that share one Postgres database and one
Redis instance:

| Process | Command | What it does |
| --- | --- | --- |
| `web` | `gunicorn shadebreak.wsgi` | The crew lead's app and the SMS webhooks |
| `worker` | `celery -A shadebreak worker` | Pulls forecasts, plans days, sends texts |
| `beat` | `celery -A shadebreak beat` | The clock: hourly forecasts, texts every minute, escalations every 2 minutes |
| `db`, `redis` | Postgres 16, Redis 7 | Storage and the task queue |

The Docker image runs any of them: `docker run IMAGE web|worker|beat|manage <command>`.

## Docker Compose (one server)

```bash
git clone https://github.com/lobojoel2003/Shadebreak.git && cd Shadebreak
cp .env.example .env
```

Edit `.env`: set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `POSTGRES_PASSWORD` and
`SHADEBREAK_NWS_USER_AGENT` (the National Weather Service asks for a way to
contact you). Then:

```bash
docker compose up -d
```

```bash
docker compose exec web python manage.py createsuperuser
```

Put a TLS-terminating proxy (Caddy, nginx, Traefik, a cloud load balancer) in
front of port 8000 and keep `DJANGO_BEHIND_PROXY=1`. A minimal Caddyfile:

```
shadebreak.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

To pin a release instead of `latest`, set `SHADEBREAK_TAG=1.0.0` in `.env`.

### Upgrading

```bash
docker compose pull && docker compose up -d
```

The `web` container runs database migrations on start
(`SHADEBREAK_MIGRATE_ON_START=1`). With more than one web replica, turn that
off and run `docker compose run --rm web manage migrate` once per upgrade.

### Backups

```bash
docker compose exec db pg_dump -U shadebreak shadebreak | gzip > shadebreak-$(date +%F).sql.gz
```

## Platform-as-a-service

Any platform that runs a container with a Postgres and a Redis add-on works
(Fly.io, Render, Railway, Heroku-style hosts, Kubernetes). Run three services
from the same image with the commands `web`, `worker` and `beat`, and set
`DATABASE_URL`, `CELERY_BROKER_URL`, `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS` and `DJANGO_BEHIND_PROXY=1`. Run exactly **one** `beat`.

## Without Celery

For a very small install you can skip the worker and beat and use cron:

```cron
*/1 * * * *  cd /srv/shadebreak && python manage.py shell -c "from messaging.tasks import send_due_messages, escalate_missed_checkins; send_due_messages(); escalate_missed_checkins()"
7 * * * *    cd /srv/shadebreak && CELERY_TASK_ALWAYS_EAGER=1 python manage.py shell -c "from crews.tasks import refresh_all_sites; refresh_all_sites()"
```

## Settings

Every setting is an environment variable; `.env.example` lists them all with
comments. The important ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | none (required in production) | Django signing key |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names the app answers to |
| `DATABASE_URL` | SQLite file | Postgres URL in production |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis for Celery |
| `SHADEBREAK_NWS_USER_AGENT` | `Shadebreak/<version> (+repo URL)` | Identify yourself to the NWS API |
| `SHADEBREAK_SMS_BACKEND` | console | Where texts go (see [SMS](sms.md)) |
| `SHADEBREAK_PUBLIC_URL` | empty | Public base URL, for Twilio signature checks behind proxies |
| `SHADEBREAK_ACCLIMATIZATION_GAP_DAYS` | `7` | Days away before the returning ramp restarts |
| `SHADEBREAK_CHECKIN_GRACE_MINUTES` | `15` | Wait before alerting the crew lead |
| `SHADEBREAK_ALLOW_SIGNUP` | `1` | Let new crew leads sign up |

## Health and version

* `GET /healthz` checks the database and returns version and build.
* `GET /version` returns `{"version", "build", "commit", "date"}`; the same
  appears in the footer of every page and the heat plan PDF.
