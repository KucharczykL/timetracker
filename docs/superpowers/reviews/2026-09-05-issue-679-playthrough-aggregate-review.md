# Review: #679 (PLAY-01) as PR #1016

Five reviewers read `main...claude/issue-679-playthrough-aggregate`: general
code, test coverage, silent failures, comment accuracy, type design. The three
highest-value comment claims were re-checked against the source before this
record was written; one cross-library claim is recorded as disputed, with the
verdict stated.

The branch adds the `Playthrough` projection, the one creation event both
`TrackGame` and `CreatePlaythrough` append, the read-time display number, and
the registry reshape that lets one `ProjectorFamily` hold many projectors.

## Fix before merge

### 1. The `id` tie-break sort key has no test that can fail

`tests/test_playthrough_numbering.py:84`, `:143`.

`make_run` mints monotonic `uuid.uuid7()`, so `sorted(..., key=lambda row:
row.pk)` at `:87-90` is a no-op: the expected order equals the insertion order.
Drop `F("id")` from the window and the test still passes. The rebuild test at
`:143` is weaker still — five separate dispatches mean five `stream.append`
calls, and `games/events/append.py:180` stamps one `recorded_at` per append, so
`created_at` alone already totalizes the order and the fourth key is never
reached.

Mint four uuid7 values up front and insert in reverse pk order; append three or
more creation events in one `stream.append` (the helper is at
`tests/test_playthrough_projection.py:97`).

Cost of the gap: someone trims the key, `Playthrough 2` and `Playthrough 3`
trade places after a rebuild, and CI stays green.

### 2. The projector's four-column contract is asserted by a row count

`games/projectors/playthrough.py:31-36` against
`tests/test_playthrough_projection.py:151`.

`project()` passes `update_fields=list(columns)`
(`games/events/projection.py:288`), so a column the handler does not name
survives a re-applied creation event. The only re-apply test asserts
`Playthrough.objects.count() == 1`, which still passes after adding `name=""`,
`note=""` or `removed_at=None` to the handler — the exact edit #681 is tempted
to make, and the one that would erase amendments on every rebuild.

Testable today: `UPDATE` the row, re-apply the recorded event, assert the
amendment survived.

### 3. `projection.py` still teaches that a family is one class

`games/events/projection.py:1-15, 39, 81-87, 108-123, 146, 154, 172, 185, 242,
250, 255, 327`.

`docs/vocabulary.md`, added on this branch, settles the new meaning: one family
holds many projectors. `_families` is now `dict[ProjectorFamily,
dict[DefinitionSite, Projector]]`, and `games/projectors/__init__.py:1` was
updated. The module that owns the concept was not. A dozen sites say "family"
where they mean "projector", including three `TypeError` strings a person
reads, and `for_target`'s loop at `:172` binds a `Projector` into a variable
named `family`.

`make vale` cannot catch this: `family` is settled, not refused.

### 4. The `_claims` comment contradicts its own key

`games/events/projection.py:94`.

`#: One owner per act, not per family.` sits above
`dict[tuple[ProjectorFamily, EventType], DefinitionSite]`. As written it
forbids CURRENT_STATE and JOURNAL both handling one act, which is the thing the
reshape exists for. The `ProjectorFamily` docstring at `:61-62` states it
correctly.

### 5. `CreatePlaythrough`'s lock comment claims a guard that is not there

`games/commands/playthrough.py:24`.

`#: Under dispatch's lock: no concurrent duplicate.` sits above a removal
refusal. This command has no duplicate check — a repeat is the point, and
`tests/test_playthrough_command.py:96` proves it. The line was copied from
`games/commands/playergame.py`, where it guards a real `Unchanged` return. What
the lock buys here is that a concurrent `RemovePlayerGame` cannot land between
the read and the append.

### 6. Two documents state an invariant that is false on every migrated database

`CLAUDE.md` (the `Playthrough` model paragraph) and
`docs/superpowers/specs/2026-09-04-issue-679-playthrough-aggregate-design.md`,
"The event and the commands".

Only `TrackGame` appends the creation event. The other producer of
`PLAYERGAME_CREATED` is `games/backfill/playergame.py:188-193`, run by
migration `0033`, which appends no companion event; migration `0043` creates an
empty table. So every game tracked before this branch has zero playthroughs,
permanently — `TrackGame` answers `Unchanged` and cannot repair it.

The code is right: #679's scope gives that backfill to #684, and
`tests/test_playthrough_command.py:151` pins the refusal to invent a second
default. The defect is that both documents state the invariant without the
exception, and #1012 and #1013 will be written against them.

## Worth fixing, decide the timing

### The registry takes its claims before it builds the projector

`games/events/projection.py:143-151`. Three reviewers found this
independently. If `projector_class(target)` raises, `_claims` holds an entry
with no matching `_families` or `_classes` row, and the next registration is
refused naming a class that is not registered. Free fix: instantiate at `:147`
first, then claim. Theoretical while `Projector.__init__` only stores `target`.

### `kind`'s model default defeats the check that would catch a missing column

`games/models.py:1630`. `_required_columns`
(`games/events/projection.py:209-229`) exempts every field with a default, so a
future creation-adjacent handler that omits `kind` silently writes `"ordinary"`
instead of being refused. `kind` is the only column both stated by the creation
event and defaulted; `created_at`, the other event-stated column, correctly has
none. Dropping it costs about six lines of test churn
(`tests/test_playthrough_projection.py:46`, and `make_run` in
`tests/test_playthrough_numbering.py:34`).

### The ownership audit says of itself that it has no completeness test

`games/management/commands/audit_library_ownership.py:237`,
`tests/test_library_commands.py:603`. The test proves the audit reports, not
that the list is whole. A short guard walking `projection_models()` for foreign
keys into other `ProjectionModel`s closes it, once the hand-written block at
`:245-252` becomes a list of `(model, foreign key)` pairs.

### The "can never be rebuilt" consequence is overstated — disputed, verdict recorded

`games/models.py:1518-1522` and
`games/management/commands/audit_library_ownership.py:237-242` both claim a
cross-library projection foreign key fails the deferred key at COMMIT and
leaves the library unable to rebuild. `swap_in`
(`games/events/rebuild.py:295-318`) runs DELETE then INSERT per table inside
one atomic block and restores the same primary keys, because the key is the
event's `aggregate_id` and replay is stable. The deferred key is therefore
satisfied at COMMIT.

The code reviewer read it the other way. The comment reviewer's reading is the
one that survives the source. What is proven, by this branch's own test, is the
**purge**: `on_delete=RESTRICT` blocks it, and
`tests/test_retention.py:512` exercises that through the real command.

Both wordings also say "that library" without saying which. It is the library
owning the referenced row.

### `with_display_number()` yields a wrong number on a narrowed queryset

`games/reads/playthrough_numbering.py:13-38`. `RowNumber` partitions over
whatever the caller already selected, so
`with_display_number(Playthrough.objects.filter(pk=one))` answers `1` for the
row a list page correctly calls `4`. No exception. The docstring warns
carefully about ordering and says nothing about the likelier mistake. A
`numbered_for(player_game_ids)` entry point would make the partition
un-narrowable.

### `display_name()` has no answer for two classes of row

`games/reads/playthrough_numbering.py:40-52`. `with_display_number` filters to
live ordinary rows at `:25`, so a blank-named `IMPORTED_HISTORY` row and a
blank-named removed row can never be named: `UnnumberedPlaythrough` is the only
outcome, raised from a render helper. Nothing calls it yet. #684's importer
creates exactly the first kind, and #1011 the second.

### The refusal sentence names an affordance that does not exist

`games/commands/playthrough.py:29-32` tells a person to restore the game first.
`RestorePlayerGame` (`games/commands/playergame.py:211`) has no write wrapper,
no view and no route. `TrackGame`'s refusal at `:74-81` points at the same
missing thing, so the two sentences form a loop with no exit.

### A rebuild can report green and then fail at the swap

`games/events/rebuild.py:51-56, 226-248`;
`games/management/commands/rebuild_projections.py:39-47`. Shadow tables are
`CREATE TEMP TABLE (LIKE ... INCLUDING ALL)`, which copies no foreign key; the
payload's `player_game` is a bare `ReferenceId`, so
`require_resolvable_references` never reads it; the diff compares equal rows and
reports none. Only `UnresolvedReferences` is caught, so an operator gets a raw
psycopg traceback naming neither the library nor `audit_library_ownership`.

`games/events/retry.py:80-92` correctly refuses to retry SQLSTATE 23503, so the
violation is never laundered into a "try again" sentence.

### Nothing checks that every event type has a projector

`games/events/projection.py:195` reads `self._handlers.get(event.event_type,
())`, so an unclaimed type commits, advances the stream head and writes
nothing. The property holds only because `games/projectors/__init__.py:3`
imports every module; this branch took that line from one import to two. #681
is one forgotten import away from silent drift.

### Two behaviours are claimed and untested

`tests/test_playthrough_command.py:96` never asserts `result.outcome`, and
"runs no projector" on an idempotent repeat is invisible because `project()` is
an upsert — `counter.work(...).projection_statements` already exists for this.
`:60` covers a game untracked here, never one tracked by a **different**
library, so nothing pins `tracked_game()`'s `library=context.library` filter.

## Smaller notes

- `games/models.py:1622` — `#: No cascade may remove a projection row.`
  `remove` is the `removed_at` stamp; `RESTRICT` blocks a destroy. The sibling
  at `:1568` says `delete`, so the two now disagree about one constraint.
- `games/events/playthrough.py:11` — the sweep kept "on purpose" and cut the
  purpose. Restore one line: strict validation refuses a plain string for an
  enum field. A stronger second reason is available — the recorded vocabulary
  is frozen (`games/events/vocabulary.py:146` refuses a version above 1) while
  `PlaythroughKind` is free to change.
- `games/events/benchmark.py:79` — `WorkPerEvent.events` counts dispatches now,
  not events. `docs/event-benchmarks.md:41` shows it: "over 200 event(s)" for
  400 events.
- `tests/test_event_benchmark.py:410` — the arithmetic is right, but 8 and 6 no
  longer map onto `iterations=3, warmup=1`. `#: 30 seeded; 4 and 3 dispatches,
  two events each.` restores the mapping.
- `games/events/projection.py:43` — name `type FamilyClaim =
  tuple[ProjectorFamily, EventType]` and a generic `type BySite[T] =
  dict[DefinitionSite, T]`, beside the `DefinitionSite` and `ColumnNames`
  aliases three lines up. `BySite` also removes the wrap at `:162-163`. Leave
  the outer dict un-named.
- `games/events/playthrough.py` — `type PlayerGameId = ReferenceId` names the
  role the format alias does not.
- `games/reads/playthrough_numbering.py` — `"display_number"` appears as a
  keyword at `:27` and a `getattr` literal at `:44`, unconnected. One constant
  ties them.
- `tests/test_playthrough_events.py:26` — `imported_history` is exactly 16
  characters against `max_length=16`. One assertion closes the headroom.
- `games/events/vocabulary.py:65` — an `EventSpec.read()` returning the typed
  payload would take `event.payload["kind"]`
  (`games/projectors/playthrough.py:23-24`) from `Any` to checked, for every
  projector.
- `games/commands/playthrough.py:8` — an abstract `TrackedGameCommand` holding
  `game_id` and the lookup would let `tracked_game` go back to private.
  `games/events/dispatch.py:24-25` already names this as the composition route.
- `games/reads/playthrough_numbering.py:41` — `display_name` collides with
  `Edition.display_name` (`games/models.py:532`).
- `games/events/rebuild.py:33-39` — the swap's table order is alphabetical, not
  topological, and only the deferred key absorbs that. Worth one line.
- `games/removal.py:29-30` — the carve-out names `PlayerGame`; there are two
  projections now.
- `tests/test_playthrough_projection.py:109` and `:115` assert a handler count
  but not a family; `:40-62` repeats `tests/test_projection_model.py:262`;
  `tests/test_event_benchmark.py:365` hard-codes `44`; six lockstep drift
  assertions want one `assert_no_drift(checked)` helper.

## What holds

- `tests/test_playthrough_projection.py:176` — the empty-database replay
  reproducing both tables is the strongest test on the branch.
- The `pg_constraint` assertion at `:217` is not a hollow proxy. `swap_in`
  sorts by table name, so the parent is deleted while the child references it:
  `:197` is the behavioural proof and `:217` the schema pin over it.
- `games/management/commands/audit_library_ownership.py:243-255` cannot drop a
  violation — a non-nullable join, `Q(...) | Q(...)` catching the offender from
  either side, the plain manager so a removed row is still audited, and a
  non-zero exit.
- `games/events/retry.py:86-92` — refusing to retry a foreign key violation is
  what keeps this whole class of failure out of a person's toast.
- `games/events/projection.py:184-203` — `apply()` annotates and re-raises
  rather than wrapping, so `run_in_transaction` still reads the SQLSTATE off
  `__cause__`. A wrapper here would have broken retry classification.
- `games/events/playthrough.py:19-24` — the bare-`ReferenceId` plea names the
  alternative, the mechanism and why it matters for a rebuild. One nit: the
  claim holds for a REQUIRED kind, since `games/events/reconcile.py:130-132`
  skips an evidence-only one.
- E004 through E007 pass; the migration matches the model field for field;
  nothing writes a `GeneratedField`; `Playthrough`'s absence from
  `REMOVABLE_MODELS` is deliberate and needs no exemption; no new
  `@transaction.atomic` wraps a dispatch; no server-side cursor; one verb
  across the event, the command and the column.

## Order of work

1. The documents and comments: items 3, 4, 5 and 6 above, plus the
   `remove`/destroy word at `games/models.py:1622` and the restored reason at
   `games/events/playthrough.py:11`.
2. The two test gaps, items 1 and 2. Both guard decisions #681 revisits.
3. The two free code fixes: instantiate before claiming, and drop `kind`'s
   default.
4. Decide, and record the verdict in the issue rather than only here: the audit
   completeness guard, `numbered_for`, `display_name`'s answer for an imported
   or removed row, and the rebuild's message to an operator. Each is arguably
   #681, #684 or #1010 scope.

## Verdicts on the four, 2026-09-05

Recorded on #679, on each owner, and in the #601 wave block.

**The audit completeness guard and the rebuild's message: #1017, opened.** One
cause, so one issue. `Playthrough.player_game` is the first foreign key between
two projection tables, and it makes both gaps costly at once: an unaudited
relation becomes a library that can never be purged, and the rebuild that meets
one reports green and then raises a raw `IntegrityError` at the swap. Neither
fits #679's boundary, and no open issue contained them. It depends on #679 and
blocks nothing.

**`numbered_for(player_game_ids)`: #1012.** The entry point's shape is decided
by the first caller, and nothing calls the numbering yet. #1012 needs both —
many tracked games on the list page, one on Game detail. This is the reasoning
#601 already applied to #909: a helper promoted from a single caller states the
convention rather than removing it.

**`display_name()`'s two unanswerable rows: no change, with a named trigger.**
Both are unreachable by construction — #684's bucket carries the name "Imported
history", and a removed row leaves every list. The refusal is right: a helper
that invented a number for a row the numbering excludes would print one a
player never learned. #684 owns the imported case if its importer ever leaves a
bucket unnamed, and #1011 owns the removed case, its restore affordance being
the first screen that renders such a row on purpose.
