# The Playthrough aggregate and its default

Issue [#679](https://github.com/KucharczykL/timetracker/issues/679). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).

`Playthrough` is the second projection table and the second command family.

## The registry

One projector family holds many projectors. `ProjectorRegistry` keys ownership
on the `(family, event type)` pair. Two projectors in one family must not claim
one event type. The order between families is the member order of
`ProjectorFamily`, and later families read what earlier families write. The
order in one family is the registration order, and it has no effect.

## The table

`Playthrough` subclasses `ProjectionModel`. The primary key is the creation
event's `aggregate_id`, so the model supplies no default. `created_at` is the
event's `recorded_at`.

`player_game` is a `RESTRICT` foreign key to `PlayerGame`. `kind` is `ordinary`
or `imported_history`; the numbering skips the second kind. `name` and `note`
are blank text. `started` and `completed` are `TemporalValueField` columns, each
with a generated lower bound and a generated upper bound beside it.

`removed_at` is the projector's mark. `Playthrough` is not in
`REMOVABLE_MODELS`, because no user command stamps that column.

## The event and the commands

`library.playthrough.created` carries the tracked game as a `ReferenceId` and
the kind as a `Literal`. The payload names no reference kind, so a rebuild of a
library that lost rows still runs.

`CreatePlaythrough` states one ordinary playthrough for a tracked game. It
refuses a game the library does not track, and a game the library removed.

`TrackGame` appends the `PlayerGame` creation event and the `Playthrough`
creation event together. One dispatch resolves one `correlation_id`, and one
idempotency record covers both events. Every tracked game therefore holds a
default playthrough from the first act.

## The display number

A blank name displays as `Playthrough N`. `N` is derived at read time and stored
nowhere. The window counts the live ordinary playthroughs of one tracked game,
ordered by known start bound, then known completion bound, then creation time,
then primary key. The primary key makes the order total, so the number is the
same after a rebuild.

## The library invariant

A projection row and every projection row it names belong to one library. A
cross-library row makes the library un-rebuildable, because the swap works one
library at a time. `audit_library_ownership` reports the violation.
