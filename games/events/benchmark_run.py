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
    command_budget,
    environment,
    rebuild_budget,
)
from games.events.benchmark_workload import (
    purge_scratch_user,
    run_amplification_scenario,
    run_command_scenario,
    run_rebuild_scenario,
    seed_library,
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
    library: UserLibrary | None = None,
    keep: bool = False,
    count_fold: bool = True,
    announce_scratch_user: Callable[[str], None] | None = None,
) -> BenchmarkReport:
    """Seed a library, measure it, remove it.

    With `library`, run the read-only rebuild scenario against one that
    exists and ignore `seed`.

    `announce_scratch_user` takes the username as soon as the user exists,
    before any scenario can fail. --keep needs it: a run that raises leaves
    the library behind, and the operator has to be told its name.
    """
    if library is not None:
        return _measure_existing(library, count_fold=count_fold)
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
            count_fold=count_fold,
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
    user: User, *, seed: int, iterations: int, warmup: int, count_fold: bool
) -> BenchmarkReport:
    library = user.library
    spares = 2 * iterations + warmup
    seeded = seed_library(library, actor=user, events=seed, spares=spares)
    #: One iterator; islice leaves the next spares.
    games = spare_games(library)
    command = run_command_scenario(
        library, actor=user, games=games, iterations=iterations, warmup=warmup
    )
    amplification = run_amplification_scenario(
        library, actor=user, games=games, iterations=iterations
    )
    rebuild, fold = run_rebuild_scenario(
        library, mode=RebuildMode.REBUILD, count_fold=count_fold
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        scratch_username=user.username,
        seed=seeded,
        command=command,
        amplification=amplification,
        fold=fold,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(command_budget(command), rebuild_budget(rebuild)),
    )


def _measure_existing(library: UserLibrary, *, count_fold: bool) -> BenchmarkReport:
    rebuild, fold = run_rebuild_scenario(
        library, mode=RebuildMode.CHECK, count_fold=count_fold
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        scratch_username=None,
        seed=None,
        command=None,
        amplification=None,
        fold=fold,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(rebuild_budget(rebuild),),
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
