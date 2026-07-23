"""Request-scoped presentation preference activation."""

from zoneinfo import ZoneInfo

from django.utils import timezone

from timetracker.settings_resolver import resolve_for_user


class TimezoneActivationMiddleware:
    """Activate the resolved display time zone for one request only.

    The formatting locale is intentionally kept on the request for
    ``DateTimePresentation``. It must not activate Django's translation locale,
    which would translate application copy as well as date names.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Settings API responses contain only raw preference values; they never
        # render a date, parse a form, or expose the presentation contract.
        # Avoid warming the transaction-safe whole-table preference snapshot
        # before the endpoint writes a value whose invalidation runs on commit.
        if request.path.startswith("/api/settings/"):
            return self.get_response(request)
        user = getattr(request, "user", None)
        time_zone = resolve_for_user(user, "DISPLAY_TIME_ZONE")
        locale = resolve_for_user(user, "DATE_FORMAT_LOCALE")
        if isinstance(locale, str):
            request._date_format_locale = locale
        with timezone.override(ZoneInfo(str(time_zone))):
            return self.get_response(request)
