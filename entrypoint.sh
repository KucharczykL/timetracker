#!/bin/bash
# Apply database migrations
set -euo pipefail
echo "Apply database migrations"
poetry run python manage.py migrate

echo "Collect static files"
poetry run python manage.py collectstatic --clear --no-input

_term() {
  echo "Caught SIGTERM signal!"
  kill -SIGTERM "$gunicorn_pid"
  kill -SIGTERM "$django_q_pid"
}
trap _term SIGTERM

echo "Starting Django-Q cluster"
poetry run python manage.py qcluster & django_q_pid=$!

echo "Starting app"
poetry run python -m gunicorn --bind 0.0.0.0:8001 timetracker.asgi:application -k uvicorn.workers.UvicornWorker --access-logfile - --error-logfile - & gunicorn_pid=$!

wait "$gunicorn_pid" "$django_q_pid"
