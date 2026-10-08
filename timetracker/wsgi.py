"""
WSGI config for timetracker project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")

from timetracker.database import limit_request_statements

#: Before Django opens a connection.
limit_request_statements()

application = get_wsgi_application()

from games.readiness import assert_library_structure, report_cookie_security

assert_library_structure()
report_cookie_security()
