# Server-side cursors: keyset paging and the `DISABLE_SERVER_SIDE_CURSORS` lever

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every first-party `QuerySet.iterator()` with keyset paging, guard against new ones, and make `DISABLE_SERVER_SIDE_CURSORS` reachable through `config()` for the reads only Django owns.

**Architecture:** One generator, `common/keyset.py::keyset_pages()`, reads a queryset one indexed page at a time using a row-value comparison, so no server-side cursor is opened and no pooler can close one under us. The four first-party `.iterator()` call sites move onto it, an AST test refuses new ones, and `required_database_settings()` grows a boolean read through `config()` for the reads that stay inside Django (`ModelChoiceIterator`, `dumpdata`, `serialize_db_to_string`).

**Tech Stack:** Django 6, PostgreSQL 18, psycopg 3.3, Python 3.14, pytest + pytest-django, `ast` from the standard library.

**Spec:** `docs/superpowers/specs/2026-08-29-issue-917-server-side-cursors-design.md`

**Issue:** [#917](https://github.com/KucharczykL/timetracker/issues/917)

## Global Constraints

- **Everything through `make`.** Never `direnv exec .`, never a raw `uv run` / `pytest` / `pnpm`. Focused runs: `make test ARGS="tests/test_keyset.py -x"`. Iterate with `make check-fast`; the gate is the full `make check`.
- **Python 3.14.** If `except A, B:` raises a `SyntaxError`, the interpreter is wrong, not the code.
- **The comparison must be a row value.** `TupleLessThan` / `TupleGreaterThan` from `django/db/models/fields/tuple_lookups.py`. Never `Q(a__lt=x) | Q(a=x, b__lt=y)` — PostgreSQL cannot read an `OR` as an index range condition, and the walk becomes quadratic (measured at 200k deep: 200001 rows / 15.021 ms against 1 row / 0.279 ms).
- **Every key must range-scan an index.** A key without one re-sorts the table on every page, which is worse than the single sort it replaces.
- **Complete words in identifiers.** `element` not `el`, `option` not `o`, `queryset` not `qs`.
- **Name compound and primitive roles.** A `tuple`/`dict` crossing a signature gets a `TypedDict`/`NamedTuple`/alias; a bare `str` standing for a domain concept gets a PEP 695 alias.
- **`make vale` refuses words.** `fold`, `tombstone`, `archive`, `delete`, `heal` and the rest of `docs/vocabulary.md` are refused in docs and in code comments. A projector *replays* events; the row it leaves is the *projection*.
- **Never write to a `GeneratedField`** (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`).
- **Commit after every task.** The plan says which files.

## File Structure

| File | Responsibility |
|------|----------------|
| `common/keyset.py` | **Create.** One generator, `keyset_pages()`, plus `DEFAULT_PAGE_SIZE`. The only place a row-value keyset comparison is written. |
| `tests/test_keyset.py` | **Create.** The helper's behaviour *and* the SQL form of its comparison. |
| `games/events/replay.py` | **Modify.** Read the stream by key on `sequence`; drop `cast`, `closing`, and the `WITH HOLD` comment. |
| `games/backfill/playergame.py` | **Modify.** Two reads keyed on `id`; add `BACKFILL_PAGE_SIZE`. |
| `common/layout.py` | **Modify.** `recent_session_resumes()` keyed on `(timestamp_start, id)` descending; add `RESUME_PAGE_SIZE`. |
| `games/models.py` | **Modify.** `Session.Meta.indexes` gains `(timestamp_start, id)`. |
| `games/migrations/0037_session_start_id_index.py` | **Create.** That index. |
| `games/events/benchmark_workload.py` | **Modify.** `_catalog` moves onto the helper; its comment stops naming #917 unsolved. |
| `games/management/commands/benchmark_events.py` | **Modify.** `CURSOR_UNDER_A_POOLER` stops saying the setting cannot be set. |
| `tests/test_iterator_guard.py` | **Create.** The AST walk over first-party packages. |
| `CLAUDE.md` | **Modify.** The rule. |
| `timetracker/database.py` | **Modify.** `required_database_settings()` reads the lever. |
| `tests/test_database_configuration.py` | **Modify.** Four assertions for the lever. |
| `docs/configuration.md` | **Modify.** One settings-reference row. |
| `docs/database.md` | **Modify.** A new pooling section. |

---

### Task 1: The keyset helper

**Files:**
- Create: `common/keyset.py`
- Test: `tests/test_keyset.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  type FieldName = str  # e.g. "timestamp_start"
  DEFAULT_PAGE_SIZE: int = 500


  def keyset_pages[ModelT: Model](
      queryset: QuerySet[ModelT],
      *,
      key: Sequence[FieldName],
      descending: bool = False,
      page_size: int = DEFAULT_PAGE_SIZE,
  ) -> Iterator[ModelT]: ...
  ```
  Every later task calls exactly this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keyset.py`:

```python
"""Reading a queryset one indexed page at a time, without a server-side cursor.

Two of these matter more than the rest. A tie that straddles a page boundary is
what a wrong comparison breaks, and it breaks by skipping a row. The SQL form is
what the `OR` spelling breaks, and it breaks by being slow while every row is
still correct -- so a rows-only test passes on the wrong query.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext

from common.keyset import keyset_pages
from games.models import Game, Platform, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 1, 1, 12, 0, tzinfo=ZONEINFO)


@pytest.fixture
def library(db):
    user = User.objects.create_user(username="keyset", password="p")
    return user.library


@pytest.fixture
def game(library):
    platform = Platform.objects.create(library=library, name="PC", icon="pc")
    return Game.objects.create(library=library, name="A", platform=platform)


def _sessions(game, offsets: list[int]) -> list[Session]:
    return [
        Session.objects.create(game=game, timestamp_start=BASE + timedelta(hours=hours))
        for hours in offsets
    ]


def test_one_field_ascending_reads_every_row_in_order(game):
    _sessions(game, [0, 1, 2, 3, 4])
    rows = list(
        keyset_pages(Session.objects.all(), key=("timestamp_start",), page_size=2)
    )
    assert [row.timestamp_start for row in rows] == sorted(
        row.timestamp_start for row in Session.objects.all()
    )


def test_two_fields_descending_read_from_the_newest(game):
    _sessions(game, [0, 1, 2])
    rows = list(
        keyset_pages(
            Session.objects.all(),
            key=("timestamp_start", "id"),
            descending=True,
            page_size=2,
        )
    )
    assert [row.timestamp_start for row in rows] == sorted(
        (row.timestamp_start for row in Session.objects.all()), reverse=True
    )


def test_a_tie_straddling_a_page_boundary_yields_every_row_once(game):
    """Three sessions share one start time, and the page holds two of them."""
    _sessions(game, [0, 1, 1, 1, 2])
    rows = list(
        keyset_pages(
            Session.objects.all(),
            key=("timestamp_start", "id"),
            descending=True,
            page_size=2,
        )
    )
    identifiers = [row.id for row in rows]
    assert len(identifiers) == 5
    assert len(set(identifiers)) == 5


def test_a_result_ending_on_a_page_boundary_stops(game):
    _sessions(game, [0, 1, 2, 3])
    rows = list(
        keyset_pages(Session.objects.all(), key=("timestamp_start", "id"), page_size=2)
    )
    assert len(rows) == 4


def test_one_row_and_no_rows(game):
    assert list(keyset_pages(Session.objects.all(), key=("id",), page_size=2)) == []
    only = _sessions(game, [0])[0]
    assert [row.id for row in keyset_pages(Session.objects.all(), key=("id",))] == [
        only.id
    ]


def test_a_composite_key_emits_a_row_value_comparison(game):
    """PostgreSQL reads a row value as an index range condition. It cannot read
    an OR that way, so the OR spelling is quadratic and this assertion is the
    only thing that catches it."""
    _sessions(game, [0, 1, 2])
    with CaptureQueriesContext(connection) as captured:
        list(
            keyset_pages(
                Session.objects.all(),
                key=("timestamp_start", "id"),
                descending=True,
                page_size=1,
            )
        )
    second = captured.captured_queries[1]["sql"]
    assert '("games_session"."timestamp_start", "games_session"."id") <' in second
    assert " OR " not in second


def test_a_single_field_key_emits_a_plain_comparison(game):
    _sessions(game, [0, 1])
    with CaptureQueriesContext(connection) as captured:
        list(keyset_pages(Session.objects.all(), key=("id",), page_size=1))
    assert '"games_session"."id" >' in captured.captured_queries[1]["sql"]


def test_an_empty_key_is_refused(game):
    with pytest.raises(ValueError, match="at least one key field"):
        list(keyset_pages(Session.objects.all(), key=()))


def test_a_page_smaller_than_one_row_is_refused(game):
    with pytest.raises(ValueError, match="at least one row"):
        list(keyset_pages(Session.objects.all(), key=("id",), page_size=0))
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `make test ARGS="tests/test_keyset.py -x"`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.keyset'`.

- [ ] **Step 3: Write the helper**

Create `common/keyset.py`:

```python
"""Reading a large queryset one page at a time, without a server-side cursor.

`QuerySet.iterator()` opens a cursor, and a cursor belongs to one connection: a
pooler in transaction or statement pooling mode hands the next FETCH a different
connection and the read fails. A keyset read runs one ordinary query per page,
each carrying its own WHERE, so it depends on no connection state at all.

The key names the order. Its last field must be unique, or a page boundary can
skip a row or yield one twice. Every field of the key must lie in one index,
ascending: PostgreSQL scans a btree in either direction, so one ascending index
serves both directions of the same key. A key without an index re-sorts the
whole table on every page, which costs more than the single sort it replaces.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from django.db.models import F, Model, QuerySet
from django.db.models.fields.tuple_lookups import (
    Tuple,
    TupleGreaterThan,
    TupleLessThan,
)

#: A concrete local field of the model, named as `order_by` would name it.
type FieldName = str

#: Matches REPLAY_CHUNK_SIZE: a memory decision rather than a speed one.
DEFAULT_PAGE_SIZE = 500


def keyset_pages[ModelT: Model](
    queryset: QuerySet[ModelT],
    *,
    key: Sequence[FieldName],
    descending: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[ModelT]:
    """Yield every row of `queryset` in `key` order, one query per page.

    Any ordering already on the queryset is replaced: the order and the key are
    the same thing here, and a mismatch between them skips rows silently.
    """
    if not key:
        raise ValueError("A keyset read needs at least one key field.")
    if page_size < 1:
        raise ValueError("A keyset page holds at least one row.")

    prefix = "-" if descending else ""
    ordered = queryset.order_by(*(f"{prefix}{field}" for field in key))
    last: tuple[Any, ...] | None = None
    while True:
        page = ordered if last is None else _after(ordered, key, last, descending)
        rows = list(page[:page_size])
        if not rows:
            return
        yield from rows
        if len(rows) < page_size:
            return
        last = tuple(getattr(rows[-1], field) for field in key)


def _after[ModelT: Model](
    queryset: QuerySet[ModelT],
    key: Sequence[FieldName],
    last: tuple[Any, ...],
    descending: bool,
) -> QuerySet[ModelT]:
    """Everything strictly past `last` in the key's order.

    A composite key compares as a row value. Written as
    `Q(a__lt=x) | Q(a=x, b__lt=y)` it is the same logic and the wrong SQL:
    PostgreSQL cannot read an OR as an index range condition, so each page would
    scan from the start of the index and the whole walk would be quadratic.
    """
    if len(key) == 1:
        return queryset.filter(**{f"{key[0]}__{'lt' if descending else 'gt'}": last[0]})
    comparison = TupleLessThan if descending else TupleGreaterThan
    return queryset.filter(comparison(Tuple(*(F(field) for field in key)), last))
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `make test ARGS="tests/test_keyset.py -v"`
Expected: PASS, all ten.

If `test_a_composite_key_emits_a_row_value_comparison` fails on the exact string, print `second` and match what PostgreSQL actually emitted — but the assertion must still name a parenthesised column pair followed by the operator, and must still refuse `" OR "`. Do not weaken it to a rows-only check.

- [ ] **Step 5: Type-check and lint**

Run: `make typecheck && make lint && make format`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add common/keyset.py tests/test_keyset.py
git commit -m "Read a page by key, not through a cursor"
```

---

### Task 2: The replay reads by key

**Files:**
- Modify: `games/events/replay.py:86-112`
- Test: `tests/test_event_replay.py`

**Interfaces:**
- Consumes: `common.keyset.keyset_pages`.
- Produces: nothing new. `REPLAY_CHUNK_SIZE` keeps its name and value (500) and becomes the page size.

The key is `sequence`, ascending. `UniqueConstraint(fields=("stream", "sequence"))` at `games/models.py:1629` is its index, and `stream_id=head.id` scopes it. The read is already bounded by `sequence__lte=bound`, so a page and a cursor see the same rows.

**Behaviour change to record:** with a cursor, a row removed underneath the read was invisible. With pages, the contiguity test raises `StreamNotContiguous`. That is the better outcome — append-only is a convention here, not a database constraint.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_event_replay.py`:

Append to `tests/test_event_replay.py`, next to
`test_a_stream_replays_every_event_in_sequence_order`. It reuses that file's
existing `append_stream` helper, the `owned_library` fixture, the module-level
`wiring`, and the `SEEN` sink:

```python
def test_a_stream_longer_than_one_page_replays_whole(owned_library, monkeypatch):
    """Five events over pages of two: three pages, the last one short. A
    fixture inside one page never reaches the boundary code at all."""
    import games.events.replay as replay_module

    monkeypatch.setattr(replay_module, "REPLAY_CHUNK_SIZE", 2)
    append_stream(owned_library, 5)
    SEEN.clear()

    result = replay(owned_library, wiring=wiring)

    assert [event.sequence for event in SEEN] == [1, 2, 3, 4, 5]
    assert result.replayed_through == 5
```

- [ ] **Step 2: Run it and confirm it passes for the wrong reason**

Run: `make test ARGS="tests/test_event_replay.py -k longer_than_one_page -x"`
Expected: PASS today — a cursor also handles five rows, and `monkeypatch` on
`REPLAY_CHUNK_SIZE` currently only shrinks the cursor's chunk. That is fine. The
point of writing it now is that it must still pass after Step 3, where the same
constant sizes a page and three separate queries run.

- [ ] **Step 3: Convert the read**

In `games/events/replay.py`, replace lines 86-112 (the comment block, the `cast`,
and the `with closing(rows):` wrapper) with:

```python
    bound = head.current_sequence
    #: Filtering on the stream alone scopes the read to one library: a composite
    #: foreign key ties an event's stream and library together in the database.
    #: Paged by key rather than read through a cursor: the unique constraint on
    #: (stream, sequence) is the index, and no connection state is held between
    #: pages.
    rows = keyset_pages(
        LibraryEvent.objects.filter(stream_id=head.id, sequence__lte=bound),
        key=("sequence",),
        page_size=REPLAY_CHUNK_SIZE,
    )

    previous = 0
    for row in rows:
        event = RecordedEvent.from_row(row)
        if event.sequence != previous + 1:
            raise StreamNotContiguous(
                f"This stream records no event #{previous + 1}: sequence "
                f"{event.sequence} follows {previous}. Every sequence from 1 "
                f"to {bound} must be present for a replay to reach the state "
                "the append path did."
            )
        previous = event.sequence
        _check_readable(event, wiring.event_types)
        wiring.projectors.apply(event)
```

Note the loop body is now one indent level shallower.

Then fix the imports at the top of the file: remove `from collections.abc import
Generator`, `from contextlib import closing`, and `from typing import cast` — but
only if nothing else in the file uses them. Add:

```python
from common.keyset import keyset_pages
```

Also update the `REPLAY_CHUNK_SIZE` comment, which now sizes a page:

```python
#: Page size is a memory decision rather than a speed one: 500 and 10000 replay
#: 100k events within 2% of each other, at 1 MB against 22 MB.
REPLAY_CHUNK_SIZE = 500
```

- [ ] **Step 4: Run the replay suite**

Run: `make test ARGS="tests/test_event_replay.py -v"`
Expected: PASS. `make lint` will name any import left unused (F401).

- [ ] **Step 5: Lint, format, type-check**

Run: `make lint && make format && make typecheck`
Expected: clean. `make typecheck` is where the removed `cast` proves it was not
load-bearing.

- [ ] **Step 6: Commit**

```bash
git add games/events/replay.py tests/test_event_replay.py
git commit -m "Replay a stream by key, not through a cursor"
```

---

### Task 3: The backfill reads by key

**Files:**
- Modify: `games/backfill/playergame.py:271-276` and `:344-346`
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `common.keyset.keyset_pages`.
- Produces: `BACKFILL_PAGE_SIZE: int = 200`, a module constant of
  `games/backfill/playergame.py`, so a test can shrink it.

**The key is `id`, ascending, at both sites.** `Game` carries no index on
`created_at` — its only indexed fields are `library` and `platform`, and it
declares no `Meta.indexes`. A key of `(created_at, pk)` would sort the whole
library on every page: one page of 200 over 100,410 rows scans 100,410 rows in
5.201 ms against 13.165 ms for the single sorted read of today, and at 502 pages
that is about 2.6 s, growing with the square of the catalog.

`Game.id` is a `UUIDv7Field`, so it sorts in the order rows were inserted, and
the primary key is its index. The docstring asks only that two runs order the
stream identically, and `id` gives that. A run made after this change can order
its events differently from the run migration 0033 made; the backfill is
one-shot, so that is recorded here rather than solved.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playergame_backfill.py`:

Append to `tests/test_playergame_backfill.py`, next to
`test_a_library_tracks_every_live_game_it_holds`. It uses that file's existing
`owned_user` / `owned_library` fixtures:

```python
@pytest.mark.django_db(transaction=True)
def test_a_catalog_longer_than_one_page_is_backfilled_whole(
    owned_user, owned_library, monkeypatch
):
    """Five games over pages of two: three pages, the last one short."""
    import games.backfill.playergame as backfill_module

    monkeypatch.setattr(backfill_module, "BACKFILL_PAGE_SIZE", 2)
    for index in range(5):
        Game.objects.create(library=owned_library, name=f"Game {index}")

    counts = backfill_module.backfill_library(owned_library)

    assert (counts.games, counts.tracked) == (5, 5)
    assert PlayerGame.objects.filter(library=owned_library).count() == 5


@pytest.mark.django_db(transaction=True)
def test_reconcile_reads_a_catalog_longer_than_one_page(
    owned_user, owned_library, monkeypatch
):
    """The second paged read. Every game is tracked, so nothing mismatches --
    a page it skipped would show up as a missing projection row."""
    import games.backfill.playergame as backfill_module

    monkeypatch.setattr(backfill_module, "BACKFILL_PAGE_SIZE", 2)
    for index in range(5):
        Game.objects.create(library=owned_library, name=f"Game {index}")
    backfill_module.backfill_library(owned_library)

    assert backfill_module.reconcile(owned_library) == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `make test ARGS="tests/test_playergame_backfill.py -k longer_than_one_page -x"`
Expected: FAIL — `AttributeError: BACKFILL_PAGE_SIZE`.

- [ ] **Step 3: Convert both reads**

Add the constant near the top of `games/backfill/playergame.py`, beside the other
module constants:

```python
#: A page rather than a cursor chunk: a cursor does not survive a pooler.
BACKFILL_PAGE_SIZE = 200
```

Add the import:

```python
from common.keyset import keyset_pages
```

Replace lines 271-276 (`backfill_library`):

```python
    #: Keyed on id, which is a UUIDv7 and therefore sorts in insertion order, so
    #: two runs order the stream identically. Not (created_at, pk): Game indexes
    #: neither, and that key re-sorts the library on every page.
    games = Game.objects.filter(library=library)
    for game in keyset_pages(games, key=("id",), page_size=BACKFILL_PAGE_SIZE):
```

Replace lines 344-346 (`reconcile`):

```python
    live = Game.objects.filter(library=library, removed_at__isnull=True)
    for game in keyset_pages(live, key=("id",), page_size=BACKFILL_PAGE_SIZE):
```

- [ ] **Step 4: Run the backfill suites**

Run: `make test ARGS="tests/test_playergame_backfill.py tests/test_playergame_backfill_migration.py -v"`
Expected: PASS. The migration test exercises the same function through
`RunPython`, so it is the one that proves the change is safe inside a migration.

- [ ] **Step 5: Lint, format, type-check**

Run: `make lint && make format && make typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playergame.py tests/test_playergame_backfill.py
git commit -m "Backfill a catalog by key, not through a cursor"
```

---

### Task 4: The navbar reads by key

**Files:**
- Modify: `games/models.py:1019-1020` (`Session.Meta`)
- Create: `games/migrations/0037_session_start_id_index.py` (generated)
- Modify: `common/layout.py:178-203`
- Test: `tests/test_navbar_log_button.py`

**Interfaces:**
- Consumes: `common.keyset.keyset_pages`.
- Produces: `RESUME_PAGE_SIZE: int = 50`, a module constant of `common/layout.py`.
  `recent_session_resumes(request, limit=5) -> list[Session]` keeps its signature.

This is the read that gains the most. It is the only one of the four in
autocommit, and `django/db/backends/postgresql/base.py:421` declares a cursor
`WITH HOLD` only there — so PostgreSQL spools every session of the library to
temporary storage at `DECLARE`, on every authenticated page.

The key is `(timestamp_start, id)`, descending: a start time is not unique, an id
is. `Session` indexes `timestamp_start` alone, and a descending two-field key over
a single-column index adds an incremental sort that drains each group of equal
start times before it emits — so the index comes first, in the same task.

**Do not reach for `DISTINCT ON`.** The loop stops as soon as it holds enough
games. PostgreSQL has no loose index scan for `DISTINCT ON`, and the outer order
and limit need the whole distinct set first, so it would read every session of
the library and the navbar's cost would follow the whole history.

- [ ] **Step 1: Add the index to the model**

In `games/models.py`, replace `Session`'s Meta (lines 1019-1020):

```python
    class Meta:
        get_latest_by = "timestamp_start"
        indexes = (
            #: The navbar's resume read keys on both, descending. PostgreSQL
            #: scans a btree either way, so one ascending index serves it.
            models.Index(fields=("timestamp_start", "id"), name="session_start_id_idx"),
        )
```

- [ ] **Step 2: Generate the migration**

Run: `make makemigrations ARGS="games"`
Expected: `games/migrations/0037_*.py` created, holding one `AddIndex`.

Rename the file to `games/migrations/0037_session_start_id_index.py` if the
generated name differs, and fix the `name` in the file's `Migration` class only
if it embeds the filename (it does not — only `dependencies` matter).

- [ ] **Step 3: Apply it**

Run: `make migrate`
Expected: `Applying games.0037_session_start_id_index... OK`.

- [ ] **Step 4: Write the failing test**

Append to `tests/test_navbar_log_button.py`, inside `RecentSessionResumesTest`:

```python
    def test_pages_past_a_boundary_with_a_tie_across_it(self) -> None:
        """More sessions than a page, several per game, and one start time on
        both sides of the boundary -- the case a wrong comparison skips."""
        from common import layout

        with mock.patch.object(layout, "RESUME_PAGE_SIZE", 2):
            shared = BASE + timedelta(hours=3)
            first = self._game("first")
            second = self._game("second")
            third = self._game("third")
            self._session(first, BASE)
            self._session(first, BASE + timedelta(hours=1))
            self._session(second, shared)
            self._session(third, shared)
            self._session(third, BASE + timedelta(hours=5))
            resumes = recent_session_resumes(self._request(authenticated=True))
        self.assertEqual(
            [session.game.name for session in resumes], ["third", "second", "first"]
        )
```

Add `from unittest import mock` to the file's imports.

- [ ] **Step 5: Run it and confirm it fails**

Run: `make test ARGS="tests/test_navbar_log_button.py -k tie_across -x"`
Expected: FAIL — `AttributeError: <module 'common.layout'> does not have the attribute 'RESUME_PAGE_SIZE'`.

- [ ] **Step 6: Convert the read**

In `common/layout.py`, add the constant beside the other module constants:

```python
#: The resume scan stops after `limit` distinct games, so a page this size
#: usually answers in one query.
RESUME_PAGE_SIZE = 50
```

Add the import:

```python
from common.keyset import keyset_pages
```

Replace the loop head in `recent_session_resumes` (lines 190-197):

```python
    for session in keyset_pages(
        Session.objects.for_library(cast(User, request.user).library).select_related(
            "game"
        ),
        key=("timestamp_start", "id"),
        descending=True,
        page_size=RESUME_PAGE_SIZE,
    ):
```

Update the docstring's last line so it says what now happens:

```python
    The scan pages by key and early-exits after ``limit`` distinct games, so it
    reads one page in the ordinary case and never opens a server-side cursor."""
```

- [ ] **Step 7: Run the navbar suite**

Run: `make test ARGS="tests/test_navbar_log_button.py -v"`
Expected: PASS, including the pre-existing test that reads the first session
query out of `CaptureQueriesContext` — paging keeps that first query.

- [ ] **Step 8: Lint, format, type-check**

Run: `make lint && make format && make typecheck`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add games/models.py games/migrations/0037_session_start_id_index.py common/layout.py tests/test_navbar_log_button.py
git commit -m "Resume the navbar by key, over an index that serves it"
```

---

### Task 5: The benchmark workload uses the helper

**Files:**
- Modify: `games/events/benchmark_workload.py:129-145`
- Modify: `games/management/commands/benchmark_events.py:26-31`

**Interfaces:**
- Consumes: `common.keyset.keyset_pages`.
- Produces: nothing. `_catalog` keeps its signature, `CATALOG_BATCH` keeps its name.

`_catalog` already pages by key on `id` with a hand-written slice, and its
docstring cites this issue as unsolved. Both stop being true here.

- [ ] **Step 1: Move `_catalog` onto the helper**

Replace `games/events/benchmark_workload.py:129-145`:

```python
def _catalog(library: UserLibrary, prefix: str) -> Iterator[Game]:
    """Pages by key, because callers commit mid-iteration.

    A server-side cursor would not survive that, nor a transaction-pooling
    pooler. UUIDv7 primary keys sort in insertion order, so an id key pages just
    as lazily.
    """
    return keyset_pages(
        Game.objects.filter(library=library, name__startswith=prefix).only(
            *_CAPTURED_FIELDS
        ),
        key=("id",),
        page_size=CATALOG_BATCH,
    )
```

Add `from common.keyset import keyset_pages` to the imports. Remove
`import uuid` if nothing else in the file uses it — `make lint` will say.

- [ ] **Step 2: Correct the pooler message**

Replace `games/management/commands/benchmark_events.py:26-31`:

```python
CURSOR_UNDER_A_POOLER = (
    "A server-side cursor did not survive. A transaction-pooling connection "
    "pooler closes one between statements. Our own reads page by key and open "
    "none, so this came from inside Django: set DISABLE_SERVER_SIDE_CURSORS, or "
    "point this at a direct connection rather than the pooler."
)
```

- [ ] **Step 3: Run the tests that touch the workload**

Run: `make test ARGS="tests/ -k benchmark -v"`
Expected: PASS. If nothing is collected, that is the answer — the workload is
covered by `make bench`, which Task 9 runs.

- [ ] **Step 4: Lint, format, type-check**

Run: `make lint && make format && make typecheck`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark_workload.py games/management/commands/benchmark_events.py
git commit -m "Page the benchmark catalog through the one helper"
```

---

### Task 6: The guard

**Files:**
- Create: `tests/test_iterator_guard.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing. It reads source text, not the running code.
- Produces: `GUARDED_PACKAGES`, `ALLOWED_FILES`, and
  `cursor_calls(source: str, path: str) -> list[str]`, so a future allowlist
  entry has one place to go.

The walk covers `games/`, `common/`, `timetracker/`, `contrib/`, and `scripts/`.
`scripts/` is first-party Python and `make vale` already reads it. `tests/` and
`e2e/` stay outside: they are not the path a pooler serves.

There is one known class of wrong report. `RawQuerySet.iterator()` at
`django/db/models/query.py:2216` yields rows and opens no cursor, and a syntax
tree cannot tell it from a queryset. No call site uses it today, so the allowlist
starts empty and takes an entry with a reason, as a conflict answer does.

Run this task **after** Tasks 2-5. Run it before them and it fails on the code
they are about to change.

- [ ] **Step 1: Write the guard and its self-test**

Create `tests/test_iterator_guard.py`:

```python
"""Refusing `QuerySet.iterator()` anywhere in first-party code.

It opens a server-side cursor, which belongs to one connection: a pooler in
transaction or statement pooling mode hands the next FETCH a different one and
the read fails. `DISABLE_SERVER_SIDE_CURSORS` turns a cursor off globally, at the
cost of holding every raw row in the process. Paging by key needs neither.

`tests/` and `e2e/` are outside the walk. They are not the path a pooler serves.
"""

import ast
from pathlib import Path

GUARDED_PACKAGES = ("games", "common", "timetracker", "contrib", "scripts")
CURSOR_METHODS = frozenset({"iterator", "aiterator"})

#: Repository-relative path -> the reason it is exempt. `RawQuerySet.iterator()`
#: (django/db/models/query.py:2216) yields rows and opens no cursor, and a syntax
#: tree cannot tell it from a queryset -- that is what an entry here is for.
ALLOWED_FILES: dict[str, str] = {}

REPORT = (
    "{path}:{line} calls .{method}(), which opens a server-side cursor. "
    "A transaction-pooling or statement-pooling connection pooler closes one "
    "between statements. Page by key with common.keyset.keyset_pages instead. "
    "If this is a RawQuerySet, add the file to ALLOWED_FILES with the reason."
)


def cursor_calls(source: str, path: str) -> list[str]:
    """Every call to an attribute named `iterator` or `aiterator` in `source`."""
    reports = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and called.attr in CURSOR_METHODS:
            reports.append(
                REPORT.format(path=path, line=node.lineno, method=called.attr)
            )
    return reports


def test_the_guard_reports_a_call() -> None:
    """Proved on a string, so no violation has to live in the repository."""
    reports = cursor_calls(
        "rows = Game.objects.all().iterator(chunk_size=200)\n", "x.py"
    )
    assert len(reports) == 1
    assert "x.py:1" in reports[0]
    assert "common.keyset.keyset_pages" in reports[0]


def test_the_guard_passes_ordinary_source() -> None:
    assert cursor_calls("rows = list(Game.objects.all())\n", "x.py") == []


def test_no_first_party_module_opens_a_server_side_cursor() -> None:
    root = Path(__file__).resolve().parent.parent
    reports: list[str] = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in ALLOWED_FILES:
                continue
            reports.extend(cursor_calls(path.read_text(encoding="utf-8"), relative))
    assert not reports, "\n".join(reports)
```

- [ ] **Step 2: Run it**

Run: `make test ARGS="tests/test_iterator_guard.py -v"`
Expected: PASS, all three. A failure here names a `.iterator()` Tasks 2-5 missed
— convert it with `keyset_pages` rather than adding it to `ALLOWED_FILES`.

- [ ] **Step 3: Add the rule to CLAUDE.md**

In `CLAUDE.md`, under `## Conventions for AI assistants`, add a bullet next to
the other database rules:

```markdown
- **Nothing opens a server-side cursor** — never `QuerySet.iterator()` or
  `aiterator()`. A cursor belongs to one connection, and a pooler in transaction
  or statement pooling mode hands the next `FETCH` a different one. Page with
  `keyset_pages()` from `common/keyset.py`, keyed on fields that lie in one
  index, last field unique. `tests/test_iterator_guard.py` walks the syntax tree
  of `games/`, `common/`, `timetracker/`, `contrib/` and `scripts/` and fails on
  a new call. `DISABLE_SERVER_SIDE_CURSORS` exists for the reads inside Django
  that cannot be rewritten, not for ours.
```

- [ ] **Step 4: Lint the prose**

Run: `make vale`
Expected: no new errors. Three `archive` warnings in `scripts/` are pre-existing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_iterator_guard.py CLAUDE.md
git commit -m "Refuse a server-side cursor in first-party code"
```

---

### Task 7: The lever

**Files:**
- Modify: `timetracker/database.py:106-120`
- Test: `tests/test_database_configuration.py`
- Modify: `docs/configuration.md:53`

**Interfaces:**
- Consumes: `timetracker.config.config`.
- Produces: `required_database_settings()` returns a mapping that now also holds
  `"DISABLE_SERVER_SIDE_CURSORS"`. `database_settings_from_url()` is unchanged.

The setting sits beside `ENGINE` and `NAME`, not inside `OPTIONS` — `OPTIONS`
holds driver arguments. It goes in `required_database_settings()` and **not** in
`database_settings_from_url()`: that function translates one URL and does nothing
else, and `test_postgresql_url_maps_to_django_database_settings` asserts its whole
return value against an exact dictionary.

`cast=bool` accepts `true`, `1`, `yes`, `on` in any case (`timetracker/config.py:207`).
Every other string reads `False` and none of them raises, so a typed `ture` reads
as off — which is why `docs/configuration.md` must list the four words.

`timetracker/settings_registry.py` gets no entry. `DATABASE_URL` has none either,
and `tests/test_settings_registry.py` freezes the set of keys. That is a decision.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_database_configuration.py`:

```python
def _settings_with(monkeypatch, tmp_path, value: str | None):
    from timetracker import config as config_module
    from timetracker.database import required_database_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://timetracker@127.0.0.1/tracker")
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)
    monkeypatch.delenv("DISABLE_SERVER_SIDE_CURSORS", raising=False)
    if value is not None:
        monkeypatch.setenv("DISABLE_SERVER_SIDE_CURSORS", value)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    try:
        return required_database_settings()
    finally:
        config_module.reset_caches()


def test_server_side_cursors_stay_on_by_default(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, None)
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is False


def test_server_side_cursors_can_be_turned_off(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, "true")
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is True


def test_a_misspelled_value_reads_as_off(monkeypatch, tmp_path):
    """cast=bool accepts true/1/yes/on and raises on nothing, so `ture` is off.
    docs/configuration.md lists the four words for this reason."""
    settings = _settings_with(monkeypatch, tmp_path, "ture")
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is False


def test_the_setting_sits_beside_engine_not_inside_options(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, "true")
    assert "ENGINE" in settings
    assert "DISABLE_SERVER_SIDE_CURSORS" not in settings["OPTIONS"]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `make test ARGS="tests/test_database_configuration.py -k cursor -x"`
Expected: FAIL — `KeyError: 'DISABLE_SERVER_SIDE_CURSORS'`.

- [ ] **Step 3: Add the lever**

In `timetracker/database.py`, replace the last line of
`required_database_settings()` (line 120, `return database_settings_from_url(url)`):

```python
    settings = database_settings_from_url(url)
    #: Django reads this on QuerySet.iterator() and nowhere else. Our own reads
    #: page by key and open no cursor; this governs the ones inside Django --
    #: ModelChoiceIterator, dumpdata, and the test database's serializer. It sits
    #: beside ENGINE rather than inside OPTIONS, which holds driver arguments.
    settings["DISABLE_SERVER_SIDE_CURSORS"] = config(
        "DISABLE_SERVER_SIDE_CURSORS", default=False, cast=bool
    )
    return settings
```

- [ ] **Step 4: Run the configuration suite**

Run: `make test ARGS="tests/test_database_configuration.py tests/test_settings_registry.py -v"`
Expected: PASS. `test_postgresql_url_maps_to_django_database_settings` must still
pass untouched — that is the check that the lever stayed out of the URL translator.

- [ ] **Step 5: Document the setting**

In `docs/configuration.md`, add a row directly under the `DATABASE_URL` row
(line 53):

```markdown
| `DISABLE_SERVER_SIDE_CURSORS` | bool | `false` | no | Turn off PostgreSQL server-side cursors. Set it behind a connection pooler in transaction or statement pooling mode, where a cursor does not survive between statements. Only `true`, `1`, `yes`, `on` (any case) read as true — anything else, a typo included, reads as false. Our own large reads page by key and open no cursor; this governs the ones inside Django (`ModelChoiceIterator`, `dumpdata`, the test database serializer), which then hold every raw row in memory. See [Connection pooling](database.md#connection-pooling). |
```

- [ ] **Step 6: Lint the prose and the code**

Run: `make vale && make lint && make format && make typecheck`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add timetracker/database.py tests/test_database_configuration.py docs/configuration.md
git commit -m "Let a deployment turn off server-side cursors"
```

---

### Task 8: The pooling section

**Files:**
- Modify: `docs/database.md`

**Interfaces:** none. This is the one place the whole picture is written down.

`docs/database.md` has no pooling section today. It must say what a pooler does
to a cursor, that our reads page by key, what the setting governs and what it
costs, and — this is the part a reader will otherwise get wrong — that the
rebuild is bound to one session by its temp tables and is **not** pooler-safe
whatever the setting says.

- [ ] **Step 1: Add the section**

Append to `docs/database.md`:

```markdown
## Connection pooling

No deployment here runs a connection pooler. Connections go straight to
PostgreSQL 18, and `make dev-prod` and the container both use a direct
`DATABASE_URL`. This section says what would have to hold if one were adopted.

A pooler in **transaction** or **statement** pooling mode gives consecutive
statements different backend connections. Anything a statement leaves behind on
its connection is gone by the next one.

**Cursors.** `QuerySet.iterator()` declares a server-side cursor and then
`FETCH`es from it. Under transaction pooling the `FETCH` arrives on a connection
that never saw the `DECLARE`. No first-party code calls `iterator()`:
`tests/test_iterator_guard.py` walks the syntax tree of `games/`, `common/`,
`timetracker/`, `contrib/` and `scripts/` and fails on a new call. Large reads use
`keyset_pages()` from `common/keyset.py`, which runs one ordinary query per page
over an index and holds no connection state.

Django opens cursors of its own that cannot be rewritten:
`ModelChoiceIterator` (one plain `<select>` here —
`LibraryPreferencesForm.default_device`), `dumpdata` (`make dumpgames`) and the
serializers it uses, and `serialize_db_to_string` in the test database.
`DISABLE_SERVER_SIDE_CURSORS=true` turns those off. It is not free: without a
cursor, psycopg receives every row on `execute()` and
`django/db/models/sql/compiler.py` materialises the lot, so the process holds the
whole result. `chunk_size` then sizes `fetchmany()` calls over rows that already
arrived and bounds nothing.

**Temp tables.** `games/events/rebuild.py` creates a temp table per projection
table, and its phases run in separate transactions on the same session —
`_require_shadow_tables()` already states that dependence in its error text. A
temp table belongs to a session. **Under transaction pooling the rebuild is
broken whatever `DISABLE_SERVER_SIDE_CURSORS` says and whatever the reads do.**
Adopting a pooler starts there, not with the setting.
```

- [ ] **Step 2: Lint the prose**

Run: `make vale`
Expected: no new errors.

- [ ] **Step 3: Check the anchor resolves**

The `docs/configuration.md` row from Task 7 links to
`database.md#connection-pooling`. Confirm the heading text is exactly
`## Connection pooling`.

- [ ] **Step 4: Commit**

```bash
git add docs/database.md
git commit -m "Say what a pooler would break, and what it would not fix"
```

---

### Task 9: The benchmark and the gate

**Files:** none changed by default. If `make bench` regresses, the fix lands in
the key of whichever read regressed.

**Interfaces:** none.

`docs/event-benchmarks.md` records 100,410 events and a budget of 60.246 s. #930
is closed — it took the rebuild from 60.223 s to 16.258 s. #932 is open and holds
the next 9 s. The replay is not the read at risk here: its key is one field, its
index is a unique constraint, and #932 measures the whole read half at 4.33 s of
14.80 s, so two hundred range scans on a unique index are tens of milliseconds.
The two reads to watch are the backfill and the navbar, and both are watched by
an index rather than by a benchmark.

- [ ] **Step 1: Run the benchmark**

Run: `make bench`
Expected: ~1.7 min. It seeds and removes a scratch library.

- [ ] **Step 2: Compare against the recorded numbers**

Read `docs/event-benchmarks.md` and compare the rebuild time against 16.258 s and
the budget against 60.246 s. A regression in the backfill or the navbar is a
reason to revisit that read's key — not to put its cursor back.

- [ ] **Step 3: Run the full gate**

Run: `make check`
Expected: green. Lint, format-check, mypy, vale, ts-check, vitest, and the entire
pytest suite including `e2e/`. Never a hand-picked subset — `ARGS` is for
iterating, not for the gate.

- [ ] **Step 4: Post the numbers to the issue**

```bash
gh issue comment 917 --body "make bench after the change: rebuild <X>s (was 16.258s), budget <Y>s (60.246s). Full make check green."
```

- [ ] **Step 5: Open the pull request**

```bash
git push -u origin HEAD
gh pr create --title "Page reads by key, and make DISABLE_SERVER_SIDE_CURSORS reachable" --body "Closes #917. See docs/superpowers/specs/2026-08-29-issue-917-server-side-cursors-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Branch first if you are still on `main`.
