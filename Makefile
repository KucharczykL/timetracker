.PHONY: createsuperuser

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
	python src/web/manage.py makemigrations

migrate: makemigrations
	python src/web/manage.py migrate

dev: migrate
	python src/web/manage.py runserver

dumptracker:
	python src/web/manage.py dumpdata --format yaml tracker --output tracker_fixture.yaml

loadplatforms:
	python src/web/manage.py loaddata platforms.yaml

loadsample:
	python src/web/manage.py loaddata sample.yaml

createsuperuser:
	python src/web/manage.py createsuperuser