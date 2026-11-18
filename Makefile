# Common tasks. Run `make help` for the list.
PYTHON ?= python
VERSION := $(shell $(PYTHON) -c "import re,pathlib;print(re.search(r'__version__ = \"(.+)\"',pathlib.Path('shadebreak/__init__.py').read_text()).group(1))")

.PHONY: help install dev demo worker beat test lint format messages plan screenshots docker release-notes

help:  ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-15s %s\n", $$1, $$2}'

install:  ## Install runtime and development dependencies
	$(PYTHON) -m pip install -r requirements-dev.txt

dev:  ## Run the development server on http://127.0.0.1:8000
	DJANGO_DEBUG=1 $(PYTHON) manage.py migrate
	DJANGO_DEBUG=1 $(PYTHON) manage.py runserver

demo:  ## Load the demo crew (sign in as demo / demo-pass-123)
	$(PYTHON) manage.py migrate
	$(PYTHON) manage.py seed_demo --password demo-pass-123

worker:  ## Run a Celery worker
	celery -A shadebreak worker --loglevel info

beat:  ## Run Celery beat (forecast refresh, reminders, escalations)
	celery -A shadebreak beat --loglevel info

test:  ## Run the test suite with coverage
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint:  ## Check style and common bugs
	ruff check .
	ruff format --check .

format:  ## Auto-format the code
	ruff format .
	ruff check --fix .

messages:  ## Refresh and compile the Spanish translation catalog
	$(PYTHON) manage.py makemessages -l es --ignore=.venv --ignore=tests --ignore=scripts --ignore=staticfiles
	$(PYTHON) manage.py compilemessages --ignore=.venv

plan:  ## Render sample heat plan PDFs into dist/
	$(PYTHON) scripts/sample_plan.py --out dist

screenshots:  ## Regenerate the README images (needs Node and Playwright)
	$(PYTHON) scripts/make_screenshots.py

docker:  ## Build the Docker image with version and build labels
	docker build --build-arg VERSION=$(VERSION) --build-arg BUILD_NUMBER=local \
	  --build-arg GIT_SHA=$$(git rev-parse HEAD) --build-arg BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
	  -t shadebreak:$(VERSION) .

release-notes:  ## Print the changelog section for the current version
	$(PYTHON) scripts/release.py notes $(VERSION)
