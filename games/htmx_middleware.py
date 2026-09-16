import json

from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.messages import constants as message_constants

from common.notices import toast_payloads


class HTMXMessagesMiddleware:
    """
    Converts Django messages into HX-Trigger headers so toasts display
    automatically without changes to views.

    Works for HTMX requests (processed natively by HTMX client),
    vanilla fetch() calls using fetchWithHtmxTriggers(), and is harmless
    for full-page loads (browsers ignore HX-Trigger).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Leave a navigation's messages in the session for the page it lands
        # on. Reading them here marks the storage used, so MessageMiddleware
        # then stores an empty queue -- and the header rides a response the
        # browser discards, which loses the sentence entirely.
        if (
            "HX-Redirect" in response
            or "HX-Refresh" in response
            or 300 <= response.status_code < 400
        ):
            return response

        min_level = (
            message_constants.DEBUG if settings.DEBUG else message_constants.INFO
        )
        backend = django_messages.get_messages(request)
        if hasattr(backend, "_set_level") and backend._get_level() > min_level:
            backend._set_level(min_level)
        payloads = toast_payloads(request)
        if not payloads:
            return response

        response["HX-Trigger"] = json.dumps({"show-toast": payloads})
        return response
