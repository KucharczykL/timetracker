#!/bin/bash
# Apply database migrations
set -euo pipefail
echo "Apply database migrations"
poetry run python manage.py migrate

echo "Collect static files"
poetry run python manage.py collectstatic --clear --no-input

echo "Starting server"
caddy start
poetry run python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker --access-logfile - --error-logfile -
