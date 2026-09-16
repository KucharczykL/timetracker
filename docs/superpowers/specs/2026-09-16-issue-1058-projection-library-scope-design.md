# A projector writes the event's library

Issue: [#1058](https://github.com/KucharczykL/timetracker/issues/1058).

## The rule

A projector writes only rows that the event's library owns. The two write
helpers in `games/events/projection.py` enforce the rule. Each one reads the
library from the envelope. No handler supplies a library.

```text
project(Model, event, **columns)
amend(Model, event, **columns)
```

## Why the rule is necessary

An `aggregate_id` is unique in one stream, not across libraries. Before this
rule, `amend` wrote on the primary key alone, and `project` upserted on it with
`library_id` in the update set. An event that named a row of another library
changed that row and reported success. The audit walks foreign keys out of
projections, not the row an event writes, so the error showed later, in a
rebuild diff or in `make verify-replay-parity`.

No command makes such an event: each resolves its subject through
`library_row`. The exposure is an append outside a command: a conversion
pass, a repair script, a hand-edited stream.

## `project`

`project` merges `library_id=event.library_id` into the columns before
`_unfilled_columns`, which counts `library` as required. A handler that names
`library` or `library_id` gets a `TypeError`.

Each projection table is unique on `(id, library)`. `library_identity_constraint()`
in `games/models.py` builds the constraint, named
`unique_%(app_label)s_%(class)s_library_identity`. Each concrete `Meta` names
it. An abstract `Meta` cannot supply it: a concrete `Meta` inherits none of
it. Migration `0008` adds the four. `games.E012` refuses
a managed projection whose constraints do not hold the pair. `LibraryCalendar`
keeps its CHECK `id = library` and carries the pair as well.

The upsert names `unique_fields=(pk, "library")`. The conflict target is the
pair. A creation under an identity that another library holds matches no pair,
inserts, and the primary key refuses it with SQLSTATE 23505; on the calendar
the CHECK refuses first, with 23514. `is_retryable` does not retry it. A re-projection in the same library conflicts on the pair
and updates. No path costs an extra query.

A bare append raises the `IntegrityError` with the note from `apply`. A
rebuild replays into an empty shadow table, so the foreign creation inserts
there; the swap's `INSERT … SELECT` then hits the live primary key. `swap_in`
answers that 23505 with `SwapRefusedByIdentity`, beside
`SwapRefusedByReference` under `SwapRefused`: it reads the live row after the
rollback, names table, identity and holding library, and logs it. Both
commands catch `SwapRefused`. Shadow tables are `LIKE … INCLUDING ALL`, so
the pair exists there.

## `amend`

`amend` filters on `(pk, library_id)`. A handler that names `library_id`, or
no column, gets a `TypeError`. The happy path is one `UPDATE`. When the
`UPDATE` changes no row, one lookup by primary key on the live table tells two
defects apart. Both raise `ProjectionRowMissing`, which stays in
`NOT_ANSWERED`:

- No row: the stream has no creation event.
- A row in another library: the message names the row and both library ids.
  The stream is wrong, not the row.

## The other writer

`LibraryCalendars` rewrites `PlayerSession.day_zone` on every session of the
library through `library_rows(Model, event)`, the third helper.
`tests/test_projector_scope_guard.py` refuses a manager reach anywhere in
`games/projectors/`.

## Assumption

A projection row's library is fixed at creation. No event moves a row between
libraries: `amend` refuses it, and `project` needs the old row removed first.

## Out of scope

A typed refusal for the primary-key collision on a bare append. The path is
loud and rolls back, and no command can produce the event.
