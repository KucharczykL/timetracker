# Remove and restore a Playthrough

Issue [#1011](https://github.com/KucharczykL/timetracker/issues/1011). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Predecessors: [the Playthrough aggregate](2026-09-04-issue-679-playthrough-aggregate-design.md),
[a start and a completion](2026-09-06-issue-681-playthrough-endpoints-design.md),
and [corrections](2026-09-06-issue-1010-playthrough-corrections-design.md).
The model for the pair is [archive and restore a tracked
game](2026-08-27-issue-675-playergame-archive-restore-design.md), read together
with the rename [#944](2026-08-29-issue-944-one-removal-act-design.md) applied
to it.

A library takes a run out of its lists, and later puts it back. Both acts are
stated as commands, because `Playthrough.removed_at` is the projector's column
and no other writer may touch it.

## No schema change

`Playthrough.removed_at` exists. #679 added it with the row, nullable, not
editable, starting at `None`. `tests/test_projection_model.py` already pins the
default, so `PINNED_DEFAULTS` gained no entry.

Two places read the column besides the projector: the numbering excludes a
removed row, and `_live_run` refuses every statement about one.

This issue added no migration, no field and no index. Its whole reversal is the
projection rebuild [#667](2026-08-25-issue-667-shadow-rebuild-design.md)
already provides.

## Two events

The types are `library.playthrough.removed` and `library.playthrough.restored`.
The aggregate id is the run's own identity, and both payloads are empty.

Removing and restoring are two facts, so the type is the fact and no payload
holds a direction that could disagree with it. Each payload is a bodyless
`TypedDict` under `STRICT_SCHEMA`, so a later fact takes a later type rather
than a key nobody declared.

Neither payload states the time. `recorded_at` carries it, exactly as the
creation event carries `created_at`, so a replay writes what was recorded.

Each spec has a builder function beside it, `playthrough_removed()` and
`playthrough_restored()`. #675 called its specs directly; every Playthrough
event since #679 has a builder, and the commands and the projector import
builders rather than specs.

## Two commands

`RemovePlaythrough(playthrough_id)` and `RestorePlaythrough(playthrough_id)`,
with `CommandName.PLAYTHROUGH_REMOVE` as `library.playthrough.remove` and
`CommandName.PLAYTHROUGH_RESTORE` as `library.playthrough.restore`.

Both resolve the row with `library_playthrough()`, the library-scoped resolver
#681 wrote. Neither uses `_live_run()`. That helper refuses a run whose
`removed_at` is set, which is right for a statement about a live run and wrong
for both of these: a repeated removal must answer `Unchanged`, and a restore
can only ever name a removed row.

### The order the refusals run in

`RemovePlaythrough.build`, under the lock:

1. the run is already removed, so answer `Unchanged`;
2. the run's `PlayerGame` is removed, so refuse;
3. a registered referrer names the run, so refuse;
4. the run is ordinary and no other live ordinary run remains on its
   `PlayerGame`, so refuse.

`RestorePlaythrough.build`, under the lock:

1. the run is not removed, so answer `Unchanged`;
2. the run's `PlayerGame` is removed, so refuse.

The no-op comes first, which is the rule
[#906](2026-08-28-issue-906-no-op-command-semantics-design.md) settled: a
command asking for state that already holds is a success recording no event,
and it is never refused for a reason that could not apply to it. A second
removal of a run whose game was removed in between therefore still answers
success.

This is a different order from `_live_run`, which reads the parent first and
the run second. Both are correct for what they guard, and neither is obvious
from the other, so each build carries a comment naming #906 as the reason it
differs.

`RestorePlaythrough` refuses under a removed game, and
`RestorePlayerGame` refuses under nothing. The two do not contradict each
other. `RestorePlayerGame` consults no catalog row because a removed catalog
Game is not restorable from the library, and refusing would leave a library a
game it can neither see nor recover. Here the thing above is a `PlayerGame`,
`RestorePlayerGame` never refuses, and so the way out is always open: restore
the game, then restore the run. The refusal states that order rather than
hiding a restored row behind a removed game.

Each refusal carries a `sentence`, and the removal pair writes its own rather
than borrowing the one `_live_run` states. `_refuse_under_a_removed_game()`
holds it for both commands. "Restore it before recording this"
names an act the person is not performing. The pair says the game was removed
and asks for it back before its runs are changed.

### The last ordinary run

Every tracked game is meant to hold `Playthrough 1`. A removal that would leave
a game with no run at all is refused.

The rule counts **live ordinary rows**, and it applies only when the run being
removed **is** ordinary. Both halves matter:

- the display number is counted only across live ordinary rows, so an ordinary
  run is what a tracked game must never be without;
- a run of the imported-history kind takes no ordinary run away when it goes.
  Gating only the count and not the kind of the run in hand would refuse the
  removal of a bucket from a game that already has no ordinary run — a refusal
  that defends nothing and would make the bucket #700 creates permanently
  unremovable.

The sibling query states its library:

    Playthrough.objects.filter(
        library=context.library,
        player_game=run.player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).exclude(pk=run.pk)

`library_playthrough()` scopes on `Playthrough.library`, not on the library of
the `PlayerGame` the run names, and those two can differ: a run naming another
library's `PlayerGame` is exactly what `cross_library_violations` reports and
what `tests/test_projection_references.py` builds. A query keyed on the parent
alone would count another library's rows.

**The invariant does not hold in the database yet.** `games/backfill/playergame.py`
appends the creation event for a `PlayerGame` and no `library.playthrough.created`
beside it, so every game the #676 backfill tracked has zero runs until #684
supplies them. The rule is written as a conservative guard on the way in, not
as the maintenance of a property that already holds, and no test may assume a
fixture `PlayerGame` owns a run.

### No two removals can race

Two removals of sibling runs cannot both read "one other live run remains" and
leave the game with none. `LibraryEventStreamHead.library` is a
`OneToOneField`, so a library has one head row; `lock_stream` takes
`select_for_update()` on it, and `idempotent_append` takes that lock before
`build` runs. The lock is per library, not per aggregate, so the second
command's `build` reads the row the first one's projector already wrote. The
rebuild's `swap_in` takes the same lock, so a rebuild cannot interleave either.

### A reference that does not exist yet

The wave commits to refusing removal while any Session names the run, and to
writing that refusal now, so that #700 does not have to add a rule to a shipped
command.

No Session names a run today, and `Playthrough` has no incoming foreign key at
all. The refusal is therefore written as a registry the command reads, empty on
delivery:

    class BlockingReferrer(NamedTuple):
        """A live row that blocks a removal.

        Every entry's model must carry `removed_at`.
        """

        model: type[models.Model]
        #: Field name alias from games/projections.py.
        field_name: FieldName
        #: What a person is shown.
        sentence: str

    #: Empty until #700 and #701 land.
    BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = ()

Each entry writes its own sentence, because "move the sessions" is advice only
its own referrer can give. The model must carry `removed_at`, because what a
person removed states nothing about a run.

`blocking_referrer(run)` returns the first entry whose model has a live row
naming the run, or `None`, and `RemovePlaythrough` turns an entry into a
refusal carrying that entry's sentence.

The registry is a module-level tuple in `games/commands/playthrough.py`, beside
its one reader. It is deliberately **not** a second entry in
`games/projections.py`, and it adds no system check:

- the wave states that #701 makes `Session` a projection. A `Session.playthrough`
  foreign key is then a reference out of a projection into a library-scoped
  model, which `projection_references()` already walks, and `games.E009` already
  refuses `manage.py check` until the pair is registered. A second check would
  duplicate that forcing function for every case except the one the wave has
  ruled out;
- an incoming registry would also bless what `ProjectionModel` refuses. Its
  docstring states that no model outside the projections may point at a
  projection row, because the swap removes and re-inserts every row of the
  library. Deciding that contract is not this issue's work;
- `games/projections.py` is documented as "projection tables, and what they name
  outside". An incoming registry is the other direction, and widening that module
  is an adjacent addition the boundary clause keeps in its own issue.

The empty tuple has no production path, so the machinery is proven at function
level: a test patches `BLOCKING_REFERRERS` with a pair naming a model built
under `isolate_apps`, the way `tests/test_projection_references.py` builds its
own, and asserts both the refusal and its sentence. A second test pins that the
delivered registry is empty, so the command refuses nothing today.

## The handlers

The `Playthroughs` projector has `_removed`, which amends
`removed_at=event.recorded_at`, and `_restored`, which amends it to `None`. Each
is one `UPDATE` on the primary key of the created row, and an absent row raises
`ProjectionRowMissing`.

The creation handler names four columns and not this one, so re-applying a
creation event cannot take a later removal back out.
`tests/test_playthrough_projection.py` already pins that behaviour by setting
`removed_at` directly and re-applying the creation event; that test keeps its
direct write, because what it proves is about the handler and not about the
command.

`amend()` goes through the default manager, and `Playthrough` declares no custom
one, so a removed row is still reachable — which is what makes a restore
possible at all.

## What a screen calls a run with no number

`with_display_number()` keeps excluding removed rows, and `display_name()` keeps
raising `UnnumberedPlaythrough` for a blank-named row it did not number. Both
are right: a number counted across removed rows would shift under a player.

The set that function refuses is not "removed rows". It is **unnumbered** rows,
and there are two ways to be one: the row is removed, or its kind is not
ordinary. So the answer is a keyword-only `fallback` on the one function rather
than a second function named after half the set:

    def display_name(
        playthrough: Playthrough, *, fallback: str | None = None
    ) -> str:

With no `fallback`, the refusal stands, and a screen that forgot to number its
rows still hears about it. With one, a caller that means to render a row no
number is counted across says what to call it. #1012 renders the first such
screen and chooses the words; this issue delivered the seam and its tests, which
are its only callers today.

## What this issue does not change

Verified inert, so that nobody hunts for them: `PINNED_DEFAULTS`,
`REMOVABLE_MODELS` (a projection stays out — `remove()` writes an `UPDATE` the
next replay would overwrite), `AUDITED_PROJECTION_REFERENCES` and its two
checks, `CONFLICT_ANSWERS` / `ANSWERED_DIRECTLY` / `NOT_ANSWERED` (the commands
raise no new exception type), the benchmark workload, the UUID identity audit,
and the route return-classification table. The suite holds no completeness test
over event types or command names, so nothing goes red on its own when the two
new members land; the coverage is the tests this issue writes.

No view, form or API endpoint calls either command, so no `answered()` boundary
runs and no `CommandFailed` reaches HTTP here. Filters, saved presets and
statistics read no Playthrough column yet; #1013 and #1014 own them.

`remove` and `restore` are the words `docs/vocabulary.md` sanctions, and
`removed_at` satisfies the one-act-one-verb rule in `docs/event-retention.md`.
Neither document changes.

Four comments did:

- `games/models.py`, the `removed_at` comment, which named an issue rather than
  the two commands that state it;
- `games/removal.py`, which named `PlayerGame` as the one projection absent from
  `REMOVABLE_MODELS`, and now names both;
- `CLAUDE.md`, whose `Playthrough` bullet said "the command #1011 adds",
  singular and in the future;
- the wave review's #1011 section, which now records what was delivered against
  what it committed to.

## Verification and reversibility

The gate is the full `make check`, green on delivery. The focused tests, in the
four files the family already uses:

- **`tests/test_playthrough_events.py`** — both types are in the default
  vocabulary, and both payloads refuse an extra key.
- **`tests/test_playthrough_projection.py`** — a removal writes the event's own
  time; a restore states the way back; each amendment costs one statement; a
  replay of created, removed, restored and removed again reaches one state; a
  rebuild reproduces a removed row without drift.
- **`tests/test_playthrough_command.py`** — a repeat of each command answers
  `Unchanged`; an unknown id and another library's run answer alike; a removal
  and a restore under a removed `PlayerGame` are refused, each with its
  sentence; the last live ordinary run is refused; a bucket is removable from a
  game holding no ordinary run; a removal is allowed while a sibling ordinary
  run is live; a sibling in another library does not count; one idempotency key
  covers a repeat; the patched blocking referrer refuses, and the delivered
  registry refuses nothing.
- **`tests/test_playthrough_numbering.py`** — `display_name` still raises with no
  fallback, and answers with one, for a removed row and for a non-ordinary row
  alike.

Three tests stamped `removed_at` with a raw `update()` because no command
existed — in `tests/test_playthrough_command.py`, for a start, a description and
a correction of a removed run. Each now dispatches `RemovePlaythrough`, so the
state they assert against is the state the command produces. The numbering
test keeps its direct write, because what it tests is the read.

A revert is the commits alone. There is no migration, and no caller appends
either event until #687 switches the writes, so no recorded event is lost.
