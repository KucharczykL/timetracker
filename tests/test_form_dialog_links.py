"""The row menus and entry points that open a form page in a dialog.

Each builder renders real rows. A link that edits or adds opens in the
dialog; a remove, reset or one-click POST stays a page of its own.
"""

import re
from collections.abc import Callable
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from devices import create_device
from django.urls import reverse
from entries import end_entry_access, record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from purchases import record_purchase
from session_rows import duration_only_row, tracked_run

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.layout import NavbarLogButton
from games.models import Game, Platform, UserLibrary
from games.reads.playthrough_numbering import numbered_for
from games.views.device_menu import device_row_menu
from games.views.entry_menu import entry_row_menu
from games.views.game_menu import game_row_menu
from games.views.historical_playtime import record_row_menu
from games.views.platform_menu import platform_row_menu
from games.views.playthrough_rows import _row_menu as playthrough_row_menu
from games.views.purchase_menu import purchase_items
from games.views.session_menu import session_row_menu

pytestmark = pytest.mark.django_db

#: Each element: its tag and attributes, and its text.
ELEMENT = re.compile(r"<(a|button)\b([^>]*)>((?:(?!</\1>).)*?)</\1>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")
MARKER = "data-form-dialog"


def _elements_naming(html: str, label: str) -> list[str]:
    """The attributes of each element whose text names ``label``."""
    return [
        attributes
        for _, attributes, text in ELEMENT.findall(html)
        if label in TAG.sub("", text)
    ]


def _presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def _game(library: UserLibrary, name: str = "Tunic") -> Game:
    return Game.objects.create(library=library, name=name)


def _session_menu(library: UserLibrary) -> str:
    """Duration-only, so the historical record act is offered."""
    run = tracked_run(library, _game(library))
    session = duration_only_row(run, date(2024, 6, 1), timedelta(hours=9))
    return str(session_row_menu(session, "token", origin=None))


def _playthrough_menu(library: UserLibrary) -> str:
    """The run as the screen reads it: numbered over its game's runs."""
    run = tracked_run(library, _game(library))
    numbered = numbered_for(library, [run.player_game_id], with_condition=True)
    (numbered_run,) = numbered.select_related("player_game__game")
    return str(playthrough_row_menu(numbered_run, None, "token"))


def _historical_menu(library: UserLibrary) -> str:
    record = record_row([tracked_run(library, _game(library))])
    return str(record_row_menu(record, _presentation(), origin=None))


def _device_menu(library: UserLibrary) -> str:
    return str(device_row_menu(create_device(library, "Steam Deck"), origin=None))


def _platform_menu(library: UserLibrary) -> str:
    platform = Platform.objects.create(library=library, name="Amiga", group="Commodore")
    return str(platform_row_menu(platform, origin=None))


def _game_menu(library: UserLibrary) -> str:
    return str(game_row_menu(_game(library), origin=None))


def _entry(library: UserLibrary):
    platform = Platform.objects.create(library=library, name="PS5", group="Sony")
    graph = default_graph(
        Game(name="Tunic", library=library), library, platform=platform
    )
    return record_entry(library, graph.release)


def _entry_menu(library: UserLibrary) -> str:
    return str(entry_row_menu(_entry(library), None, "token", purchases=[]))


def _ended_entry_menu(library: UserLibrary) -> str:
    entry = end_entry_access(_entry(library))
    return str(entry_row_menu(entry, None, "token", purchases=[]))


def _purchase_menu(library: UserLibrary) -> str:
    purchase = record_purchase(_entry(library))
    return "".join(str(item) for item in purchase_items(purchase, None, "token"))


def _navbar_log_button(_library: UserLibrary) -> str:
    """The split button's primary link; no recent resumes to list."""
    return str(NavbarLogButton([], csrf_token="token", origin=None))


type Case = tuple[Callable[[UserLibrary], str], tuple[str, ...], tuple[str, ...]]

#: The builder, the links it marks, the acts it leaves alone.
CASES: dict[str, Case] = {
    "session": (
        _session_menu,
        ("Edit", "Record as historical playtime"),
        ("Remove",),
    ),
    "playthrough": (
        _playthrough_menu,
        ("Edit",),
        ("Remove",),
    ),
    "historical_playtime": (
        _historical_menu,
        ("Edit",),
        ("Remove",),
    ),
    "device": (_device_menu, ("Edit",), ("Remove",)),
    "platform": (_platform_menu, ("Edit",), ("Remove",)),
    "game": (_game_menu, ("Edit",), ("Remove",)),
    "entry": (
        _entry_menu,
        ("Edit…", "Add purchase…", "With details…"),
        ("Remove…", "Just mark it gone"),
    ),
    "ended_entry": (
        _ended_entry_menu,
        ("Edit how it left…", "With details…"),
        ("Remove…", "Just add it back"),
    ),
    "purchase": (
        _purchase_menu,
        ("Edit purchase…",),
        ("Remove purchase…", "Refund"),
    ),
    "navbar_log_button": (_navbar_log_button, ("Log game",), ()),
}


@pytest.mark.parametrize("name", list(CASES))
def test_named_links_open_in_the_dialog_and_the_rest_do_not(name, owned_library):
    build, marked, unmarked = CASES[name]
    html = build(owned_library)

    for label in marked:
        found = _elements_naming(html, label)
        assert found, f"no element names {label!r}"
        for attributes in found:
            assert MARKER in attributes, f"{label!r} is not a dialog link"

    for label in unmarked:
        found = _elements_naming(html, label)
        assert found, f"no element names {label!r}"
        for attributes in found:
            assert MARKER not in attributes, f"{label!r} opens in the dialog"


def test_the_library_tab_marks_add_to_library(client, owned_user):
    client.force_login(owned_user)
    html = client.get(reverse("games:list_library")).content.decode()

    links = [
        attributes
        for tag, attributes, _ in ELEMENT.findall(html)
        if f'href="{reverse("games:add_to_library")}' in attributes
    ]
    assert links
    assert all(MARKER in attributes for attributes in links)
