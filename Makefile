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
	$(MAKE) loadplatforms

server:
	uv run python -Wa manage.py runserver

dev:
	@pnpm concurrently \
		--names "Django,Tailwind" \
		--prefix-colors "blue,green" \
		"uv run python -Wa manage.py runserver" \
		"pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css --watch"


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

test: uv.lock
	uv run --with pytest-django pytest

test-e2e: uv.lock
	uv run pytest e2e/

lint:
	uv run ruff check

lint-fix:
	uv run ruff check --fix

format:
	uv run ruff format

format-check:
	uv run ruff format --check

check: lint format-check test

date:
	uv run python -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r static/*

clean: cleanstatic
