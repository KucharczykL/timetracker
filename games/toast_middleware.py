import json

from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.messages import constants as message_constants

from common.notices import toast_payloads

#: Events the page dispatches, as JSON.
EVENTS_HEADER = "X-Events"
#: The page answers this by reloading.
RELOAD_HEADER = "X-Reload"


class ToastMessagesMiddleware:
    """Puts queued messages into the X-Events header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Redirects and reloads keep their messages.
        # Reading them here marks the storage used, so MessageMiddleware
        # then stores an empty queue -- and the header rides a response the
        # browser discards, which loses the sentence entirely.
        if RELOAD_HEADER in response or 300 <= response.status_code < 400:
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

        response[EVENTS_HEADER] = json.dumps({"show-toast": payloads})
        return response
