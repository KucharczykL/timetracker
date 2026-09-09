"""The completion a Purchase row reports."""

from datetime import date

import pytest
from completed_runs import add_game, add_run, make_purchase
from django.db.models import Subquery

from games.commands.playthrough import RemovePlaythrough
from games.events.dispatch import dispatch
from games.models import Purchase
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    reported_completion,
    reported_completion_day,
)
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def read(library, purchase):
    """The value and day the purchase reports."""
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
    """Both values start on 1 May."""
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
    """No lower bound still states words."""
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
    """A tracked game already holds one run."""
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
    """A subquery shares no join to narrow."""
    assert isinstance(reported_completion(owned_library, PURCHASE_RUNS), Subquery)
    assert isinstance(reported_completion_day(owned_library, PURCHASE_RUNS), Subquery)
