"""Form links open dialogs; removes stay pages."""

import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple
from urllib.parse import urlsplit
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

#: Tag, attributes and text of each element.
ELEMENT = re.compile(r"<(a|button)\b([^>]*)>((?:(?!</\1>).)*?)</\1>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")
HREF = re.compile(r'\bhref="([^"]*)"')
#: The marker attribute alone, not ``data-form-dialog-title``.
MARKER = re.compile(r"\bdata-form-dialog(?=[\s=/>]|$)")
#: A described item states its label in its first span.
DESCRIBED = re.compile(
    r'<span class="flex flex-col"[^>]*>\s*<span[^>]*>(.*?)</span>', re.DOTALL
)


def _label_of(inner: str) -> str:
    described = DESCRIBED.search(inner)
    text = described[1] if described else inner
    return TAG.sub("", text).strip()


def _elements_named(html: str, label: str) -> list[str]:
    """Attributes of elements whose label is exactly ``label``."""
    return [
        attributes
        for _, attributes, inner in ELEMENT.findall(html)
        if _label_of(inner) == label
    ]


def _path(attributes: str) -> str | None:
    """The path of an element's link, without its query."""
    match = HREF.search(attributes)
    return None if match is None else urlsplit(match[1]).path


class Built(NamedTuple):
    """Rendered markup and the path each marked link names."""

    html: str
    paths: dict[str, str]


def _presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def _game(library: UserLibrary, name: str = "Tunic") -> Game:
    return Game.objects.create(library=library, name=name)


def _session_menu(library: UserLibrary) -> Built:
    """Duration-only; offers the historical record."""
    run = tracked_run(library, _game(library))
    session = duration_only_row(run, date(2024, 6, 1), timedelta(hours=9))
    return Built(
        str(session_row_menu(session, "token", origin=None)),
        {
            "Edit": reverse("games:edit_session", args=[session.pk]),
            "Record as historical playtime…": reverse(
                "games:reclassify_session", args=[session.pk]
            ),
        },
    )


def _playthrough_menu(library: UserLibrary) -> Built:
    """Run numbered as the screen shows it."""
    run = tracked_run(library, _game(library))
    numbered = numbered_for(library, [run.player_game_id], with_condition=True)
    (numbered_run,) = numbered.select_related("player_game__game")
    return Built(
        str(playthrough_row_menu(numbered_run, None, "token")),
        {"Edit": reverse("games:edit_playthrough", args=[numbered_run.pk])},
    )


def _historical_menu(library: UserLibrary) -> Built:
    record = record_row([tracked_run(library, _game(library))])
    return Built(
        str(record_row_menu(record, _presentation(), origin=None)),
        {"Edit": reverse("games:edit_historical_playtime", args=[record.pk])},
    )


def _device_menu(library: UserLibrary) -> Built:
    device = create_device(library, "Steam Deck")
    return Built(
        str(device_row_menu(device, origin=None)),
        {"Edit": reverse("games:edit_device", args=[device.pk])},
    )


def _platform_menu(library: UserLibrary) -> Built:
    platform = Platform.objects.create(library=library, name="Amiga", group="Commodore")
    return Built(
        str(platform_row_menu(platform, origin=None)),
        {"Edit": reverse("games:edit_platform", args=[platform.pk])},
    )


def _game_menu(library: UserLibrary) -> Built:
    game = _game(library)
    return Built(
        str(game_row_menu(game, origin=None)),
        {"Edit": reverse("games:edit_game", args=[game.pk])},
    )


def _entry(library: UserLibrary):
    platform = Platform.objects.create(library=library, name="PS5", group="Sony")
    graph = default_graph(
        Game(name="Tunic", library=library), library, platform=platform
    )
    return record_entry(library, graph.release)


def _entry_menu(library: UserLibrary) -> Built:
    entry = _entry(library)
    return Built(
        str(entry_row_menu(entry, None, "token", purchases=[])),
        {
            "Edit…": reverse("games:edit_library_entry", args=[entry.pk]),
            "Add purchase…": reverse("games:add_purchase", args=[entry.pk]),
            "With details…": reverse("games:end_library_entry", args=[entry.pk]),
        },
    )


def _ended_entry_menu(library: UserLibrary) -> Built:
    entry = end_entry_access(_entry(library))
    return Built(
        str(entry_row_menu(entry, None, "token", purchases=[])),
        {
            "Edit how it left…": reverse(
                "games:edit_library_entry_end", args=[entry.pk]
            ),
            "With details…": reverse("games:resume_library_entry", args=[entry.pk]),
        },
    )


def _purchase_menu(library: UserLibrary) -> Built:
    purchase = record_purchase(_entry(library))
    return Built(
        "".join(str(item) for item in purchase_items(purchase, None, "token")),
        {"Edit purchase…": reverse("games:edit_purchase", args=[purchase.pk])},
    )


def _navbar_log_button(_library: UserLibrary) -> Built:
    """Log game with nothing to resume."""
    return Built(
        str(NavbarLogButton([], csrf_token="token", origin=None)),
        {"Log game": reverse("games:add_session")},
    )


type Case = tuple[Callable[[UserLibrary], Built], tuple[str, ...]]

#: Builder and unmarked acts.
CASES: dict[str, Case] = {
    "session": (_session_menu, ("Remove",)),
    "playthrough": (_playthrough_menu, ("Remove",)),
    "historical_playtime": (_historical_menu, ("Remove",)),
    "device": (_device_menu, ("Remove",)),
    "platform": (_platform_menu, ("Remove",)),
    "game": (_game_menu, ("Remove",)),
    "entry": (_entry_menu, ("Remove…", "Just mark it gone")),
    "ended_entry": (_ended_entry_menu, ("Remove…", "Just add it back")),
    "purchase": (_purchase_menu, ("Remove purchase…", "Refund")),
    "navbar_log_button": (_navbar_log_button, ()),
}


@pytest.mark.parametrize("name", list(CASES))
def test_named_links_open_in_the_dialog_and_the_rest_do_not(name, owned_library):
    build, unmarked = CASES[name]
    built = build(owned_library)

    for label, path in built.paths.items():
        found = _elements_named(built.html, label)
        assert found, f"no element names {label!r}"
        for attributes in found:
            assert MARKER.search(attributes), f"{label!r} is not a dialog link"
            assert _path(attributes) == path, f"{label!r} links elsewhere"

    for label in unmarked:
        found = _elements_named(built.html, label)
        assert found, f"no element names {label!r}"
        for attributes in found:
            assert not MARKER.search(attributes), f"{label!r} opens in the dialog"


#: The Library tab's Add links: overflow item and wide link each.
LIBRARY_ADD_ROUTES = (
    "games:add_game",
    "games:add_platform",
    "games:add_device",
    "games:add_to_library",
)


def test_the_library_tab_opens_its_add_links_in_the_dialog(client, owned_user):
    client.force_login(owned_user)
    html = client.get(reverse("games:library")).content.decode()

    for route in LIBRARY_ADD_ROUTES:
        found = [
            attributes
            for _, attributes, _ in ELEMENT.findall(html)
            if _path(attributes) == reverse(route)
        ]
        assert len(found) >= 2, f"{route} is linked fewer than twice"
        assert all(MARKER.search(attributes) for attributes in found)
