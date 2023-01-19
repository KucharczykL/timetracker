#!/bin/bash
# Apply database migrations
set -euo pipefail
echo "Apply database migrations"
poetry run python src/timetracker/manage.py migrate

echo "Collect static files"
poetry run python src/timetracker/manage.py collectstatic --clear --no-input

echo "Starting server"
caddy start
cd src/timetracker || exit
poetry run python -m gunicorn --bind 0.0.0.0:8001 root.asgi:application -k uvicorn.workers.UvicornWorker --access-logfile - --error-logfile -
