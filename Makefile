all: css migrate

initialize: npm css migrate loadplatforms

PYTHON_VERSION = 3.12

npm:
	pnpm install

css: common/input.css
	pnpm tailwindcss -i ./common/input.css -o  ./games/static/base.css

makemigrations:
	uv run python manage.py makemigrations

migrate: makemigrations
	uv run python manage.py migrate

init:
	uv python install $(PYTHON_VERSION)
	uv sync
	pnpm install
	$(MAKE) migrate
	$(MAKE) loadplatforms

server: gen-element-types
	@pnpm concurrently \
		--names "Django,TS" \
		--prefix-colors "blue,green" \
		"uv run python -Wa manage.py runserver" \
		"pnpm exec tsc --watch"

gen-element-types:
	uv run python manage.py gen_element_types

ts: gen-element-types
	pnpm exec tsc

ts-check: gen-element-types
	pnpm exec tsc --noEmit

dev: gen-element-types
	@pnpm concurrently \
		--names "Django,Tailwind,TS" \
		--prefix-colors "blue,green,magenta" \
		"uv run python -Wa manage.py runserver" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch" \
		"pnpm exec tsc --watch"


caddy:
	caddy run --watch

dev-prod: migrate collectstatic
	@npx concurrently \
		--names "Caddy,Django,Django-Q" \
		"caddy run --config Caddyfile.dev" \
		"PROD=1 uv run python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker" \
		"PROD=1 uv run manage.py qcluster"

dumpgames:
	uv run python manage.py dumpdata --format yaml games --output tracker_fixture.yaml

loadplatforms:
	uv run python manage.py loaddata platforms.yaml

loadall:
	uv run python manage.py loaddata data.yaml

loadsample:
	uv run python manage.py loaddata sample.yaml

createsuperuser:
	uv run python manage.py createsuperuser

shell:
	uv run python manage.py shell

collectstatic:
	uv run python manage.py collectstatic --clear --no-input

uv.lock: pyproject.toml
	uv sync

# base.css (Tailwind) and js/dist (TS) are build artifacts, gitignored and not
# tracked — build both before tests so e2e/static serving has fresh assets.
test: uv.lock css ts
	uv run --with pytest-django pytest

test-e2e: uv.lock css ts
	uv run pytest e2e/

lint:
	uv run ruff check

lint-fix:
	uv run ruff check --fix

format:
	uv run ruff format

format-check:
	uv run ruff format --check

check: lint format-check ts-check test

date:
	uv run python -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r static/*

clean: cleanstatic
