#!/bin/bash
# Apply database migrations
echo "Apply database migrations"
poetry run python src/web/manage.py migrate

echo "Collect static files"
poetry run python src/web/manage.py collectstatic

# Start server
echo "Starting server"
poetry run python src/web/manage.py runserver 0.0.0.0:8000