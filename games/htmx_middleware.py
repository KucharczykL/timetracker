import json

from django.contrib import messages as django_messages
from django.contrib.messages import constants as message_constants

MESSAGE_LEVEL_MAP = {
    message_constants.DEBUG: "debug",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "error",
}


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

        # Skip HX-Trigger and don't consume messages if there's an HX-Redirect
        # so the message persists in the session for the redirect target page
        if "HX-Redirect" in response:
            return response

        messages = list(django_messages.get_messages(request))
        if not messages:
            return response

        triggers = []
        for msg in messages:
            toast_type = MESSAGE_LEVEL_MAP.get(msg.level, "info")
            triggers.append(
                {
                    "message": msg.message,
                    "type": toast_type,
                }
            )

        if triggers:
            # Use last message (most recent) as the primary toast
            trigger = triggers[-1]
            response["HX-Trigger"] = json.dumps(
                {
                    "show-toast": trigger,
                }
            )

        return response
