"""Project middleware: health probes and request-scoped presentation preferences."""

from zoneinfo import ZoneInfo

from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.utils import timezone

from timetracker.settings_resolver import resolve_for_user


class HealthCheckMiddleware:
    """Answer container health probes.

    Must sit first in MIDDLEWARE: probes hit 127.0.0.1, which
    CommonMiddleware's ALLOWED_HOSTS check would reject.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health":
            return HttpResponse("ok", content_type="text/plain")
        if request.path == "/health/ready":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except DatabaseError:
                return HttpResponse(
                    "unavailable", status=503, content_type="text/plain"
                )
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


class TimezoneActivationMiddleware:
    """Activate presentation preferences for one request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Avoid caching preferences before a settings write commits.
        if request.path.startswith("/api/settings/"):
            return self.get_response(request)
        user = getattr(request, "user", None)
        time_zone = resolve_for_user(user, "DISPLAY_TIME_ZONE")
        locale = resolve_for_user(user, "DATE_FORMAT_LOCALE")
        if isinstance(locale, str):
            # Date formatting must not change application translations.
            request._date_format_locale = locale
        with timezone.override(ZoneInfo(str(time_zone))):
            return self.get_response(request)
