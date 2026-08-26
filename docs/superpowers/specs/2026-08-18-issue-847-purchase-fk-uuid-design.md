# ID-09: the base-game relation on UUID, and the deferred many-to-many — decision record

Slice ID-09 (#847) of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
whose "What *swap every read/write path* actually means" checklist carries the
reusable mechanics. This record keeps only what neither the code nor that
checklist can: why the slice was cut where it was, why one nominated piece of
work turned out not to exist, and what the design got wrong.

Delivered: `Purchase.related_game` → a real `uuid_v7` foreign key at
`Game.uuid`, reversibly. **`Purchase.games` (M2M) is deferred to ID-11/ID-13.**

## Why the many-to-many could not move

Established by probe against the installed Django 6.0.7, not by reading:

- `ManyToManyField.__init__` accepts no `to_field`, and
  `create_many_to_many_intermediary_model` builds its two foreign keys as plain
  `ForeignKey(to_model)`. An auto-created through always references the target's
  **primary key**. Pointing `Purchase.games` at `Game.uuid` therefore requires
  replacing the auto-created through with an **explicit through model**.
- With an explicit through, `Serializer.handle_m2m_field` bails
  (`if field.remote_field.through._meta.auto_created:`), so `dumpdata` emits
  purchase records with **no `games` key at all**. The committed fixture is
  produced by `anonymize_sample` through `dumpdata`, so it would carry ~4505
  `games.purchasegame` records instead of 795 `games:` lists.
- The current fixture shape cannot survive either. Probed against an explicit
  through whose target FK carries `to_field="uuid"`: `loaddata` of
  `games: [<int pk>]` fails with `IntegrityError: FOREIGN KEY constraint failed`
  (the `.set()` path writes the integer into the UUID column), and
  `games: [<uuid>]` fails with `DeserializationError: value must be an integer`,
  because `deserialize_m2m_values` converts every element through
  `field.remote_field.model._meta.pk.to_python` — the **target's pk**, never the
  through's `to_field`. The M2M fixture pipeline is wired to the target's primary
  key in both directions.

**Rejected — introduce the explicit through model anyway.** It is a permanent
modeling change (or a second shape flip in Wave E to remove it) plus a
fixture-format change plus `load_sample_data` / `PORTABLE_LIBRARY_MODELS` /
`DUMP_LABELS` learning a model that exists only to carry a transition.

**Chosen — defer the through column to the slice that promotes the pk.** It costs
no application code in either wave, because every site touching the M2M speaks
"Game primary key" and each follows automatically once that pk *is* the UUID:
`PurchaseFilter._games_to_q`, both `games__id` `relation_to_q` lookups,
`m2m_changed`'s `pk_set`, `anonymize_sample`'s direct `Through(...)` build,
`audit_library_ownership`'s pair projection, the fixture's `games:` lists, and
`games/sorting.py`'s reverse-join annotations. Under the explicit-through
alternative the first four would all have changed. What ID-11 inherits is one
database-level conversion inside the migration that is *already* rewriting
`Game.id`, and ID-13 owes the same table the mirror-image conversion of
`purchase_id` regardless — so Wave E pays for `games_purchase_games` once instead
of twice.

This is a deliberate, single exception to the slice-by-target-model principle
ID-07 and ID-08 established. After this slice every *field-backed* foreign key to
a converted model resolves through its target's `uuid`. What remains on integers,
enumerated by introspecting every FK in the app:

| Column | Status |
| --- | --- |
| `games_purchase_games.game_id` → `Game.id` | **anomalous** — the only `Game` reference that did not move in Wave C. ID-11's. |
| `games_purchase_games.purchase_id` → `Purchase.id` | normal until ID-13 promotes `Purchase.uuid`. |
| `UserLibrary.user`, `UserPreferences.user` → `auth.User.id` | out of scope for the whole cutover — `auth.User` keeps its integer pk. |

`tests/test_purchase_fk_uuid.py::test_the_purchase_games_through_table_is_still_integer_keyed`
pins **both** through columns, so the deferral is a contract rather than a
comment, and it fails loudly in the slice that moves either. Pinning only
`game_id` would have left ID-13 with no warning at all.

## Why the value flip is not an issue of its own

ID-09 was nominated to own the global integer→UUID flip of filter criterion
values and search-endpoint option values, on the reasoning that it is the last
Wave C slice. There is nothing there to own.

Every Wave C lookup was rewritten to `<name>__id`, which resolves to the target's
primary key. The moment ID-11 promotes `Game.uuid`, that same unchanged lookup
resolves UUIDs and `_game_options` starts emitting them. A dedicated flip issue
between Waves C and D would have to move every lookup from `<name>__id` to
`<name>__uuid` while the pks are still integers, and back again after Wave E: two
rewrites of the same lines for no coverage.

**The residual is type annotations, not lookups**, and it belongs to the promoting
slices. Verified against the installed pydantic: `GameOption.value: int`
(`games/api.py`) is the response schema of **all three** search endpoints, and a
`UUID` against it raises `ValidationError: Input should be a valid integer` — the
promotion 500s the endpoint rather than flipping it for free. `Game` and
`Platform` promote in ID-11 while `Device` waits for ID-14, so the shared schema
must tolerate both types across that window rather than flipping per model group.
`SearchSelectOption["value"]` and the three option resolvers in `games/forms.py`
carry the same obligation, as does `PurchaseFilter._games_to_q`'s `int(...)`
coercion.

## What the design missed

- **The anonymizer's second seam shape.** The wave checklist described the
  anonymizer as a *lookup* problem — a per-game offset map keyed by the wrong
  identity. `related_game` is an *assignment*: the command reassigns each add-on
  purchase to a random game, so the pk→uuid translation is needed on the write
  side. Merged into checklist item 4.
- **The anonymizer and the loader are not independently green.** The plan
  expected the anonymizer task to pass on its own; it cannot.
  `test_output_reloads_via_loaddata` runs `load_sample_data` over the
  anonymizer's fresh output, so it stays red until the loader declares
  `reference_field="uuid"` — which the plan had scheduled as the next task. Also
  merged into item 4.
- **`Purchase` has no `Meta` at all**, so ID-07's constraint-cascade trap
  (checklist item 6) had nothing to take down and restore on the model. It does
  apply to `games_purchase_games`, whose auto-created `unique_together` is over
  the column ID-11 will drop; that is in the handoff.
- **The form shim has exactly one test.** `e2e/test_widgets_e2e.py`'s five
  `related_game` cases all drive the *add* page, where the form is unbound and
  `seed_related_initial` short-circuits. None of them would have noticed the shim
  missing.
- **Reconciliation evidence against real data expires with the fixture.** The
  migration's evidence line is asserted from a seeded historic world in the
  migration test. It could not also be captured from the committed fixture after
  the fact, because that blob is now post-cutover and no longer loads at `0011`.

## Rollback

`manage.py migrate games 0011` restores the integer column with its original
values and NULLs. Reversing also requires reverting the regenerated fixture blob;
they are a single unit.

## Handoffs

Each of these is also a comment on the issue itself.

- **ID-10 (#645)** audits the integer→UUID map with two columns still on
  integers, both on `games_purchase_games`. Its scope must name both and keep
  them apart: `game_id` is anomalous, `purchase_id` is normal until ID-13.
  Neither is a gap.
- **ID-11 (#646)** promotes `Game.uuid` and, in the same migration, converts
  `games_purchase_games.game_id` — add a UUID holding column, `UPDATE … FROM
  games_game`, drop, rename, restore the FK **and** the `(purchase, game)` unique
  index that `DROP COLUMN` cascades away. Migration *state* needs no operation:
  an auto-created through derives its FK from the target's pk at state-render
  time.

  ID-11 also owns everything keyed to *Game* ceasing to be an integer, which is
  the larger half of the slice: deleting `to_field="uuid"` from every FK naming
  `Game.uuid` (`Purchase.related_game`, `Session.game`, `PlayEvent.game`,
  `GameStatusChange.game`) — mandatory, since it becomes `fields.E312` the moment
  the field is renamed — the `PurchaseForm`/`SessionForm` `seed_related_initial`
  game arguments, `audit_library_ownership`'s `related_game__id` projection,
  `_games_to_q`'s `int(...)` coercion, the fixture's `games:` lists and their
  `reference_field`, and the game half of the annotation widening above.
  `Platform` promotes in the same slice, so its `to_field`s and shims go with it.
- **ID-13 (#849)** promotes `Purchase.uuid`. Its through-table work is the mirror
  image of ID-11's on `purchase_id`, and the same unique index cascades away
  again.
