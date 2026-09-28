"""A row checkbox reads its name once.

Mirrors `identityName` in `ts/elements/selectable-table.ts`; change both.
"""

from html.parser import HTMLParser

from devices import create_device
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Device

# Void elements push no stack frame.
_VOID_TAGS = frozenset({"input", "img", "br", "hr", "meta", "link", "source", "wbr"})

type RowName = str


def _unread(attributes: dict[str, str | None]) -> bool:
    return (
        "hidden" in attributes
        or attributes.get("aria-hidden") == "true"
        or "data-row-summary" in attributes
        or "data-selection-checkbox" in attributes
    )


class _RowNames(HTMLParser):
    """Body row headers' text, minus unread parts."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[RowName] = []
        self._in_body = False
        # Per open element in header: unread?
        self._stack: list[bool] = []
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tbody":
            self._in_body = True
        elif self._stack:
            if tag not in _VOID_TAGS:
                self._stack.append(self._stack[-1] or _unread(attributes))
        elif self._in_body and tag == "th" and attributes.get("scope") == "row":
            self._stack.append(False)
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tbody":
            self._in_body = False
        elif self._stack:
            self._stack.pop()
            if not self._stack:
                self.names.append("".join(self._text).strip())

    def handle_data(self, data: str) -> None:
        if self._stack and not self._stack[-1]:
            self._text.append(data)


class RowSelectionNameTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="tester", password="pw")
        self.client.force_login(self.user)

    def test_the_device_list_names_each_row_once(self) -> None:
        create_device(self.user.library, "Steam Deck", Device.HANDHELD)

        html = self.client.get(reverse("games:list_devices")).content.decode()
        parser = _RowNames()
        parser.feed(html)

        self.assertIn("<selectable-table", html)
        self.assertEqual(parser.names, ["Steam Deck"])
