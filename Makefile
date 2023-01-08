all: css migrate

initialize: npm css migrate sethookdir loadplatforms

HTMLFILES := $(shell find src/web/tracker/templates -type f)

npm:
	npm install

css: src/input.css
	npx tailwindcss -i ./src/input.css -o  ./src/web/tracker/static/base.css

css-dev: css
	npx tailwindcss -i ./src/input.css -o  ./src/web/tracker/static/base.css --watch

makemigrations:
	poetry run python src/web/manage.py makemigrations

migrate: makemigrations
	poetry run python src/web/manage.py migrate

dev: migrate sethookdir
	poetry run python src/web/manage.py runserver_plus

caddy:
	caddy run --watch

dev-prod: migrate collectstatic sethookdir
	cd src/web/; PROD=1 poetry run python -m gunicorn --bind 0.0.0.0:8001 web.asgi:application -k uvicorn.workers.UvicornWorker

dumptracker:
	poetry run python src/web/manage.py dumpdata --format yaml tracker --output tracker_fixture.yaml

loadplatforms:
	poetry run python src/web/manage.py loaddata platforms.yaml

loadsample:
	poetry run python src/web/manage.py loaddata sample.yaml

createsuperuser:
	poetry run python src/web/manage.py createsuperuser

shell:
	poetry run python src/web/manage.py shell

collectstatic:
	poetry run python src/web/manage.py collectstatic --clear --no-input

poetry.lock: pyproject.toml
	poetry install

test: poetry.lock
	poetry run pytest

sethookdir:
	git config core.hooksPath .githooks

date:
	python3 -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.isoformat(datetime.datetime.now(ZoneInfo("Europe/Prague")), timespec="minutes", sep=" "))'

cleanstatic:
	rm -r src/web/static/*

clean: cleanstatic
