# PR #1006 review — provider-neutral external references

**Branch:** `claude/issue-896-provider-neutral-references`
**Base:** `main` (44 files, +5993 / -375)
**Closes:** #896, #976. Also carries the unmerged #988 commits.
**Reviewed:** 2026-09-03, five parallel reviewers (code, tests, error handling,
comments, type design). Findings below were each checked against the code;
the ones marked **reproduced** were run.

Status of the branch at review time: full `make check` green — 5086 passed,
1 xfailed. Every finding here is something the suite does not catch.

**All three Critical findings are fixed** (2026-09-03, five regression tests
added, full `make check` green at 5091 passed / 1 xfailed). Each carries a
**Fixed** note below.

**Important I1, I2, I3 and I4 are fixed** (2026-09-03, full `make check` green
at 5089 passed / 1 xfailed — six tests added, eight deleted with the two dead
functions). **I5 is fixed too** (2026-09-03, full `make check` green at 5095
passed / 1 xfailed — six more tests). I6 and I7 are open, as is everything from
the docs table down.

---

## Critical

### C1. `restore()` raises `IntegrityError`, and resurrects a key a person cleared

`games/removal.py:80`. **Reproduced. Fixed.**

```python
held.filter(removed_at__isnull=False).filter(free).update(removed_at=None)
```

`free` tests only whether the *key* is taken. It un-marks every removed
reference of the row. A record accrues one removed row per key change,
because `_state_one` (`games/external_references.py:217-220`) marks the
incumbent and creates a successor. So:

- `state(Q1) → state(Q2) → remove → restore` brings both rows back live:

  ```
  django.db.utils.IntegrityError: duplicate key value violates unique constraint
    "unique_live_game_reference_per_provider"
  DETAIL:  Key (provider, game_id)=(wikidata, 01a06806-…) already exists.
  ```

- `state(Q1) → clear → remove → restore` brings the cleared reference back
  live, and `_mirror_the_wikidata_column` writes `Q1` back into the column.
  Silent resurrection: `AssertionError: assert 'Q1' == ''`.

The root cause is a "one act, one verb" violation. `removed_at` carries two
acts — *cleared by a person* (`external_references.py:220`) and *removed with
its row* (`removal.py:70`) — and the restore path cannot tell them apart.

Compounding it: `_stamp` commits `removed_at=None` on the row before
`_AFTER_STAMP` runs, and nothing wraps the pair, so the raise leaves the row
restored, its references not, and `_mirror_the_wikidata_column` /
`_recount_purchases` never run.

`restore()` has no production caller yet, so this is latent — but the
constraint this PR adds is what makes it reachable, and #695/#795 will call it.

**Fix.** Restore at most one reference per `(provider, target)` — the most
recently marked free one — and wrap `_stamp`'s UPDATE plus its `_AFTER_STAMP`
callables in `transaction.atomic()`. A narrower alternative that keeps one
column: capture the row's prior stamp before the UPDATE and restore only the
references whose `removed_at` equals it, which makes the column mean "removed
*with* the row" wherever the value matches.

**Fixed** — the narrower alternative, because it is exact rather than a
heuristic. `_stamp` now reads the row's mark from the database before it
writes the new one and passes it to every `_AFTER_STAMP` callable, and the
whole sequence runs in one `transaction.atomic()`.
`_mark_the_references_of` restores only the references carrying that mark,
still filtered by the `free` guard. Migration 0041 changed with it: it stamps
a removed row's references with a `Subquery` reading the row's own
`removed_at` rather than the migration's clock, or a migrated database could
never restore anything.

The mark is now the record of *which act* took a reference out: a person
correcting or clearing a key stamps at that moment, a removal stamps with the
row's mark, and 0041's duplicate resolver stamps with its own clock — so none
of the three can be undone by another's restore.

Regression tests: `test_restoring_takes_back_only_the_key_the_row_went_out_with`
and `test_restoring_does_not_state_a_key_a_person_let_go_of`, in
`tests/test_reference_removal.py`. Both reproduced the reported failures before
the fix.

### C2. The backfill aborts the whole sample load on a removed Game

`games/external_references.py:401` and `:421`, called from
`games/management/commands/load_sample_data.py:155`.

`Game.objects.filter(library=library)` is the plain manager, which still sees
removed rows, and nothing excludes `removed_at__isnull=False`. A removed Game
keeps its `wikidata` column (`_mirror_the_wikidata_column` no-ops on removal)
and holds no live reference, so it lands in the queryset. Then
`state_external_references` refuses it with `REMOVED_TARGET` — and that call
sits *outside* the `try` that guards `normalize_provider_key`.

`handle()` wraps the load in `transaction.atomic()`, so `make loadsample`
loads nothing, with a raw traceback and an end-user sentence ("Put it back
before you change it") that means nothing to an operator. It is not wrapped in
`CommandError` like every other failure in that command.

Dormant only because today's `sample.yaml.gz` has no removed games.
`anonymize_sample`'s `_prune_other_libraries` keeps the library's removed rows
and `dumpdata` uses `_default_manager`, so the next regeneration against
production — which has had `removed_at` since #944 — bakes the crash in.

**Fixed.** The queryset takes `removed_at__isnull=True`, which is what makes
the refusal unreachable rather than merely handled. `handle()` now wraps the
backfill in `CommandError`, so a refusal that does escape reads as a defect an
operator can report instead of a raw traceback.

I4 is fixed in the same change, since it is the same three lines:
`BackfilledReferences` counts `written` / `taken` / `malformed` apart, each
skip is logged with the Game's pk and the offending value, and the command
prints one sentence per cause.

Regression tests: `test_the_backfill_leaves_a_removed_game_alone` and
`test_the_backfill_counts_a_malformed_column_apart_from_a_taken_key`, in
`tests/test_external_references.py`.

### C3. The reference inputs render unstyled

`games/reference_form.py:48`.

`PrimitiveWidgetsMixin.__init__` calls `apply_primitive_widget_classes(self.fields)`
immediately after `super().__init__()` (`games/forms.py:158-160`).
`ReferenceSetForm` builds its fields *after* that call, so the mixin is a
no-op. Actual rendering:

```html
<input type="text" name="reference_wikidata" maxlength="255"
       aria-describedby="id_reference_wikidata_helptext" id="id_reference_wikidata">
```

No `INPUT_CLASS`, no `DISABLED_CONTROL_CLASS` — a browser-default box between
two fully styled areas on all four hosting pages (Add/Edit Game, Add/Edit
Platform). Breaks the CLAUDE.md rule that native controls take their classes
from `PrimitiveWidgetsMixin`. The e2e tests fill by `name`, so they pass.

**Fixed.** `apply_primitive_widget_classes(self.fields)` runs after the loop
and `PrimitiveWidgetsMixin` is off the bases, following
`games/settings_forms.py:128`. Regression test:
`test_every_box_wears_the_native_control_classes` in
`tests/test_reference_form.py`, which asserts the class on the widget *and* in
the rendered markup.

---

## Important

### I1. A lost race is a 500, and three comments claim it cannot happen — **fixed**

`games/external_references.py:183` says the conditional constraint answers the
loser and `catalog_submit.py` reads the name the database gave.
`games/catalog_submit.py:55` files
`unique_external_reference_provider_kind_key` under
`UNREACHABLE_FROM_THE_GAME_FORM`, so `answered_constraint()` returns `None`
and the `IntegrityError` re-raises. `games/reference_form.py:120` repeats the
claim for the Platform path, which has no `IntegrityError` handler at all.

The constraint is reachable: `select_for_update()` at `:255` locks only rows
already attached to *this* target, never the key another target is about to
claim, so two requests can both pass `_refuse_a_taken_key` for a key nobody
holds yet. Pre-PR, `save_external_reference` caught this in its own savepoint
and raised a `provider_key` refusal — so this is a concurrency regression, not
only stale prose.

**Fix.** Catch `IntegrityError` in `state_external_references` around the
`create()` in a savepoint and re-raise as `ReferencesRefused(KEY_TAKEN,
provider=provider)`, which both callers already answer onto the right box.
Then correct whichever comments lose.

**Fixed.** `_state_one` writes the `create()` in a savepoint of its own and
hands the collision to `_refusal_for`, which reads the constraint name the
database gave and states one of two sentences on the provider's box:
`KEY_TAKEN` for `unique_external_reference_provider_kind_key`, and a new
`RECORD_RACED` for `unique_live_<kind>_reference_per_provider` — the review
asked for `KEY_TAKEN` for both, but the per-record constraint means the record
holding the key is *this* record, and "another record already states this
identifier" would be false. A constraint neither shape matches rises as itself,
as `answered_constraint()` treats an unmapped one. The three comments now say
this. `UNREACHABLE_FROM_THE_GAME_FORM` keeps all five entries under one shared
reason: they are still out of `answered_constraint()`'s reach, now because the
service converts them before the boundary sees them, not because nothing can
trip them. Four tests: two driving a rival claim in from where the pre-check
runs (one per constraint), two on `_refusal_for`'s unmapped and wrong-kind
paths.

### I2. `resolve_external_reference` ignores the mark — **fixed**

`games/external_references.py:337`. No `removed_at__isnull=True`, and `.first()`
on a queryset with no ordering and no `Meta.ordering`. Before this PR the
unconditional unique constraint made at most one such row exist; now a live row
and any number of removed rows can share the tuple, so it resolves
nondeterministically — possibly to a removed row's target.
`save_external_reference` got the `live` filter; this one was missed.

**Fixed.** The filter is there. Ordering needs nothing further: among live rows
the conditional constraint leaves at most one to find, which the docstring now
says. Two tests — a key handed on from one record to another resolves to the
holder, and a key nobody holds resolves to `None`.

### I3. Three public functions are test-only, and two are now unsafe — **fixed**

`save_external_reference`, `resolve_external_reference` and `provider_labels`
have no production caller (`grep` finds only `tests/test_external_references.py`).
`save_external_reference` does not know about the four per-record uniques: for a
target already holding a live key under that provider, the `create()` trips
`unique_live_<kind>_reference_per_provider`, and the `except IntegrityError`
handler re-queries by the *new* key and raises `DoesNotExist`. Delete all three,
or route the writer through `state_external_references`, before #783/#784/#785
build on them.

**Fixed, two of three.** `save_external_reference` and `provider_labels` are
gone with their eight tests: the first is superseded by
`state_external_references` and cannot be repaired without duplicating it, and
the second had no caller and one assertion. `resolve_external_reference` stays
and was repaired instead (see I2) — the IGDB wave needs a resolver, its fix was
two lines, and its five tests are the seam's only description. Its remaining
setup no longer goes through a writer: it creates the reference row directly.

### I4. `skipped` conflates two causes, and the operator message states the wrong one — **fixed**

`games/external_references.py:415` and `:418` both increment `skipped` — one for
a malformed column value, one for a key already stated. The warning at
`load_sample_data.py:161` attributes every skip to the second:

> "N game(s) kept a Wikidata column no reference states: another library
> already holds the key."

A malformed value sends the operator hunting a conflict that does not exist.
The bare `except ValidationError:` also discards the refusal message, the Game's
pk and the offending value, so nothing identifies which of 858 fixture games is
broken.

**Fixed** alongside C2 — same three lines. See C2 for what landed.

### I5. Migration 0041 has no test, and its reverse is broken — **fixed**

`games/migrations/0041_external_reference_marks.py`. Two `RunPython` data
functions, a hand-rolled keyset pager, and a `_keeper` tie-break that is
mirror-aware only for `entity_kind == "game"` — for the other three kinds it
silently keeps the lowest `id`. Zero coverage; `grep` for `0041` across `tests/`
finds nothing. `tests/test_external_reference_migration.py:34` already has the
harness (`MigrationExecutor` + `flush`) used for seven tests around 0022.

Missing cases: a reference of an already-removed row per kind; the mirror
tie-break when `Game.wikidata` names the *later* row; the fallback when the
column is empty; a Platform pair (where the mirror plays no part); and more
than `BATCH_SIZE` rows so `_paged` takes a second page.

Reverse order runs `RemoveField(removed_at)` and *then* `AddConstraint` of the
unconditional unique on `(provider, entity_kind, provider_key)`. Any database
holding a marked row and a live row with the same tuple — the state this
feature creates by design, per `tests/test_reference_removal.py:31` — cannot
roll back, and dies after `removed_at` is already gone, so the operator cannot
inspect the collision.

**Fixed.** A last `RunPython` — noop forward, thus first to reverse — refuses
the reverse with `Cannot reverse external reference marks while marked
reference rows exist.` while any mark stands, so the marks are still readable
when it stops. Six tests in `tests/test_external_reference_migration.py` on a
second `MigrationExecutor` harness pinned at 0040: a reference per kind under a
removed row taking that row's own mark, the mirror tie-break in both
directions, the empty-column fallback, a Platform pair, a duplicate whose two
rows straddle the `BATCH_SIZE` page break, and the refused reverse. The reverse
test was run against the migration without the guard first and fails there.

Left as it is: `_keeper` consulting the mirror for `entity_kind == "game"`
alone. No other kind carries a mirror column, so there is nothing for one to
prefer; the docstring now says so.

### I6. `list_games` 500s on a non-canonical `wikidata` column

`games/views/game.py:196` calls `external_reference_url(provider_key=game.wikidata)`
unguarded; it raises `ValidationError` on anything the pattern rejects. One such
row takes down the whole list, not one cell.

The call is pre-existing on `main`, but this PR deletes `GameForm.clean_wikidata`
— the guard that canonicalized the column on save — and adds a skip path that
deliberately leaves such columns behind. Related: the backfill canonicalizes
into the reference and never mirrors back, so a column holding `q123` beside a
reference stating `Q123` is now representable.

**Test that fails today:** create a Game with `wikidata="n/a"` via
`Game.objects.create()`, then GET `games:list_games` and assert 200.
`tests/test_paths_return_200.py` is the natural home.

### I7. `confirm_and_apply` catches the base `ValidationError`

`games/views/removal.py:72` (#988 code). `action()` now runs the `_AFTER_STAMP`
chain, including `_recount_purchases` → `purchase.save()` → `clean()`. Any
model-validation failure beneath it renders as "here is why the removal was
refused" with a hardcoded 409 and field-dict wording written for a form,
unlogged — exactly what `answered()` in `games/writes/answers.py:110` goes out of
its way to prevent.

`games/views/playergame_writes.py:78` compounds it by downgrading a typed
`CommandFailed` into an untyped `ValidationError`, discarding
`failure.status_code` and erasing the type that distinguished "safe to show"
from "a defect happened underneath".

**Fix.** Introduce a dedicated refusal type, catch only that, and let a real
`ValidationError` reach the 500 handler where a defect belongs.

---

## Docs and comments

All verified against the code.

| Where | Problem |
|---|---|
| `docs/event-retention.md:61` | **Fixed.** Was inverted: One constraint on `(provider, entity_kind, provider_key)`; **four** on `(provider, <fk>)`. The doc swaps them, and now disagrees with `docs/catalog.md:220`, which is right. |
| `tests/test_name_key.py:25` | `#998` is *"A duplicate Edition name is blamed on whichever row the service saw second"* — nothing to do with `İ` case mapping. The `strict=True` xfail will outlive #998's closure. File the residue issue or state the condition. |
| `games/migrations/0041_…:64` | Names `sync_game_wikidata`, deleted in this same branch. Exists nowhere reachable from `main`. Keep the next sentence; drop the dead symbol. |
| `games/external_references.py:352` | Lists "the API" as a reader of `Game.wikidata`. No `wikidata` in `games/api.py` or `ts/`. |
| `games/models.py:833` | "`games/removal.py` writes it" — `_state_one` writes it when a person changes or clears a key, and migration 0041 writes it too. |
| `docs/event-retention.md:65`, `docs/catalog.md:232` | **Fixed in event-retention.md** (catalog.md still silent). Neither stated the tested exception: a removed Game does **not** stamp its Editions'/Releases' references, so those keys stay claimed by rows nobody can see — the exact harm event-retention cites as the reason for the rule. Most likely thing in the diff to be read as a bug later. |
| `games/models.py:695` | `Provider`/`EntityKind` `TextChoices` declared, zero callers, `choices=` never attached to the columns they describe. |
| `common/naming.py:1` | The module's central claim has a known exception (`İ`) it does not mention, proved by its own `strict=True` xfail. |
| `games/external_references.py:391` | **Fixed with C2.** Was `#654 owns that reconciliation` — #654 is scoped to redirects and hands the workflow to #785. The branch's own spec says `#654/#785`. |
| `games/removal.py:57` | `#695 and #795` — #695 is Session Undo only; #795 is the load-bearing citation. |
| `games/external_references.py:214` | **Fixed with I1.** Was `"""One provider's box, as one write."""` — it performs up to two (an UPDATE then an INSERT). |
| `games/views/game.py:1019` | `One read for the page` contradicts `reads/external_references.py:1` ("one query per kind"); this call passes three kinds. |
| `games/migrations/0041_…:4` | "the two backfills" — `BATCH_SIZE` feeds `_paged`, which only `_keep_one_key_per_record` uses. |
| `games/removal.py:84` | Explains the restore branch, not the guard. The interesting half — that a removal deliberately leaves the column alone so a restore can take the key back — is unexplained. |
| `games/views/reference_section.py:13` | `_BLOCK_CLASS` is byte-identical to `games/views/catalog_section.py:63` and the comment asserts an invariant nothing enforces. Import it instead. |

---

## Design questions worth settling

**The provider registry and the check constraints disagree.**
`external_reference_supported_provider` hardcodes `Q(provider="wikidata")`, and
`external_reference_canonical_provider_key` applies `^Q[1-9][0-9]*$` to **every**
row regardless of provider. Meanwhile `ProviderPolicy`'s docstring promises
"registering a policy is the whole UI cost of a provider". Register a second
provider without a matching migration and `ExternalReferenceLinks` raises
`KeyError`/`ValidationError` mid-render, so the Game detail page and the whole
Platform list 500 on every request. A render path should not be what enforces a
data invariant.

Either derive the constraints from `PROVIDER_POLICIES`, or add a guard test
asserting the two agree — in the spirit of
`test_every_unique_constraint_the_form_can_reach_is_mapped` — and degrade the
renderer to plain text with a logged error rather than taking the page down.

**`ProviderPolicy` does not validate its own template.** `url_template: str` is
the sole trusted source of an `href`, and `ExternalReferenceLinks`' "safe by
three layers" docstring rests layer two entirely on it. A `__post_init__`
refusing a template that lacks `{provider_key}` or does not start with
`https://` is three lines and catches a security-relevant mistake at import.
Nothing checks the registry key is casefolded either, so a policy registered as
`"Wikidata"` is silently unreachable.

**`KEY_TAKEN` is unactionable.** "Another record already states this identifier"
names no record. The case where a person most needs to know is one the design
deliberately creates: a Release under a removed Game keeps its claim
(`tests/test_reference_removal.py:83`) while being invisible in every list and
unreachable for editing. The key is held hostage by a row the person can neither
see nor free.

---

## Type design

Ratings from the type reviewer, for the record:

| Type | Encapsulation | Expression | Usefulness | Enforcement |
|---|---|---|---|---|
| `ExternalReference` | 6 | 6 | 9 | 7 |
| `ProviderPolicy` / `PROVIDER_POLICIES` | 7 | 4 | 9 | 4 |
| `BackfilledReferences` | 8 | 5 | 6 | n/a |
| `ReferenceSetForm` | 5 | 6 | 9 | 6 |
| `ReferenceMap` | 7 | 6 | 8 | 5 |
| `NameKey` | 8 | 9 | 10 | 5 (intentional) |

Smaller points:

- `reference_form.py:99` guards a real invariant with a bare `assert`, which
  `python -O` strips. `bind()` is public and unguarded, so binding a *different*
  record than the one that seeded `initial` writes one record's keys onto
  another.
- `reads/external_references.py:18` takes `Sequence[Model]` and does an
  unguarded `TARGET_FIELDS_BY_MODEL[type(row)]`. A `Device` raises a bare
  `KeyError` where every other entry point raises
  `ValidationError("Unsupported catalog target.")`. `Sequence[CatalogTarget]`
  makes it unreachable statically.
- `references_for` returns `dict(found)`, so callers must supply a default —
  and they disagree: `game.py:698` passes `()`, `platform.py:98` passes `[]`,
  against an alias promising `list`.
- Unnamed compounds, against CLAUDE.md: `normalize_provider_key → tuple[str, str]`,
  `_target_metadata → tuple[str, str]`, `_owner_and_mark → tuple[UUID | None, bool]`.
  All same-typed pairs, so a swap type-checks. `provider`, `provider_key` and
  `entity_kind` are bare `str` across roughly twenty signatures; the same branch
  added `common/naming.py` specifically to name one such role.
- `common/naming.py:14` uses `str.strip()`, but `Trim()` compiles to `btrim(x)`,
  which strips ASCII spaces only. A name with a trailing tab or non-breaking
  space keys equal in Python and unequal in Postgres — the class of bug the
  module exists to prevent.
- `PROVIDER_POLICIES` is a plain mutable dict with no `Final`, while
  `catalog_submit.py:40,54` annotates its two registries `Final`.
- `external_references.py:24-26` makes `CatalogTarget` mean `object` at runtime.
  PEP 695 aliases are lazily evaluated, so the `else` branch may be unnecessary.

---

## Test gaps

Beyond the migration (I5) and the `list_games` 500 (I6):

- **The backfill's non-happy branches are entirely untested.** The fixture's 858
  wikidata values are all distinct and all canonical, so the parity test at
  `tests/test_external_references.py:669` exercises only the `written` path.
  Neither skip branch fires and the command's warning never prints.
- **`_owner_and_mark`'s Edition and Release branches** are unexercised, including
  the library boundary (ownership derived through `edition.game.library_id`).
  The docstring's claim about a removed ancestor is untested.
- **Remove/restore for Edition, Release and Platform.** Covered: Game remove,
  Game restore, Platform remove. Untested: `remove(edition)`, `remove(release)`,
  and restore for any non-Game kind — and the restore branch is the subtle one.
- **The Editions table's References column** never renders in any test;
  `tests/test_reference_presentation.py:62` reaches only the header meta-row, so
  `_references_cell` is untouched.
- **`references_for` is only tested for one kind**, against a docstring
  promising one query per kind, while the detail page feeds it three.
- **Cross-kind key coexistence** (a Game and a Platform may both claim `Q123`) is
  a deliberate scoping decision that nothing pins.
- **A POST that omits `reference_wikidata` entirely** silently clears the
  reference; every test posts through a fixture that always includes the key.
- **`edit_platform` rollback on a taken key** — the Game path proves the rename
  is taken back; the Platform path has only the add case.

Test-quality nits: `pytest.raises(Exception)` at `tests/test_reference_form.py:85`
and `:99` should name `ReferencesRefused`;
`assert str(ExternalReferenceLinks([])).strip() in ("", "—")` accepts an
alternative nothing produces; `assert "&lt;ul" not in markup` in
`tests/test_components.py` is scoped to a tag a caller may legitimately use.

---

## What is done well

- `test_every_unique_constraint_the_form_can_reach_is_mapped`
  (`tests/test_catalog_submit.py:355`) forces every new constraint to be
  classified as answered or unreachable, with a written reason. The best
  structural test in the diff.
- `submitted_game_or_form_error` and `submitted_or_form_error` both **re-raise**
  a refusal no handler claimed rather than inventing a sentence, and
  `answered_constraint` returns `None` for an unmapped constraint instead of
  guessing. I1 and I7 are precisely where that discipline was asserted in a
  docstring but not implemented.
- The #976 constraint behaviour is tested at the database layer
  (`tests/test_external_references.py:469` onward), so it survives a refactor of
  the Python guard — and `tests/test_reference_removal.py:53` covers the hard
  case, a restore that must *not* reclaim a contested key.
- `tests/test_reference_removal.py:83` pins a non-obvious consequence of the
  ancestor-marking design and proves the key is still *claimed*, not merely
  unmarked.
- The `xfail(strict=True)` on `İ` records a deferral the right way: it will fail
  loudly when someone fixes it.
- `transaction=True` is applied deliberately, with the reason stated at the
  point of use.
- The comment register is consistent and the `make vale` vocabulary holds
  throughout; several comments explain a design choice a reviewer would
  otherwise challenge (`models.py:781`, `migration 0041:11`,
  `views/reference_section.py:1`, `catalog_form.py:437`).

---

## Suggested order

1. **C1** and **C2** — reachable data bugs. C1 has two ready-made regression
   tests above, both of which fail today.
2. **C3** — one line.
3. **I1** — pick a side, then correct whichever comments lose.
4. **I2**, **I3**, **I4**.
5. **I5** — the migration harness already exists.
6. **I6**, **I7**.
7. Docs and comments in one sweep.
8. Re-run the full `make check`.

Not run: `code-simplifier`, which edits files.
