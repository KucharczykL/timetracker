"""Seeding, the three scenarios, and the scratch teardown.

Everything here works on a real library through the real write path. There is
no workload protocol and no plug point: #671 shipped one command, one event
type and one projector family, and this module names them.

Imports benchmark.py for its vocabulary and nothing from benchmark_run.py.
"""

import uuid
from collections.abc import Iterator
from io import StringIO
from itertools import batched
from time import monotonic

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import transaction

from games.events.append import lock_stream
from games.events.benchmark import Seconds, SeedReport
from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import capture_reference
from games.models import Game, UserLibrary

#: The seeded catalog rows, and the untracked ones scenarios consume.
SEEDED_NAME_PREFIX = "Benchmark game "
SPARE_NAME_PREFIX = "Benchmark spare "

CATALOG_BATCH = 1_000
APPEND_BATCH = 1_000

#: One key for every batch: only LibraryIdempotencyRecord is unique on it,
#: and a direct append() never writes one.
SEED_IDEMPOTENCY_KEY = "benchmark-seed"

#: capture_reference reads exactly these three.
_CAPTURED_FIELDS = ("id", "name", "year_released")


def seed_library(
    library: UserLibrary, *, actor: User, events: int, spares: int
) -> SeedReport:
    """Fill `library` with `events` real events, plus `spares` untracked games."""
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

    return SeedReport(
        catalog_rows=events + spares,
        catalog_seconds=catalog_seconds,
        events=events,
        append_seconds=append_seconds,
        events_per_second=events / append_seconds if append_seconds else 0.0,
    )


def _create_catalog(library: UserLibrary, *, prefix: str, count: int) -> None:
    """Rows nothing has tracked, named so a scenario can find them."""
    for start in range(0, count, CATALOG_BATCH):
        Game.objects.bulk_create(
            Game(library=library, name=f"{prefix}{index}")
            for index in range(start, min(start + CATALOG_BATCH, count))
        )


def _seeded_games(library: UserLibrary) -> Iterator[Game]:
    return _catalog(library, SEEDED_NAME_PREFIX)


def spare_games(library: UserLibrary) -> Iterator[Game]:
    """The untracked rows the command scenarios consume, one each."""
    return _catalog(library, SPARE_NAME_PREFIX)


def _catalog(library: UserLibrary, prefix: str) -> Iterator[Game]:
    """Keyset pages, because every caller commits mid-iteration.

    `.iterator()` would open a server-side cursor, which a
    transaction-pooling pooler closes under us -- issue #917, and no reason
    to depend on it for an iteration a `WHERE id > ?` does just as lazily.
    UUIDv7 primary keys sort in insertion order, so the paging is stable.
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
    """Delete the scratch user through the command that already knows how.

    At 100,000 events this collects roughly 400,000 rows -- the events, their
    reference rows, the catalog, and the projections -- and takes about a sixth
    of the run. A second, raw-SQL copy of the cascade would be faster and would
    be a second thing that can drift from `on_delete`.

    delete_user_library walks the collector twice, once to print the scope and
    once to delete. Both walks are inside this number.
    """
    started = monotonic()
    call_command(
        "delete_user_library",
        user=username,
        confirm=username,
        stdout=StringIO(),
    )
    return monotonic() - started
