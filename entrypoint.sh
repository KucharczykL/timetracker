#!/bin/bash
set -euo pipefail

# Container-bootstrap configuration. These variables are consumed only by this
# entrypoint, NOT by Django (see timetracker/config.py for the app settings):
#   CREATE_DEFAULT_SUPERUSER — create an admin/admin user on first start
#   STAGING / LOAD_SAMPLE_DATA — staging-only data bootstrap (see below)
#
# The flags are translated into arguments here rather than read from the
# environment inside Django, and the work runs as ONE `manage.py` call: each
# invocation pays Django's startup twice over on a cold container (~10-30s on a
# small VM), which is time a request waits for the machine to come up.
#
# STAGING=true scrubs a database seeded from a production snapshot — sessions
# and the inherited django-q schedule/queue — so staging neither shares prod's
# session cookies nor independently runs scheduled tasks (see issue #20).
# LOAD_SAMPLE_DATA=true instead seeds demo data into a fresh public staging
# database (e.g. Fly.io), and only while the games table is empty.
# if, not `[ … ] && …`: under `set -e` a false test as the last statement of the
# script's flow would exit 1.
bootstrap_args=()
if [ "${STAGING:-false}" = "true" ]; then
    bootstrap_args+=(--scrub-staging)
fi
if [ "${LOAD_SAMPLE_DATA:-false}" = "true" ]; then
    bootstrap_args+=(--sample-data)
fi
if [ "${CREATE_DEFAULT_SUPERUSER:-false}" = "true" ]; then
    bootstrap_args+=(--default-superuser)
fi

# Static files are collected into the image at build time, not here.
bootstrap_started=$SECONDS
python manage.py bootstrap_container "${bootstrap_args[@]}"
# Printed because nothing else measures it: a request to a stopped machine waits
# out this whole span, and a regression here is invisible until it exceeds
# whatever the fronting proxy is willing to hold.
echo "Bootstrap finished in $((SECONDS - bootstrap_started))s."

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisor.conf
