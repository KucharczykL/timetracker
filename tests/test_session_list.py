"""The session list reads the projection."""

import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from devices import create_device
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.list_columns import state_shown_columns
from games.models import Game, PlayerGame, Playthrough, PlaythroughKind
from games.views.session import SESSION_COLUMNS

pytestmark = pytest.mark.django_db

STARTED_AT = datetime(2026, 3, 5, 10, tzinfo=UTC)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _another_run(library, game, *, kind=PlaythroughKind.ORDINARY, name=""):
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=PlayerGame.objects.get(library=library, game=game),
        kind=kind,
        name=name,
        created_at=timezone.now(),
    )


def _rows(body: str) -> list[str]:
    return re.findall(r'<tr[^>]*id="session-row-[^"]+"[^>]*>.*?</tr>', body, re.DOTALL)


def _labels(body: str) -> list[str]:
    return re.findall(r'data-run-label=""[^>]*>([^<]*)<', body)


def _cells(row: str) -> list[str]:
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)


def _run_column(body: str) -> list[str]:
    """Each row's Playthrough cell, the first `<td>`."""
    names = []
    for row in _rows(body):
        clipped = re.findall(r'data-truncated-clip=""[^>]*>([^<]*)<', _cells(row)[0])
        names.append(clipped[0] if clipped else "")
    return names


def _headers(body: str) -> list[str]:
    """The table's own column headers."""
    header_rows = re.findall(r"<thead.*?</thead>", body, re.DOTALL)
    return re.findall(r"<th[^>]*>(?:.*?>)??([A-Za-z ]+)<", "".join(header_rows))


def _summaries(body: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", found).strip()
        for found in re.findall(
            r'data-row-summary=""[^>]*>(.*?)</div>', body, re.DOTALL
        )
    ]


def test_the_list_renders_every_mode_from_the_projection(
    logged_in, owned_library, game
):
    run = tracked_run(owned_library, game)
    timed_row(run, STARTED_AT, STARTED_AT + timedelta(hours=1))
    duration_only_row(run, date(2026, 3, 4), timedelta(minutes=30))
    timed_row(run, STARTED_AT + timedelta(days=1), None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert len(_rows(body)) == 3
    assert "Outer Wilds" in body
    #: The Duration-only row prints its day alone.
    assert "2026-03-04" in body or "04/03/2026" in body


def test_a_list_naming_one_game_names_the_run_in_its_own_column(
    logged_in, owned_library, game
):
    """The column replaces the name cell's label."""
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert "Playthrough" in body
    assert _run_column(body) == ["Playthrough 1"]
    assert _labels(body) == []


def test_a_game_with_two_live_runs_names_each_session(logged_in, owned_library, game):
    first = tracked_run(owned_library, game)
    second = _another_run(owned_library, game, name="Second run")
    timed_row(first, STARTED_AT, None)
    timed_row(second, STARTED_AT + timedelta(days=1), None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert sorted(_run_column(body)) == ["Playthrough 1", "Second run"]
    assert _labels(body) == []


def test_a_session_in_the_bucket_is_named_beside_a_live_run(
    logged_in, owned_library, game
):
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)
    bucket = _another_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    timed_row(bucket, STARTED_AT - timedelta(days=30), None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert sorted(_run_column(body)) == ["Imported history", "Playthrough 1"]


def _mixed_list(owned_library, game) -> None:
    """Two games, and two runs at one of them."""
    first = tracked_run(owned_library, game)
    second = _another_run(owned_library, game, name="Second run")
    timed_row(first, STARTED_AT, None)
    timed_row(second, STARTED_AT + timedelta(days=1), None)
    other = Game.objects.create(library=owned_library, name="Anodyne")
    timed_row(tracked_run(owned_library, other), STARTED_AT, None)


def test_a_list_naming_two_games_states_the_column_too(logged_in, owned_library, game):
    """The column is declared always; no page decides."""
    _mixed_list(owned_library, game)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert sorted(_run_column(body)) == [
        "Playthrough 1",
        "Playthrough 1",
        "Second run",
    ]
    assert _labels(body) == []


def test_a_person_hiding_the_column_is_named_no_run_anywhere(
    logged_in, owned_user, owned_library, game
):
    """Not beside the name, and not in the line below md."""
    _mixed_list(owned_library, game)
    state_shown_columns(
        owned_user, "sessions", ["name", "date", "duration", "device"], SESSION_COLUMNS
    )

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert "Playthrough" not in _headers(body)
    assert "Second run" not in body
    assert _labels(body) == []
    assert all("Second run" not in summary for summary in _summaries(body))


def test_the_summary_names_the_run_the_time_and_the_duration(
    logged_in, owned_library, game
):
    timed_row(
        tracked_run(owned_library, game), STARTED_AT, STARTED_AT + timedelta(hours=1)
    )

    body = logged_in.get(reverse("games:list_sessions")).content.decode()
    summary = _summaries(body)[0]

    assert summary.startswith("Playthrough 1, ")
    assert summary.count(",") >= 2


def test_the_summary_states_no_column_the_person_hid(
    logged_in, owned_user, owned_library, game
):
    """Below md every column but the first has dropped, so this line is the
    one place a hidden column could come back."""

    device = create_device(library=owned_library, name="Steam Deck")
    timed_row(
        tracked_run(owned_library, game),
        STARTED_AT,
        STARTED_AT + timedelta(hours=1),
        device=device,
    )
    state_shown_columns(
        owned_user, "sessions", ["name", "playthrough"], SESSION_COLUMNS
    )

    summary = _summaries(
        logged_in.get(reverse("games:list_sessions")).content.decode()
    )[0]

    assert summary == "Playthrough 1"


def test_the_summary_omits_a_device_the_session_does_not_name(
    logged_in, owned_library, game
):
    """A scarce line does not spend itself saying No device."""
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert "No device" not in _summaries(body)[0]


def test_the_summary_names_a_device_the_session_states(logged_in, owned_library, game):

    device = create_device(library=owned_library, name="Steam Deck")
    timed_row(tracked_run(owned_library, game), STARTED_AT, None, device=device)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert "Steam Deck" in _summaries(body)[0]


def test_the_list_costs_no_query_per_row(logged_in, owned_library):
    def seed(count: int) -> None:
        for index in range(count):
            other = Game.objects.create(library=owned_library, name=f"Game {index}")
            timed_row(tracked_run(owned_library, other), STARTED_AT, None)

    seed(2)
    with CaptureQueriesContext(connection) as few:
        logged_in.get(reverse("games:list_sessions"))
    seed(6)
    with CaptureQueriesContext(connection) as many:
        logged_in.get(reverse("games:list_sessions"))

    assert len(many) == len(few)


# --- The row menu and the tray ------------------------------------------------


def _tray_labels(body: str) -> list[str]:
    """Each act the selection line offers, in the order it lays them out."""
    slot = re.search(
        r'data-selection-actions=""(.*?)</selection-actions>', body, re.DOTALL
    )
    assert slot is not None
    return [
        re.sub(r"<[^>]+>", "", found).strip()
        for found in re.findall(
            r"<button[^>]*formaction=[^>]*>(.*?)</button>", slot.group(1), re.DOTALL
        )
    ]


def test_the_table_states_no_actions_column(logged_in, game, owned_library):
    timed_row(
        tracked_run(owned_library, game), STARTED_AT, STARTED_AT + timedelta(hours=1)
    )

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    headers = re.findall(r"<th[^>]*>(.*?)</th>", body, re.DOTALL)
    assert not any("Actions" in header for header in headers)


def test_each_row_states_its_own_menu(logged_in, game, owned_library):
    session = timed_row(
        tracked_run(owned_library, game), STARTED_AT, STARTED_AT + timedelta(hours=1)
    )

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert f'id="session-menu-{session.pk}"' in body


def test_the_tray_offers_four_acts_with_remove_last(logged_in, game, owned_library):
    timed_row(
        tracked_run(owned_library, game), STARTED_AT, STARTED_AT + timedelta(hours=1)
    )

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert _tray_labels(body) == [
        "Finish",
        "Move to playthrough…",
        "Record as historical playtime",
        "Remove",
    ]
