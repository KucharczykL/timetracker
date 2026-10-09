"""Unknown access is held, not owned."""

from zoneinfo import ZoneInfo

import pytest
from entries import record_entry
from graphs import default_graph

from common.components import AccessBadge
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.purchase import refund_ends_the_copy
from games.models import EditionKind, EntryAccess, Game, LibraryEntry, PurchaseKind
from games.reads.copy_figures import copies_matching, owned, owned_held
from games.reads.entries import AccessSummary
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

YEAR = 2021
PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def _record(library, name: str, access: str) -> LibraryEntry:
    game = Game(library=library, name=name)
    graph = default_graph(game, library, edition_kind=EditionKind.FULL)
    return record_entry(
        library,
        graph.release,
        access=access,
        acquired=TemporalValue.parse(f"{YEAR}-03-01"),
    )


def test_an_unknown_copy_is_not_an_owned_copy(owned_library):
    owned_copy = _record(owned_library, "Owned", "owned")
    unknown_copy = _record(owned_library, "Unknown", "unknown")

    held = set(copies_matching(owned_library, owned_held(YEAR)))
    counted = set(copies_matching(owned_library, owned(YEAR)))

    assert held == {owned_copy}
    assert counted == {owned_copy}
    assert unknown_copy not in counted


def test_an_unknown_copy_leaves_the_badge_hollow():
    unknown = LibraryEntry(access=EntryAccess.UNKNOWN, format="unknown")
    summary = AccessSummary(held=(unknown,), ended=())
    html = str(AccessBadge(summary, PRESENTATION, id="access-1"))

    assert summary.owned_now is False
    assert "solid-brand" not in html
    assert "border-default-medium" in html


def test_a_game_purchase_refund_ends_no_unknown_copy():
    unknown = LibraryEntry(access=EntryAccess.UNKNOWN, format="unknown")
    owned_entry = LibraryEntry(access=EntryAccess.OWNED, format="digital")

    assert refund_ends_the_copy(PurchaseKind.GAME, unknown) is False
    assert refund_ends_the_copy(PurchaseKind.GAME, owned_entry) is True
