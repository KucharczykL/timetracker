"""The session list reads the projection."""

import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.models import Game, PlayerGame, Playthrough, PlaythroughKind

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


def test_a_game_with_one_run_shows_no_run_label(logged_in, owned_library, game):
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert _labels(body) == []


def test_a_game_with_two_live_runs_labels_each_session(logged_in, owned_library, game):
    first = tracked_run(owned_library, game)
    second = _another_run(owned_library, game, name="Second run")
    timed_row(first, STARTED_AT, None)
    timed_row(second, STARTED_AT + timedelta(days=1), None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert sorted(_labels(body)) == ["Playthrough 1", "Second run"]


def test_a_session_in_the_bucket_is_labelled_beside_a_live_run(
    logged_in, owned_library, game
):
    timed_row(tracked_run(owned_library, game), STARTED_AT, None)
    bucket = _another_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    timed_row(bucket, STARTED_AT - timedelta(days=30), None)

    body = logged_in.get(reverse("games:list_sessions")).content.decode()

    assert sorted(_labels(body)) == ["Imported history", "Playthrough 1"]


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
