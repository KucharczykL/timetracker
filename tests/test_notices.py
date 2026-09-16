"""A toast payload rides the message queue."""

from typing import Any, cast

import pytest
from django.contrib import messages
from django.contrib.messages import constants
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest

from common.notices import Undo, notify, toast_payloads


@pytest.fixture
def request_with_queue() -> HttpRequest:
    #: Any: the queue and the session are set by hand, as the middleware would.
    request = cast(Any, HttpRequest())
    request.method = "GET"
    request.META = {"SERVER_NAME": "localhost", "SERVER_PORT": "80"}
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_a_notice_with_an_action_round_trips(request_with_queue):
    notify(
        request_with_queue,
        "Session removed.",
        level=constants.SUCCESS,
        action=Undo("/session/x/restore"),
    )

    assert toast_payloads(request_with_queue) == [
        {
            "message": "Session removed.",
            "type": "success",
            "action": {"label": "Undo", "url": "/session/x/restore"},
        }
    ]


def test_a_plain_message_decodes_with_no_action(request_with_queue):
    messages.error(request_with_queue, "no")

    assert toast_payloads(request_with_queue) == [{"message": "no", "type": "error"}]


@pytest.mark.parametrize(
    ("level", "toast_type"),
    [
        (constants.DEBUG, "debug"),
        (constants.INFO, "info"),
        (constants.SUCCESS, "success"),
        (constants.WARNING, "warning"),
        (constants.ERROR, "error"),
        (99, "info"),
    ],
)
def test_each_level_maps_to_its_type(request_with_queue, level, toast_type):
    request_with_queue._messages._set_level(constants.DEBUG)
    notify(request_with_queue, "x", level=level)

    assert toast_payloads(request_with_queue)[0]["type"] == toast_type


@pytest.mark.parametrize("extra_tags", ["urgent", '{"colour": "red"}'])
def test_a_foreign_extra_tags_value_raises(request_with_queue, extra_tags):
    messages.add_message(request_with_queue, constants.INFO, "x", extra_tags=extra_tags)

    with pytest.raises(ValueError, match="notice slot"):
        toast_payloads(request_with_queue)


@pytest.mark.django_db
def test_a_queued_action_reaches_the_page_script(request_with_queue):
    """The layout's carrier: the `django-messages` script."""
    from django.contrib.auth.models import AnonymousUser

    from common.components import Div
    from common.layout import render_page

    request_with_queue.user = AnonymousUser()
    notify(
        request_with_queue,
        "Session removed.",
        level=constants.SUCCESS,
        action=Undo("/session/x/restore"),
    )

    html = render_page(request_with_queue, Div()["x"]).content.decode()

    assert '"action": {"label": "Undo", "url": "/session/x/restore"}' in html
