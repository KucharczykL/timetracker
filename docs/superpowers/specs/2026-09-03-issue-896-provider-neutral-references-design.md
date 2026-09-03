# A reference names a work, and a removed row lets go of its key

Issue [#896](https://github.com/KucharczykL/timetracker/issues/896) (CAT-07),
with [#976](https://github.com/KucharczykL/timetracker/issues/976). One section
states every external reference a record holds, and the key a removed record
claimed goes back to the pool.

## What is already here

[#652](https://github.com/KucharczykL/timetracker/issues/652) built the storage
and the service. `games/external_references.py` holds a policy per provider,
each with a key normalizer and a trusted HTTPS template, and it holds
`normalize_provider_key()`, `external_reference_url()`,
`save_external_reference()`, `resolve_external_reference()` and
`sync_game_wikidata()`. `ExternalReference` carries a `(provider, entity_kind,
provider_key)` tuple and exactly one of four target columns, and four
constraints hold that shape. Migration `0022_external_references` moved every
nonblank `Game.wikidata` value across and verified the move.

What #652 did not build is a way for a person to see or state one. The whole
user-facing surface today is:

- `GameForm.wikidata`, one text field over `Game.wikidata`, validated by
  `clean_wikidata()`, which normalizes the key and refuses one another Game
  holds;
- a `Wikidata` column on the games list, whose cell is the only place
  `external_reference_url()` is called in a view;
- `sync_game_wikidata()`, called by `catalog_submit.save_game_columns()`, which
  reads the column and writes the reference to match.

Nothing shows a reference on Game detail, on the platform list, or anywhere an
Edition or a Release is drawn. Nothing but the compatibility adapter writes one.

## What this specification does not do

The issue's boundary already refuses a public API, admin CRUD, bulk ingestion,
IGDB and Steam policies, helper routes and reconciliation. Two further
decisions narrow it, and each is recorded so that a later reader finds a verdict
rather than a gap.

**Edition and Release references are read-only.** The issue asks for add,
replace and remove on all four kinds. Neither an Edition nor a Release has a
route of its own, `ExternalReference` is the only inbound foreign key either one
has, and `docs/catalog.md` says on the page that the Editions section stands
until [#690](https://github.com/KucharczykL/timetracker/issues/690) replaces it.
No person types a Wikidata entity ID for a Release; the rows exist for
[#782](https://github.com/KucharczykL/timetracker/issues/782)'s importer to
write. So this issue builds the writer for all four kinds and hosts the editor
on the two records a person already edits — Game and Platform — and presents
Edition and Release references read-only, with their links. #782 owns the
producer that fills them, and #690 owns the section that will show them better.

**A provider key is unique across every library.** Two libraries cannot both
name `Q123`, because `unique_external_reference_provider_kind_key` spans the
table. That is #652's rule and this issue keeps it: the acceptance list asks for
the conflict to be reported rather than silently retargeted, which is what the
constraint plus a readable sentence gives. It is nonetheless a product
consequence worth naming — a shared catalog would let both libraries point at
one work, and a per-library catalog cannot. Identity reconciliation
([#654](https://github.com/KucharczykL/timetracker/issues/654),
[#785](https://github.com/KucharczykL/timetracker/issues/785)) owns the answer.
The verdict goes into #896 and into #601 beside this design.

## The policy grows a face

`ProviderPolicy` gains a `label` and a `hint`: the words a person reads beside
the key box, and the words that say what a valid key looks like. The Wikidata
policy reads `Wikidata` and `An entity ID such as Q123.`

`PROVIDER_POLICIES` becomes the one source of both. `ExternalReference.Provider`
keeps its `TextChoices` for the database column, and its human labels stop being
read anywhere: two places that name a provider is one too many, and the registry
is the one every new provider must touch anyway.

Registering a policy is then the whole UI cost of a provider. Nothing in a form,
a renderer or a template names `wikidata`.

Two check constraints still do. `external_reference_supported_provider` pins the
column to `wikidata` and `external_reference_canonical_provider_key` pins the
key to `^Q[1-9][0-9]*$`. Both are correct today and both are a migration a
second provider must write. This specification changes neither; it states the
bill so #782 is not surprised by it.

## One key per record, per provider

A Wikidata entity is an identity, not a tag. A Game holding two entity IDs is a
mistake nobody can resolve, and `Game.wikidata` would have no rule for which of
the two it mirrors. Nothing enforces this today: `sync_game_wikidata()` deletes
the extras it finds, which is the only reason the shape has held.

Four partial unique constraints state it, one per kind, each over `(provider,
<target column>)` and conditional on that column being set and the row being
live:

- `unique_live_game_reference_per_provider`
- `unique_live_edition_reference_per_provider`
- `unique_live_release_reference_per_provider`
- `unique_live_platform_reference_per_provider`

Four rather than one constraint over all five columns with `nulls_distinct =
False`. Postgres 18 would take the single one, but the check constraint
`external_reference_kind_matches_target` already enumerates the four kinds in
the same file, and a reader who has met that one reads these without a footnote
about how a unique index treats a null.

Each index is partial on its own target column, so each holds only the rows of
its kind.

With this rule the editor's shape follows: the rows a record can hold are
exactly the registered providers.

## The mark a reference carries

This is #976. `unique_external_reference_provider_kind_key` carries no
`removed_at` condition and the reference holds no mark, so a removed Game keeps
its Wikidata key. Entering that work again raises an `IntegrityError` from a row
the writer cannot see in any list. Every other uniqueness constraint a removal
must not hold is conditional, as `docs/event-retention.md` requires.

A partial index cannot read another table, so the mark has to sit on the
reference. `ExternalReference` gains a `removed_at`, nullable and not editable,
like the nine removable models carry. It stays out of `REMOVABLE_MODELS`: no
person removes a reference on its own, and `remove()` on one would be an act
with no verb. The mark is derived — it follows the row the reference points at.

`unique_external_reference_provider_kind_key` becomes conditional on it, and so
are the four constraints above.

`games/removal.py` writes it. `_AFTER_STAMP` today maps one model to one
callable and Game's slot is taken by `_recount_purchases`, so the values become
tuples, run in order. Game, Edition, Release and Platform each gain a hook that
reads `instance.removed_at` — which `_stamp` has already set — and writes the
same value onto every reference naming that row. Game's tuple runs the reference
hook, then the mirror described below, then `_recount_purchases`.

An Edition or a Release under a removed Game keeps its own mark, exactly as
`RemovableMixin.ancestor_marks` reads it: a removed Game hides its children
without stamping them, and their references are not stamped either. The
reference of a live Release under a removed Game therefore still claims its key.
That is consistent — nothing about that Release was removed, and restoring the
Game brings the whole subtree back unchanged. The defect #976 names is about the
row a person removed, and that row's own references let go.

## Restore takes back only the keys that are free

Between a removal and a restore, another record may enter the key. A restore
that re-claimed it would repeat the silent theft in the other direction, and a
restore that raised would surface as a traceback: `restore()` has no error
channel, and Trash and undo
([#695](https://github.com/KucharczykL/timetracker/issues/695),
[#795](https://github.com/KucharczykL/timetracker/issues/795)) do not exist yet.

So a restore clears the mark on every reference whose tuple no live row holds,
and leaves the rest marked. The record comes back without that one reference.

One statement does the check and the write, so no window opens between them:

```text
UPDATE the references naming this row
   SET removed_at = NULL
 WHERE removed_at IS NOT NULL
   AND NOT EXISTS (a live reference with the same provider, kind and key)
```

In Django that is `.filter(~Exists(...)).update(removed_at=None)`. A concurrent
writer that beats it raises `IntegrityError`, which is what a lost race deserves
and what the tests state.

## A set is stated, not patched row by row

`state_external_references()` joins `state_catalog_graph()` in
`games/external_references.py`, with the contract `docs/catalog.md` already
sets out for a graph:

- it takes one target and the keys that target should hold, as a mapping of
  provider to key, where an empty key means the record holds none;
- a provider the caller does not name is left alone, so a future importer that
  knows one provider cannot take another's row;
- removal is a mark on the row, never a destroying delete;
- every refusal is checked against the desired end state before anything is
  written, and each carries the provider that caused it, so a sentence reaches
  the box a person typed into;
- the whole set is one transaction.

It refuses, each with one sentence a person can read, held as a module constant
so a screen and a test name the same words:

- a **shared** target — `library IS NULL` on the Game or the Platform, or on a
  Release's Edition's Game;
- a target of **another library**;
- a **removed** target, which goes back first;
- a key another record holds, live — the conflict the acceptance list requires
  be reported without retargeting.

`save_external_reference()` stays as the single-tuple writer beneath it, and
grows one change: it looks for the tuple among live rows only. A key a marked
row holds is free, so the writer makes a new live row and leaves the marked one
as it is. The two never collide, because the constraint reads live rows alone,
and the restore rule above then finds the tuple taken and leaves the marked row
marked. That is one rule read from two ends.

## The two forms that host it

`games/reference_form.py` holds `ReferenceSetForm`: one `CharField` per
registered provider, named `reference_<provider>`, labelled from the policy's
`label`, helped by its `hint`, required never. It is built from
`PROVIDER_POLICIES` at instance time, so a registered provider is a field with
no other edit. The provider itself rides as a hidden input beside the key rather
than as a select: with one key per record per provider the row set is the
registry, and a control a person cannot change is noise.

`clean_reference_<provider>` runs the policy's normalizer, so the policy's own
sentence — `Enter a Wikidata entity ID such as Q123.` — lands on the box that
holds the malformed key. A blank box states that the record holds no reference
from that provider, and the set form asks the service to remove one that is
there.

`answer(refusal)` puts a service sentence on the field its provider names, and a
refusal naming no provider on the form's non-field errors, mirroring
`CatalogGraphForm.answer()`.

`games/views/reference_section.py` renders it: one labelled row per field, its
errors beneath, inside the same block idiom `catalog_section.py` uses. No add
button, no count field, no clone template and no custom element — the rows are
the registry and the registry does not change while a page is open.

**Add and Edit Game.** The area is drawn under the Editions area.
`catalog_submit.save_game_and_graph()` writes the reference set inside the
transaction it already opens, after the graph, so a refused key leaves no Game
behind. `submitted_game_or_form_error()` hands a refusal to the set form's
`answer()` alongside the graph's. `GameForm` loses the `wikidata` field, its
`Meta.fields` entry and `clean_wikidata()`; `_game_form_refusal()` loses its
`provider_key` branch and `WIKIDATA_CONFLICT_MESSAGE` moves into the reference
module as the conflict sentence for every provider.

**Add and Edit Platform.** The same area under `PlatformForm`.
`edit_platform()` already resolves through `Platform.objects.for_library()`, so
a shared platform answers 404 and the read-only rule holds with no new guard.
The two views gain the two-form submit shape `add_game()` and `edit_game()`
already carry — both forms read, then one call writes both — through a small
shared helper in the reference module rather than a second copy of
`catalog_submit`.

## The column becomes the mirror

`sync_game_wikidata()` reads `Game.wikidata` and writes the reference. That
direction has to invert: the reference is what a person now states, and the
column is what filters, sorting, the games list, the API and the sample fixture
still read until [#889](https://github.com/KucharczykL/timetracker/issues/889)
takes it.

`mirror_game_wikidata(game)` replaces it. It reads the live Wikidata reference
naming that Game and writes its key into `Game.wikidata`, or the empty string
where there is none, with an `UPDATE` rather than a `save()` — the same shape
`mirror_legacy_columns()` uses for `Game.platform` and `Game.year_released`, and
for the same reason. It is called inside the write transaction, after the
reference set is stated, and again from Game's `_AFTER_STAMP` tuple on restore,
where a reference that could not take its key back must not leave the column
naming it.

`Game.wikidata` keeps its value while the Game is removed. Nothing live reads a
removed Game's column, and rewriting it on removal would lose the value a
restore wants.

Neither the filter field, the sort key, nor the games-list column changes. That
is the stability the acceptance list asks for, and it is why the mirror is worth
keeping for one more issue.

## What a reader sees

One component, `ExternalReferenceLinks(references)`, in
`common/components/domain.py`. It renders each reference as the provider's label
and its key, wrapped in a link whose `href` comes only from
`external_reference_url()`. Three layers keep it safe, and each is tested: the
database refuses a key the canonical regular expression does not match, the
policy template is the only source of a URL and quotes the key it interpolates,
and the node layer escapes every attribute value it writes.

- **Game detail** gains a `References` metadata row in `_game_header()`, beside
  Original release and Status. Today the page shows no reference at all.
- **Game detail, Editions section** gains a `References` column, holding an
  Edition's own references and its Releases'. This is the only place either can
  ever be read.
- **The platform list** gains a `References` column. Platforms have no detail
  page.
- **The games list** is untouched, still reading `Game.wikidata`.

A read helper, `references_for(targets)`, takes the rows a page draws and
returns their live references in one query, so no surface pays per row.

## What a constraint says

`catalog_submit.CONSTRAINT_ANSWERS` and `UNREACHABLE_FROM_THE_GAME_FORM` are
read by a guard test that fails unless every unique constraint on Game, Edition,
Release and ExternalReference is either mapped to a sentence or named as out of
reach with a reason. Five constraints change or arrive here, so five entries
follow: the conditional tuple constraint keeps its existing note, and each of
the four per-provider constraints is named unreachable, because the set form
refuses a second key for one provider before a post reaches the database.

## Migration, and what a rollback costs

One migration, `games/migrations/00NN_external_reference_marks.py`:

1. add `removed_at`, nullable, default `None`;
2. stamp the references whose target row is removed, in batches keyed by
   `keyset_pages()` — never `iterator()`;
3. resolve any record already holding two live keys from one provider before the
   new constraints are added. Deterministic rule: for a Game, the reference
   whose key equals `Game.wikidata` stays and the rest are stamped; where the
   column names none of them, the lowest `id` stays, which is the earliest,
   because the primary key is a UUIDv7. Every other kind has no column to
   consult, so the lowest `id` stays there too. The count of stamped rows is
   reported the way `0022_external_references` reports its own work;
4. alter `unique_external_reference_provider_kind_key` to carry the condition;
5. add the four per-provider constraints.

Step 3 should find nothing. `sync_game_wikidata()` has been removing the extras,
and only a direct service call could have made one. It runs anyway, because a
migration that assumes a shape it can check is a migration that fails on the one
database that broke it.

The migration is reversible. Reversing it drops the four constraints, lifts the
condition and drops the column; a reference stamped in step 2 then claims its
key again, which is the state before this issue. Nothing is destroyed either
way, and no row's tuple changes.

The rollback of the code is a revert. The mirror runs both ways over one issue's
life: before this change `sync_game_wikidata()` keeps the reference true to the
column, after it `mirror_game_wikidata()` keeps the column true to the
reference, and the two agree on every row at every point, which is what makes
the revert safe.

## Parity evidence

Three claims are measured rather than argued.

1. **Every nonblank `Game.wikidata` still resolves.** A test walks every Game in
   the sample fixture and asserts the column equals the key of its live Wikidata
   reference, and that a blank column has no live reference. This is the
   acceptance line about equivalence through the compatibility adapter, and it
   holds against the anonymized production snapshot rather than a handful of
   built rows.
2. **The URLs a page emits are unchanged.** The games-list cell keeps its
   current markup, and `Q123` still reaches
   `https://www.wikidata.org/wiki/Q123`.
3. **The filter, the sort and the API answer the same.** `wikidata` stays a
   `StringCriterion` on `GameFilter` and a `SortSpec`, and no API schema names a
   reference. A test asserts the filter's result set over the fixture is
   identical before and after.

## Tests

Extending `tests/test_external_references.py`: the mark, the conditional
constraints, the four per-provider constraints, the set writer's contract and
each of its four refusals, the restore rule and the race that loses.

New `tests/test_reference_form.py`: the fields the registry builds, the
normalizer's sentence landing on its own box, a blank box removing a reference,
a conflict answering onto the box, and both hosting forms writing in one
transaction with the graph and the columns.

New `tests/test_reference_removal.py`: #976 end to end — remove a Game, enter
its key on a second Game, restore the first, and read what each holds.

Isolation: two libraries, each with a Game; the second cannot state the first's
key, cannot see it in any list, and cannot reach it through a shared Platform.

Safety: a key that would escape its attribute cannot be stored, cannot be
rendered, and cannot select a URL other than its policy's.

Accessibility: every key box has a label the accessibility tree exposes, every
error is tied to its field, and a link states which provider it goes to rather
than reading as a bare identifier.

An e2e case walks Add Game with a key, Edit Game changing it, and Edit Game
clearing it, reading the database only after the server-rendered page returns.

## Files, and the re-slice guard

Touched: `games/models.py`, one migration, `games/external_references.py`,
`games/removal.py`, `games/forms.py`, `games/catalog_submit.py`,
`games/reference_form.py` (new), `games/views/reference_section.py` (new),
`games/views/game.py`, `games/views/platform.py`,
`common/components/domain.py`, a reads helper, `docs/catalog.md`,
`docs/event-retention.md`, and six test modules. Around twenty files, three
runtime subsystems — catalog writes, forms and rendering, removal — and well
under two thousand non-generated lines.

The forecast does not cross the guard, and no re-slice is needed beyond the two
narrowings recorded above.
