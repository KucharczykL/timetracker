"""The registered ways to name a run."""

from datetime import UTC, datetime

import pytest
from django.utils import timezone
from session_rows import timed_row, tracked_run

from games.models import Game, PlayerSession
from games.reads.playthrough_referrers import (
    BLOCKING_REFERRERS,
    blocking_referrer,
    rows_naming,
)

pytestmark = pytest.mark.django_db

STARTED_AT = datetime(2026, 3, 5, 10, tzinfo=UTC)

#: The entry a session answers.
SESSION_REFERRER = BLOCKING_REFERRERS[0]


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def test_rows_naming_finds_a_live_session(owned_library, game):
    run = tracked_run(owned_library, game)
    session = timed_row(run, STARTED_AT, None)

    assert list(rows_naming(SESSION_REFERRER, run)) == [session]


def test_rows_naming_finds_a_removed_session_the_live_read_skips(owned_library, game):
    run = tracked_run(owned_library, game)
    session = timed_row(run, STARTED_AT, None)
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert blocking_referrer(run) is None
    assert list(rows_naming(SESSION_REFERRER, run)) == [session]


def test_rows_naming_finds_a_row_of_another_library(
    owned_library, game, django_user_model
):
    run = tracked_run(owned_library, game)
    other = django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library
    session = timed_row(run, STARTED_AT, None)
    PlayerSession.objects.filter(pk=session.pk).update(library=other)

    assert list(rows_naming(SESSION_REFERRER, run)) == [
        PlayerSession.objects.get(pk=session.pk)
    ]


def test_rows_naming_answers_nothing_for_an_unnamed_run(owned_library, game):
    run = tracked_run(owned_library, game)

    assert not rows_naming(SESSION_REFERRER, run).exists()
