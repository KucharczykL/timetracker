"""Seeding, the scenarios, and the scratch teardown."""

import uuid
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from io import StringIO
from itertools import batched, islice
from time import monotonic
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection, transaction
from django.db.models import Model

from common.keyset import keyset_pages
from games.bulk_reclassification import (
    RECLASSIFY,
    REVIEW_THRESHOLD_HOURS,
    reviewable_sessions,
)
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playergame import TrackGame, tracking_events
from games.commands.playersession import (
    CreateSession,
    DurationOnlyTiming,
    session_events,
)
from games.events.append import NewEvent, lock_stream
from games.events.benchmark import (
    ReadTimings,
    Seconds,
    SeedReport,
    StatementCounter,
    Timings,
    WorkPerEvent,
    summarize,
)
from games.events.benchmark_reads import READS
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildMode, RebuildReport, rebuild_projections
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerSession,
    Playthrough,
    UserLibrary,
)
from games.reads.calendar import calendar_day_zone

#: The seeded rows, and the untracked spares.
SEEDED_NAME_PREFIX = "Benchmark game "
SPARE_NAME_PREFIX = "Benchmark spare "

CATALOG_BATCH = 1_000
APPEND_BATCH = 1_000

#: One key per batch; only records collide.
SEED_IDEMPOTENCY_KEY = "benchmark-seed"

#: capture_reference reads exactly these three.
_CAPTURED_FIELDS = ("id", "name", "year_released")

#: Every table the seed writes, for ANALYZE.
_SEEDED_TABLES = (
    Game,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerSession,
    Playthrough,
)

#: The two tables a record writes.
RECORD_TABLES = (HistoricalPlaytime, HistoricalPlaytimeRun)

#: Days cycle over two years, so per-day and per-month
#: reads aggregate many rows a cell and played_years stays small.
SEEDED_DAY_CYCLE = 730


def seed_library(
    library: UserLibrary, *, actor: User, games: int, spares: int
) -> SeedReport:
    """Fill `library`, and leave `spares` untracked games.

    The parameter counts games rather than events, because a game is
    three events -- the tracking pair, then one finished session on
    the run -- and a parameter named for the other one reads wrong at
    every call site.
    """
    catalog_started = monotonic()
    _create_catalog(library, prefix=SEEDED_NAME_PREFIX, count=games)
    _create_catalog(library, prefix=SPARE_NAME_PREFIX, count=spares)
    catalog_seconds = monotonic() - catalog_started

    append_started = monotonic()
    correlation_id = uuid.uuid7()
    #: Read, never a literal: a direct append runs no command check.
    day_zone = calendar_day_zone(library).key
    today = datetime.now(tz=ZoneInfo(day_zone)).date()
    events = 0
    for batch in batched(enumerate(_seeded_games(library)), APPEND_BATCH):
        with transaction.atomic():
            lock_stream(library).append(
                [
                    event
                    for index, game in batch
                    for event in _seeded_events(game, index, today, day_zone)
                ],
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=SEED_IDEMPOTENCY_KEY,
            )
        events += 3 * len(batch)
    append_seconds = monotonic() - append_started
    analyze_tables()

    return SeedReport(
        catalog_rows=games + spares,
        catalog_seconds=catalog_seconds,
        games=games,
        events=events,
        append_seconds=append_seconds,
        events_per_second=events / append_seconds if append_seconds else 0.0,
    )


def _seeded_events(
    game: Game, index: int, today: date, day_zone: str
) -> list[NewEvent]:
    """The tracking pair, then a session on the run it stated."""
    pair = tracking_events(game)
    run_id = pair[1].aggregate_id
    day = today - timedelta(days=index % SEEDED_DAY_CYCLE)
    return [*pair, *session_events(run_id, day=day, day_zone=day_zone)]


def analyze_tables(tables: Sequence[type[Model]] = _SEEDED_TABLES) -> None:
    """Leave statistics that describe the rows just written.

    Without this the command scenario races autovacuum's one-minute naptime,
    and measures which index the planner guessed at. Named tables rather than
    a bare `ANALYZE`, which would rewrite statistics for a whole database the
    benchmark did not touch.
    """
    named = ", ".join(f'"{model._meta.db_table}"' for model in tables)
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {named}")


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
    """Pages by key, because callers commit mid-iteration."""
    return keyset_pages(
        Game.objects.filter(library=library, name__startswith=prefix).only(
            *_CAPTURED_FIELDS
        ),
        key=("id",),
        page_size=CATALOG_BATCH,
    )


def purge_scratch_user(username: str) -> Seconds:
    """Purge the scratch user, through purge_user_library."""
    started = monotonic()
    call_command(
        "purge_user_library",
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


def seeded_runs(library: UserLibrary) -> Iterator[Playthrough]:
    """The runs the seed stated, for the session command."""
    return keyset_pages(
        Playthrough.objects.filter(library=library).only("id"),
        key=("id",),
        page_size=CATALOG_BATCH,
    )


def _record(library: UserLibrary, *, actor: User, run: Playthrough) -> None:
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 6, 1), duration=timedelta(minutes=30)
            ),
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def run_session_command_scenario(
    library: UserLibrary,
    *,
    actor: User,
    runs: Iterator[Playthrough],
    iterations: int,
    warmup: int,
) -> Timings:
    """Dispatch CreateSession against the seeded runs.

    A Duration-only statement: the cheapest shape, so the number is the
    dispatch's own cost -- the run resolve, the calendar check, the
    projector -- and not the zone arithmetic.
    """
    for run in islice(runs, warmup):
        _record(library, actor=actor, run=run)
    samples: list[Seconds] = []
    for run in islice(runs, iterations):
        started = monotonic()
        _record(library, actor=actor, run=run)
        samples.append(monotonic() - started)
    return summarize(samples)


def _record_playtime(library: UserLibrary, *, actor: User, run: Playthrough) -> None:
    dispatch(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when="2005",
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=(run.pk,),
                device_id=None,
                emulated=False,
                note="",
            )
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def _cycling(
    library: UserLibrary, runs: Iterator[Playthrough]
) -> Iterator[Playthrough]:
    """Start over when the runs run out."""
    yield from runs
    while True:
        again = seeded_runs(library)
        first = next(again, None)
        if first is None:
            raise ValueError("The records scenario needs a run to name.")
        yield first
        yield from again


def run_record_command_scenario(
    library: UserLibrary,
    *,
    actor: User,
    runs: Iterator[Playthrough],
    records: int,
    warmup: int,
) -> Timings:
    """Dispatch `records` records: an import's shape.

    ANALYZE last, so the reads plan right.
    """
    cycle = _cycling(library, runs)
    for run in islice(cycle, warmup):
        _record_playtime(library, actor=actor, run=run)
    samples: list[Seconds] = []
    for run in islice(cycle, records):
        started = monotonic()
        _record_playtime(library, actor=actor, run=run)
        samples.append(monotonic() - started)
    analyze_tables(RECORD_TABLES)
    return summarize(samples)


def _written_down(library: UserLibrary, *, actor: User, run: Playthrough) -> None:
    """One Duration-only session long enough for the review to offer it."""
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 6, 1),
                duration=timedelta(hours=REVIEW_THRESHOLD_HOURS),
            ),
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def _rows_to_convert(
    library: UserLibrary, *, actor: User, count: int
) -> list[PlayerSession]:
    """Write the batch's own rows, then read back what the act offers.

    Its own rows, because converting the seed's would take them out of
    the population the read scenario measures. Read back rather than
    kept, because the statement a conversion makes is built from
    columns the database generates.

    The act's own scope answers, newest first: a key sorts by the
    instant it was minted, so the rows just written are the ones it
    hands back.
    """
    cycle = _cycling(library, seeded_runs(library))
    for run in islice(cycle, count):
        _written_down(library, actor=actor, run=run)
    return list(
        reviewable_sessions(library)
        .select_related("playthrough__player_game__game")
        .order_by("-id")[:count]
    )


def run_bulk_command_scenario(
    library: UserLibrary, *, actor: User, sessions: int, warmup: int
) -> Timings:
    """Convert `sessions` written-down rows the way the runner does.

    The runner's own loop and not its view: one dispatch a row, keyed
    from the batch's token and the row, every append under the one
    correlation id the token states. The per-row number is what a chunk
    budget is spent against, so it is the number worth having.

    ANALYZE last, so the reads that follow plan right.
    """
    rows = iter(_rows_to_convert(library, actor=actor, count=sessions + warmup))
    #: The token is the batch's correlation id, as the runner mints it.
    correlation_id = uuid.uuid7()
    for row in islice(rows, warmup):
        _convert(actor, row, correlation_id)
    samples: list[Seconds] = []
    for row in islice(rows, sessions):
        started = monotonic()
        _convert(actor, row, correlation_id)
        samples.append(monotonic() - started)
    analyze_tables(RECORD_TABLES)
    return summarize(samples)


def _convert(actor: User, row: PlayerSession, correlation_id: uuid.UUID) -> None:
    RECLASSIFY.run(
        actor, row, f"{RECLASSIFY.name}-{correlation_id}-{row.pk}", correlation_id
    )


def run_read_scenario(
    library: UserLibrary, *, iterations: int, warmup: int
) -> tuple[ReadTimings, ...]:
    """Execute every named read to a list, `iterations` times each.

    Zero iterations runs no read: a distribution needs an observation.
    """
    if iterations == 0:
        return ()
    timings: list[ReadTimings] = []
    for read in READS:
        for _ in range(warmup):
            read.execute(library)
        samples: list[Seconds] = []
        for _ in range(iterations):
            started = monotonic()
            read.execute(library)
            samples.append(monotonic() - started)
        timings.append(ReadTimings(read.name, summarize(samples)))
    return tuple(timings)


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
    library: UserLibrary, *, mode: RebuildMode, count_replay: bool
) -> tuple[RebuildReport, WorkPerEvent | None]:
    """Replay, diff, and swap.

    The counter is installed for the whole rebuild, so the gated time carries
    its own instrumentation. That makes a PASSED verdict conservative; pass
    count_replay=False to re-measure a verdict inside the overhead.
    """
    if not count_replay:
        return rebuild_projections(library, mode=mode), None
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        report = rebuild_projections(library, mode=mode)
    return report, counter.work(events=report.replayed_through)
