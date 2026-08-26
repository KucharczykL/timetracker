"""The benchmark harness: percentiles, counting, budgets, scenarios."""

import uuid

import pytest
from django.db import connection

from games.commands.playergame import TrackGame
from games.events.benchmark import (
    StatementCounter,
    Timings,
    nearest_rank,
    summarize,
)
from games.events.dispatch import dispatch
from games.models import Game, PlayerGame


def track_one_game(library, *, name: str = "Benchmark probe") -> Game:
    """Dispatch one real TrackGame against a fresh catalog row.

    Every caller must be marked django_db(transaction=True): dispatch
    refuses to run inside an enclosing atomic block.
    """
    game = Game.objects.create(library=library, name=name)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return game


def test_nearest_rank_returns_an_observation_for_one_sample():
    assert nearest_rank([0.5], 95) == 0.5


def test_nearest_rank_never_interpolates_between_two_observations():
    #: statistics.quantiles would answer 0.15 here.
    assert nearest_rank([0.1, 0.2], 50) == 0.1


def test_nearest_rank_can_land_on_the_last_observation():
    samples = [float(value) for value in range(1, 11)]
    assert nearest_rank(samples, 95) == 10.0


def test_nearest_rank_sorts_before_ranking():
    assert nearest_rank([0.3, 0.1, 0.2], 50) == 0.2


def test_nearest_rank_refuses_an_empty_sample_set():
    with pytest.raises(ValueError, match="at least one sample"):
        nearest_rank([], 95)


def test_summarize_reports_the_count_the_tail_and_the_worst():
    samples = [float(value) for value in range(1, 21)]
    assert summarize(samples) == Timings(samples=20, p50=10.0, p95=19.0, maximum=20.0)


@pytest.mark.django_db
def test_the_counter_attributes_an_insert_an_update_and_a_delete():
    """Counting statements is what makes an in-place update visible."""
    counter = StatementCounter()
    with connection.execute_wrapper(counter), connection.cursor() as cursor:
        cursor.execute('CREATE TEMP TABLE "counter_probe" (id integer PRIMARY KEY)')
        cursor.execute('INSERT INTO "counter_probe" (id) VALUES (1), (2)')
        cursor.execute('UPDATE "counter_probe" SET id = id + 10')
        cursor.execute('DELETE FROM "counter_probe" WHERE id = 11')
    assert counter.statements == 4
    #: CREATE names no write keyword, so it is counted but not attributed.
    assert counter.statements_per_table == {"counter_probe": 3}
    assert counter.rows_per_table == {"counter_probe": 5}


@pytest.mark.django_db
def test_the_counter_attributes_nothing_to_a_statement_that_only_reads():
    counter = StatementCounter()
    table = PlayerGame._meta.db_table
    with connection.execute_wrapper(counter), connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
    assert counter.statements_per_table == {}
    assert counter.statements == 1


@pytest.mark.django_db
def test_the_counter_counts_statements_that_name_no_table():
    counter = StatementCounter()
    with connection.execute_wrapper(counter), connection.cursor() as cursor:
        cursor.execute("SAVEPOINT benchmark_probe")
        cursor.execute("RELEASE SAVEPOINT benchmark_probe")
    assert counter.statements == 2
    assert counter.statements_per_table == {}


@pytest.mark.django_db(transaction=True)
def test_the_counter_separates_projections_from_the_event_store(owned_library):
    #: One tracked game: one projection row, one event, one reference.
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        track_one_game(owned_library)
    work = counter.work(events=1)
    assert work.projection_rows == 1
    assert work.projection_statements == 1
    assert work.event_store_rows >= 3
    assert work.statements > work.projection_statements
