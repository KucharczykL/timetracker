from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from games.models import UserPreferences
from timetracker import settings_resolver


def test_authenticated_request_activates_personal_presentation_and_restores_context(db):
    from common.date_time_presentation import date_time_presentation_for_request
    from common.middleware import TimezoneActivationMiddleware

    user = get_user_model().objects.create_user(username="tester", password="pw")
    UserPreferences.objects.create(
        user=user,
        display_time_zone="Pacific/Kiritimati",
        date_format_locale="cs",
    )
    settings_resolver.clear_cache()
    observed: dict[str, str] = {}

    def response(request):
        presentation = date_time_presentation_for_request(request)
        observed["time_zone"] = timezone.get_current_timezone_name()
        observed["locale"] = presentation.locale
        return HttpResponse()

    request = RequestFactory().get("/")
    request.user = user
    middleware = TimezoneActivationMiddleware(response)

    with timezone.override(ZoneInfo("UTC")):
        middleware(request)
        assert timezone.get_current_timezone_name() == "UTC"

    assert observed == {"time_zone": "Pacific/Kiritimati", "locale": "cs"}
