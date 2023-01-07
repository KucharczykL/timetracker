#!/bin/bash
# Apply database migrations
set -euo pipefail
echo "Apply database migrations"
poetry run python src/web/manage.py migrate

echo "Collect static files"
poetry run python src/web/manage.py collectstatic

echo "Starting server"
caddy start
cd src/web || exit
poetry run python -m gunicorn --bind 0.0.0.0:8001 web.asgi:application -k uvicorn.workers.UvicornWorker
