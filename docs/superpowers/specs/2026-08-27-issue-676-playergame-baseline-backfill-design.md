# Backfill baseline PlayerGame events

Issue [#676](https://github.com/KucharczykL/timetracker/issues/676). The code is
a new `games/backfill/` package, a data migration, and one call added to
`load_sample_data`. #671 gives the row, #672 gives `amend()`, and #673, #674 and
#675 give the five events this replays.

Every catalog game a library holds becomes a game the library *tracks*. The
projection is written only by its projector, so the backfill states facts as
events and lets `PlayerGames` fold them. Nothing writes `PlayerGame` directly.

`games/commands/playergame.py` already names this issue: `_tracked_game()`
rejects a game with no projection row, and says #676 backfills one for every
game a library has. #677 switches the writes, and its commands reject every
status change until this runs.

## The four facts

Per game, in this order:

| # | Event | When it is emitted |
|---|---|---|
| 1 | `library.playergame.created` | Always |
| 2 | `library.playergame.mastered_changed`, `{"mastered": true}` | Only when `Game.mastered` |
| 3 | `library.playergame.status_changed`, one per `GameStatusChange` row | Per legacy row, in order |
| 4 | `library.playergame.status_changed`, corrective | Only when 3 does not fold to `Game.status` |

Event 1 carries `{"game": capture_reference(game)}` and mints the aggregate
identity with `uuid.uuid7()`. Events 2 to 4 read that identity from the
projection row, which the projector wrote synchronously inside this
transaction. That is the same lookup `_tracked_game()` makes, and it is why
event 1 is always sequenced first: `amend()` raises `ProjectionRowMissing`
against a row no creation event made.

No `excluded_from_unfinished` event and no `archived` event. The catalog states
neither. #674 hands exclusion to the Purchase cutover, and #675 states that the
catalog knows no archived game.

## Recorded time and effective time

The charter separates the two, and this section is only about that separation.
A recorded time says when the system learned a fact. An effective time says
when the fact was true. `LibraryEvent` holds both: `recorded_at`, and
`effective_time` as a `TemporalValueField`.

| # | `recorded_at` | `effective_time` |
|---|---|---|
| 1 | `Game.created_at` | Not stated |
| 2 | `Game.created_at` | Not stated |
| 3 | The legacy row's `timestamp`, or `Game.created_at` when it is null | `TemporalValue.from_day` of the local day, or `TemporalValue.unknown()` when it is null |
| 4 | The backfill's run time | `TemporalValue.unknown()` |

Event 1 is backdated because `Game.created_at` *is* a recording time. The row
was written then, and the projector takes `tracked_at` from `recorded_at`, so a
game added in April 2023 reads as tracked since April 2023. Nothing is invented:
the column already held that instant.

Event 3 is different, and the charter says so directly. A non-null legacy
`GameStatusChange.timestamp` is the effective transition time, not a migration
recording time. Live signals wrote the moment of the player's action,
and the original data migration deliberately used the earliest Session, the
refund or drop date, or the PlayEvent completion date. So it enters
`effective_time` at day precision, computed with `timezone.localtime`.

A null legacy timestamp stays unknown. It is not coerced to `Game.created_at`.
The charter puts an undated transition in the Game Journal's approximate
history, and only an unknown effective time can land there.
`TemporalValue.unknown()` serializes to `None`, so an unknown effective time and
an unstated one are one column value. Only the emitter knows which it meant, and
events 1 and 2 mean the unstated one.

Event 4 states a status whose transition date nobody recorded. Dating it with
`Game.updated_at` would be a fabrication: that column is `auto_now`, so it holds
the last time *any* field of the game changed, which is not when the status
changed. The charter's fourth verification requirement forbids fabricated
temporal precision. So the event says what is true — the migration recorded this
status at its run time — and leaves the transition date unknown.

### The timezone is baked once

There is no per-library display timezone. `settings.TIME_ZONE` is it, and #748
introduces the per-library setting with a Journal rebuild behind it. A rebuild
moves projections; it cannot move an immutable event. So the day this backfill
computes for event 3 is permanent, and a transition at `2023-06-02T23:30Z`
recorded as `2023-06-02` under `Europe/Prague` stays `2023-06-02` if the setting
later changes. The charter prescribes the owner's display timezone, and this is
the only one that exists. The choice conforms, and it is one-way.

## Ordering and the fold

Legacy rows are read ordered by `timestamp` with nulls first, tie-broken by
primary key. The query states that order explicitly, because
`GameStatusChange.Meta.ordering` is `-timestamp` and an inherited descending
order would fold the history backwards.

`old_status` is ignored. The fold sets a value rather than applying a delta, so
a legacy row whose `old_status` disagrees with the previous row's `new_status`
changes nothing about the result. Reconciliation checks the result, not the
chain.

Games are processed ordered by `created_at` then primary key, so a run is
deterministic. Within one aggregate the sequence order is the chronological
order, which is what the fold needs. Across the stream it is not:
game B's creation event can carry an earlier `recorded_at` than game A's status
events. No constraint requires `recorded_at` to be monotonic with `sequence`,
and none is added. The log orders by `sequence`.

## The status map

`Game.Status` is one letter; `PlayerGameStatus` is a word, because a recorded
payload cannot be upcast. The map is `u` to `unplayed`, `p` to `played`, `f` to
`completed`, `r` to `retired`, and `a` to `abandoned`.

`shelved` has no legacy source and is never emitted. A test iterates
`Game.Status.values` and asserts each maps, so a sixth letter added later fails
the suite instead of reaching a mismatch record. An unmapped letter found at run
time is a reconciliation mismatch, not a `KeyError`.

## Which games are skipped

A tombstoned game is skipped. Retention emptied the row and kept it only for the
events that name it, so there is nothing left for a library to track.

A shared game — `library` is null — is skipped. `GameForm.__init__` always
stamps `instance.library`, so the production catalog holds none; the skip is a
guard, not a code path with data behind it.

Everything else gets a row, including a game whose status is `unplayed` and
whose history is empty. That game gets event 1 only, and the projection's
constant default supplies the status.

## One append per event

`LockedStream.append()` stamps one `recorded_at` across every row of one call.
That is correct for one act of recording and wrong here: these events carry four
different dates. So each event is its own `idempotent_append`, with its own
`recorded_at`, `effective_time`, `idempotency_key` and `correlation_id`.

The keys are deterministic, so a repeat replays rather than duplicates:

- `backfill:676:playergame:created:{game_id}`
- `backfill:676:playergame:mastered:{game_id}`
- `backfill:676:playergame:status:{status_change_id}`
- `backfill:676:playergame:status:current:{game_id}`

Each stays well inside the 255-character column. `idempotent_append` takes a
`command_input` dictionary and fingerprints it, so a repeated key carrying
different input raises `IdempotencyKeyMismatch` instead of replaying the wrong
fact. The corrective event's input names the status it sets, which makes a
changed current status loud rather than silent.

`dispatch()` is not used. It requires a `Command`, and a command validates
against current state to refuse a duplicate — `SetPlayerGameStatus` rejects
setting the status a game already has, which is the normal case here.
`idempotent_append` accepts an arbitrary `command_input` and a `recorded_at`,
so the backfill composes the same append and idempotency machinery without
borrowing a command's refusals.

`run_in_transaction` is also not used. Its retry answers a concurrent writer,
and a migration has none. `backfill_game` opens the atomic block `lock_stream`
requires, so one game's facts are recorded whole or not at all; inside the
migration's transaction that block is a savepoint, and the repeated
`SELECT ... FOR UPDATE` on one stream head is a no-op after the first.

## The actor and the correlation IDs

The actor is the library's owner. The facts are that person's, and
`idempotent_append` takes `actor` directly, so no authorization is bypassed —
`authorize()` belongs to `dispatch`, and it would pass regardless.

Each event gets its own correlation ID. #685 correlates unambiguous lifecycle
and status facts, and it cannot happen here: the PlayEvent side is not
backfilled until the PLAY wave, so there is nothing to pair against.

`correlation_id` is immutable, so #685 cannot retrofit a pairing onto these
rows. It does not need to. #685 runs later, so its appends can *adopt* the
correlation ID this backfill already minted. For that join to be possible the
source row must be findable, so `source_metadata` carries it:
`{"origin": "backfill", "issue": 676, "status_change_id": …}` for event 3, and
the same pair without the third key for events 1, 2 and 4. This is the one
requirement #676 accepts on behalf of a later issue, and it costs a dictionary
key.

## Where the code lives

`games/backfill/playergame.py`, beside `games/commands/playergame.py` and
`games/projectors/playergame.py`. One `games/backfill/__init__.py` opens the
package.

The migration imports it, and so does `load_sample_data`. A migration is a
vehicle, not a home: putting the logic in the module keeps it testable without
a `MigrationExecutor` and gives the sample loader the same baseline a real
database gets.

The module imports the live `games.events` and `games.models`, not
`apps.get_model`. Historical models cannot run projectors or validate payloads,
so an `apps.get_model` backfill would have to write events and projection rows
by hand — a second event writer, which the charter forbids. The cost is that
migration 0033 is pinned to whatever the application looks like when it runs.
That is deliberate, and the reconciliation below is what keeps a future
incompatibility loud.

## The migration

`0033_playergame_baseline_backfill`, depending on
`0032_playergame_archived_at`, one `RunPython` with
`migrations.RunPython.noop` as `reverse_code`, and `elidable=True` — a squash
has no reason to keep it once it has run.

It follows `0020_catalog_hierarchy_backfill`, which is the house precedent. It
runs the backfill, runs it a second time, and reconciles. The second pass
appends nothing and proves it: every key is already recorded, so the pass is
lookups. It doubles the run time of a job of roughly two appends per game, which
is seconds.

Reconciliation emits one machine line and one human line, as 0020 does:

```text
PLAYERGAME_BASELINE_RECONCILIATION_JSON={"schema_version":1,"summary":{…},"mismatches":[…]}
PGAME baseline reconciliation: games=… tracked=… created_events=… …
```

The summary counts games, tracked rows, events of each of the four kinds,
unknown effective times, skipped tombstoned games, and mismatches. Shared games
are one global count, not a per-library one: a count of the games no library
owns means nothing under a library heading. A nonzero mismatch count raises `RuntimeError`, and PostgreSQL rolls
the migration back.

A mismatch is one of: `unmapped_legacy_status`, a letter the map does not know;
`status_disagreement`, a folded `PlayerGame.status` that is not the mapped
`Game.status`; `mastered_disagreement`, the same for the flag;
`missing_projection_row`, a game the backfill covered with no row behind it; and
`count_drift`, a second pass that appended an event.

## Sample data

`load_sample_data` calls the backfill after it loads the fixture, so a
development database gets the same baseline. The fixture carries
`GameStatusChange` rows, so events 3 and 4 both occur there.

`make anonymize-sample` is unchanged. It omits `GameStatusChange` from its dump
labels and regenerates the rows, which is upstream of this and stays that way.

## Consequences outside the backfill

**A backdated recording backdates its identity.** The identity audit holds every
`LibraryEvent` row's UUIDv7 to its `recorded_at` order, and no constraint
enforces it. This backfill is the first writer to record a past moment, so
`LockedStream.append()` mints each row's identity from the `recorded_at` it was
handed, with the `uuid7_at` every Wave B backfill used. The microseconds below
the millisecond go in the 12-bit field RFC 9562 reserves for a same-millisecond
counter, because `Game.created_at` is `auto_now_add` and the sample fixture
loads hundreds of games inside a few milliseconds. A live append is unaffected:
its `recorded_at` is already now. This does not make `recorded_at` monotonic
with `sequence`, which nothing requires.

**Deleting a game changes shape.** `catalog.game` is a `REQUIRED` reference
kind, so after the backfill every live game is named by at least one event.
`must_be_retained()` then answers true for all of them, and
`tombstone_or_delete()` returns `Retirement.TOMBSTONED` where it used to return
`Retirement.DELETED`. The confirmation page switches to `retention_message()`.
This is the retention policy working as designed, not a regression, and it makes
#929's `RestrictedError` path harder to reach. Existing tests build games without
running the migration, so the suite is unaffected; one new test pins the new
behaviour.

**The legacy history stays editable.** `games/views/statuschange.py` keeps its
add, edit, list and delete views, and the game detail page keeps its history
section. #771 removes the legacy storage, and until then a player can edit a
`GameStatusChange` row that this backfill already turned into an immutable
event.

The divergence is real and bounded. `GameStatusChangeForm` writes
`GameStatusChange` only; it never touches `Game.status`. So an edit rewrites
history, not current state, and `PlayerGame.status` cannot drift — event 4 pins
the fold to `Game.status` at run time. Only intermediate transitions can
disagree, and nothing reads them from the log until the Journal wave. Making the
form read-only is a write-path change, which this issue's boundary assigns
elsewhere.

**The run happens once, late.** Production applies this migration at the end of
Phase 2, together with every other migration of the phase, and not before. Three
things follow. The catalog keeps growing until then, so the mastered and dated
status paths will have data behind them at run time whatever today's counts say
— neither is trimmed on the strength of a current zero. The migration executes
under end-of-phase code rather than today's, which is the live-import cost named
above. And the reconciliation output is the only evidence the run produces, so
the verification below requires a rehearsal against a restored production
database before the deploy.

## Verification

The gate is the full `make check`, over tests for:

- the status map's totality against `Game.Status.values`
- an unplayed game with no history: one event, one row, status unplayed
- a non-unplayed game with no history: creation plus a corrective event whose
  effective time is unknown
- dated history that folds to the current status: no corrective event
- dated history that does not: a corrective event, and a folded status equal to
  `Game.status`
- a null legacy timestamp: a null `effective_time`, and `recorded_at` at
  `Game.created_at`
- a dated legacy row: `effective_time` at the local day, `recorded_at` at the
  row's timestamp
- a mastered game: one `mastered_changed`, and `PlayerGame.mastered`
- a tombstoned game and a shared game: skipped, with no row
- two libraries: each stream holds only its own events, and no row crosses
- a second run: no new event, and identical rows
- `rebuild_projections` in `RebuildMode.CHECK`: no drift after the backfill
- a forced disagreement: `RuntimeError`, and a rolled-back migration
- `source_metadata` carrying `status_change_id` on event 3 and omitting it
  elsewhere
- a delete after the backfill: tombstoned rather than deleted
- a backdated append: an identity that orders by `recorded_at`, and two moments
  one millisecond apart that still order the way they happened
- the committed sample fixture: the whole identity audit, after the loader ran
- the migration itself, 0032 to 0033, through the `MigrationExecutor` harness
  `tests/test_catalog_hierarchy_migration.py` established

Before the production deploy, the migration runs against a restored production
database and its reconciliation output is read. `make anonymize-sample`
documents that restore. This is the issue's migration evidence, and it is not
optional here: the run is unrepeatable and unrehearsed anywhere else.

## Reversibility

`reverse_code` is a no-op, by decision: a reverse migration is out of scope. A
revert is the commits.

The failure mode is a migration that raises. Django wraps each migration in its
own transaction on PostgreSQL, so a reconciliation `RuntimeError` rolls back 0033
alone and stops the deploy with the migrations before it committed. That state is the
database as it was, plus prior migrations, and it is recoverable by fixing the
backfill and running `migrate` again — the idempotency keys make a partial
first attempt impossible, because the rollback took the records with it.

## Out of scope

No view, form or API changes. #677 switches the writes and #678 the reads. #685
correlates these status facts with lifecycle facts and is unblocked by
`source_metadata`, not by anything else here. #771 removes the legacy storage
and the editing UI with it. No filter, saved preset or statistic reads
`PlayerGame` yet, so none changes.
