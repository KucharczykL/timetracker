"""Order the scenarios; remove the scratch library."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace

from django.contrib.auth.models import User

from games.events.benchmark import (
    REPORT_SCHEMA,
    BenchmarkReport,
    RebuildDiffNotEmpty,
    bulk_command_budget,
    command_budget,
    environment,
    read_budget,
    rebuild_budget,
    record_command_budget,
    session_command_budget,
)
from games.events.benchmark_workload import (
    purge_scratch_user,
    run_amplification_scenario,
    run_bulk_command_scenario,
    run_command_scenario,
    run_read_scenario,
    run_rebuild_scenario,
    run_record_command_scenario,
    run_session_command_scenario,
    seed_library,
    seeded_runs,
    spare_games,
)
from games.events.rebuild import RebuildMode, RebuildReport
from games.models import UserLibrary

logger = logging.getLogger(__name__)

SCRATCH_USERNAME_PREFIX = "benchmark-"


def run_benchmark(
    *,
    seed: int,
    iterations: int,
    warmup: int,
    records: int,
    bulk: int,
    library: UserLibrary | None = None,
    keep: bool = False,
    count_replay: bool = True,
    announce_scratch_user: Callable[[str], None] | None = None,
) -> BenchmarkReport:
    """Seed a library, measure it, remove it.

    With `library`, run the read scenario and the read-only rebuild
    against one that exists, dispatch nothing, and ignore `seed` and
    `records`.

    `announce_scratch_user` takes the username as soon as the user exists,
    before any scenario can fail. --keep needs it: a run that raises leaves
    the library behind, and the operator has to be told its name.
    """
    if library is not None:
        return _measure_existing(
            library, iterations=iterations, warmup=warmup, count_replay=count_replay
        )
    username = f"{SCRATCH_USERNAME_PREFIX}{uuid.uuid7()}"
    user = User.objects.create_user(username=username)
    if announce_scratch_user is not None:
        announce_scratch_user(username)
    purged = False
    try:
        report = _measure_scratch(
            user,
            seed=seed,
            iterations=iterations,
            warmup=warmup,
            records=records,
            bulk=bulk,
            count_replay=count_replay,
        )
        teardown = None if keep else purge_scratch_user(username)
        purged = True
        return replace(report, teardown_seconds=teardown)
    finally:
        if not purged and not keep:
            try:
                purge_scratch_user(username)
            except Exception:
                #: Never mask the failure underneath.
                logger.exception("Could not purge scratch user %s.", username)


def _measure_scratch(
    user: User,
    *,
    seed: int,
    iterations: int,
    warmup: int,
    records: int,
    bulk: int,
    count_replay: bool,
) -> BenchmarkReport:
    library = user.library
    spares = 2 * iterations + warmup
    #: `seed` counts events; the seed takes games.
    seeded = seed_library(library, actor=user, games=seed // 3, spares=spares)
    #: One iterator; islice leaves the next spares.
    games = spare_games(library)
    command = run_command_scenario(
        library, actor=user, games=games, iterations=iterations, warmup=warmup
    )
    amplification = run_amplification_scenario(
        library, actor=user, games=games, iterations=iterations
    )
    session_command = run_session_command_scenario(
        library,
        actor=user,
        runs=seeded_runs(library),
        iterations=iterations,
        warmup=warmup,
    )
    record_command = run_record_command_scenario(
        library,
        actor=user,
        runs=seeded_runs(library),
        records=records,
        warmup=warmup,
    )
    bulk_command = run_bulk_command_scenario(
        library, actor=user, sessions=bulk, warmup=warmup
    )
    reads = run_read_scenario(library, iterations=iterations, warmup=warmup)
    rebuild, replay = run_rebuild_scenario(
        library, mode=RebuildMode.REBUILD, count_replay=count_replay
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        scratch_username=user.username,
        seed=seeded,
        command=command,
        session_command=session_command,
        record_command=record_command,
        bulk_command=bulk_command,
        reads=reads,
        amplification=amplification,
        replay=replay,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(
            command_budget(command),
            session_command_budget(session_command),
            record_command_budget(record_command),
            bulk_command_budget(bulk_command),
            *(read_budget(read, on_real_library=False) for read in reads),
            rebuild_budget(rebuild),
        ),
    )


def _measure_existing(
    library: UserLibrary, *, iterations: int, warmup: int, count_replay: bool
) -> BenchmarkReport:
    reads = run_read_scenario(library, iterations=iterations, warmup=warmup)
    rebuild, replay = run_rebuild_scenario(
        library, mode=RebuildMode.CHECK, count_replay=count_replay
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        scratch_username=None,
        seed=None,
        command=None,
        session_command=None,
        record_command=None,
        bulk_command=None,
        reads=reads,
        amplification=None,
        replay=replay,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(
            *(read_budget(read, on_real_library=True) for read in reads),
            rebuild_budget(rebuild),
        ),
    )


def _refuse_a_diff(report: RebuildReport) -> None:
    """A quick, wrong rebuild is no benchmark."""
    drifted = sum(
        table.only_live + table.only_rebuilt + table.differing
        for table in report.tables
    )
    if drifted:
        raise RebuildDiffNotEmpty(
            f"{drifted} row(s) differ from the replay, so the parity this run "
            "exists to demonstrate does not hold. The timings above are real "
            "and the claim they support is not."
        )
