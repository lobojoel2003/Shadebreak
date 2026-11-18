# Contributing to Shadebreak

Thanks for helping keep outdoor workers safe. Bug reports, translations,
field feedback from crew leads and code are all welcome.

## Getting set up

```bash
python -m venv .venv && . .venv/bin/activate
```

```bash
make install
```

```bash
make demo && make dev
```

Then open http://127.0.0.1:8000 and sign in as `demo` / `demo-pass-123`.
WeasyPrint needs Pango (`apt install libpango-1.0-0 libpangoft2-1.0-0` on
Debian/Ubuntu, `brew install pango` on macOS), and `make messages` needs
GNU gettext.

## Before you open a pull request

* `make lint` and `make test` pass. CI also runs the tests on Postgres.
* New behavior has tests. Heat rules (`heat/`) are pure functions and should
  be tested directly.
* Changes to how risk, breaks, ramps or check-ins are calculated cite their
  source in the code and in [`docs/heat-science.md`](docs/heat-science.md).
* Every new user-facing string is wrapped for translation (`{% translate %}`,
  `gettext`) and has a Spanish translation (`make messages`, then edit
  `shadebreak/locale/es/LC_MESSAGES/django.po`). Keep Spanish in the formal
  *usted* form, plain and short.
* Text messages stay short: aim for one or two SMS segments.
* Add an entry under `## [Unreleased]` in `CHANGELOG.md`.

## Style

* Python is formatted and linted with Ruff (`make format`).
* Templates are mobile-first; check a 390 px wide screen first.
* No build step for CSS or JavaScript; HTMX is vendored in `shadebreak/static`.

## Releases

See [`docs/releasing.md`](docs/releasing.md).
