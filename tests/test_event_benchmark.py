"""The benchmark harness: percentiles, counting, budgets, scenarios."""

import json
import uuid
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.utils import timezone

from games.commands.playergame import TrackGame
from games.events import benchmark as benchmark_module
from games.events.append import lock_stream
from games.events.benchmark import (
    BenchmarkReport,
    BudgetVerdict,
    Environment,
    RebuildDiffNotEmpty,
    SeedReport,
    StatementCounter,
    Timings,
    command_budget,
    environment,
    nearest_rank,
    rebuild_budget,
    summarize,
)
from games.events.benchmark_run import run_benchmark
from games.events.benchmark_workload import (
    purge_scratch_user,
    run_amplification_scenario,
    run_command_scenario,
    run_rebuild_scenario,
    seed_library,
    spare_games,
)
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildAttempt, RebuildMode, RebuildReport
from games.events.targets import SHADOW_SUFFIX
from games.models import (
    Game,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
)


def track_one_game(library, *, name: str = "Benchmark probe") -> Game:
    """Dispatch one TrackGame against a fresh row.

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
    """Statements are what make an update visible."""
    counter = StatementCounter()
    with connection.execute_wrapper(counter), connection.cursor() as cursor:
        cursor.execute('CREATE TEMP TABLE "counter_probe" (id integer PRIMARY KEY)')
        cursor.execute('INSERT INTO "counter_probe" (id) VALUES (1), (2)')
        cursor.execute('UPDATE "counter_probe" SET id = id + 10')
        cursor.execute('DELETE FROM "counter_probe" WHERE id = 11')
    assert counter.statements == 4
    #: CREATE is counted, but not attributed.
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
    #: One game: one row in each table.
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
    """One pass whose phases sum to `seconds`."""
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
    """Three passes that met it are not one miss."""
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
    #: Scaling is verified linear from 2,000 up.
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
    #: append() folds inline; the rows exist already.
    assert PlayerGame.objects.filter(library=owned_library).count() == 25


@pytest.mark.django_db
def test_seeding_batches_the_stream_rather_than_locking_per_event(owned_library):
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    head = LibraryEventStreamHead._meta.db_table
    #: One batch, two writes: the insert, then the advance.
    #: A second batch adds one UPDATE, not two.
    assert counter.statements_per_table[head] == 2


@pytest.mark.django_db
def test_a_second_batch_only_advances_the_head(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=1, spares=0)
    counter = StatementCounter()
    with connection.execute_wrapper(counter), transaction.atomic():
        lock_stream(owned_library)
    head = LibraryEventStreamHead._meta.db_table
    #: The head exists, so get_or_create writes nothing.
    assert head not in counter.statements_per_table


@pytest.mark.django_db
def test_seeding_leaves_the_spare_games_untracked(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=5, spares=3)
    spares = list(spare_games(owned_library))
    assert len(spares) == 3
    assert not PlayerGame.objects.filter(game__in=spares).exists()


@pytest.mark.django_db(transaction=True)
def test_seeding_leaves_statistics_that_know_the_rows_exist(owned_library):
    """Otherwise the command scenario races autovacuum's naptime."""
    seed_library(owned_library, actor=owned_library.user, events=25, spares=0)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT reltuples FROM pg_class WHERE relname = %s",
            [PlayerGame._meta.db_table],
        )
        estimated = cursor.fetchone()[0]

    assert estimated == 25


@pytest.mark.django_db
def test_seeding_reports_append_throughput(owned_library):
    report = seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    assert report.events_per_second > 0
    assert report.append_seconds > 0
    #: Setup is timed apart from the measurement.
    assert report.catalog_seconds > 0


@pytest.mark.django_db(transaction=True)
def test_the_scratch_user_is_purged_and_the_purge_is_timed(owned_library):
    username = owned_library.user.username
    track_one_game(owned_library, name="Purged by the harness")
    elapsed = purge_scratch_user(username)
    assert elapsed > 0
    assert not User.objects.filter(username=username).exists()


@pytest.mark.django_db(transaction=True)
def test_warmup_samples_are_additional_and_are_not_recorded(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=5, spares=7)
    timings = run_command_scenario(
        owned_library,
        actor=owned_library.user,
        games=spare_games(owned_library),
        iterations=5,
        warmup=2,
    )
    #: 7 dispatched, 5 recorded.
    assert timings.samples == 5
    assert PlayerGame.objects.filter(library=owned_library).count() == 12


@pytest.mark.django_db(transaction=True)
def test_one_dispatch_writes_one_projection_row_through_one_statement(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=0, spares=1)
    work = run_amplification_scenario(
        owned_library,
        actor=owned_library.user,
        games=spare_games(owned_library),
        iterations=1,
    )
    assert work.projection_rows == 1
    assert work.projection_statements == 1
    rows = work.rows_per_table
    assert rows[LibraryEvent._meta.db_table] == 1
    assert rows[LibraryEventReference._meta.db_table] == 1
    assert rows[LibraryIdempotencyRecord._meta.db_table] >= 1
    #: events=0 seeded no head: two rows, not one.
    assert rows[LibraryEventStreamHead._meta.db_table] == 2
    assert work.event_store_rows == 4 + rows[LibraryIdempotencyRecord._meta.db_table]


@pytest.mark.django_db
def test_folding_one_event_costs_one_statement(django_user_model):
    """The fold is one upsert.

    A rebuild also pays 13 fixed statements, so ten events average 2.3. The
    slope between two sizes is the per-event number, and it is exact.
    """
    totals: dict[int, int] = {}
    for events in (10, 30):
        user = django_user_model.objects.create_user(username=f"fold-{events}")
        seed_library(user.library, actor=user, events=events, spares=0)
        _report, fold = run_rebuild_scenario(
            user.library, mode=RebuildMode.REBUILD, count_fold=True
        )
        assert fold is not None
        totals[events] = fold.statements
    assert (totals[30] - totals[10]) / 20 == pytest.approx(1.0, abs=0.01)


@pytest.mark.django_db
def test_the_fold_counts_the_shadow_table_as_its_projection(owned_library):
    """A replay writes the shadow; the swap writes live."""
    seed_library(owned_library, actor=owned_library.user, events=10, spares=0)
    _report, fold = run_rebuild_scenario(
        owned_library, mode=RebuildMode.REBUILD, count_fold=True
    )
    assert fold is not None
    live = PlayerGame._meta.db_table
    shadow = f"{live}{SHADOW_SUFFIX}"
    assert fold.statements_per_table[shadow] == 10
    assert fold.projection_statements == (
        fold.statements_per_table[shadow] + fold.statements_per_table[live]
    )


@pytest.mark.django_db(transaction=True)
def test_a_run_folds_the_events_both_write_paths_produced():
    report = run_benchmark(seed=30, iterations=3, warmup=1, keep=True)
    #: 30 seeded, 4 dispatched, 3 amplified.
    assert report.rebuild.folded_through == 37
    assert all(
        table.only_live == table.only_rebuilt == table.differing == 0
        for table in report.rebuild.tables
    )


@pytest.mark.django_db(transaction=True)
def test_a_run_purges_its_scratch_user_after_a_scenario_raises(monkeypatch):
    """No plug point left; a monkeypatch is the seam."""
    from games.events import benchmark_run as run_module

    def explode(*args, **kwargs):
        raise RuntimeError("the scenario failed")

    monkeypatch.setattr(run_module, "run_command_scenario", explode)
    before = set(User.objects.values_list("username", flat=True))
    with pytest.raises(RuntimeError, match="the scenario failed"):
        run_benchmark(seed=5, iterations=2, warmup=0)
    assert set(User.objects.values_list("username", flat=True)) == before


@pytest.mark.django_db(transaction=True)
def test_a_kept_run_names_its_scratch_user_before_it_can_fail():
    """--keep prints the cleanup, even when raising."""
    announced: list[str] = []
    report = run_benchmark(
        seed=5,
        iterations=1,
        warmup=0,
        keep=True,
        announce_scratch_user=announced.append,
    )
    assert announced == [report.scratch_username]
    assert User.objects.filter(username=report.scratch_username).exists()


@pytest.mark.django_db(transaction=True)
def test_no_count_fold_leaves_the_fold_unmeasured():
    report = run_benchmark(seed=5, iterations=1, warmup=0, count_fold=False)
    assert report.fold is None
    assert report.rebuild is not None


@pytest.mark.django_db
def test_library_mode_writes_no_persistent_row(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=6, spares=0)
    before = set(
        PlayerGame.objects.filter(library=owned_library).values_list("id", flat=True)
    )
    head_before = LibraryEventStreamHead.objects.get(
        library=owned_library
    ).current_sequence
    report = run_benchmark(seed=0, iterations=0, warmup=0, library=owned_library)
    assert report.seed is None
    assert report.command is None
    assert report.scratch_username is None
    assert (
        set(
            PlayerGame.objects.filter(library=owned_library).values_list(
                "id", flat=True
            )
        )
        == before
    )
    assert (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
        == head_before
    )


@pytest.mark.django_db
def test_a_non_empty_rebuild_diff_fails_the_run(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=6, spares=0)
    #: A row the replay will not produce.
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=Game.objects.create(library=owned_library, name="Unfolded"),
        tracked_at=timezone.now(),
    )
    with pytest.raises(RebuildDiffNotEmpty):
        run_benchmark(seed=0, iterations=0, warmup=0, library=owned_library)


@pytest.mark.django_db(transaction=True)
def test_the_report_carries_every_scenario_and_a_schema():
    report = run_benchmark(seed=25, iterations=3, warmup=1)
    assert isinstance(report, BenchmarkReport)
    assert report.schema == 1
    assert report.seed is not None
    assert report.command is not None
    assert report.amplification is not None
    assert report.fold is not None
    assert report.teardown_seconds is not None
    parsed = json.loads(report.as_json())
    assert parsed["schema"] == 1
    assert set(parsed) >= {
        "environment",
        "scratch_username",
        "seed",
        "command",
        "amplification",
        "fold",
        "rebuild",
        "teardown_seconds",
        "budgets",
    }


def run_command(**options) -> str:
    output = StringIO()
    call_command("benchmark_events", stdout=output, **options)
    return output.getvalue()


@pytest.mark.django_db
def test_seed_and_library_together_are_refused(owned_library):
    with pytest.raises(CommandError, match="--seed and --library"):
        run_command(seed=10, library=str(owned_library.pk))


@pytest.mark.django_db
def test_an_unknown_library_is_named():
    with pytest.raises(CommandError, match="No library"):
        run_command(library=str(uuid.uuid7()))


@pytest.mark.django_db(transaction=True)
def test_the_command_prints_what_it_will_create_before_creating_it():
    output = run_command(seed=25, iterations=2, warmup=1)
    assert "25" in output
    #: A three-minute default says so first.
    assert "estimate" in output.lower()


@pytest.mark.django_db(transaction=True)
def test_gate_raises_on_a_missed_budget(monkeypatch):
    """25 samples clear the floor; no seeding needed."""
    monkeypatch.setattr(benchmark_module, "COMMAND_BUDGET_SECONDS", 0.0)
    with pytest.raises(CommandError, match="budget"):
        run_command(seed=0, iterations=25, warmup=1, gate=True)


@pytest.mark.django_db(transaction=True)
def test_gate_is_silent_when_every_budget_passes():
    #: Below both floors: NOT_GATED is not MISSED.
    run_command(seed=25, iterations=2, warmup=1, gate=True)


@pytest.mark.django_db(transaction=True)
def test_json_output_parses_and_carries_the_schema():
    parsed = json.loads(run_command(seed=25, iterations=2, warmup=1, json=True))
    assert parsed["schema"] == 1


@pytest.mark.django_db(transaction=True)
def test_keep_names_the_scratch_user_it_leaves_behind():
    output = run_command(seed=10, iterations=1, warmup=0, keep=True)
    assert "delete_user_library" in output
    assert User.objects.filter(username__startswith="benchmark-").exists()
