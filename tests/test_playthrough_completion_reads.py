"""The completion a Purchase row reports."""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.db.models import Subquery

from games.commands.playergame import TrackGame
from games.commands.playthrough import (
    ActStatement,
    CompletePlaythrough,
    RemovePlaythrough,
)
from games.events.dispatch import dispatch
from games.models import Game, Playthrough, Purchase
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    reported_completion,
    reported_completion_day,
)
from games.removal import remove
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def make_purchase(library, name="Bundle"):
    return Purchase.objects.create(
        library=library,
        name=name,
        date_purchased=datetime(2020, 1, 1, tzinfo=UTC),
        price=0,
        price_currency="USD",
    )


def add_game(user, library, purchase, name, completed):
    """Track a game the purchase names, and state its completion."""
    game = Game.objects.create(library=library, name=name)
    purchase.games.add(game)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key=f"track-{name}",
    )
    run = Playthrough.objects.get(player_game__game=game)
    if completed is not False:
        dispatch(
            CompletePlaythrough(playthrough_id=run.pk, when=completed, note=""),
            actor=user,
            library=library,
            idempotency_key=f"done-{name}",
        )
    return game, run


def add_run(user, game, completed):
    """State one more run at a game the library tracks.

    The game's first run states a completion already, so
    `run_to_adopt` refuses it and this creates a second.
    False is a run that reached no completion.
    """
    record_run(
        user,
        game,
        RunDraft(
            started=None,
            completed=None if completed is False else ActStatement(completed),
            note="",
        ),
        correlation_id=uuid.uuid7(),
    )


def read(library, purchase):
    """The value and the day the purchase reports."""
    row = (
        Purchase.objects.for_library(library)
        .annotate(
            value=reported_completion(library, PURCHASE_RUNS),
            day=reported_completion_day(library, PURCHASE_RUNS),
        )
        .get(pk=purchase.pk)
    )
    return row.value, row.day


@pytest.mark.django_db(transaction=True)
def test_the_latest_completion_is_reported(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Early",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Late",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2024, 7, 1))
    assert day == date(2024, 7, 1)


@pytest.mark.django_db(transaction=True)
def test_a_dated_completion_outranks_a_dayless_one(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 3, 4))
    assert day == date(2020, 3, 4)


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_alone_reports_no_day(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    value, day = read(owned_library, purchase)

    assert value is None
    assert day is None


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_completion_reports_nothing(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Playing", False)

    assert read(owned_library, purchase) == (None, None)


@pytest.mark.django_db(transaction=True)
def test_a_narrower_interval_wins_a_shared_lower_bound(owned_user, owned_library):
    """`2020-05-01` and `2020-05` both start on 1 May."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user, owned_library, purchase, "Month", TemporalValue.from_month(2020, 5)
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Day",
        TemporalValue.from_day(date(2020, 5, 1)),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 5, 1))
    assert day == date(2020, 5, 1)


@pytest.mark.django_db(transaction=True)
def test_an_open_start_range_reports_no_day(owned_user, owned_library):
    """A completion with no lower bound still states words."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Open",
        TemporalValue.parse("../2020-05-01"),
    )

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.parse("../2020-05-01")
    assert day is None


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_reports_nothing(owned_user, owned_library):
    """A tracked game holds one run, so the game gains a second first."""
    purchase = make_purchase(owned_library)
    game, run = add_game(
        owned_user,
        owned_library,
        purchase,
        "Gone",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_run(owned_user, game, completed=False)
    dispatch(
        RemovePlaythrough(playthrough_id=run.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove",
    )

    value, day = read(owned_library, purchase)

    assert value is None
    assert day is None


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_leaves_the_live_one_reporting(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    gone, _ = add_game(
        owned_user,
        owned_library,
        purchase,
        "Gone",
        TemporalValue.from_day(date(2024, 7, 1)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Live",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    remove(gone)

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2020, 3, 4))
    assert day == date(2020, 3, 4)


@pytest.mark.django_db(transaction=True)
def test_another_librarys_run_reports_nothing(
    owned_user, owned_library, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Mine",
        TemporalValue.from_day(date(2020, 3, 4)),
    )

    row = (
        Purchase.objects.for_library(owned_library)
        .annotate(value=reported_completion(stranger.library, PURCHASE_RUNS))
        .get(pk=purchase.pk)
    )

    assert row.value is None


@pytest.mark.django_db(transaction=True)
def test_a_second_run_at_one_game_reports_the_later(owned_user, owned_library):
    purchase = make_purchase(owned_library)
    game, _ = add_game(
        owned_user,
        owned_library,
        purchase,
        "Twice",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_run(owned_user, game, TemporalValue.from_day(date(2024, 7, 1)))

    value, day = read(owned_library, purchase)

    assert value == TemporalValue.from_day(date(2024, 7, 1))
    assert day == date(2024, 7, 1)


@pytest.mark.django_db(transaction=True)
def test_the_readers_are_subqueries(owned_library):
    """A subquery shares no join, so a filter cannot narrow it."""
    assert isinstance(reported_completion(owned_library, PURCHASE_RUNS), Subquery)
    assert isinstance(reported_completion_day(owned_library, PURCHASE_RUNS), Subquery)
