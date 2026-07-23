"""Request-scoped presentation preferences."""

from zoneinfo import ZoneInfo

from django.utils import timezone

from timetracker.settings_resolver import resolve_for_user


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
