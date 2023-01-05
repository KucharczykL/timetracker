.PHONY: createsuperuser shell

all: css migrate

initialize: npm css migrate loadplatforms

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

dev: migrate
	TZ=Europe/Prague poetry run python src/web/manage.py runserver

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

poetry.lock: pyproject.toml
	poetry install

test: poetry.lock
	poetry run pytest