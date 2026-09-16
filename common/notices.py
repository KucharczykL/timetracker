"""What a toast carries; the action rides extra_tags."""

import json
from typing import Literal, TypedDict

from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.http import HttpRequest

type ToastType = Literal["success", "error", "info", "warning", "debug"]

#: The element's words; else info.
_TOAST_TYPES: frozenset[str] = frozenset(
    {"success", "error", "info", "warning", "debug"}
)


class ToastAction(TypedDict):
    label: str
    url: str


class ToastPayload(TypedDict, total=False):
    message: str
    type: ToastType
    action: ToastAction


class _Slot(TypedDict):
    action: ToastAction


def Undo(url: str) -> ToastAction:
    """The one action a removal offers."""
    return ToastAction(label="Undo", url=url)


def notify(
    request: HttpRequest,
    sentence: str,
    *,
    level: int,
    action: ToastAction | None = None,
) -> None:
    """Queue one toast."""
    extra_tags = json.dumps(_Slot(action=action)) if action is not None else ""
    messages.add_message(request, level, sentence, extra_tags=extra_tags)


def _toast_type(message: Message) -> ToastType:
    tag = message.level_tag
    if tag in _TOAST_TYPES:
        return tag  # type: ignore[return-value]
    return "info"


def _action_of(message: Message) -> ToastAction | None:
    if not message.extra_tags:
        return None
    try:
        slot = json.loads(message.extra_tags)
    except json.JSONDecodeError as error:
        raise ValueError(
            "extra_tags is the notice slot and holds JSON: "
            f"{message.extra_tags!r} is not."
        ) from error
    if not isinstance(slot, dict) or "action" not in slot:
        raise ValueError(
            f"extra_tags is the notice slot and names an action: {slot!r} does not."
        )
    return slot["action"]


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
