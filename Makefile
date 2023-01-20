all: css migrate

initialize: npm css migrate sethookdir loadplatforms

HTMLFILES := $(shell find games/templates -type f)

npm:
	npm install

css: input.css
	npx tailwindcss -i ./input.css -o  ./games/static/base.css

css-dev: css
	npx tailwindcss -i ./input.css -o  ./games/static/base.css --watch

makemigrations:
	poetry run python manage.py makemigrations

migrate: makemigrations
	poetry run python manage.py migrate

dev: migrate
	poetry run python manage.py runserver

caddy:
	caddy run --watch

dev-prod: migrate collectstatic
	PROD=1 poetry run python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker

dumpgames:
	poetry run python manage.py dumpdata --format yaml games --output tracker_fixture.yaml

loadplatforms:
	poetry run python manage.py loaddata platforms.yaml

loadsample:
	poetry run python manage.py loaddata sample.yaml

createsuperuser:
	poetry run python manage.py createsuperuser

shell:
	poetry run python manage.py shell

collectstatic:
	poetry run python manage.py collectstatic --clear --no-input

poetry.lock: pyproject.toml
	poetry install

test: poetry.lock
	poetry run pytest

date:
	poetry run python -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r static/*

clean: cleanstatic
