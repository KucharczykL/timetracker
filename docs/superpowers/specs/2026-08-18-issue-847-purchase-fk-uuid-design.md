# ID-09: Rewrite `Purchase.related_game` to UUID, and defer `Purchase.games` — design specification

Status: design for #847 (2026-08-18). Parent phase #600, wave C of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
whose "What *swap every read/write path* actually means" checklist carries the
reusable mechanics. ID-06's [play-history design](2026-08-18-issue-644-playhistory-fk-uuid-design.md)
is the worked example; ID-07's [platform design](2026-08-18-issue-845-platform-fk-uuid-design.md)
established the nullable shape; ID-08's [session design](2026-08-18-issue-846-session-fk-uuid-design.md)
is the immediate predecessor.

Depends on #640 (`Game.uuid`) and #642 (`Purchase.uuid`), both merged.

## Scope, and why it shrank by one relation

The issue names `Purchase.games` (M2M) and `Purchase.related_game`.
`Purchase.platform` already moved in ID-07. This design delivers
**`related_game` only** and defers the M2M's through column to ID-11 (#646).

The reason is a hard Django limitation, established by probe rather than by
reading alone (Django 6.0.7):

- `ManyToManyField.__init__` accepts no `to_field`, and
  `create_many_to_many_intermediary_model` builds its two foreign keys as plain
  `ForeignKey(to_model)`. An auto-created through table always references the
  target's **primary key**. Pointing `Purchase.games` at `Game.uuid` therefore
  requires replacing the auto-created through with an **explicit through
  model**.
- With an explicit through, `Serializer.handle_m2m_field` bails
  (`if field.remote_field.through._meta.auto_created:`), so `dumpdata` emits a
  purchase record with **no `games` key at all**. The fixture's shape is
  produced by `anonymize_sample`, which dumps through `dumpdata`, so the
  committed blob would have to carry ~4505 `games.purchasegame` records instead
  of 795 `games:` lists — roughly doubling its record count.
- The current shape cannot survive either: probed against an explicit through
  whose target FK carries `to_field="uuid"`, `loaddata` of `games: [<int pk>]`
  fails with `IntegrityError: FOREIGN KEY constraint failed` (the `.set()` path
  writes the integer into the UUID column), and `games: [<uuid>]` fails with
  `DeserializationError: value must be an integer`, because
  `deserialize_m2m_values` converts every element through
  `field.remote_field.model._meta.pk.to_python` — the **target's pk**, never the
  through's `to_field`. Django's M2M fixture pipeline is wired to the target's
  primary key in both directions.

So moving the M2M inside Wave C is not a column retype. It is a modeling change
(a permanent explicit through model, or a second shape flip in Wave E to remove
it), plus a fixture-format change, plus `load_sample_data` /
`PORTABLE_LIBRARY_MODELS` / `DUMP_LABELS` learning a model that exists only to
carry the transition.

**Deferring costs nothing in application code, in either wave.** Every site that
touches the M2M speaks "Game primary key", and each one follows automatically the
moment ID-11 makes that primary key the UUID:

| Site | Why it needs no change |
| --- | --- |
| `PurchaseFilter._games_to_q` (`games__in=`, `games=`, `games.exclude(id__in=)`) | resolves against `Game.pk` |
| `GameFilter._extra_q` `related_lookup="games__id"`, `PurchaseFilter._extra_q` `parent_field="games__id"` | already traverse the relation |
| `m2m_changed` `pk_set` in `validate_purchase_game_ownership` | `filter(pk__in=pk_set)` — pk_set carries target pks |
| `anonymize_sample`'s `Through(purchase_id=…, game_id=…)` build (`:251`) | `all_game_ids` are pks |
| `audit_library_ownership`'s `values_list("purchase_id", "game_id")` (`:208`) | pk projection |
| the fixture's `games: [18, 100, …]` lists | serialized as target pks |
| `games/sorting.py`'s `Min("games__name")` / `Max("games__playevents__ended")` | reverse-join annotations, no FK column |
| `stats_data`'s ~20 `games__…` traversals | relation traversals |

Under the explicit-through alternative, all of the first four *would* change —
`pk_set` becomes UUIDs, `games=<int>` stops matching (Postgres: `operator does
not exist: uuid_v7 = bigint`), and the anonymizer builds rows from a UUID map.

What ID-11 inherits is one database-level conversion, inside the migration that
is *already* rewriting `Game.id`: add a UUID holding column on
`games_purchase_games`, `UPDATE … FROM games_game`, drop `game_id`, rename, and
restore the FK plus the `(purchase, game)` unique index that `DROP COLUMN`
cascades away (checklist item 6 — it applies to the through table, whose
`unique_together` is over the dropped column). Django's migration *state* needs
no operation there: an auto-created through's FK type is derived from the
target's pk at state-render time, so the state follows the pk promotion for
free. ID-13 performs the mirror-image conversion on the same table's
`purchase_id` when it promotes `Purchase.uuid`, so `games_purchase_games` needs
this treatment in Wave E whatever ID-09 does — which is the argument for not
paying for it twice.

This is a deliberate, single exception to the slice-by-target-model principle
ID-07 and ID-08 established. After this slice every *field-backed* foreign key
to a converted model resolves through its target's `uuid`. What remains on
integers, enumerated by introspecting every FK in the app rather than by
reading:

| Column | Status |
| --- | --- |
| `games_purchase_games.game_id` → `Game.id` | **anomalous** — every other `Game` reference has moved. ID-11's, pinned by a test here. |
| `games_purchase_games.purchase_id` → `Purchase.id` | normal until ID-13 promotes `Purchase.uuid`, and it needs the identical conversion then. Pinned by the same test. |
| `UserLibrary.user`, `UserPreferences.user` → `auth.User.id` | out of scope for the whole cutover — `auth.User` is not a converted model and keeps its integer pk. |

## Goals

- `Purchase.related_game` → `Game.uuid`, a real database foreign key on a
  `uuid_v7`-typed column.
- No user-visible change: same pages, same filter semantics, same API payloads
  and value types.
- Data-preserving in **both** directions; Wave B's reversal window stays open.
- The committed sample fixture keeps loading.
- Reconciliation evidence in-migration and in tests.
- The deferred M2M is visible in the repository, not only in this document.

## Non-goals

- **`Purchase.games`.** Deferred to ID-11 as argued above.
- Dropping any integer `id` or promoting any `uuid` to primary key (Wave E).
- Changing URLs or `<int:...>` converters (#647/#648).
- **Flipping any API or filter value to a UUID.** `/api/games/search` and every
  filter criterion keep carrying **integer** pks. See the next section.
- Remapping existing `FilterPreset` content (wave plan; zero preset rows in the
  only real deployment).

## The value flip dissolves into Wave E

ID-09 was nominated as the owner of the global integer→UUID flip of filter
criterion values and search-endpoint option values, on the reasoning that it is
the last Wave C slice. It is not a separate act, and it should not be a separate
issue.

Every Wave C lookup was rewritten to `<name>__id`, which resolves to the
target's primary key. The moment ID-11 renames `Game.uuid` to `id` and promotes
it, that same unchanged lookup resolves UUIDs, and `_game_options` starts
emitting them. The *lookups* therefore need no flip at all — which is the whole
argument, because a dedicated flip issue between Waves C and D would have to
move every lookup from `<name>__id` to `<name>__uuid` while the pks are still
integers, and back to `<name>__id` after Wave E: two rewrites of the same lines
for no coverage.

**The flip is not free, though, and the residual work is type annotations, not
lookups.** Verified against the installed pydantic: `games/api.py:129-132`
declares `class GameOption(Schema): value: int`, and that one schema is the
response type of **all three** search endpoints — `/api/games/search` (`:141`),
`/api/devices/search` (`:218`) and `/api/platforms/search` (`:231`). A `UUID`
against `value: int` raises `ValidationError: Input should be a valid integer`,
so the pk promotion does not flip the endpoint for free, it 500s it. Because
`Game` and `Platform` promote together in ID-11 while `Device` waits for ID-14,
the schema must tolerate both types across that window rather than flipping
per model group.

Three annotations carry that, and they are recorded here as Wave E obligations
rather than as work for this slice:

- `GameOption.value` (`games/api.py:129-132`) must widen for the ID-11→ID-14
  window.
- `SearchSelectOption["value"]` (`common/components/search_select.py:77`) is
  already `str | int` and must gain `UUID`, or the resolvers must stringify.
- `_game_options` / `_platform_options` / `_device_options`
  (`games/forms.py:216-241`) each return `{"value": <obj>.id}` typed against it.

`PurchaseFilter._games_to_q`'s `int(...)` coercion — which raises
`FilterError("games filter values must be integers")` — belongs to ID-11 for the
same reason. The equivalent coercions and option-value expectations for
`Session`, `Purchase`, `Device` and `FilterPreset` belong to ID-12/ID-13/ID-14.

## Final model definition

```python
related_game = models.ForeignKey(
    Game,
    to_field="uuid",
    on_delete=models.SET_NULL,
    default=None,
    null=True,
    blank=True,
    related_name="addon_purchases",
    verbose_name="Base game",
)
```

Column name stays `related_game_id`; only the type changes. The reverse accessor
stays `addon_purchases`, but not for the reason a reader might assume:
`comparable_columns` deliberately **does not** enumerate
`related_game__addon_purchases__…` paths — `_comparison_multivalued_sources`
(`common/criteria.py:2255-2262`) skips the reverse of the FK it just traversed,
and `tests/test_filters.py:3272-3275` asserts that absence while `:3278` asserts
`related_game__purchases__` is present. What depends on the accessor name is
`_multivalued_relation_label` (`common/criteria.py:2229-2241`), which uses it to
keep `Game`'s two Purchase blocks distinct, plus
`tests/test_purchase_related_game.py:50`.

`Purchase` declares **no `Meta` at all** — no `unique_together`, no
`constraints`, no `ordering` — so ID-07's cascade trap (checklist item 6) has
nothing to take down and restore here. Verified against `games/models.py`; the
migration test asserts the resulting FK constraint exists rather than assuming
it. The trap does apply to `games_purchase_games`, whose auto-created
`unique_together` is over the column ID-11 will drop; that is recorded in the
handoff.

## Migration: `games/migrations/0012_purchase_related_game_uuid.py`

One hand-written file depending on `0011_session_fk_uuid`. One nullable
relation, so the **five-operation** shape (ID-07):

1. `AddField` `related_game_uuid` → `UUIDv7Field(null=True, default=None,
   db_default=None, editable=False)` — the explicit `None`s suppress the field's
   own defaults so the column is added empty.
2. `RunPython` backfill + reconcile (below).
3. `RemoveField` `related_game`.
4. `RenameField` `related_game_uuid` → `related_game`.
5. `AlterField` `related_game` → the final `ForeignKey(Game, to_field="uuid",
   …)`: renames the column to `related_game_id`, creates the FK constraint and
   index.

ID-06's leading `AlterField` is absent: it exists only to relax a `NOT NULL`
this column does not have.

`0011`'s module-level `backfill` / `restore` / `reconcile` helpers are already
generic over `(table_name, column, target_table)`; copy them verbatim rather
than re-deriving. One `RunSQL("SET CONSTRAINTS ALL IMMEDIATE")` sits between the
`RunPython` and the schema alterations — every FK in this schema is `DEFERRABLE
INITIALLY DEFERRED`, and `0006`/`0009`/`0011` all needed this guard.

`makemigrations` would emit one unrunnable `AlterField` (PostgreSQL has no
`integer`→`uuid` cast); the file is hand-written, and the drift guard compares
final state only. Confirm `makemigrations --check --dry-run` is clean after the
model change.

### Reconciliation

`reconcile(..., nullable=True)` asserts, before any FK constraint exists:

- no row gained NULL and no row lost it (two zero-row anti-joins, not a count
  comparison — that passes when one row gains NULL while another loses it);
- every non-NULL `related_game_uuid` equals the `uuid` of the `Game` the row
  pointed at (zero-row anti-join);
- the distinct referenced-`Game` count is unchanged.

One evidence line, in `0010`/`0011`'s format:

```
FK identity rewritten purchase_rows=<n> purchase_related_games=<n> purchase_related_game_nulls=<n> unmatched=0
```

Against the committed fixture's data shape that is 795 rows, 40 non-NULL.

## Read/write paths

**`games/forms.py:699` — `PurchaseForm.__init__`.** `seed_related_initial(self,
"platform")` becomes `seed_related_initial(self, "platform", "related_game")`.
Without it the edit page loses the Base-game preselection and `_game_options`
gets a `UUID` into a `pk__in`.

Nothing is at risk of being stomped, but check the reason rather than the
outcome: `add_purchase`'s chained-from-`add_game` branch
(`games/views/purchase.py:363-372`) *does* pass model instances in `initial`
(`{"games": [game], "platform": game.platform}`) — exactly the shape ID-08's
guard exists for — and `PurchaseForm.__init__` itself writes
`self.initial["price_currency"]` (`games/forms.py:702-703`). Those branches
build an **unsaved** instance, so `seed_related_initial` returns at
`games/forms.py:195` (`if not form.instance.pk`) before touching anything. The
only construction that passes an `instance=` is `edit_purchase`
(`games/views/purchase.py:404-410`), which passes no `initial` at all.

**`games/forms.py` — `PurchaseForm.games` needs nothing.** For a
`ManyToManyField`, `model_to_dict` calls `value_from_object`, which returns a
list of **model instances**, and `ModelMultipleChoiceField.prepare_value` maps
each back through `ModelChoiceField.prepare_value` to `.pk`. The M2M is
self-consistent today and stays so after ID-11.

**`games/management/commands/audit_library_ownership.py:196`.**
`values_list("pk", "related_game_id")` becomes `values_list("pk",
"related_game__id")`. ID-07 and ID-08 moved the other four projections to
relation lookups so the report cannot print two kinds of id at once; this is the
fifth. Note that `related_game__id` yields the target's **integer pk**, which is
the same identity the through-table line at `:208` prints — the report stays
internally consistent, which is the point of the rewrite.

**`games/management/commands/anonymize_sample.py:247`.**
`purchase.related_game_id = random.choice(all_game_ids)` assigns an integer to
what is now a UUID column. Map it through a new pk→uuid dict built beside
`game_offsets_by_uuid` (`:194`), which already runs the same
`Game.objects.filter(pk__in=all_game_ids).only("pk", "uuid")` query — extend
that comprehension's source loop rather than adding a second query.

Keep sampling `all_game_ids` and translate the *result*, rather than replacing
it with a UUID list. The reason is the deferral, not determinism: the through-row
build at `:251` (`Through(purchase_id=…, game_id=…)`) still needs integer Game
pks, so the integer list has to exist either way. (Determinism does not
discriminate here — `random.choice`/`random.sample` consume the RNG identically
for equal-length sequences.)

**`games/models.py:373`** — `if self.related_game_id is not None:` in `clean()`
is a presence check and is unaffected; a `UUID` is truthy and `is not None`
holds. `_validate_related_library(self.library_id, self.related_game, …)`
dereferences the relation, which is what the database-integrity test has to work
around.

**`games/views/purchase.py:318` and `:640`** pass `data.get("related_game")` /
`purchase.related_game` — instances, unaffected.

**`OuterRef` sweep** (checklist item 0), all eight hits read: `readiness.py:28,33,38,43`
correlate `User`/`UserLibrary` pks; `games/views/game.py:109` and
`games/api.py:243,250` already correlate `OuterRef("uuid")` from ID-07/ID-08;
`games/views/stats_data.py:236` correlates `Purchase.pk` against itself
(`library_purchases.filter(pk=OuterRef("pk"))`), which stays integer because
`Purchase.id` is not touched in Wave C. None involve `related_game`.

## No filter work

`PurchaseFilter.fields` (`games/filters.py:372-397`) has no `related_game` entry
— the Base game is not a facet — so there is no `FilterField("related_game_id")`
to rewrite, and no `relation_to_q` in `games/filters.py` names it in either
direction.

Every other `related_game__…` string in the codebase resolves *through* the
relation and is therefore type-agnostic, but they are not all
`comparable_columns` paths and the distinction matters for a sweep whose job is
to be exhaustive:

- `comparable_columns` operand paths: `related_game__year_released`,
  `related_game__name`, `related_game__purchases__…`
  (`tests/test_filters.py:3201,3278,6170`).
- ORM traversals in `audit_library_ownership`:
  `Q(related_game__library_id__in=…)` (`:192`), `related_game__isnull=False`
  (`:193`), `.exclude(related_game__library_id=F("library_id"))` (`:195`) — the
  same command whose `:196` projection *is* being rewritten.
- A docstring reference at `common/criteria.py:2237`.

`QUICK_FACETS`, `is_quick_editable`, the TS serializer, the criterion classes,
`PURCHASE_SORTS` and `stats_links` are untouched.

## Fixture, loader, anonymizer

**`games/fixtures/sample.yaml.gz`** is regenerated by a throwaway, uncommitted
transform (ID-06's recipe; a database round trip is not executable, because
loading the old blob needs pre-cutover code while the migration needs
post-cutover code):

1. Rewrite the 40 non-NULL `related_game` values on the 795 `games.purchase`
   records from a Game pk to that game's `uuid` string, leaving the 755 NULLs
   NULL.
2. Leave every `games:` list untouched — they are Game pks and stay Game pks.
3. Re-emit exactly as `anonymize_sample._write_fixture` does —
   `yaml.safe_dump(sort_keys=True, default_flow_style=False)` then
   `gzip.compress(compresslevel=9, mtime=0)` — so the blob stays a stable git
   object.

No new `uuid` fields are minted: `games.game` records already carry theirs from
#640's Wave B blob work.

Recorded in the PR as verification: per-model counts unchanged (851 game, 2718
session, 795 purchase, 203 playevent, 25 platform, 14 device, 75 exchangerate);
no field differs except the 40 rewritten `related_game` values; each resolves to
exactly one `game.uuid`; the NULL count is still 755; the total `games:` link
count is still 4505.

**`load_sample_data.FIXTURE_RELATIONSHIPS`** — `games.purchase`'s
`related_game` entry gains `reference_field="uuid"`. Its `games` entry keeps
`reference_field="pk"`. The validator derives its reference index generically
from that field; the comment at `:178` names this exact move as the case it was
built for. Games are private rows loaded with their fixture pk *and* uuid, so no
remap analogous to `_load_platforms` is needed.

## Making the deferral visible

Three artifacts, so ID-11 cannot rediscover this the hard way:

1. **A test** (in the new test module) pinning **both** through-table columns:
   `games_purchase_games.game_id` is still `bigint` and FK-constrained to
   `games_game(id)`, and `purchase_id` is still `bigint` and FK-constrained to
   `games_purchase(id)`. It states the remaining integer references as a
   contract and fails loudly when ID-11 and ID-13 respectively move them, which
   is exactly when someone should be reading this document. Pinning only
   `game_id` would leave ID-13 with no warning at all.
2. **A comment on `Purchase.games`** naming the Django limitation and pointing at
   ID-11 — short, no issue-history narration.
3. **Documentation**: this spec, an amendment to the wave plan's Wave C section
   and its ID-09 row, a comment on #646 carrying the through-table migration
   sketch plus the probe findings and its enlarged `to_field`/shim/annotation
   scope, a comment on #849 for the mirror-image `purchase_id` conversion, and a
   note on #645 so ID-10 does not read either column as a gap. #847's scope note
   is a comment on the issue.

## Verification

New `tests/test_purchase_fk_uuid.py`, mirroring `tests/test_session_fk_uuid.py`:

- **Migration**, via `MigrationExecutor` from `0011`: purchases with and without
  a `related_game`, spread across several games; migrate to `0012`; assert every
  row still points at the same target (compared by name), the NULL rows are
  still NULL, the column type is `uuid_v7`, and the FK constraint targets
  `(games_game, uuid)`.
- **Reverse**: back to `0011`; every integer `related_game_id` is exactly what
  it was, NULLs included.
- **ORM**: `purchase.related_game_id == game.uuid`,
  `filter(related_game=instance)`, `filter(related_game__id=game.id)`, the
  `game.addon_purchases` reverse accessor, and `Game.delete()` leaving the
  purchase with a NULL `related_game` (`SET_NULL`, not cascade).
- **Database integrity**: a purchase row naming a game uuid no game owns is
  rejected, inserted with `bulk_create` — `Purchase.save()` calls `clean()`,
  which dereferences `self.related_game` via `_validate_related_library` and
  would raise before reaching the database (ID-07 and ID-08 both hit this trap).
- **Form**: editing a DLC purchase renders the Base-game combobox preselected
  with an integer option value, and posting an integer saves the right game.
- **Deferral tripwire**: both through-table columns as described above, plus the
  `(purchase_id, game_id)` unique index present and enforced.

The new form test is the **only** coverage of the `related_game` shim.
`e2e/test_widgets_e2e.py`'s five `related_game` cases (`:158`, `:271`, `:311`,
`:460`, `:521`) all drive the *add* page, where the form is unbound and
`seed_related_initial` short-circuits — none of them would notice the shim
missing.

Existing tests that gate this change and must be named, not assumed:

- `tests/test_library_commands.py:197` —
  `test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
  loads the *committed* `sample.yaml.gz` under
  `@pytest.mark.django_db(transaction=True)`. A botched regeneration is a hard
  `make check` failure here, not a dev-only annoyance. This is the gate the wave
  plan names at `:196`.
- `tests/test_anonymize_sample.py:174` — `test_output_reloads_via_loaddata` is
  what actually catches a missed pk→uuid translation in the anonymizer:
  `_build_dataset` creates a DLC purchase with `related_game=base_game`
  (`:46-55`), and an untranslated integer into a `uuid_v7` column fails on
  `bulk_update`.

Extended existing tests:

- `tests/test_library_commands.py:321` — the
  `("games.purchase", {"library": "__target_library__", "related_game": 999},
  "Game")` parameter case moves to `ABSENT_GAME_UUID`. The sibling
  `{"games": [999]}` case at `:316` stays integer and keeps covering the pk
  reference path.
- `tests/test_library_commands.py:250` — the inline fixture's
  `related_game: null` stays valid; the module's other inline purchase records
  need a uuid-valued `related_game` only where they set one.
- `tests/test_anonymize_sample.py:162` — `assertIsNotNone(fields["related_game"])`
  still holds; add an assertion that the emitted value is a `uuid` carried by a
  `games.game` record in the same dump, which pins the anonymizer's new
  translation directly rather than through a load failure.

Expected to pass untouched: `tests/test_purchase_related_game.py`,
`tests/test_library_models.py`, `tests/test_library_form_isolation.py`,
`tests/test_library_reconciliation.py`, `tests/test_filters.py`,
`tests/test_filter_cross_entity.py`, `tests/test_date_picker.py`,
`tests/test_paths_return_200.py`, `tests/test_rendered_pages.py`,
`tests/test_stats.py`, `tests/test_signals.py`, and the e2e suite.

The gate is the full `make check`, including `e2e/`.

## Rollback

`manage.py migrate games 0011` restores the integer column with its original
values and NULLs. Reversing also requires reverting the regenerated fixture
blob; they are a single unit.

## Handoffs

- **ID-10 (#645)** audits the integer→UUID map with *two* columns still on
  integers, both on `games_purchase_games`. Its scope must name both and keep
  them apart: `game_id` is anomalous — deferred by this design, and the only
  `Game` reference that did not move in Wave C — while `purchase_id` is normal,
  because `Purchase.uuid` is not promoted until ID-13. Neither is a gap.
- **ID-11 (#646)** promotes `Game.uuid` to primary key and, in the same
  migration, converts `games_purchase_games.game_id` — add a UUID holding
  column, `UPDATE … FROM games_game`, drop, rename, restore the FK and the
  `(purchase, game)` unique index that `DROP COLUMN` cascades away. State-side
  needs nothing: an auto-created through derives its FK from the target's pk.

  ID-11 also owns everything keyed to *Game* ceasing to be an integer, which is
  the larger half of the slice: deleting `to_field="uuid"` from every FK naming
  `Game.uuid` (`Purchase.related_game`, `Session.game`, `PlayEvent.game`,
  `GameStatusChange.game`) — mandatory, since `to_field="uuid"` becomes
  `fields.E312` the moment the field is renamed — the `PurchaseForm` and
  `SessionForm` `seed_related_initial` game arguments,
  `audit_library_ownership`'s `related_game__id` lookup,
  `PurchaseFilter._games_to_q`'s `int(...)` coercion, and the game half of the
  option-value widening listed in the value-flip section above. `Platform` is in
  the same slice, so `Purchase.platform`/`Game.platform`'s `to_field` and the
  platform shims go with it.
- **ID-13 (#849)** promotes `Purchase.uuid` to primary key. Its through-table
  work is the mirror image of ID-11's: `games_purchase_games.purchase_id` takes
  the identical conversion, and the same unique index cascades away again.
