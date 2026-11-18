# Changelog

All notable changes to Shadebreak are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-18

The first release: a crew lead adds job sites and workers, and Shadebreak
plans every hot day around the National Weather Service forecast.

### Added

- **Forecasts:** hourly National Weather Service grid forecasts (api.weather.gov)
  for every job site, refreshed hourly by Celery beat, with retries for the
  API's brief outages and automatic re-lookup when an office re-grids.
- **Heat rating:** NWS heat index plus wet bulb globe temperature (WBGT)
  estimated with the Liljegren method (ECMWF `thermofeel`), using sunlight
  modeled from solar position and forecast sky cover. Sites can be full sun,
  partly shaded or mostly shaded. Each hour is rated Low, Caution, High,
  Very high or Extreme on the higher of the two scales.
- **Breaks:** work/rest cycles from the ACGIH TLV (crew) and Action Limit
  (new workers) for the site's workload and clothing, with ACGIH's
  metabolic-rate equations filling the table's blank continuous-work cells;
  a 15-minute rest before anyone passes two hours of work at High heat;
  "stop" blocks when even 45 minutes of rest an hour is not enough.
- **Acclimatization:** the NIOSH ramp for new workers (20/40/60/80/100%) and
  for experienced or returning workers (50/60/80/100%). Only hot days count,
  the ramp restarts after time away, and only hot hours are reduced, so new
  workers can still work a cool morning. First-week workers are flagged.
- **Buddies and check-ins:** automatic pairing (new workers with experienced
  ones), buddy check-ins by text every 1–2 hours depending on heat and when a
  worker comes off the heat, one text per buddy, safety-first reading of
  replies (`1` OK, `2`/`help`/`ayuda` needs help), and alerts to the crew lead
  for help requests and unanswered check-ins.
- **Text messages:** morning briefings, break and water reminders, check-ins
  and alerts in English and Spanish, with `STOP`/`START` handling. Pluggable
  backends: console, Twilio (REST, signed webhooks) and any HTTP SMS gateway.
  Spanish texts are folded to the GSM-7 alphabet to keep them in 160-character
  segments.
- **Morning screen:** a mobile-first dashboard (HTMX) with a colored hourly
  risk strip, break timeline, crew list with first-week badges and reduced
  hours, and one-tap check-in marking.
- **Written heat plan:** a printable PDF (WeasyPrint) with triggers, hourly
  forecast, breaks, roster and hours in the heat, buddy pairs, acclimatization
  tables, warning signs and first aid, emergency steps and a sign-off sheet,
  in English or Spanish.
- **English and Spanish** throughout the app, the texts and the plan.
- Crew, site and worker management, U.S. Census address lookup, "use my
  location", per-day roster changes and exposure overrides.
- `seed_demo` management command with a labelled sample forecast.
- Docker image (non-root, health check), Docker Compose stack with Postgres,
  Redis, Celery worker and beat.
- CI (lint, tests on Postgres for Python 3.12 and 3.13, deploy checks,
  package and Docker smoke tests), CodeQL, Dependabot, and a tag-driven
  release workflow that publishes versioned images to GHCR and a GitHub
  release with the wheel, sdist, sample heat plans and checksums.

[Unreleased]: https://github.com/lobojoel2003/Shadebreak/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/lobojoel2003/Shadebreak/releases/tag/v1.0.0
