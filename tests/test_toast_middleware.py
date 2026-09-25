import json

from django.contrib.messages import constants as message_constants
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import TestCase, override_settings

from games.toast_middleware import ToastMessagesMiddleware


def get_response_ok(request):
    return HttpResponse("OK")


class ToastMessagesMiddlewareTest(TestCase):
    def _build_request(self, message_level=None):
        """Build a request with FallbackStorage message backend."""
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test"
        request.META = {"SERVER_NAME": "localhost", "SERVER_PORT": "80"}
        request.session = {}

        storage = FallbackStorage(request)
        if message_level is not None:
            storage._set_level(message_level)
        request._messages = storage

        return request

    def test_a_request_with_messages_sends_the_events_header(self):
        """A request with messages should include the X-Events header."""
        request = self._build_request()
        request._messages.add(message_constants.SUCCESS, "Item saved")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        self.assertIn("X-Events", response)
        data = json.loads(response["X-Events"])
        self.assertIn("show-toast", data)
        self.assertEqual(data["show-toast"][-1]["message"], "Item saved")
        self.assertEqual(data["show-toast"][-1]["type"], "success")

    def test_a_notice_action_rides_the_trigger(self):
        """An Undo action reaches the header beside the sentence."""
        from django.contrib.messages import constants

        from common.notices import Undo, notify

        request = self._build_request()
        notify(
            request,
            "Session removed.",
            level=constants.SUCCESS,
            action=Undo("/session/x/restore"),
        )
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(
            data["show-toast"][-1],
            {
                "message": "Session removed.",
                "type": "success",
                "action": {"label": "Undo", "url": "/session/x/restore"},
            },
        )

    def test_every_queued_message_rides_the_trigger(self):
        """Two messages, two toasts: the element takes a list."""
        request = self._build_request()
        request._messages.add(message_constants.SUCCESS, "Session removed.")
        request._messages.add(message_constants.INFO, "Also this")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(
            [payload["message"] for payload in data["show-toast"]],
            ["Session removed.", "Also this"],
        )

    def test_a_request_with_an_error_message(self):
        """Error messages should map to 'error' toast type."""
        request = self._build_request()
        request._messages.add(message_constants.ERROR, "Something failed")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(data["show-toast"][-1]["type"], "error")

    def test_a_request_with_a_success_message(self):
        """Success messages should map to 'success' toast type."""
        request = self._build_request()
        request._messages.add(message_constants.SUCCESS, "Saved successfully")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(data["show-toast"][-1]["type"], "success")

    def test_a_request_without_messages_sends_no_events_header(self):
        """A request without messages should not include the X-Events header."""
        request = self._build_request()
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        self.assertNotIn("X-Events", response)

    def test_warning_message_maps_to_warning(self):
        """Warning messages should map to 'warning' toast type."""
        request = self._build_request()
        request._messages.add(message_constants.WARNING, "Warning message")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(data["show-toast"][-1]["type"], "warning")

    def test_a_redirect_keeps_its_messages_for_the_next_page(self):
        """A 302 has no body, so the toast belongs to the page it lands on."""
        request = self._build_request()
        request._messages.add(message_constants.ERROR, "Refused")
        middleware = ToastMessagesMiddleware(
            lambda request: HttpResponseRedirect("/next/")
        )

        response = middleware(request)

        self.assertNotIn("X-Events", response)
        #: Reading them is what loses them:
        #: MessageMiddleware stores an empty queue after.
        self.assertFalse(request._messages.used)

    @override_settings(DEBUG=True)
    def test_debug_message_maps_to_debug(self):
        """Debug messages should map to 'debug' toast type."""
        request = self._build_request(message_level=message_constants.DEBUG)
        request._messages.add(message_constants.DEBUG, "Debug info")
        middleware = ToastMessagesMiddleware(get_response_ok)

        response = middleware(request)

        data = json.loads(response["X-Events"])
        self.assertEqual(data["show-toast"][-1]["type"], "debug")
