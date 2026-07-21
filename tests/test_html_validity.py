"""Global HTML-validity invariant: no interactive element nested inside another.

The touch-affordance work (#445) renders popover triggers as real ``<button>``s.
A ``<button>`` (or any interactive element) inside an ``<a>``/``<button>`` is
invalid HTML, and a tap on it competes with the ancestor's own activation. This
suite renders the app's pages and fails if any interactive element nests inside
another — the safety net that lets popover triggers default to tappable without
a per-component guard a caller-supplied wrapper could defeat.
"""

from datetime import date, datetime
from collections import Counter
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Device, Game, PlayEvent, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)

# Elements that must not contain another interactive element. An <a> here is
# always a link (the app never emits bare anchors), so it counts unconditionally.
_INTERACTIVE_ANCESTORS = {"a", "button"}
# Interactive descendants that are illegal inside the ancestors above.
_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}
_INTERACTIVE_ROLES = {"menuitem", "menuitemcheckbox", "menuitemradio"}
# Void elements never open a scope, so they need no stack pop.
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _InteractiveNestingParser(HTMLParser):
    """Track open tags and record any interactive-in-interactive nesting."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        # Names of the currently-open interactive ancestors, innermost last.
        self._open_interactive: list[str] = []
        self.violations: list[str] = []
        self.ids: list[str] = []
        self.describedby: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if attr_map.get("id"):
            self.ids.append(attr_map["id"] or "")
        if attr_map.get("aria-describedby"):
            self.describedby.extend((attr_map["aria-describedby"] or "").split())
        role = (attr_map.get("role") or "").strip()
        if (tag in _INTERACTIVE_TAGS or role in _INTERACTIVE_ROLES) and (
            self._open_interactive
        ):
            descriptor = f"<{tag}" + (f' role="{role}"' if role else "") + ">"
            self.violations.append(
                f"{descriptor} nested inside <{self._open_interactive[-1]}>"
            )
        if tag in _VOID_TAGS:
            return
        self._stack.append(tag)
        if tag in _INTERACTIVE_ANCESTORS or role in _INTERACTIVE_ROLES:
            self._open_interactive.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or tag not in self._stack:
            return
        # Pop back to the matching open tag (tolerates unclosed inner tags).
        while self._stack:
            popped = self._stack.pop()
            if self._open_interactive and self._open_interactive[-1] == popped:
                self._open_interactive.pop()
            if popped == tag:
                break


class HtmlValidityTest(TestCase):
    """Every rendered page is free of interactive-in-interactive nesting."""

    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client.force_login(self.user)

        self.platform = Platform.objects.create(name="Test Platform", icon="test")
        self.device = Device.objects.create(name="Test Device", type="c")

        # A long display name with a different sort name exercises both the
        # width-based reveal and the game-list tooltip's informative IDREF.
        self.long_game = Game.objects.create(
            name="A Very Long Game Name That Exceeds Thirty Characters For Sure",
            sort_name="Very Long Game Name, A",
            platform=self.platform,
        )
        self.other_game = Game.objects.create(
            name="Second Game In The Bundle", platform=self.platform
        )

        # A multi-game bundle: LinkedPurchase renders the games-list popover.
        self.bundle = Purchase.objects.create(
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
        )
        self.bundle.games.add(self.long_game, self.other_game)
        self.other_bundle = Purchase.objects.create(
            date_purchased=datetime(2022, 9, 27, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
            price=1,
        )
        self.other_bundle.games.add(self.long_game, self.other_game)

        Session.objects.create(
            game=self.long_game,
            timestamp_start=datetime(2022, 9, 26, 15, 0, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 16, 0, tzinfo=ZONEINFO),
            device=self.device,
        )
        PlayEvent.objects.create(
            game=self.long_game,
            started=date(2022, 9, 1),
            ended=date(2022, 9, 26),
        )

    def _urls(self) -> list[str]:
        urls = [
            reverse("games:list_games"),
            reverse("games:list_sessions"),
            reverse("games:list_playevents"),
            reverse("games:list_purchases"),
            reverse("games:list_devices"),
            reverse("games:list_platforms"),
            reverse("games:view_game", args=[self.long_game.id]),
            reverse("games:view_purchase", args=[self.bundle.id]),
            reverse("games:edit_game", args=[self.long_game.id]),
            reverse("games:add_game"),
            reverse("games:add_purchase"),
            reverse("games:add_session"),
            reverse("games:add_playevent"),
            reverse("games:stats_alltime"),
            reverse("games:stats_by_year", args=[2022]),
        ]
        # Every filter-builder page (the "!"-badge / advanced-filter surface).
        for model in ("game", "session", "purchase", "playevent", "device", "platform"):
            urls.append(reverse("games:filter_builder", args=[model]))
        return urls

    def test_no_interactive_element_nested_in_another(self) -> None:
        failures: list[str] = []
        for url in self._urls():
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200, f"{url} did not return 200")
            parser = _InteractiveNestingParser()
            parser.feed(response.content.decode())
            for violation in parser.violations:
                failures.append(f"{url}: {violation}")
        self.assertEqual(
            failures,
            [],
            "Interactive elements nested inside interactive ancestors:\n"
            + "\n".join(failures),
        )

    def test_ids_are_unique_and_describedby_targets_resolve_once(self) -> None:
        """Informative purchase and sort-name tooltips keep valid IDREFs."""
        failures: list[str] = []
        for url in (reverse("games:list_games"), reverse("games:list_purchases")):
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200)
            parser = _InteractiveNestingParser()
            parser.feed(response.content.decode())
            counts = Counter(parser.ids)
            failures.extend(
                f"{url}: duplicate id {element_id!r}"
                for element_id, count in counts.items()
                if count > 1
            )
            failures.extend(
                f"{url}: aria-describedby {token!r} resolves {counts[token]} times"
                for token in parser.describedby
                if counts[token] != 1
            )
        self.assertEqual(
            failures, [], "Invalid page ID relationships:\n" + "\n".join(failures)
        )
