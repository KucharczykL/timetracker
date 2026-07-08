all: css migrate

initialize: npm css migrate loadplatforms

PYTHON_VERSION = 3.14

# Ensure a usable CPython 3.14 exists for uv before any target that needs it.
# Fast no-op when one is already available (a Nix shell puts it on PATH; a
# provisioned .venv counts too). Otherwise try uv's own downloader, and only if
# THAT can't reach the interpreter — e.g. the Claude Code cloud sandbox blocks
# the python-build-standalone download on github — stop with a pointer to the
# bootstrap script instead of failing cryptically deep inside uv/pytest.
ensure-python:
	@uv python find '>=3.14,<4' >/dev/null 2>&1 && exit 0; \
	test -x .venv/bin/python && exit 0; \
	uv python install $(PYTHON_VERSION) && exit 0; \
	echo "==> Python $(PYTHON_VERSION) is required but couldn't be provisioned here."; \
	echo "    (In the Claude Code cloud sandbox the interpreter download is blocked.)"; \
	echo "    Run  ./scripts/bootstrap-cloud-env.sh  then retry your make target."; \
	exit 1

npm:
	pnpm install

css: common/input.css
	pnpm tailwindcss -i ./common/input.css -o  ./games/static/base.css

makemigrations:
	uv run --frozen python manage.py makemigrations

migrate: makemigrations
	uv run --frozen python manage.py migrate

init: ensure-python
	uv sync
	pnpm install
	$(MAKE) migrate
	$(MAKE) loadplatforms
	$(MAKE) gen-icons

server: gen-element-types
	@pnpm concurrently \
		--names "Django,TS" \
		--prefix-colors "blue,green" \
		"uv run --frozen python -Wa manage.py runserver" \
		"pnpm exec tsc --watch"

gen-element-types:
	uv run --frozen python manage.py gen_element_types

gen-icons:
	uv run --frozen python manage.py gen_icons

check-icons:
	uv run --frozen python manage.py gen_icons --check

ts: gen-element-types
	pnpm exec tsc

ts-check: gen-element-types
	pnpm exec tsc --noEmit -p tsconfig.check.json

# gen-element-types prereq: field-comparison-set.ts value-imports the generated
# filter-metadata module, so vitest needs it present AND current — a stale file
# would silently validate against outdated vocabulary.
test-ts: gen-element-types
	pnpm exec vitest run

dev: ensure-python gen-element-types
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run --frozen python -Wa manage.py runserver" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"


caddy:
	caddy run --watch

dev-prod: migrate collectstatic
	@npx concurrently \
		--names "Caddy,Django,Django-Q" \
		"caddy run --config Caddyfile.dev" \
		"PROD=1 uv run --frozen python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker" \
		"PROD=1 uv run --frozen manage.py qcluster"

dumpgames:
	uv run --frozen python manage.py dumpdata --format yaml games --output tracker_fixture.yaml

loadplatforms:
	uv run --frozen python manage.py loadplatforms

loadall:
	uv run --frozen python manage.py loaddata data.yaml

loadsample:
	uv run --frozen python manage.py loaddata sample.yaml

createsuperuser:
	uv run --frozen python manage.py createsuperuser

shell:
	uv run --frozen python manage.py shell

collectstatic:
	uv run --frozen python manage.py collectstatic --clear --no-input

uv.lock: pyproject.toml
	uv sync

# base.css (Tailwind) and js/dist (TS) are build artifacts, gitignored and not
# tracked — build both before tests so e2e/static serving has fresh assets.
test: ensure-python uv.lock css ts test-ts
	uv run --frozen --with pytest-django pytest

test-e2e: uv.lock css ts
	uv run --frozen pytest e2e/

lint:
	uv run --frozen ruff check

lint-fix:
	uv run --frozen ruff check --fix

format:
	uv run --frozen ruff format

format-check:
	uv run --frozen ruff format --check

typecheck:
	uv run --frozen mypy .

check: ensure-python lint format-check typecheck ts-check check-icons test-ts test

date:
	uv run --frozen python -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r static/*

clean: cleanstatic
