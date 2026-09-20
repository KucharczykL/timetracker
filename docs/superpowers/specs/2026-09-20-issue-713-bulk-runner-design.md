# The bulk-command runner

Issue: [#713](https://github.com/KucharczykL/timetracker/issues/713). Part of
the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md).

One act runs on many rows as one batch. A person undoes the batch as one.

## The declaration

A bulk action is a value in `games/bulk_actions.py`. Construction declares it.
`__post_init__` refuses a name twice stated, and an inverse aggregate no event
speaks about. A view of the table admits no write. Each act states a name, a
label, the noun its answer speaks of, a cardinality, and five things:

| stated | what it is |
|---|---|
| scope | the act's base queryset, narrowed by the statement's filter. An unreadable filter refuses the act, and never widens it |
| resolve | keys to rows, and a sentence for each row left alone |
| run | one row, through its wrapper in `games/writes/` |
| inverse | one row's opposite, by key |
| inverse aggregate | which half of a mixed batch the Undo reads |

An act can write two aggregates. The reclassification appends a created record
beside the moved session, and the inverse takes the session. Each act's own
half is in its own module, imported at the foot of the table.

## The two POSTs

One route, `/bulk/<action>/`, origin-aware. The submission token tells its two
POSTs apart. A POST with no token resolves the statement under the library and
answers a confirmation: the act, the count, the rows to a cap, each refusal
with its reason, a fresh token, and the resolved keys. A POST with a token
acts. The keys and the tally each ride one field, so the runner keeps nothing
between requests. The token is the batch's correlation id, a UUIDv7.

## The chunk

A chunk is the rows one request acts on inside `CHUNK_BUDGET`. A chunk is no
transaction. Each row is its own dispatch, keyed from the token and the row, so
a token posted twice acts once. Rows left over render a waypoint, which states
the tally, posts the rest back, and offers a Stop. `<continuing-batch>` posts
that form on connect.

The tally counts four things apart: rows moved, rows already in that state,
rows refused on their merits, and rows gone since the confirmation. It keeps
each reason once, apart from the counts, because one sentence can stand over
many rows. A defect ends the batch, and the rows done stay done.

The answer states counts and sentences. The log states keys, under the batch's
identity, for every row left alone: refused by the resolve, refused by the
command, or reached by no dispatch after a Stop or a defect.

## The batch

Every append shares the correlation id, and states the act's name in its source
metadata. The Undo reads one event to learn the act, then the aggregates of
that act's aggregate type to learn the rows. It applies the inverse as a batch
of its own: its own token, correlation id, budget, waypoint and answer. A name
the table does not hold is refused. A correlation that states no name is not
found. `LibraryEvent` declares two indexes beside its sequence:
`(library, correlation_id)` for the batch reader, and `(library, aggregate_id)`
for the move inverse in #714.

## Delivered

The reclassification is the first act. "Move all" on the Library page states an
`all` selection over the review. A selection names a scope and a count, never
keys, so the runner resolves the scope again at the press.

Tests cover two chunks under one correlation, a token posted twice, a lost row,
a refused row, a defect, an unreadable filter, a count that moved, a Stop, and
an Undo that reads past the record events.

`make bench` times 600 rows through the runner's own loop, the resolve and the
dispatch together. On the 2026-09-20 seed: p50 8.3 ms, p95 9.1 ms, max 14.0 ms
against the 100 ms a command is given, of which the resolve is 1.9 ms at p95. A
three-second chunk holds about three hundred rows. The replay reconciles clean.
The recording is `docs/event-benchmarks.md`.
