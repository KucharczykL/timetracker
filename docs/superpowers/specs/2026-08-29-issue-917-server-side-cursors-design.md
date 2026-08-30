# Who opens a server-side cursor

The code is in `timetracker/database.py`, `common/keyset.py`,
`games/events/replay.py`, `games/backfill/playergame.py`, and
`common/layout.py`. Two comments name this issue and go stale with it:
`games/management/commands/benchmark_events.py` and
`games/events/benchmark_workload.py`. The tests are in
`tests/test_database_configuration.py`, `tests/test_keyset.py`, and
`tests/test_iterator_guard.py`.

`QuerySet.iterator()` opens a server-side cursor. A cursor belongs to one
connection. A pooler in transaction or statement pooling mode gives the next
`FETCH` a different connection. The cursor is not there, and the read fails.

Django reads one setting to stop this. `DISABLE_SERVER_SIDE_CURSORS` sits beside
`ENGINE` and `NAME` in the database settings, not inside `OPTIONS`. `OPTIONS`
holds the arguments of the driver. This deployment builds its settings from one
URL, so it can set `OPTIONS` and it cannot set this.

## Two territories

`iterator()` and `aiterator()` are the only readers of the setting.
`django/db/models/query.py:531` and `:543` read it, and no other line does.

Four of those calls are ours: `games/events/replay.py`,
`games/backfill/playergame.py` twice, and `common/layout.py`.

The rest are Django's, and there are fewer than they look.
`ModelChoiceIterator.__iter__` calls `iterator()` for the choices of a model
field. Seven model fields of this repository render through
`SearchSelectWidget`, which passes `options=None` and resolves the selected rows
with a `pk__in` query. That widget never reads the choices, so those seven never
reach the call. One field renders a plain `select`:
`LibraryPreferencesForm.default_device`. There is no `games/admin.py`.

The other callers of Django are `dumpdata`, which is `make dumpgames`, the
serializers it uses, and `serialize_db_to_string` in the test database.

So the setting governs one list of devices, one management command, and the test
harness. That is small, and it is the only control there is over any of them. We
can rewrite our four. We cannot rewrite Django's.

## What the setting costs

The setting does not make a read lazy or eager. It moves where the rows sit.

With a cursor, the rows arrive one page at a time, and the process holds one
page.

Without a cursor, psycopg 3.3 receives every row on `execute()`, and
`django/db/models/sql/compiler.py:1662` returns `list(result)`. The process
holds every raw row before it builds one model instance. `chunk_size` then sizes
`fetchmany()` calls over rows that already arrived. It bounds nothing.

The cost is not the same at the four sites, because `WITH HOLD` is not.
`django/db/backends/postgresql/base.py:421` declares a cursor `WITH HOLD` only
in autocommit. PostgreSQL then writes the whole result to temporary storage when
the declaring transaction commits, which in autocommit is at once.

One of the four reads is in autocommit. `recent_session_resumes()` renders the
navbar. Its cursor spools every session of the library to temporary storage at
`DECLARE`, on every authenticated page. For that read the setting moves rows
that are already spooled, and keyset paging removes the spool.

The other two are inside a transaction, so their cursors hold nothing.
`replay()` runs under `with transaction.atomic()` at `games/events/rebuild.py:171`,
its only production caller. `backfill_library()` runs inside `RunPython` in
`games/migrations/0033_playergame_baseline_backfill.py`. Both read lazily today.
Throwing the setting at them really would pull the whole result into memory —
for the replay, every event row of a library with its JSONB payload.

That is the argument for doing both halves. The setting is safe to throw only
after the large reads stop depending on a cursor.

## What this does not make safe

`games/events/rebuild.py:48` creates a temp table for each projection table, and
phases 2 and 3 run in separate transactions on the same session.
`_require_shadow_tables()` already states that dependence in its error text. A
temp table belongs to a session. Under transaction pooling the rebuild is broken
whatever this setting says and whatever the reads do.

`docs/database.md` states this. The setting is not a pooler adoption, and this
specification is not one either.

## The lever

`required_database_settings()` reads it.

```python
settings = database_settings_from_url(url)
settings["DISABLE_SERVER_SIDE_CURSORS"] = config(
    "DISABLE_SERVER_SIDE_CURSORS", default=False, cast=bool
)
```

`database_settings_from_url()` does not read it. That function translates one
URL and does nothing else, and `tests/test_database_configuration.py` asserts
its whole return value against an exact dictionary. A setting that comes from
the environment does not belong in that value.

The name is Django's name. One string finds the documentation of Django and this
repository.

The default is `False`.

`cast=bool` accepts `true`, `1`, `yes`, and `on`, in any case. Every other
string reads `False`, and none of them raises. A typed `ture` therefore reads as
off. `docs/configuration.md` lists the four accepted words for that reason.

`timetracker/settings_registry.py` does not get an entry. `DATABASE_URL` has
none either, and `tests/test_settings_registry.py` freezes the set of keys. This
is a decision, not an omission.

## The helper

`common/keyset.py` holds one generator, `keyset_pages()`. It takes a queryset, an
ordered key, and a page size. It yields rows. It runs one query for each page.

A key is one field or several, and each field has a direction. The last field is
unique. A key with no unique field can skip a row or yield one twice.

**The comparison is a row value.** Django 6 ships one:
`django/db/models/fields/tuple_lookups.py` holds `Tuple`, `TupleLessThan`, and
`TupleGreaterThan`.

```python
TupleLessThan(Tuple(F("timestamp_start"), F("id")), (last_start, last_id))
```

Do not write it as `Q(a__lt=x) | Q(a=x, b__lt=y)`. That is the same logic and
the wrong SQL. PostgreSQL cannot read an `OR` as an index range condition, so
each page filters from the start of the index and the whole walk is quadratic. A
measurement on 600k rows at a depth of 200k rows read 200001 rows and 3423
buffers in 15.021 ms; the row value read 1 row and 39 buffers in 0.279 ms. The
gap grows with the page number. The `OR` form is slower than the cursor it
replaces, at the size that motivates the change.

A test of rows alone passes on both forms. `tests/test_keyset.py` therefore
asserts the SQL of the query as well.

`_catalog` in `games/events/benchmark_workload.py` pages on `id` with a slice.
It is the single-field case, where this hazard cannot arise. It is the template
for the two backfill reads below, not a copy of the comparison above. It uses
the helper when the helper exists, and its comment stops naming this issue as
unsolved.

## The four reads

Every key below range-scans an index. A key without one re-sorts the table on
every page, which is worse than the single sort it replaces.

### The replay

`replay()` reads a stream in order of `sequence`. The key is `sequence`,
ascending. `UniqueConstraint(fields=("stream", "sequence"))` at
`games/models.py:1629` makes it unique, and `stream_id=head.id` scopes it. The
constraint is the index.

The read is already bounded. `sequence__lte=bound` names the head before the
first row. A page and a cursor therefore see the same rows, as long as no row
goes away underneath.

Nothing in the database enforces that. There is no trigger and no rule.
`purge_user_library.py` removes a user, and the cascade takes the events of the
library with it. Append-only is a convention here, not a constraint. With a
cursor a lost row was invisible; with pages the contiguity test raises
`StreamNotContiguous`. That is the better outcome, and it is a change of
behaviour worth stating.

The contiguity test stays. It reads every sequence from 1 to the bound.

The `cast` to `Generator` and the `closing()` block go. Both are there because
`iterator()` returns a generator that holds a cursor. The comment about
`WITH HOLD` goes with them.

This is the cheapest and safest of the four. The key is one field, the index
exists, and #932 measures the whole read half of the replay at 4.33 s of
14.80 s. Two hundred range scans on a unique index are tens of milliseconds.

### The backfill

`backfill_library()` orders by `created_at` and `pk` today. **The key is `id`,
ascending.** `Game` carries no index on `created_at`: its only indexed fields
are `library` and `platform`, and it declares no `Meta.indexes`. A key of
`(created_at, pk)` sorts the whole library on every page. One page of 200 over
100,410 rows scans 100,410 rows in 5.201 ms, against 13.165 ms for the single
sorted read of today. At 502 pages that is about 2.6 s, and it grows with the
square of the catalog.

`Game.id` is a `UUIDv7Field`, so it sorts in the order rows were inserted, and
the primary key is its index. This is what `_catalog` already does and what its
comment argues for.

The read stops ordering by `created_at`. The docstring asks only that two runs
order the stream identically, and `id` gives that. A run made after this change
can order its events differently from the run migration 0033 made. The backfill
is one-shot, so this is recorded rather than solved.

`reconcile()` orders by `pk`. That is the key, ascending, and the primary key
index serves it.

### The navbar

`recent_session_resumes()` at `common/layout.py:178` reads sessions from the
newest. It keeps the first session of each game and stops at the limit. The
navbar calls it at `common/layout.py:397`, so it runs on every authenticated
page.

Today it calls `iterator()` with no `chunk_size`, which is 2000, in autocommit.
PostgreSQL spools every session of the library at `DECLARE`. This read gains the
most and is not a wash.

The key is `timestamp_start` and `id`, descending. A start time is not unique.
An id is.

`Session` indexes `timestamp_start` alone and declares no `Meta.indexes`. A
descending key of two fields over a single-column index adds an incremental
sort, which drains each group of equal start times before it emits. **A
migration adds an index on `(timestamp_start, id)`.** Without it the tie case
that the tests below must create is also the case that reads far more rows than
the limit.

Do not use `DISTINCT ON`. The loop stops when it holds enough games. PostgreSQL
has no loose index scan for `DISTINCT ON`, and the outer order and limit need
the whole distinct set first, so it reads every session of the library. The cost
of the navbar would follow the whole history.

## The guard

A test walks the syntax tree of `games/`, `common/`, `timetracker/`, `contrib/`,
and `scripts/`. It reports a call to an attribute named `iterator` or
`aiterator`. The report names the file, the line, and `common/keyset.py`.

`scripts/` is in the walk. It is first-party Python, and `make vale` already
reads it.

`tests/` and `e2e/` are outside the walk. They are not the path a pooler serves.

The test does not put a violation in the tree to prove itself. It reads a string
of source and asserts the report.

There is one known class of wrong report. `RawQuerySet.iterator()` at
`django/db/models/query.py:2216` yields rows and opens no cursor, and a syntax
tree cannot tell it from a queryset. No call site uses it today. The allowlist
holds no entries and takes one with a reason, as a conflict answer does.

CLAUDE.md gets the rule.

## The tests

The helper is tested first. One field ascending. Two fields ascending. Two
fields descending. A result set that ends on a page boundary. One row. No rows.

Two cases matter most.

Two rows share a sort value, and the page boundary falls between them. This is
what a wrong comparison breaks, and it breaks by skipping a row.

The query text holds a row-value comparison. This is what the `OR` form breaks,
and it breaks by being slow while every row is correct.

Each call site is tested across a page boundary. A fixture inside one page
proves nothing. Each site therefore names its page size as a module constant, as
`REPLAY_CHUNK_SIZE` already does, so a test can set it small.

The navbar test holds more sessions than a page, several sessions of one game,
and one start time on both sides of the boundary.
`tests/test_navbar_log_button.py` reads the first session query out of
`CaptureQueriesContext`, and paging keeps that first query, so it stands.

`tests/test_database_configuration.py` gets four assertions. The key is absent
and reads `False`. The key is `true` and reads `True`. The key is `ture` and
reads `False`. The key sits beside `ENGINE`.

## The benchmark

`make bench` runs before the change and after it, and the numbers go in the
issue.

`docs/event-benchmarks.md` records 100,410 events and a budget of 60.246 s. #930
is closed: it took the rebuild from 60.223 s to 16.258 s. #932 is open and holds
the next 9 s.

The replay is not the read at risk here, so there is no escape hatch written for
it. The two reads to watch are the backfill and the navbar, and both are watched
by an index rather than by a benchmark. A regression in either is a reason to
revisit its key, not to keep its cursor.

## The documentation

`docs/configuration.md` states the setting, its default, the four words that
read as true, and the reason to set it.

`docs/database.md` gains a pooling section. It has none today. It states what a
pooler in transaction or statement mode does to a cursor. It states that our
reads page by key. It states that the setting governs the remaining reads of
Django, and it names them. It states that the rebuild is bound to one session by
its temp tables and is not pooler-safe.

## Not in this specification

A pooler. No deployment here runs one, and adopting one is its own work, of
which the temp tables of the rebuild are the first item.

The batched writes of #932.
