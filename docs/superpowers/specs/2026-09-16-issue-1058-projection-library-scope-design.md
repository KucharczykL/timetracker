# A projector writes the event's library

Issue: [#1058](https://github.com/KucharczykL/timetracker/issues/1058).

## The problem

`Projector.amend` writes on the primary key alone. `Projector.project` upserts
on the primary key with `library_id` in its update set. An `aggregate_id` is
unique within one stream, not across libraries, so an event naming a row of
another library amends that row, or rewrites it into the event's library, and
reports success. Nothing refuses it: `audit_library_ownership` walks foreign
keys out of projections, not the mapping from an event to the row it writes.
The difference surfaces later, in the other library's rebuild diff or in
`make verify-replay-parity`.

No command produces such an event: every one resolves its subject through
`library_row`. The exposure is anything that appends without a command: a
conversion pass, an operator repair script, a hand-edited stream. The issue
read `project` as safe and asked for no schema change; both were wrong.

## The decision

A projector writes rows the event's library owns, and the two write helpers
enforce it by reading the library off the envelope.

Both helpers take the event, not an identity:

```text
project(Model, event, **columns)
amend(Model, event, **columns)
```

`project` merges `library_id=event.library_id` into the columns ahead of
`_unfilled_columns`, which counts `library` as required, and refuses a handler
that names `library` or `library_id` itself, so no caller holds a library to get
wrong. `amend` filters on `(pk, library_id)`. The twenty-five handler calls
change mechanically; the four hand-typed `library_id=event.library_id` lines go.
`LibraryCalendars` also rewrites `PlayerSession.day_zone` through a filter it
scopes by hand; that write stays outside the helpers and keeps its scope.

### An amendment outside the library

The happy path stays one `UPDATE`. When it changes no row, one lookup by primary
key tells the two defects apart, and both raise `ProjectionRowMissing`:

- no row: the stream lacks its creation event, as today;
- a row in another library: the message names the row, both library ids, and
  that the stream is wrong, not the row.

`ProjectionRowMissing` stays in `NOT_ANSWERED`; the lookup runs only on the
defect path.

### A creation outside the library

Every projection table carries a unique constraint on `(id, library)`. It is
built by one function, `library_identity_constraint()` in `games/models.py`,
named `unique_%(app_label)s_%(class)s_library_identity`, and named in each
concrete `Meta.constraints`: an abstract `Meta` cannot supply it, because a
child that assigns `constraints` shadows the base's tuple, and three of the four
do. Migration `0008` adds the four. `LibraryCalendar` already pins `id` to
`library` with a CHECK; it carries the pair as well, for one rule over every
table.

`project` upserts with `unique_fields=(pk, "library")`, so the conflict target
is the pair. A creation under an id another library holds matches no pair,
inserts, and the primary key refuses it with SQLSTATE 23505, which
`is_retryable` does not retry; on the calendar the CHECK refuses first, with
23514. A re-projection in the same library conflicts on the pair and updates,
as before. No extra query on any path.

Where the refusal surfaces follows the path. A bare append raises the
`IntegrityError` with `apply`'s note naming handler, family and event. A
rebuild replays into an empty shadow, so the foreign creation inserts there
and the diff lists it as rebuilt-only; the swap's `INSERT … SELECT` then hits
the live primary key, and `swap_in` re-raises it, the transaction rolled back.
No path reaches `answered`, because no command produces the event.

`games.E012` refuses a managed projection whose constraints hold no unique
constraint over its primary key and `library`, so a new table cannot omit the
call. Every synthetic projection in the tests carries it too. Shadow tables are
`LIKE … INCLUDING ALL`, so a rebuild's upsert finds the same pair.

### The test harness

The helper tests stand `Device` in for a projection; it holds no pair, so the
pair arbiter is refused there with 42P10. They move to a synthetic
`ProjectionModel` under `isolate_apps`, created with `schema_editor` as
`tests/test_projection_rebuild.py` does, carrying the pair.

## Proof

- `amend` on a row of another library raises `ProjectionRowMissing` naming both
  libraries, in two statements, and the row is unchanged; the happy path still
  costs one `UPDATE`.
- `project` under an id another library holds raises `IntegrityError` with
  23505, and the row is unchanged; re-projection in the same library still
  updates in one statement.
- `games.E012` fires on a projection whose `Meta` omits the pair and
  `manage.py check` is silent on the four live tables.
- `tests/test_projection_replay_gate.py` and `tests/test_projection_rebuild.py`
  unchanged and green: replay, rebuild and swap through both helpers under the
  pair.
- Full `make check`.

## Baked-in assumption

A projection row's library is fixed at creation. A future act that moves a row
between libraries has no event shape here: `amend` refuses it, and `project`
would need the old row removed first. That is the rule the audit already
states, made structural.

## Out of scope

- A typed refusal for the swap's primary-key collision. It is loud and rolls
  back; a sentence there would name a defect in a stream, not an act a person
  can restate.
- A typed refusal for a foreign creation on a bare append, for the same
  reason.
