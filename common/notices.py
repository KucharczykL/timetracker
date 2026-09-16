"""What a toast carries; the action rides extra_tags."""

import json
import logging
from typing import Literal, NotRequired, TypedDict, get_args

from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.http import HttpRequest

logger = logging.getLogger("games")

type ToastType = Literal["success", "error", "info", "warning", "debug"]
#: A route path; the element stamps the page as origin.
type ActionUrl = str  # "/session/<id>/restore"
#: One of django.contrib.messages' level constants.
type MessageLevel = int  # messages.SUCCESS

#: The element's words; else info.
_TOAST_TYPES: frozenset[str] = frozenset(get_args(ToastType.__value__))


class ToastAction(TypedDict):
    label: str
    url: ActionUrl


class ToastPayload(TypedDict):
    message: str
    type: ToastType
    action: NotRequired[ToastAction]


class _NoticeSlot(TypedDict):
    action: ToastAction


def Undo(url: ActionUrl) -> ToastAction:
    """The one action a removal offers."""
    return ToastAction(label="Undo", url=url)


def notify(
    request: HttpRequest,
    sentence: str,
    *,
    level: MessageLevel,
    action: ToastAction | None = None,
) -> None:
    """Queue one toast."""
    extra_tags = json.dumps(_NoticeSlot(action=action)) if action is not None else ""
    messages.add_message(request, level, sentence, extra_tags=extra_tags)


def _toast_type(message: Message) -> ToastType:
    tag = message.level_tag
    if tag in _TOAST_TYPES:
        return tag  # type: ignore[return-value]
    return "info"


def _action_of(message: Message) -> ToastAction | None:
    """The slot's action; a foreign value is logged, not shown.

    Raising here would take the page down for a display attribute
    and lose every queued sentence with it.
    """
    if not message.extra_tags:
        return None
    try:
        slot = json.loads(message.extra_tags)
        action = slot["action"]
        if isinstance(action["label"], str) and isinstance(action["url"], str):
            return ToastAction(label=action["label"], url=action["url"])
    except ValueError, KeyError, TypeError:
        pass
    logger.error(
        "[notices]: extra_tags is the notice slot and %r is no notice; "
        "the toast shows without its action.",
        message.extra_tags,
    )
    return None


def toast_payloads(request: HttpRequest) -> list[ToastPayload]:
    """Read the queue; marks it used."""
    payloads: list[ToastPayload] = []
    for message in messages.get_messages(request):
        payload = ToastPayload(message=str(message.message), type=_toast_type(message))
        action = _action_of(message)
        if action is not None:
            payload["action"] = action
        payloads.append(payload)
    return payloads
