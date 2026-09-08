"""#1014: the statistics read a run."""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import (
    Game,
    PlayerGameStatus,
    PlayEvent,
    Playthrough,
    PlaythroughKind,
    Purchase,
)
from games.removal import remove
from games.views.stats_data import compute_stats
from games.writes.playergame import new_correlation_id, record_facts, track_game
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

YEAR = 2024


def _bought_and_completed(
    user, library, name: str, day: date | None = None
) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    track_game(user, game, correlation_id=new_correlation_id())
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=date(YEAR, 1, 5),
    )
    purchase.games.set([game])
    run = Playthrough.objects.get(player_game__game=game)
    if day is not None:
        Playthrough.objects.filter(pk=run.pk).update(
            completed=TemporalValue.from_day(day), completion_recorded_at=run.created_at
        )
        run.refresh_from_db()
    return run


def _open_bound_run(user, library, name: str) -> Playthrough:
    """A completion whose lower bound is absent."""
    run = _bought_and_completed(user, library, name)
    Playthrough.objects.filter(pk=run.pk).update(
        completed=TemporalValue.parse(f"../{YEAR}-05-01"),
        completion_recorded_at=run.created_at,
    )
    return run


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_leaves_the_backlog(owned_user, owned_library):
    _bought_and_completed(owned_user, owned_library, "Done", date(YEAR, 6, 1))

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 1
    assert data["purchased_unfinished_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_a_legacy_row_alone_counts_for_nothing(owned_user, owned_library):
    """The only test here writing PlayEvent."""
    run = _bought_and_completed(owned_user, owned_library, "Legacy only")
    PlayEvent.objects.create(
        game=run.player_game.game, ended=datetime(YEAR, 6, 1, tzinfo=UTC)
    )

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 0
    assert data["purchased_unfinished_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_counts_for_nothing(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Removed", date(YEAR, 6, 1))
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 0
    assert data["purchased_unfinished_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_completion_with_no_known_day_counts_all_time_only(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Dayless")
    Playthrough.objects.filter(pk=run.pk).update(completion_recorded_at=run.created_at)

    assert compute_stats(owned_library, YEAR)["all_finished_this_year_count"] == 0
    assert compute_stats(owned_library, None)["backlog_decrease_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_supplies_no_completion(owned_user, owned_library):
    run = _bought_and_completed(owned_user, owned_library, "Gone", date(YEAR, 6, 1))
    remove(run.player_game.game)

    assert compute_stats(owned_library, YEAR)["all_finished_this_year_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_a_year_reports_one_row_at_its_earliest_completion(owned_user, owned_library):
    """Two completions of one game, one row."""
    run = _bought_and_completed(owned_user, owned_library, "Twice", date(YEAR, 2, 1))
    second = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    Playthrough.objects.filter(pk=second.pk).update(
        completed=TemporalValue.from_day(date(YEAR, 11, 1)),
        completion_recorded_at=second.created_at,
    )

    data = compute_stats(owned_library, YEAR)
    rows = list(data["all_finished_this_year"])

    assert data["all_finished_this_year_count"] == 1
    assert [row.date_finished for row in rows] == [date(YEAR, 2, 1)]


@pytest.mark.django_db(transaction=True)
def test_a_bundle_reports_one_row_for_two_completed_games(owned_user, owned_library):
    first = _bought_and_completed(
        owned_user, owned_library, "Bundle A", date(YEAR, 3, 1)
    )
    second_game = Game.objects.create(library=owned_library, name="Bundle B")
    track_game(owned_user, second_game, correlation_id=new_correlation_id())
    second = Playthrough.objects.get(player_game__game=second_game)
    Playthrough.objects.filter(pk=second.pk).update(
        completed=TemporalValue.from_day(date(YEAR, 9, 1)),
        completion_recorded_at=second.created_at,
    )
    purchase = Purchase.objects.get(games=first.player_game.game)
    purchase.games.add(second_game)

    data = compute_stats(owned_library, YEAR)

    assert data["all_finished_this_year_count"] == 1
    assert [row.date_finished for row in data["all_finished_this_year"]] == [
        date(YEAR, 3, 1)
    ]


@pytest.mark.django_db(transaction=True)
def test_a_year_ascends_from_its_first_finish(owned_user, owned_library):
    _bought_and_completed(owned_user, owned_library, "Later", date(YEAR, 9, 1))
    _bought_and_completed(owned_user, owned_library, "Earlier", date(YEAR, 2, 1))

    rows = list(compute_stats(owned_library, YEAR)["all_finished_this_year"])

    assert [row.date_finished for row in rows] == [date(YEAR, 2, 1), date(YEAR, 9, 1)]


@pytest.mark.django_db(transaction=True)
def test_a_row_with_an_open_lower_bound_sorts_last(owned_user, owned_library):
    """A year's row that reports no day."""
    _bought_and_completed(owned_user, owned_library, "Dated", date(YEAR, 6, 1))
    _open_bound_run(owned_user, owned_library, "Open")

    rows = list(compute_stats(owned_library, YEAR)["all_finished_this_year"])

    assert [row.date_finished for row in rows] == [date(YEAR, 6, 1), None]


@pytest.mark.django_db(transaction=True)
def test_a_row_that_reports_no_day_renders(client, owned_user, owned_library):
    """The year page prints a row with no day."""
    _open_bound_run(owned_user, owned_library, "Open")
    client.force_login(owned_user)

    response = client.get(reverse("games:stats_by_year", args=[YEAR]))

    assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_a_bundle_leaves_the_backlog_once(owned_user, owned_library):
    """Two done games of one Purchase, one row."""
    first = _bought_and_completed(
        owned_user, owned_library, "Backlog A", date(YEAR, 3, 1)
    )
    purchase = Purchase.objects.get(games=first.player_game.game)
    purchase.date_purchased = date(YEAR - 1, 1, 5)
    purchase.save()
    second_game = Game.objects.create(library=owned_library, name="Backlog B")
    track_game(owned_user, second_game, correlation_id=new_correlation_id())
    second = Playthrough.objects.get(player_game__game=second_game)
    Playthrough.objects.filter(pk=second.pk).update(
        completed=TemporalValue.from_day(date(YEAR, 9, 1)),
        completion_recorded_at=second.created_at,
    )
    purchase.games.add(second_game)
    for game in (first.player_game.game, second_game):
        record_facts(
            owned_user,
            game,
            status=PlayerGameStatus.COMPLETED,
            correlation_id=new_correlation_id(),
        )

    assert compute_stats(owned_library, YEAR)["backlog_decrease_count"] == 1
