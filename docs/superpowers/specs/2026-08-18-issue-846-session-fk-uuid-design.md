# ID-08: Rewrite `Session.game`, `Session.device` and `UserLibraryPreferences.default_device` to UUID — design specification

Status: design for #846 (2026-08-18). Parent phase #600, wave C of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
whose "What *swap every read/write path* actually means" checklist carries the
reusable mechanics. ID-07's rejected alternatives are its
[decision record](2026-08-18-issue-845-platform-fk-uuid-design.md).

Depends on #640 (`Game.uuid`), #641 (`Session.uuid`) and #643 (`Device.uuid`),
all merged.

## Scope, and why it grew by one relation

The issue names `Session.game` and `Session.device`. This design also takes
**`UserLibraryPreferences.default_device`** (`games/models.py:781`), the fourth
`Device` foreign key, which the wave plan left unassigned.

ID-07 established that a Wave C slice is drawn around the **target** model, not
the owning one: leaving one foreign key to a target behind manufactures a window
in which the same field name means two column types. Here the cost of the split
would land on ID-14 (#850), which is otherwise a pure contraction — it would
gain a full FK rewrite plus its own reconciliation, on top of promoting
`Device.uuid` to primary key. `default_device` has no filter, sort, fixture or
search-endpoint surface (`UserLibraryPreferences` is not in the sample fixture
and not in `DUMP_LABELS`), so it costs this slice one nullable relation in the
migration and two lines elsewhere.

After this slice, every `Device` foreign key and every `Session` foreign key
resolves through the target's `uuid`. The relations left on integers are
`Purchase.games`, `Purchase.related_game` (ID-09/#847).

## Goals

- `Session.game` → `Game.uuid`, `Session.device` and
  `UserLibraryPreferences.default_device` → `Device.uuid`, each a real database
  foreign key on a `uuid_v7`-typed column.
- No user-visible change: same pages, same filter semantics, same API payloads
  and value types, same saved-preset behaviour for the `sessions` mode.
- Data-preserving in **both** directions; the integer values are
  reconstructable, so Wave B's reversal window stays open through this issue.
- The committed sample fixture keeps loading.
- Reconciliation evidence in-migration and in tests.

## Non-goals

- `Purchase.games` / `Purchase.related_game` (ID-09).
- Dropping any integer `id` or promoting any `uuid` to primary key (Wave E).
- Changing URLs or `<int:...>` converters (#647/#648).
- **Flipping any API or filter value to a UUID.** `/api/games/search`,
  `/api/devices/search`, the session device selector, the `default-device`
  setting endpoint and every filter criterion keep carrying **integer** pks.
  One search endpoint feeds every mode's facets, so the values flip once, after
  the last Wave C slice.
- Remapping existing `FilterPreset` content (wave plan; zero preset rows in the
  only real deployment — and because criterion values stay integer, sessions-mode
  presets keep working anyway).
- Backfilling `uuid` into fixture records that nothing references. The transform
  below adds `games.device.uuid` because the schema now needs it; `session`,
  `purchase` and `playevent` records still carry no `uuid` field and are minted
  at load time, exactly as today.

## Final model definitions

```python
# Session
game = models.ForeignKey(
    Game, to_field="uuid", on_delete=models.CASCADE, related_name="sessions"
)
device = models.ForeignKey(
    "Device", to_field="uuid", on_delete=models.SET_NULL,
    null=True, blank=True, default=None,
)

# UserLibraryPreferences
default_device = models.ForeignKey(
    Device, to_field="uuid", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
```

Column names stay `game_id` / `device_id` / `default_device_id`; only the type
changes. `Session.device` keeps its default reverse accessor (`session`) —
`/api/devices/search` orders by `Max("session__timestamp_start")`, so renaming it
is not free.

`Session.Meta` declares only `get_latest_by`; neither model has a
`unique_together` or a `constraints` entry over the columns being dropped, so
ID-07's cascade trap (checklist item 6) does not apply here. Verified against
`games/models.py`, and the migration test asserts the resulting FK constraints
exist rather than assuming it.

## Migration: `games/migrations/0011_session_fk_uuid.py`

One hand-written file depending on `0010_platform_fk_uuid`. Three relations, two
shapes.

**`Session.game` — six operations** (NOT NULL, per ID-06):

1. `AlterField` `game` → `ForeignKey(Game, null=True, …)`. Exists only so the
   reverse direction can re-impose NOT NULL after step 3's reverse refills it.
2. `AddField` `game_uuid` → `UUIDv7Field(null=True, default=None,
   db_default=None, editable=False)` — the explicit `None`s suppress the field's
   own defaults so the column is added empty.
3. `RunPython` backfill + reconcile (below).
4. `RemoveField` `game`.
5. `RenameField` `game_uuid` → `game`.
6. `AlterField` `game` → the final `ForeignKey(Game, to_field="uuid", …)`:
   renames the column to `game_id`, sets NOT NULL, creates the FK constraint and
   index.

**`Session.device` and `UserLibraryPreferences.default_device` — five
operations** (nullable, per ID-07): the same minus step 1, whose only purpose is
relaxing a NOT NULL that these columns do not have.

All three backfills are `UPDATE … FROM` joins in one `RunPython`, followed by a
single `RunSQL("SET CONSTRAINTS ALL IMMEDIATE")` before the schema alterations —
every FK in this schema is `DEFERRABLE INITIALLY DEFERRED`, and `0006`/`0009`
both needed this guard. A join leaves NULL rows untouched in both directions, so
nullability needs no special case beyond what reconciliation asserts.

`makemigrations` would emit one unrunnable `AlterField` per relation
(PostgreSQL has no `integer`→`uuid` cast); the file is hand-written, and the
drift guard compares final state only. Confirm `makemigrations --check
--dry-run` is clean after the model change.

### Reconciliation

Inside the `RunPython`, before any FK constraint exists, raising `RuntimeError`
on mismatch in the `require_match` style of `0004`/`0006`/`0010`.

`Session.game` (NOT NULL): populated `game_uuid` count equals row count; a
zero-row anti-join proving every `(session.pk, game_uuid)` matches the `uuid` of
the `Game` the row pointed at; distinct referenced-`Game` count unchanged.

`Session.device` and `default_device` (nullable): **NULL-set identity**, as two
zero-row anti-joins — no row gained NULL, no row lost it — rather than a count
comparison, which passes when one row gains NULL while another loses it. Plus
the value anti-join over the non-NULL rows and an unchanged distinct-target
count.

One evidence line, carrying a null count for each nullable relation the way
`0010` prints `game_nulls`/`purchase_nulls`:

```
FK identity rewritten session_rows=<n> session_games=<n> session_devices=<n> session_device_nulls=<n> preferences_rows=<n> preferences_devices=<n> preferences_device_nulls=<n> unmatched=0
```

## Filter lookups: six, values stay integer

`games/filters.py`, all six rewritten to traverse the relation so criterion
values stay integer pks:

| Site | From | To |
| --- | --- | --- |
| `SessionFilter.fields["game"]` | `FilterField("game_id", …)` | `FilterField("game__id", …)` |
| `SessionFilter.fields["device"]` | `FilterField("device_id", …)` | `FilterField("device__id", …)` |
| `GameFilter._extra_q` session relation | `related_lookup="game_id"` | `related_lookup="game__id"` |
| `SessionFilter._extra_q` `game_filter` | `parent_field="game_id"` | `parent_field="game__id"` |
| `SessionFilter._extra_q` `device_filter` | `parent_field="device_id"` | `parent_field="device__id"` |
| `DeviceFilter._extra_q` session relation | `related_lookup="device_id"` | `related_lookup="device__id"` |

Missing any one surfaces as `operator does not exist: uuid_v7 = bigint`. The
`# filters on game_id` / `# filters on device_id` field comments move with them.

**`DeviceFilter`'s rewrite is not behaviour-neutral, and that is the point.**
`relation_to_q` compiles NONE/ALL to `~Q(id__in=<values_list subquery>)`
(`common/criteria.py:2884-2893`). Selecting the raw `device_id` lets that
subquery yield NULL, and SQL's `NOT IN (… NULL …)` is never true — so today a
NONE-matched session sub-filter on the devices mode returns **zero devices**
whenever any matching session has no device. Traversing `device__id` joins
through the relation, which drops those rows and makes the result correct. This
is a latent bug the cutover fixes; it gets its own test rather than riding along
unremarked. `GameFilter`'s `game_id` → `game__id` has no such effect, because
`Session.game` is NOT NULL.

No nullability work: `_lookup_is_nullable` (`common/criteria.py`) already ORs
`.null` across the whole lookup path, so `device__id` keeps the device facet's
"(None)" modifier that `Device.id`'s own `NOT NULL` would otherwise have
dropped. That fix is ID-07's; this slice consumes it and its existing tests
prove it did not regress.

Untouched: `QUICK_FACETS`, `is_quick_editable`, the TS serializer, the criterion
classes, `SESSION_SORTS` (`game__sort_name`, `device__name` — no FK column in
any sort map), and `stats_links.sessions_for_game`, which builds a criterion
from `game.id`.

## Read/write paths

**`games/api.py:494` — the one raw attname write in the app.**
`partial_update_session_device` currently discards the `owned_or_404` result and
does `session.device_id = payload.device_id`, which after the cutover assigns an
`int` to a UUID column. It must bind the resolved instance:

```python
device = None
if payload.device_id is not None:
    device = owned_or_404(Device.objects.for_library(library), library, id=payload.device_id)
session.device = device
```

The payload schema stays `device_id: int | None`, and the stale-id 404 keeps its
current meaning.

**`games/views/game.py:109` — the correlated playtime subquery.**
`list_games` annotates `filtered_playtime` from
`Session.objects.filter(session_q, game=OuterRef("pk"))`, correlating
`Session.game_id` against `Game.id`. It becomes `game=OuterRef("uuid")`. The
annotation is unconditional, so leaving it would break *every* `/games/` render
with `operator does not exist: uuid_v7 = bigint` — this is exactly the class of
miss ID-07's review caught in `/api/platforms/search`, and the first draft of
this design wrongly asserted no such `OuterRef` existed.
`tests/test_paths_return_200.py` catches it if the fix is forgotten.

**`games/signals.py:113`** — `update_game_playtime` reads
`getattr(instance, "game_id", None)` off a `Session` and feeds it to
`Game.objects.filter(pk=game_pk)`. That attname is now a UUID:
`filter(uuid=game_pk)`. The `if not game_pk` bail-out (cascade deletes) stays;
a `UUID` is truthy. This is the line ID-06 explicitly deferred here.

**`games/models.py` — `UserLibraryPreferences.set_default_device`** compares
`self.default_device_id == getattr(device, "pk", None)` to short-circuit a
no-op write. The attname is now the device's `uuid`, so the comparison reads
`getattr(device, "uuid", None)`; both-None still short-circuits. `Session.save`'s
`self.game_id is not None and self.device_id is not None` is a presence check
and is unaffected.

**`audit_library_ownership`** reports violations with
`values_list("pk", "device_id")` (`:218`) and
`values_list("library_id", "default_device_id")` (`:230`). ID-07 moved the
matching platform lines to `platform__id` so the report's ids could not start
disagreeing about what an id looks like; these become `device__id` /
`default_device__id` for the same reason — otherwise the same report prints UUID
devices beside integer `related_game_id` (`:196`) and `game_id` (`:208`).

**`common/layout.py:190`** — `recent_session_resumes` dedups on
`session.game_id` with `seen: set[int]`. The annotation becomes
`set[uuid.UUID]`; mypy catches this one for free.

**`SessionForm`** — both `game` and `device` are `SearchSelect`-backed with
integer option values, and `ModelForm` initial comes from `model_to_dict`, which
reads the attname. Add `seed_related_initial(self, "game", "device")` in
`__init__` (the helper already exists, with three call sites). Without it the
edit page loses both preselections, and `_device_options`/`_game_options` get a
`UUID` into a `pk__in`.

**The helper needs one guard first, new to this slice.** `edit_session`
(`games/views/session.py:247`) passes `initial={"device": <the library's default
device>}` when the edited session has no device, and `BaseModelForm.__init__`
merges caller `initial` *over* `model_to_dict`. `seed_related_initial` today
overwrites unconditionally, so it would write the instance's own `None` back
over that deliberate prefill and regress
`tests/test_user_preference_consumers.py:167`
(`test_session_edit_uses_user_device_only_when_existing_value_is_empty`).
Presence in `form.initial` cannot distinguish the two — `model_to_dict` always
puts the key there. The discriminator is the *type*: `model_to_dict` yields the
raw attname, never a model instance, so the helper skips any field whose current
initial is already a `models.Model`. That is a caller-seeded value, and a caller
that went to the trouble of resolving an instance outranks the instance's empty
relation.

`LibraryPreferencesForm.default_device` is a plain `forms.Form`
`ModelChoiceField` already seeded with the *instance* and rendered as a native
`<select>` — self-consistent, no change.

**`/api/library/default-device`** resolves a `Device` instance before assigning
and returns `device.pk`; both stay correct and integer-valued.

## Fixture, loader, anonymizer

**`games/fixtures/sample.yaml.gz`** is regenerated by a throwaway, uncommitted
transform (ID-06's recipe; a database round trip is not executable, because
loading the old blob needs pre-cutover code while the migration needs
post-cutover code):

1. Add `uuid` to each of the 14 `games.device` records, minted with
   `timetracker.uuidv7.uuid7_at(created_at, sequence=…)` in `(created_at, pk)`
   order with the sequence counter reset per millisecond — the same algorithm
   the Wave B backfills use. `anonymize_sample` stamps every device
   `created_at = FIXED_EPOCH`, so in practice all 14 share one millisecond and
   take sequence 0–13 in pk order.
2. Rewrite each of the 2718 `games.session` records: `game` → that game's uuid
   string, `device` → that device's uuid string, leaving the 117 null `device`
   values null.
3. Re-emit exactly as `anonymize_sample._write_fixture` does —
   `yaml.safe_dump(sort_keys=True, default_flow_style=False)` then
   `gzip.compress(compresslevel=9, mtime=0)` — so the blob stays a stable git
   object.

The minted device uuids are synthetic, exactly like the game and platform uuids
already in the blob (all 851 game uuids carry the `FIXED_EPOCH` millisecond with
sequence 0–850 in pk order — verifiably a transform's output, not production
identities). A real `make anonymize-sample` run against a restored production
copy emits each row's *backfilled* uuid instead, so the blob is consistent with
the schema, not byte-identical to what a fresh dump would produce. That
divergence is what issue #869 tracks.

Recorded in the PR as verification: per-model counts unchanged (851 game, 2718
session, 795 purchase, 203 playevent, 25 platform, 14 device, 75 exchangerate);
no field differs except the added `device.uuid` and the rewritten
`session.game`/`session.device`; every `session.game` resolves to exactly one
`game.uuid`; every non-null `session.device` resolves to exactly one
`device.uuid`; the null count is still 117.

**`load_sample_data.FIXTURE_RELATIONSHIPS`** — `games.session`'s two entries gain
`reference_field="uuid"`. The validator already derives its reference index from
that field generically, and devices are private rows loaded with their fixture
pk *and* uuid, so no remap analogous to `_load_platforms` is needed. Loading the
fixture twice into one database still collides — on device `uuid` now as well as
on pk — which is the fixture's existing "load into an empty dev DB" contract.

**`anonymize_sample._anonymize`** looks up its per-game date offset with
`game_offsets[session.game_id]`. That attname is now a UUID: the session loop
moves to the existing `game_offsets_by_uuid` map ID-06 added. `game_offsets`
itself stays, but only as the source the uuid-keyed map is built from — after
this change no loop reads it directly (the purchase loop's `random.choice` and
through-row build speak `all_game_ids`, not offsets). Nothing else in the
command is keyed by a session or device foreign key: `_prune_other_libraries`
filters on `game__library`, and `--scrub-devices` renames by `device.pk`.

## Surfaces confirmed unaffected

Checked explicitly; if one of these needs editing, the diff has exceeded its
boundary.

- `/api/devices/search` orders by `Max("session__timestamp_start")` — a reverse
  join, not the FK column, so unlike ID-07's platform recency subqueries
  (`filter(platform=OuterRef("uuid"))`) it needs no change. The app's *other*
  correlated subquery over `Session` is `games/views/game.py:109`, which is
  affected and is handled above.
- `SessionDeviceSelector` (`common/components/domain.py:310`) builds option
  values from `session.device.id` and `device.id` — instance pks.
- `clone_session_by_id` copies the loaded instance's attnames wholesale and
  mints a fresh `Session.uuid`; both work unchanged.
- `SESSION_SORTS`, `GAME_SORTS`, `stats_data.compute_stats`
  (`values("game__platform__name", …)`), `stats_links`, `common/import_data.py`.
- `tests/test_navbar_log_button.py`'s SQL assertion on
  `"games_session"."game_id" IS NOT NULL` — the column name does not change.
- No Django admin registration for `Session`.

## Verification

New `tests/test_session_fk_uuid.py`, mirroring `tests/test_playhistory_fk_uuid.py`:

- **Migration**, via `MigrationExecutor` from `0010`: sessions spread across
  several games and devices *including rows with a NULL device*, plus a
  `UserLibraryPreferences` row with and without a default device; migrate to
  `0011`; assert every row still points at the same target (compared by name),
  the NULL device rows are still NULL, all three column types are `uuid_v7`, and
  the FK constraints target `(games_game, uuid)` / `(games_device, uuid)`.
- **Reverse**: back to `0010`; every integer `game_id` / `device_id` /
  `default_device_id` is exactly what it was, NULLs included.
- **ORM**: `session.game_id == game.uuid`, `session.device_id == device.uuid`,
  `filter(game=instance)`, `filter(game__id=game.id)`, `filter(device__id=…)`,
  the `game.sessions` and `device.session_set` reverse accessors (the latter is
  what `/api/devices/search` sorts on), `Game.delete()` cascading its sessions,
  and `Device.delete()` leaving sessions with a NULL device.
- **Database integrity**: a session row naming a device uuid no device owns is
  rejected, and so is a `UserLibraryPreferences` row naming one — both inserted
  with `bulk_create`, since `Session.save()` dereferences `self.device` and
  `UserLibraryPreferences.save()` calls `clean()`, which dereferences
  `self.default_device` (ID-07 hit exactly this trap on `Game.platform`).
- **Form**: editing a session renders both comboboxes preselected with integer
  option values; posting integers saves the right game and device; and a
  caller-supplied `initial["device"]` instance survives `seed_related_initial`
  on a session whose own device is NULL.
- **API**: `PATCH /api/session/{id}/device` with an integer id, with `null`, and
  with a stale id (404).
- **Filtered playtime**: a `GameFilter` carrying a session sub-filter still
  annotates `filtered_playtime` correctly — the direct cover for
  `games/views/game.py:109`.

Extended existing tests:

- `tests/test_filters.py` (including the `fields[...].lookup` metadata
  assertions, which pin `platform__id` today and gain `game__id`/`device__id`
  counterparts), `tests/test_filter_execution.py`,
  `tests/test_filter_cross_entity.py` — both relation directions on both
  relations, plus a **new** case for the `DeviceFilter` NONE/ALL null-device
  behaviour described above.
- `tests/test_library_commands.py`: the `("games.session", {"game": 999}, "Game")`
  parameter case at `:309` moves to an unreferenced UUID, and
  `test_sample_load_rejects_a_session_device_outside_the_fixture_graph`
  (`:350-378`) needs its inline `games.game` record to carry a `uuid` and its
  session to name it — otherwise the test starts failing on the Game relation
  and stops testing the Device one it exists for.
- `tests/test_user_preference_consumers.py:167` — the default-device prefill,
  which is what pins the `seed_related_initial` guard.
- `tests/test_library_models.py:219` — `set_default_device`'s no-op
  short-circuit, the only test covering the comparison being rewritten.
- `tests/test_stats_links.py:156`, `tests/test_library_api_isolation.py:262` and
  `e2e/test_custom_elements_e2e.py:108` compare against `uuid` instead of `id`.

Expected to pass untouched: `tests/test_api.py`, `tests/test_signals.py`,
`tests/test_library_preferences.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_stats.py`, the e2e suite.

The gate is the full `make check`, including `e2e/`.

## Rollback

`manage.py migrate games 0010` restores all three integer columns with their
original values and NULLs. Reversing also requires reverting the regenerated
fixture blob; they are a single unit.

## Handoffs

- **ID-09 (#847)** takes `Purchase.games` and `Purchase.related_game`, the last
  Wave C relations, and owns the global flip of filter/search option values from
  integer pks to UUIDs once they land.
- **ID-14 (#850)** promotes `Device.uuid` to primary key with no integer foreign
  key left pointing at it, and deletes `to_field="uuid"` from both device
  relations.
- **Wave E** also deletes `to_field="uuid"` from `Session.game`, the
  `SessionForm` initial shim, and reverts all six filter lookups to the FK
  column.
