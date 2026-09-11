# CLEAN-02: Remove legacy PlayEvent and GameStatusChange storage

**Date:** 2026-09-11
**Issue:** https://github.com/KucharczykL/timetracker/issues/771
**Parent phase:** #602
**Status:** Draft

**Supersedes:**
[`2026-09-10-cleaning-02-remove-playevent-and-gamestatuschange.md`](2026-09-10-cleaning-02-remove-playevent-and-gamestatuschange.md)
and [`../notes/2026-09-10-cleaning-02-lessons-learned.md`](../notes/2026-09-10-cleaning-02-lessons-learned.md).
Both sit beside this one, each opening with a banner saying what is wrong with it,
because a reader who finds only the replacement learns nothing about the trap.
They are superseded rather than amended: their root-cause diagnosis is wrong, and
the five-migration sequence they prescribe (`0049`–`0053`) creates the failure it
was written to avoid. §Why the prior design fails records that, because the prior
design will look reasonable to anyone who rereads it cold.

## Problem statement

`PlayEvent` and `GameStatusChange` are legacy tables. Every run and every status
transition they once held is now in the event store and in the
`Playthrough`/`PlayerGame` projections: migration `0045` converted the runs, `0033`
recorded the status baseline, `0048` dated the runs that held no legacy row. No
runtime reader remains — `games/reads/playthrough_completions.py` and
`games/reads/playergame_history.py` answer from the projections.

The two tables still cost: they hold schema, they carry a `GeneratedField`
(`days_to_finish`) nothing computes against, `PlayEvent` sits in `REMOVABLE_MODELS`
and `IDENTITY_ORDER_SOURCE` names `games_gamestatuschange`, and the legacy names
block #687's rename.

## Outcome

The two model classes, their two tables, the four modules and two management
commands written to migrate off them, and every reference in code, tests,
fixtures and docs are gone. `make check` green.

## Dependencies

| Issue | What it gave | State |
|-------|--------------|-------|
| #684 | conversion pass, migration `0045` | complete |
| #1038 | start repair, migration `0048` | complete (merged, `f238f672`) |
| #688 | replay-parity gate | complete |
| #687 | name cleanup | **blocked by this issue** |

**Deployment precondition, and it is load-bearing.** This change makes `0033`,
`0045` and `0048` no-ops (§Commit A). Any database that still holds unconverted
legacy rows must pass through a release that applied all three *before* taking
this one. Rehearse with `make verify-dump` against a fresh production dump and
confirm `showmigrations games` lists `0048` as applied. §Commit C adds a guard
migration so a database that slipped through fails loudly instead of silently
losing the rows.

## Why the prior design fails

Four findings, each verified against the tree at `f238f672` rather than inferred.

### 1. `RunSQL` without `state_operations` splits state from schema

The prior `0049`–`0053` are bare `migrations.RunSQL`. RunSQL does not touch
migration state, so after `0053` the project state still holds both models while
the tables are gone.

The prior spec's headline evidence — "`makemigrations --check` reports No changes
detected" — was collected while the model classes still existed, so state and
`models.py` still agreed. Delete the classes, as that spec's own §Model removal
step requires, and the autodetector emits `DeleteModel`, whose `schema_editor`
issues a plain `DROP TABLE` with no `IF EXISTS`, against a table `0052` already
dropped. Fresh-database migrate fails.

That spec's step 5 — "verify `makemigrations` still reports No changes detected"
*after* deleting the classes — cannot hold. It is self-contradictory.

### 2. The FK-constraint theory describes no real mechanism

- Postgres `DROP TABLE` drops the constraints the table owns. An *outbound* FK
  never blocks a drop. Only inbound references need `CASCADE`, and nothing
  references either table: the only FKs are `PlayEvent.game` (`models.py:1360`)
  and `GameStatusChange.game` (`models.py:1415`), both pointing out at `Game`.
- Django's flush is one statement. `sql_flush` in
  `django/db/backends/postgresql/operations.py` emits
  `TRUNCATE "a", "b", "c" …`, and its own comment says this "allows us to truncate
  tables referenced by a foreign key in any other table". FKs among the listed
  tables are fine.

`cannot truncate a table referenced in a foreign key constraint` therefore arises
in exactly one situation: a referencing table exists in the database but is *not*
in Django's table list — the state/schema split of finding 1. So `0049` and `0050`
peel constraints that never blocked anything, and `0051`–`0053` manufacture the
divergence that produces the reported error.

### 3. The real blocker is the historical migrations, and `elidable` does not help

`0033`, `0045` and `0048` call `from games.backfill… import` and
`from games.models import` inside their `RunPython`. That is deliberate — `0033`'s
docstring (`games/migrations/0033_playergame_baseline_backfill.py:64`) says
historical models "cannot run a projector or validate a payload", and accepts
that the migration "is pinned to the application as it stands when it runs".

Those modules query the legacy models: `games/backfill/playthrough.py:357,376`,
`games/backfill/playergame.py:166,349`, `games/preflight/playthrough.py:381,449,558`.

`elidable=True` does not exempt them. In Django it is read in exactly one place —
`Operation.reduce()` at `django/db/migrations/operations/base.py:166` — which is
the optimizer, reached from `squashmigrations`. On a fresh database, including
every test database, all three `RunPython`s execute.

So deleting the modules or the models while those migrations still call them
raises `ImportError` during test-database creation, and every test errors. That is
the coherent account of v1's 862 errors; the flush theory is not.

### 4. `0053` runs too early to do anything

It deletes the `ContentType` and `auth_permission` rows while `models.py` still
defines both models, so `post_migrate` recreates them on the same run. The prior
spec notices this (its lines 132–137) and calls the migration correct anyway. Net
zero on a fresh database.

## What the prior specs also missed

Inventory taken at `f238f672`. These are additions to that spec's file lists, not
corrections of them.

| Finding | Prior spec | Actual |
|---|---|---|
| `games/fixtures/sample.yaml.gz` holds **209 `games.playevent` rows** | not mentioned | `make loadsample` and `LOAD_SAMPLE_DATA=1` break the moment the model is gone — and the three backfill modules are not migration-only, because that command calls them. Resolved in §Commit D0 |
| e2e suite creates `PlayEvent` | not mentioned | `e2e/test_table_width_e2e.py:22,122`, `e2e/test_responsive_table_e2e.py:22,89`; `e2e/test_date_picker_e2e.py:2,20` names it in prose |
| Test files touching the models | "~25" | **39** under `tests/`, plus 3 under `e2e/` |
| `PlayEventFilter` | listed as a name this issue releases | **does not exist.** `filter_for_model` (`games/filters.py:864`) resolves by convention; no such class was ever written. The real names released are the `renamed_fields` aliases at `games/filters.py:142-143` and `related_name="playevents"` |
| `ts/elements/filter-tree/fixtures.canonical.json` | "remove the three canonical entries" | **gitignored** (`.gitignore:26`), regenerated by vitest. Editing it is a no-op |
| `fixtures.json` entries | "three comparison entries" | 3 cases at lines 228–252, and they are the suite's only ANY/ALL/NONE multivalued-comparison coverage — §Commit D retargets rather than deletes |
| `Makefile:336-343` targets `preflight-playthroughs`, `report-playthrough-starts` | not mentioned | must go with the commands |
| `CLAUDE.md` rows for both targets, and both models under §Models | not mentioned | must go |

Unrelated staleness noticed in passing: `CLAUDE.md` §Views lists
`games/views/statuschange.py`, which no longer exists. Out of scope — see
§Follow-ups.

## Design

Five commits, each independently green. The ordering principle is the inverse of
the prior spec's: **make the migration history stop depending on the application
first, and every later step becomes ordinary Django.**

### Commit A — neutralize the historical data passes

Replace the `RunPython` callable in `0033`, `0045` and `0048` with
`migrations.RunPython.noop`; keep the files, the dependency edges and the
module-level helpers' removal for Commit B.

The argument this rests on: those three passes only ever act on legacy rows. A
database holding legacy rows has already applied them — the row is in
`django_migrations`. A database that has not applied them is fresh, and a fresh
database has no `Game`, no `PlayEvent` and no `GameStatusChange`, so all three
passes are provably no-ops on it. There is no database on which this changes
behaviour, *given* the §Dependencies precondition. Commit C makes the exception
loud rather than silent.

Verify: fresh test database builds and the full suite is green with both model
classes still present. That isolates this commit from every later one.

### Commit B — delete the migration-only modules

| Path | Why it existed |
|---|---|
| `games/backfill/playthrough.py` | #684 conversion |
| `games/backfill/playergame.py` | #678 status baseline |
| `games/backfill/playthrough_start.py` | #1038 start repair |
| `games/preflight/playthrough.py` | #686 preflight report |
| `games/management/commands/preflight_playthroughs.py` | its report |
| `games/management/commands/report_playthrough_starts.py` | its report |

Plus `Makefile:336-343` and the two `CLAUDE.md` command rows.

Tests deleted whole, because their subject is deleted: `test_playthrough_conversion.py`,
`test_playthrough_preflight.py`, `test_playergame_backfill.py`,
`test_playthrough_start_repair.py`.

`games/backfill/appending.py` and `mismatch.py` go with them: their only importers
are `playthrough.py`, `playthrough_start.py` and the two tests deleted above.
Re-check the import graph before deleting rather than trusting this line.

**This commit is not reachable until §Commit D0 lands.** Three of the six modules
have a live non-migration caller — `load_sample_data.py` — so deleting them here
leaves `handle()` calling undefined names. D0 keeps its letter for continuity with
the prior draft's file lists, but it is ordered **before** B.

### Commit C — drop the tables the ordinary way

Two migrations:

1. **Guard.** `RunPython` that raises if either legacy table holds a row, with a
   sentence naming the release to upgrade through first. Reverse is `noop`. This
   is the only thing standing between a stale deployment and silent data loss, so
   it counts a row rather than trusting `showmigrations`.
2. **`DeleteModel` pair**, autogenerated: delete the classes (`models.py:1350-1356`
   `PlayEventQuerySet`/`PlayEvent`, `models.py:1401-1407`
   `GameStatusChangeQuerySet`/`GameStatusChange`), then `make makemigrations`.
   State and schema move together, so no `RunSQL`, no constraint peeling, and no
   flush divergence. Confirm the generated file contains `DeleteModel` and
   nothing hand-written.

`ContentType` rows: Django leaves them stale by design;
`manage.py remove_stale_contenttypes` is the supported route and it prompts. Decide
between running it in `entrypoint.sh` with `--no-input` and a small `RunPython`
that deletes the two rows *after* the classes are gone. Either is fine; the prior
spec's `0053` is not, because it ran while the classes still existed.

### Commit D0 — the sample fixture stops holding legacy rows

**Ordered before Commit B.** It removes the last non-migration caller of three of
the six modules B deletes.

#### Why: the "migration-only" premise is false for three modules

§Commit A's argument — those passes only ever act on legacy rows, and a database
holding legacy rows has already applied them — is sound *for migrations*. It says
nothing about `games/management/commands/load_sample_data.py`, which is a runtime
seeding path (`make loadsample`; and `LOAD_SAMPLE_DATA=true` in `entrypoint.sh:25`,
which reaches it through `bootstrap_container.py:50`) and calls the same modules at
load time for the same purpose the migrations served at migrate time.

| Site | What it does |
|---|---|
| `load_sample_data.py:17-31` | imports `backfill_library`, `convert_library`/`ordering_violations`/`reconcile`, and `gate`/`repair_library`/`snapshot` |
| `:167` | `backfill_library(user.library)` — "the same baseline a migrated database gets" |
| `:172-181` | `convert_library` + `reconcile` + `ordering_violations`, `CommandError` on mismatch |
| `:184-194` | `start_snapshot`/`repair_library`/`start_gate`, `CommandError` on refusal |
| `:56-61`, `:99-104` | `LOADABLE_MODELS` and `FIXTURE_RELATIONSHIPS` key on `games.playevent` and `games.gamestatuschange` |

`games/fixtures/sample.yaml.gz` is the reason. Its 4 774 records are
`games.session` 2 792, `games.game` 858, `games.purchase` 802,
**`games.playevent` 209**, `games.exchangerate` 75, `games.platform` 25,
`games.device` 13 — and **no `games.gamestatuschange` at all**, because
`anonymize_sample.py:35-45` omits that label as "regenerated". So the fixture's
only record of play history is 209 legacy rows, and the only record of a library's
statuses is the stranded `Game.status`/`Game.mastered` columns the fixture still
carries (`status: u`, `mastered: false` on every `games.game` record), which
`backfill_library` reads at `games/backfill/playergame.py:209,252`. There are no
events and no projections in it. `load_sample_data` manufactures both at load time.

Two consequences the prior draft's Commit D row ("drop both `games.playevent` map
entries and the backfill imports") does not cover:

1. Those are not unused imports. Take the calls out without a replacement and
   `make loadsample`, the container seed and `tests/test_anonymize_sample.py`
   break — the last of which is inside the `make check` gate this spec requires.
2. The fixture would still be the one place in the repository where a library's
   statuses live in `Game.status` rather than in events, which is #770's blocker,
   not just this issue's.

#### The resolved design: the fixture carries the stream

Events are the record everywhere else; the fixture becomes no exception. It dumps
the event tables and the loader replays them, so seeding uses the same path
`make verify-replay-parity` already exercises
(`rebuild_projections` at `games/events/rebuild.py:530`).

**Dump side — `anonymize_sample.py`.** `DUMP_LABELS` (`:37-45`) drops
`games.PlayEvent` and gains three labels, dependencies first:
`games.LibraryEventStreamHead`, `games.LibraryEvent`,
`games.LibraryEventReference`. The index is dumped rather than left empty: it is
what `games/retention.py:52-60` reads, so the `pre_delete` guard on Game, Platform,
Device and Release (`games/signals.py:90-99`) is inert in a seeded database without
it — and an empty index does not refuse a replay, because
`reconcile_references` (`games/events/reconcile.py:118-124`) derives the kinds it
checks *from the index*, so zero rows resolves trivially.

`_prune_other_libraries` (`:195-204`) gains the three, and they must go **before**
`Game`, `Platform` and `Device`: with another library's index rows still present,
the `.delete()` that prunes that library's Games is refused by the same guard.
Ordering is the fix; `purging_library()` from `games/retention.py:88` is the
fallback if ordering cannot be guaranteed.

`games.LibraryIdempotencyRecord` stays out, for the reason `GameStatusChange` did:
nothing replays from it, and a key that claimed a command in production claims
nothing in a seeded database.

The `playevents` pass (`:229-243`) and its count (`:308`) are replaced by an event
pass over the same rows. It runs where the `PlayEvent` pass ran — after the session
pass, before `_reassign_uuids` — and derives each event's game from its
`aggregate_id` against the source database's own `PlayerGame`/`Playthrough` rows,
which exist at dump time.

| Field | Treatment | Why |
|---|---|---|
| `effective_time` | shift by the game's `game_offsets` day delta, re-serialized at the value's own precision | it is the day a run started or finished — the datum `PlayEvent.started`/`ended` jitter existed to hide |
| `recorded_at` | `_midnight` of the shifted day where the event states one, `FIXED_EPOCH` otherwise | same recipe the `PlayEvent` pass used, and `games/projectors/playthrough.py:35` writes it into `Playthrough.created_at` |
| `payload` `note` / `name` | blanked to `""` | free text, blanked as `Session.note` and `Purchase.name` already are |
| `payload` references | re-captured with `capture_reference` after anonymization | carries the game's id *and* its name as `label` (`games/events/references.py:166-172`); re-capturing keeps both in step with the renamed, re-identified row |
| `source_metadata` | drop `play_event_id` | a real `PlayEvent` UUIDv7 is a real millisecond, and nothing reads the key once Commit B deletes the pass that filtered on it (`games/backfill/playthrough_start.py:113`) |
| `idempotency_key` | rewrite to `sample:<sequence>` | `games/backfill/playthrough.py:183` embeds a legacy row's pk, same leak; only a non-empty check constrains the column (`models.py:1979-1982`) |
| `actor` | `None` | `DUMP_LABELS` carries no `auth.User`, and the loading user is not the prod actor — the same reason `library` becomes `TARGET_LIBRARY_MARKER` rather than a literal pk. Nullable with `SET_NULL` (`models.py:2004-2010`), and nothing outside the append path reads it |

The one field needing per-value care is `effective_time`: it is a canonical
temporal value, not a datetime, so shifting is per-precision — adding 200 days to
a year value means nothing. The pass handles a day value and an unknown one, which
is what the conversion passes wrote, and raises `CommandError` naming the event and
its canonical string for any other precision, so a coarser value can never ship
unjittered without saying so.

Payload rewrites may only touch keys already present: every payload TypedDict is
`STRICT_SCHEMA` (`games/events/references.py:31`, `extra="forbid"`), so an added
key is refused on the way back in by `append`'s validator and by replay's
`_check_readable`. Which keys exist, verified against the 15 registered specs:

| Payload key | Event types carrying it |
|---|---|
| `note` | `library.playthrough.started`, `.completed`, `.start_corrected`, `.completion_corrected` (all four share `PlaythroughEndpointPayload`, `games/events/playthrough.py:61-75`), and `.note_changed` (`PlaythroughNotePayload`, `:174-183`) |
| `name` | `library.playthrough.name_changed` (`PlaythroughNamePayload`, `:167-171`) |
| a `Reference` | `library.playergame.created`'s `game`, kind `catalog.game` — the **only** reference-bearing payload field today (`games/events/playergame.py:15`) |

So the pass finds both generically — `payload.get("note")`, `payload.get("name")`,
and `wiring.event_types.references_in(event_type, payload)` for the references,
which is the same registry call `append` makes at `games/events/append.py:217`
rather than a second hardcoded key path. A new note-bearing or reference-bearing
event type is then covered without an edit here.

**Identity.** `IDENTITY_MODELS` (`:65`) drops `PlayEvent` and gains nothing: the
generic machinery cannot serve the event tables.

- `_remap_referrers` (`:394-412`) walks non-concrete relations whose
  `target_field.name` is the identity. `LibraryEvent.aggregate_id`,
  `LibraryEvent.correlation_id`/`causation_id` and
  `LibraryEventReference.referenced_id` are bare `UUIDv7Field` columns
  (`models.py:2000,2013-2016,2147`), not relations, and a game id inside `payload`
  is JSON. None of them is reachable from there.
- `_resequence_identity` orders by `created_at` (`:346`). `LibraryEvent` has
  `recorded_at` instead — which is exactly what `IDENTITY_ORDER_SOURCE` already
  records for it (`games/identity_audit.py:61-64`).

So the event pass owns its own identities, in one place, because all of them derive
from the `recorded_at` values it just rewrote:

| Identity | Re-derived from |
|---|---|
| `LibraryEvent.id` | its own rewritten `recorded_at`, sequenced as `_resequence_identity` does — the audit holds this column to `recorded_at` order (`games/identity_audit.py:481-518`) |
| `LibraryEvent.aggregate_id` | one new id per distinct aggregate, minted at the **earliest** rewritten `recorded_at` among that aggregate's events, then written to every event naming it *and* to `payload["player_game"]` of `library.playthrough.created` |
| `correlation_id` / `causation_id` | one new id per correlation group, from that group's rewritten `recorded_at` |
| `LibraryEventReference.id` | its event's rewritten `recorded_at` |

**`LibraryEventStreamHead.id` is left alone — verified impossible to reassign
safely.** `LibraryEvent.stream` is a real FK, so `_remap_referrers`'s pattern
would in principle follow it, and the head has no date column for
`_resequence_identity` to read regardless. But `games_libraryevent`'s
composite FK to it (`library_event_stream_matches_library`, migration `0023`,
`ADD CONSTRAINT ... FOREIGN KEY (stream_id, library_id) REFERENCES
games_libraryeventstreamhead (id, library_id)`) carries no `DEFERRABLE` —
unlike every other FK this pass relies on being `DEFERRABLE INITIALLY
DEFERRED`. Postgres checks it immediately per statement, so
`LibraryEvent.stream_id` and `LibraryEventStreamHead.id` cannot be swapped to
new values in two separate `UPDATE`s without one side transiently naming a row
the other doesn't have yet: `IntegrityError: ... violates foreign key
constraint "library_event_stream_matches_library"`, confirmed by running it.
The residual leak — the stream head's own uuid still encodes its real
creation millisecond — is accepted: it is far smaller than what this
command's jitter actually targets (play dates, prices, notes), and matches
the class's own documented "Residual (accepted) traits" posture.

`aggregate_id` is the load-bearing one: it becomes the `PlayerGame`/`Playthrough`
primary key on replay — "the creation event's aggregate_id, evaluated once"
(`models.py:1587,1689`) — those rows' dates are the creation event's
`recorded_at` (`PlayerGame.tracked_at` at `models.py:1597`, `Playthrough.created_at`
at `:1757`), and
`games_playthrough` is audited against `created_at` — so leaving it literal while
`recorded_at` moves puts `manage.py audit_uuid_identity` in violation on any
database seeded from the fixture. `games_playergame` carries `tracked_at` rather
than `created_at`, so it has no order source and the audit skips it
(`games/identity_audit.py:375-385`); that is luck, not license.

`_reassign_uuids` (`:311-325`) therefore collects the `replacements` maps its loop
already builds, keys them by reference kind through
`DEFAULT_REFERENCE_KINDS.kind_of`, and hands them to the event pass, which is the
only consumer that needs a Game's new id to reach a JSON payload.

**`_write_fixture` must drop an empty `effective_time`.**
`TemporalValueField.value_to_string` returns `""` for a null value
(`timetracker/temporal.py:1043-1045`), and reading that back raises:
`to_python("")` → `_normalize_temporal_model_value` → `_parse_atom("")` falls
through to `TemporalValueParseError(code="invalid_syntax")`
(`timetracker/temporal.py:453-455`), re-raised as `ValidationError` at `:997-998`.
Most events state no day, so this is the common case, not the edge. `ValidationError`
is neither `DeserializationError`, `IntegrityError` nor `ValueError`, so
`load_sample_data.py:146` would not even turn it into a sentence. The key is popped
in `_write_fixture` (`:424-432`) beside `GENERATED_FIELDS`, leaving the field at its
`None` default. The three event models also join `PORTABLE_LIBRARY_MODELS`
(`:30-32`): unlike `Session` and `PlayEvent`, each carries its own `library` FK, so
each needs the `TARGET_LIBRARY_MARKER`.

**Load side — `load_sample_data.py`.**

| What | Change |
|---|---|
| `LOADABLE_MODELS` (`:56-61`) | drop `games.playevent` and `games.gamestatuschange`; add the three event models |
| `PRIVATE_MODELS` (`:50-55`) | add the three: each carries `library`, so the marker is required and rewritten (`:416-417`, `:284-290`) |
| `FIXTURE_RELATIONSHIPS` (`:99-104`) | drop both legacy entries; add `FixtureRelationship("stream", "games.libraryeventstreamhead", False, True)` on `games.libraryevent` and `FixtureRelationship("event", "games.libraryevent", False, True)` on `games.libraryeventreference` |
| the call sequence (`:167-194`) | one `rebuild_projections(user.library, mode=RebuildMode.REBUILD)` |

The relationship check **cannot** cover an event's game: `_validate_records` reads
`fields.get(relationship.field)` (`:308`) and resolves it against `record_keys` or
`reference_index`, and an event's game reference lives inside `payload`, a JSON
blob. `reference_field` does not help — it names a field of the *target* record,
not a path into the source. So the FK-shaped references above stay in
`FIXTURE_RELATIONSHIPS`, and the payload-borne ones get their own pass:
for each `games.libraryevent` record, ask
`DEFAULT_EVENT_TYPES.references_in(event_type, payload)` for every reference the
payload carries and require each `(kind, id)` to be a fixture record of that kind's
model; do the same for each `games.libraryeventreference`'s
`(kind, referenced_id)`. That pass also refuses any reference of kind
`catalog.platform`: `_load_platforms` (`:346-392`) reuses or creates platform rows
under *fresh* pks and translates only the two fields named in
`FIXTURE_RELATIONSHIPS`, so a platform id inside a payload would dangle after load.
No such row exists today; the refusal is what keeps that true.

**The stream head needs two checks the pk collision check does not give.**

1. `current_sequence` must equal the maximum `sequence` among that stream's events,
   and the sequences must be exactly `1..N`. `replay` bounds its read by
   `head.current_sequence` (`games/events/replay.py:81`) and raises
   `StreamNotContiguous` when the stream *ends before* the head says it does
   (`:105-109`) — but a head reading **below** the last event is silent: the events
   above the bound are never replayed, `swap_in`'s `require_sequence`
   (`games/events/rebuild.py:377-381`) is satisfied by the same truncated number,
   and the load succeeds with a projection missing rows. So the loader validates
   the pair; nothing downstream will.
2. `LibraryEventStreamHead.library` is a `OneToOneField` (`models.py:1940-1944`).
   `_reject_primary_key_collisions` (`:430-442`) checks primary keys only, so a
   target library that has already appended anything — one manually tracked game —
   fails on that unique constraint with a raw `IntegrityError`. Refuse it up front
   with a sentence, beside the pk check.

**Reporting.** `rebuild_projections` returns a `RebuildReport`
(`games/events/rebuild.py:444-459`). `handle()` raises `CommandError` when
`report.swapped` is false, quoting `report.attempts[-1].conflict`, and turns the
four refusals the path can raise into sentences the same way the old gates did:
`UnresolvedReferences` (a fixture whose events name a row the fixture omits),
`StreamNotContiguous`, `PayloadVersionUnsupported` and `SwapRefusedByReference` —
each already carries its own message. The success line replaces
`converted.runs_converted`/`runs_default` with `report.replayed_through` and each
`TableDiff.rebuilt_rows` from `report.tables`.

The call stays inside `handle()`'s existing `transaction.atomic()`, so the load
still either lands projected or does not land. Nesting is legal here:
`rebuild_projections` reaches `transaction.atomic()` and `lock_stream`, not
`run_in_transaction`, so the no-nesting rule in CLAUDE.md does not apply.

### Commit D — cross-cutting code, tests and fixtures

Code:

| File | Change |
|---|---|
| `games/removal.py` | drop `PlayEvent` from `REMOVABLE_MODELS` + import |
| `games/identity_audit.py` | drop `"games_gamestatuschange": "timestamp"` from `IDENTITY_ORDER_SOURCE` |
| `games/filters.py:142-143` | drop `renamed_fields` (its own comment says #771 takes it) |
| `games/management/commands/load_sample_data.py` | **done in §Commit D0** — the map entries and the backfill call sequence are the seeding logic, not dead imports |
| `games/management/commands/audit_library_ownership.py` | drop both count queries |
| `games/management/commands/anonymize_sample.py` | **done in §Commit D0** — the `playevents` pass (`:229-243`) and its count (`:308`) are replaced by the event pass, not dropped; `IDENTITY_MODELS` (`:65`) loses `PlayEvent` there |
| `CLAUDE.md` | drop both §Models bullets |

`ts/elements/filter-tree/fixtures.json:228-252` — **retarget, do not delete.**
These three cases are the only ANY/ALL/NONE multivalued-comparison coverage in the
cross-language contract. `game__player_games__playthroughs__completed_lower` is the
candidate replacement: `PlayerGame.game` carries `related_name="player_games"`
(`models.py:1595`) and `Playthrough.player_game` carries
`related_name="playthroughs"` (`models.py:1697`), so the path stays multivalued and
the quantifier still means something. Verify against
`tests/test_filter_tree_contract.py` — if `to_q()` equivalence does not hold on
that path, pick another to-many path rather than dropping the cases.
`fixtures.canonical.json` regenerates; do not edit it.

Tests: 39 files under `tests/` and 3 under `e2e/`. Enumerate with

```bash
grep -rln "PlayEvent\|GameStatusChange" --include="*.py" tests/ e2e/
```

rather than working from a list in this document — a stale list is how the prior
spec undercounted by 14. Three shapes: fixtures to rewrite onto `Playthrough` or
`PlayerGame` events, assertions naming the dropped tables or FKs
(`test_uuid_identity_audit.py`, `test_session_playhistory_uuid_primary_key.py`,
`test_library_commands.py`), and the four alias tests in `test_filters.py` that
exercise `renamed_fields`. `test_playthrough_preset_migration.py` is untouched —
the `"playevents"` → `"playthroughs"` preset mode in `0046` is a saved-filter word,
not the model.

`games/fixtures/sample.yaml.gz` is **regenerated in §Commit D0, not here** — the
loader rewrite and the fixture format must land in one commit, or neither is green.
That is also the one commit this repository cannot produce on its own: it needs
`make fetch-dump`, `make restore-dump`, `make migrate`, `make anonymize-sample`
against a real production dump. Do not hand-edit the gz.
`tests/test_anonymize_sample.py` moves with it: it names `"games.playevent"` at
`:35`, creates `PlayEvent` rows at `:125,131`, and asserts on them at
`:223,250-251,413-423`.

## Verification

Gate is full `make check` — including `e2e/`, which the prior spec's §Verification
never names and which creates `PlayEvent` in two files.

Per-commit, in order:

1. **A:** fresh test database, full suite green, both models still defined.
2. **D0:** `make check` green, including the rewritten
   `tests/test_anonymize_sample.py`. Then, against a restored production dump:
   `make anonymize-sample`, and confirm the new gz holds
   `games.libraryeventstreamhead`, `games.libraryevent` and
   `games.libraryeventreference` records and **no** `games.playevent`. Then, into
   an empty database, `make loadsample USER=admin` succeeds, followed by four
   checks:
   - `manage.py rebuild_projections --user admin --check --fail-on-drift` exits
     zero. A second replay of the same stream must reproduce the projections the
     load wrote; drift here means the loader and the replay disagree.
   - `manage.py audit_uuid_identity` reports no violation — that is what holds
     `games_libraryevent.id` to `recorded_at` order and `games_playthrough.id` to
     `created_at` order after the date rewrite.
   - **Row-count parity against the old seeding.** Capture `PlayerGame.objects.count()`
     and `Playthrough.objects.count()` from a `make loadsample` on the *pre-change*
     commit, and require the same two numbers after. The fixture's arithmetic says
     858 and 872 — 858 games, 209 legacy rows across 195 distinct games, so 209
     converted runs plus 663 defaults — but capture the actual numbers rather than
     trusting that line: a game the conversion skipped is a difference nothing else
     here would report.
   - `make loadsample` a second time into the same database is refused with a
     sentence, not an `IntegrityError`, because the library already holds a stream
     head.
3. **B:** `make check-fast` green; `grep -rn "games.backfill\|games.preflight" games/migrations/` empty.
4. **C:** fresh database `make migrate` green; `make makemigrations ARGS="--check --dry-run"`
   reports no changes *with the classes deleted*; `make verify-dump` green against a
   production dump; guard migration raises on a database seeded with one legacy row.
5. **D:** `make check` green. `make test-ts` regenerates `fixtures.canonical.json`
   and `tests/test_filter_tree_contract.py` passes. `make loadsample` into an empty
   database still succeeds — it loads no legacy row by then, so this re-checks the
   loader against the deleted models rather than the fixture format.

Final greps, all expected empty:

```bash
grep -rn "PlayEvent\|GameStatusChange" --include="*.py" games/ common/ tests/ e2e/ | grep -v games/migrations/
grep -rn "playevent" --include="*.py" games/ | grep -v games/migrations/
grep -rn "playevents__ended" ts/
grep -rn "preflight-playthroughs\|report-playthrough-starts" Makefile CLAUDE.md
```

`games/migrations/` keeps its references: `0001_squashed_0036_alter_playevent_days_to_finish.py`
creates both tables and the history must stay replayable from zero.

## Rollback

Not reversible in production: the tables are dropped and the events are the only
copy. Acceptable for the reasons #684 and #1038 already established — both passes
ran with reconciliation gates, `make verify-replay-parity` covers the projections,
and the charter's history requirement is met by the event store.

Recovery is `git revert` of the commit range *before* the migration applies. After
it applies, recovery is a restore from dump. `make verify-dump` before deploy is
what keeps that from being needed.

## Follow-ups to file

- `CLAUDE.md` §Views lists `games/views/statuschange.py`, which does not exist.
- #687 name cleanup unblocks once this lands; retarget it at `renamed_fields`
  and `related_name="playevents"`, not at the non-existent `PlayEventFilter`.
- Decide whether `remove_stale_contenttypes --no-input` belongs in `entrypoint.sh`
  permanently, rather than being a one-off for this change.
