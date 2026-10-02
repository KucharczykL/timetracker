"""The registered ways to name a projection row."""

from datetime import UTC, datetime

import pytest
from django.utils import timezone
from session_rows import timed_row, tracked_run

from games.models import Game, PlayerGame, PlayerSession, Playthrough
from games.reads import referrers
from games.reads.referrers import (
    BLOCKING_REFERRERS,
    BlockingReferrer,
    CascadingReferrer,
    blocking_referrer,
    referrers_of,
    rows_naming,
)

pytestmark = pytest.mark.django_db

STARTED_AT = datetime(2026, 3, 5, 10, tzinfo=UTC)

#: The member a session answers.
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


def test_on_refuses_a_field_naming_another_model_than_the_target():
    with pytest.raises(TypeError, match="names Playthrough, not a playergame"):
        BlockingReferrer.on(
            PlayerSession, "playthrough", target=PlayerGame, sentence="unused"
        )


@pytest.mark.parametrize(
    ("model", "field_name", "target", "match"),
    [
        (PlayerSession, "note", Playthrough, "not a foreign key"),
        (PlayerSession, "playthrough", PlayerGame, "not a playergame"),
        (Playthrough, "player_game", PlayerGame, "states no alive"),
    ],
    ids=["not-a-key", "wrong-target", "no-alive"],
)
def test_every_construction_refuses_a_malformed_member(
    model, field_name, target, match
):
    with pytest.raises(TypeError, match=match):
        CascadingReferrer.on(model, field_name, target=target)
    with pytest.raises(TypeError, match=match):
        BlockingReferrer(model, field_name, target, "unused")


def test_referrers_of_reads_the_patched_tuple(monkeypatch):
    assert referrers_of(Playthrough) == BLOCKING_REFERRERS[:2]
    assert referrers_of(PlayerGame) == ()
    monkeypatch.setattr(referrers, "BLOCKING_REFERRERS", (SESSION_REFERRER,))
    assert referrers_of(Playthrough) == (SESSION_REFERRER,)


def test_rows_naming_refuses_a_row_of_another_model(owned_library, game):
    run = tracked_run(owned_library, game)
    with pytest.raises(TypeError, match="names a Playthrough, not a PlayerGame"):
        rows_naming(SESSION_REFERRER, run.player_game)
