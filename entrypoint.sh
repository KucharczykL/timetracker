#!/bin/bash
set -euo pipefail

# Container-bootstrap configuration. These variables are consumed only by this
# entrypoint, NOT by Django (see timetracker/config.py for the app settings):
#   DATA_DIR                 — writable dir for the SQLite database (kept in
#                              sync with Django via the same env var + default)
#   CREATE_DEFAULT_SUPERUSER — create an admin/admin user on first start
#   STAGING / LOAD_SAMPLE_DATA — staging-only data bootstrap (see below)
DATA_DIR=${DATA_DIR:-/home/timetracker/app/data}

mkdir -p "$DATA_DIR"

python manage.py migrate
python manage.py collectstatic --clear --no-input

# Staging seeded from a production snapshot: remove copied sessions and the
# inherited django-q schedule/queue so staging neither shares prod's session
# cookies nor independently runs scheduled tasks (see issue #20).
if [ "${STAGING:-false}" = "true" ]; then
    python manage.py scrub_staging
fi

# Public staging with a fresh database (e.g. Fly.io): load demo data instead
# of any production snapshot. Runs once while the games table is empty.
if [ "${LOAD_SAMPLE_DATA:-false}" = "true" ]; then
    python manage.py shell -c "
from games.models import Game
from django.core.management import call_command
if not Game.objects.exists():
    call_command('loaddata', 'sample.yaml.gz')
    print('Loaded sample data.')
"
fi

if [ "${CREATE_DEFAULT_SUPERUSER:-false}" = "true" ]; then
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', '', 'admin')
    print('Created default superuser: admin / admin')
"
fi

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisor.conf
