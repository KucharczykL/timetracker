all: css migrate

initialize: npm css migrate sethookdir loadplatforms

HTMLFILES := $(shell find games/templates -type f)
PYTHON_VERSION = 3.12

npm:
	npm install

css: common/input.css
	npx @tailwindcss/cli -i ./common/input.css -o  ./games/static/base.css

makemigrations:
	uv run python manage.py makemigrations

migrate: makemigrations
	uv run python manage.py migrate

init:
	uv install $(PYTHON_VERSION)
	uv sync
	npm install
	$(MAKE) sethookdir
	$(MAKE) loadplatforms

sethookdir:
	git config core.hooksPath .githooks
	chmod +x .githooks/*

dev:
	@npx concurrently \
		--names "Django,Tailwind" \
		--prefix-colors "blue,green" \
		"uv run python -Wa manage.py runserver" \
		"npx @tailwindcss/cli -i ./common/input.css -o ./games/static/base.css --watch"


caddy:
	caddy run --watch

dev-prod: migrate collectstatic
	PROD=1 uv run python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker

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
	uv run pytest

date:
	uv run python -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r static/*

clean: cleanstatic
