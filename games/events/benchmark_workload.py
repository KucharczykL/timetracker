"""Seeding, the scenarios, and the scratch teardown."""

import uuid
from collections.abc import Iterator
from io import StringIO
from itertools import batched, islice
from time import monotonic

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection, transaction

from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.benchmark import (
    Seconds,
    SeedReport,
    StatementCounter,
    Timings,
    WorkPerEvent,
    summarize,
)
from games.events.dispatch import dispatch
from games.events.playergame import PLAYERGAME_CREATED
from games.events.rebuild import RebuildMode, RebuildReport, rebuild_projections
from games.events.references import capture_reference
from games.models import Game, UserLibrary

#: The seeded rows, and the untracked spares.
SEEDED_NAME_PREFIX = "Benchmark game "
SPARE_NAME_PREFIX = "Benchmark spare "

CATALOG_BATCH = 1_000
APPEND_BATCH = 1_000

#: One key per batch; only records collide.
SEED_IDEMPOTENCY_KEY = "benchmark-seed"

#: capture_reference reads exactly these three.
_CAPTURED_FIELDS = ("id", "name", "year_released")


def seed_library(
    library: UserLibrary, *, actor: User, events: int, spares: int
) -> SeedReport:
    """Fill `library`, and leave `spares` untracked games."""
    catalog_started = monotonic()
    _create_catalog(library, prefix=SEEDED_NAME_PREFIX, count=events)
    _create_catalog(library, prefix=SPARE_NAME_PREFIX, count=spares)
    catalog_seconds = monotonic() - catalog_started

    append_started = monotonic()
    correlation_id = uuid.uuid7()
    for batch in batched(_seeded_games(library), APPEND_BATCH):
        with transaction.atomic():
            lock_stream(library).append(
                [
                    PLAYERGAME_CREATED.new(
                        aggregate_id=uuid.uuid7(),
                        payload={"game": capture_reference(game)},
                    )
                    for game in batch
                ],
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=SEED_IDEMPOTENCY_KEY,
            )
    append_seconds = monotonic() - append_started
    _analyze()

    return SeedReport(
        catalog_rows=events + spares,
        catalog_seconds=catalog_seconds,
        events=events,
        append_seconds=append_seconds,
        events_per_second=events / append_seconds if append_seconds else 0.0,
    )


def _analyze() -> None:
    """Leave statistics that describe the rows just written.

    Autovacuum wakes once a minute, so whether the planner knows the seeded
    library exists depends on how long the seed took. It read the duplicate
    check's 100,000 rows through the `library_id` index at 6 ms a command
    while it believed the projection was empty, and 0.01 ms once told
    otherwise. That is a fact about the naptime, not about the write path
    under measurement.
    """
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE")


def _create_catalog(library: UserLibrary, *, prefix: str, count: int) -> None:
    """Untracked rows, named for a scenario."""
    for start in range(0, count, CATALOG_BATCH):
        Game.objects.bulk_create(
            Game(library=library, name=f"{prefix}{index}")
            for index in range(start, min(start + CATALOG_BATCH, count))
        )


def _seeded_games(library: UserLibrary) -> Iterator[Game]:
    return _catalog(library, SEEDED_NAME_PREFIX)


def spare_games(library: UserLibrary) -> Iterator[Game]:
    """The untracked rows the scenarios consume."""
    return _catalog(library, SPARE_NAME_PREFIX)


def _catalog(library: UserLibrary, prefix: str) -> Iterator[Game]:
    """Keyset pages, because callers commit mid-iteration.

    `.iterator()` opens a server-side cursor, which a transaction-pooling
    pooler closes under us -- issue #917. UUIDv7 primary keys sort in
    insertion order, so `WHERE id > ?` pages just as lazily and survives.
    """
    last_id: uuid.UUID | None = None
    while True:
        page = Game.objects.filter(library=library, name__startswith=prefix)
        if last_id is not None:
            page = page.filter(id__gt=last_id)
        rows = list(page.only(*_CAPTURED_FIELDS).order_by("id")[:CATALOG_BATCH])
        if not rows:
            return
        yield from rows
        last_id = rows[-1].id


def purge_scratch_user(username: str) -> Seconds:
    """Delete the scratch user, through delete_user_library."""
    started = monotonic()
    call_command(
        "delete_user_library",
        user=username,
        confirm=username,
        stdout=StringIO(),
    )
    return monotonic() - started


def _track(library: UserLibrary, *, actor: User, game: Game) -> None:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def run_command_scenario(
    library: UserLibrary,
    *,
    actor: User,
    games: Iterator[Game],
    iterations: int,
    warmup: int,
) -> Timings:
    """Dispatch against the seeded library.

    TrackGame's duplicate check queries the projection, so a full library is
    the condition worth measuring. The warmup dispatches are additional to
    `iterations` and discarded: the first pays for connection setup and query
    planning that no later one pays for.
    """
    for game in islice(games, warmup):
        _track(library, actor=actor, game=game)
    samples: list[Seconds] = []
    for game in islice(games, iterations):
        started = monotonic()
        _track(library, actor=actor, game=game)
        samples.append(monotonic() - started)
    return summarize(samples)


def run_amplification_scenario(
    library: UserLibrary, *, actor: User, games: Iterator[Game], iterations: int
) -> WorkPerEvent:
    """What one command costs, end to end.

    Counted in its own pass, so the wrapper's per-statement cost stays out of
    the latency being gated.
    """
    counter = StatementCounter()
    dispatched = 0
    with connection.execute_wrapper(counter):
        for game in islice(games, iterations):
            _track(library, actor=actor, game=game)
            dispatched += 1
    return counter.work(events=dispatched)


def run_rebuild_scenario(
    library: UserLibrary, *, mode: RebuildMode, count_fold: bool
) -> tuple[RebuildReport, WorkPerEvent | None]:
    """Replay, diff, and swap.

    The counter is installed for the whole rebuild, so the gated time carries
    its own instrumentation. That makes a PASSED verdict conservative; pass
    count_fold=False to re-measure a verdict inside the overhead.
    """
    if not count_fold:
        return rebuild_projections(library, mode=mode), None
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        report = rebuild_projections(library, mode=mode)
    return report, counter.work(events=report.folded_through)
