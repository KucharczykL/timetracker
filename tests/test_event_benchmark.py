"""The benchmark harness: percentiles, counting, budgets, scenarios."""

import uuid

import pytest
from django.db import connection, transaction

from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.benchmark import (
    BudgetVerdict,
    Environment,
    SeedReport,
    StatementCounter,
    Timings,
    command_budget,
    environment,
    nearest_rank,
    rebuild_budget,
    summarize,
)
from games.events.benchmark_workload import seed_library, spare_games
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildAttempt, RebuildMode, RebuildReport
from games.models import Game, LibraryEvent, LibraryEventStreamHead, PlayerGame


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


@pytest.mark.django_db
def test_the_environment_records_what_the_numbers_are_true_of():
    captured = environment()
    assert isinstance(captured, Environment)
    assert captured.cpu_count >= 1
    assert captured.python_version.startswith("3.14")
    #: Same hardware, two tunings, two rebuild times.
    assert captured.shared_buffers
    assert captured.work_mem
    assert captured.postgresql_version


def timings(p95: float, *, samples: int = 200) -> Timings:
    return Timings(samples=samples, p50=p95 / 2, p95=p95, maximum=p95 * 2)


def attempt(
    *, seconds: float, folded_through: int = 0, conflict: str | None = None
) -> RebuildAttempt:
    """One pass whose three phases sum to `seconds`."""
    return RebuildAttempt(
        folded_through=folded_through,
        replay_seconds=seconds * 0.8,
        diff_seconds=seconds * 0.15,
        swap_seconds=seconds * 0.05,
        conflict=conflict,
    )


def rebuild_report(
    *,
    folded_through: int,
    elapsed_seconds: float,
    attempts: tuple[RebuildAttempt, ...] | None = None,
) -> RebuildReport:
    return RebuildReport(
        library_id=uuid.uuid7(),
        stream_id=uuid.uuid7(),
        mode=RebuildMode.REBUILD,
        swapped=True,
        folded_through=folded_through,
        head_at_diff=folded_through,
        tables=(),
        attempts=(
            (attempt(seconds=elapsed_seconds, folded_through=folded_through),)
            if attempts is None
            else attempts
        ),
        elapsed_seconds=elapsed_seconds,
    )


def test_a_command_inside_the_budget_passes():
    assert command_budget(timings(0.05)).verdict is BudgetVerdict.PASSED


def test_a_command_over_the_budget_misses():
    assert command_budget(timings(0.15)).verdict is BudgetVerdict.MISSED


def test_too_few_samples_is_not_gated_but_is_still_measured():
    budget = command_budget(timings(0.15, samples=19))
    assert budget.verdict is BudgetVerdict.NOT_GATED
    assert budget.measured == 0.15


def test_the_rebuild_budget_scales_to_the_events_actually_folded():
    #: 60s per 100k, so 10k gets 6s.
    budget = rebuild_budget(rebuild_report(folded_through=10_000, elapsed_seconds=5.9))
    assert budget.limit == pytest.approx(6.0)
    assert budget.verdict is BudgetVerdict.PASSED


def test_a_rebuild_over_its_scaled_budget_misses():
    budget = rebuild_budget(rebuild_report(folded_through=10_000, elapsed_seconds=6.5))
    assert budget.verdict is BudgetVerdict.MISSED


def test_a_retried_rebuild_is_charged_only_its_last_pass():
    """Three passes that each met the budget are not one pass that missed."""
    budget = rebuild_budget(
        rebuild_report(
            folded_through=10_000,
            elapsed_seconds=18.0,
            attempts=(
                attempt(seconds=5.8, conflict="the head moved"),
                attempt(seconds=5.9, conflict="the head moved"),
                attempt(seconds=5.5),
            ),
        )
    )
    assert budget.measured == pytest.approx(5.5)
    assert budget.verdict is BudgetVerdict.PASSED


def test_a_rebuild_below_the_gating_floor_is_not_gated():
    #: Scaling is verified linear from 2,000 up, not below.
    budget = rebuild_budget(rebuild_report(folded_through=1_999, elapsed_seconds=99.0))
    assert budget.verdict is BudgetVerdict.NOT_GATED
    assert budget.measured == pytest.approx(99.0)


@pytest.mark.django_db
def test_seeding_writes_the_events_and_the_projection_rows(owned_library):
    report = seed_library(owned_library, actor=owned_library.user, events=25, spares=4)
    assert isinstance(report, SeedReport)
    assert report.events == 25
    assert report.catalog_rows == 29
    assert LibraryEvent.objects.filter(library=owned_library).count() == 25
    #: append() folds inline, so the live rows exist already.
    assert PlayerGame.objects.filter(library=owned_library).count() == 25


@pytest.mark.django_db
def test_seeding_batches_the_stream_rather_than_locking_per_event(owned_library):
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    head = LibraryEventStreamHead._meta.db_table
    #: One batch, two writes: lock_stream inserts the head that did not
    #: exist, then append advances current_sequence once. A second batch
    #: would add one UPDATE, not two statements.
    assert counter.statements_per_table[head] == 2


@pytest.mark.django_db
def test_a_second_batch_only_advances_the_head(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=1, spares=0)
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        with transaction.atomic():
            lock_stream(owned_library)
    head = LibraryEventStreamHead._meta.db_table
    #: The head exists now, so get_or_create reads and writes nothing.
    assert head not in counter.statements_per_table


@pytest.mark.django_db
def test_seeding_leaves_the_spare_games_untracked(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=5, spares=3)
    spares = list(spare_games(owned_library))
    assert len(spares) == 3
    assert not PlayerGame.objects.filter(game__in=spares).exists()


@pytest.mark.django_db
def test_seeding_reports_append_throughput(owned_library):
    report = seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    assert report.events_per_second > 0
    assert report.append_seconds > 0
    #: Setup is timed apart from the measurement.
    assert report.catalog_seconds > 0
