# Server-side cursors and keyset pages

`QuerySet.iterator()` opens a server-side cursor. A cursor belongs to one
connection. A connection pooler in transaction or statement pooling mode gives
the next `FETCH` a different connection. The cursor is not there, and the read
fails.

The code is in `common/keyset.py`, `games/events/replay.py`,
`games/backfill/playergame.py`, `common/layout.py`, and `timetracker/database.py`.

## The helper

`keyset_pages()` reads a queryset one page at a time. It takes a key, a
direction, and a page size. It runs one query for each page. It yields rows.

A key is one field or more. The last field must be unique. A key without a
unique field can skip a row, or show one row two times.

All fields of a key must be in one index. PostgreSQL reads a btree in two
directions, thus one ascending index serves both directions of the same key. A
key without an index sorts the table again for each page.

A key of more than one field compares as a row value. `TupleLessThan` and
`TupleGreaterThan` supply that comparison. Do not write
`Q(a__lt=x) | Q(a=x, b__lt=y)`. The logic is the same, but PostgreSQL cannot read
an `OR` as an index range condition, and each page then reads from the start of
the index. A test of the rows alone accepts the incorrect form, thus
`tests/test_keyset.py` also examines the SQL.

## The four reads

| Read | Key | Index |
|---|---|---|
| `replay()` | `sequence` | `UniqueConstraint(stream, sequence)` |
| `backfill_library()` | `id` | primary key |
| `reconcile()` | `id` | primary key |
| `recent_session_resumes()` | `timestamp_start`, `id`, descending | `session_start_id_idx` |

`Game` has no index on `created_at`, thus the backfill keys on `id`. `Game.id` is
a UUIDv7 and sorts in the order of insertion, so two runs order the stream the
same way.

`recent_session_resumes()` stops when it holds sufficient games. Do not use
`DISTINCT ON`. PostgreSQL has no loose index scan for it, and the outer order and
limit need the full distinct set first.

A replay reads pages of a stream that no row leaves. If a row goes away below the
read, the contiguity test refuses the replay.

## The guard

`tests/test_iterator_guard.py` reads the syntax tree of `games/`, `common/`,
`timetracker/`, `contrib/`, and `scripts/`. It refuses a call to `iterator` or
`aiterator`. `RawQuerySet.iterator()` opens no cursor, and a syntax tree cannot
identify it: `ALLOWED_FILES` takes such a file with its reason.

## The lever

`required_database_settings()` reads `DISABLE_SERVER_SIDE_CURSORS`. The default
is false. The value goes beside `ENGINE`, not in `OPTIONS`, which holds driver
arguments. `database_settings_from_url()` does not read it.

`iterator()` and `aiterator()` are the only readers of the setting. First-party
code calls neither. The setting thus governs only the reads in Django:
`ModelChoiceIterator`, `dumpdata`, and `serialize_db_to_string`.

Without a cursor, psycopg receives all rows on `execute()`, and the process holds
the full result. `chunk_size` then limits nothing.

`cast=bool` accepts `true`, `1`, `yes`, and `on`. All other text reads as false,
and no text causes an error.

## What stays unsafe

`games/events/rebuild.py` makes a temp table for each projection table. Its
phases run in different transactions on the same session. A temp table belongs to
a session. Under transaction pooling the rebuild fails, whatever the setting says.
