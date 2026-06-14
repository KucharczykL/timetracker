#!/bin/bash
set -euo pipefail

PUID=${PUID:-1000}
PGID=${PGID:-100}

USERHOME=$(grep timetracker /etc/passwd | cut -d ":" -f6)
usermod -d "/root" timetracker
groupmod -o -g "$PGID" timetracker
usermod -o -u "$PUID" timetracker
usermod -d "${USERHOME}" timetracker

mkdir -p /home/timetracker/app/data /var/log/supervisor
chmod 755 /home/timetracker/app
chmod 755 /home/timetracker/app/.venv

chown "$PUID:$PGID" /home/timetracker/app/data
chown "$PUID:$PGID" /var/log/supervisor

python manage.py migrate
python manage.py collectstatic --clear --no-input

if [ "${CREATE_DEFAULT_SUPERUSER:-false}" = "true" ]; then
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', '', 'admin')
    print('Created default superuser: admin / admin')
"
fi

chown -R "$PUID:$PGID" /home/timetracker/app/data

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisor.conf
