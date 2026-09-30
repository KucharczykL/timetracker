# Game kind and parent, Edition kind

Issue: [#1353](https://github.com/KucharczykL/timetracker/issues/1353), member M7 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [Catalog identity](2026-08-09-timetracker-overhaul-design.md#catalog-identity).
Builds on: [Catalog](../../catalog.md), [The Library screens](2026-09-29-issue-1352-library-screens-design.md).

The wave doc is the contract; where it is silent, the wave organizer ruled
(2026-09-30), and those rulings are recorded here and in the wave doc (PR
#1388). The UI below was approved from mockups on 2026-09-30.

## Outcome

A Game states what kind of work it is and, for an add-on, the Game it
belongs to. An Edition states whether it is the full game or a prerelease
(a demo, a beta, an alpha, a network test, a playtest, a stress test; its
name says which). Nothing converts data: every existing Game reads `main`,
every existing Edition `full`. P4 (#723) states the 35 private DLC Games
through the function this issue adds.

## Words

| Column | Words (value, label) | Default |
|---|---|---|
| `Game.kind` | `main` Main game, `dlc` DLC, `expansion` Expansion, `standalone_expansion` Standalone expansion | `main` |
| `Edition.kind` | `full` Full, `prerelease` Prerelease | `full` |

`GameKind` and `EditionKind` are `TextChoices` in `games/models.py`. The
Game words are IGDB's `game_type` words; #782 admits the rest (remake,
remaster, port, …) when it meets them, one to one. Early Access is `full`.
"Add-on" is the person's word for any Game whose kind is not `main`;
`ADDON_KINDS` names the three.

## Storage

Migration `0024` (renumbered if M8 lands first):

- `Game.kind`: `CharField(max_length=20, choices=GameKind, default="main")`.
- `Game.parent`: `ForeignKey("self", on_delete=RESTRICT, null=True,
  blank=True, related_name="+")`. No reverse accessor: a shared Game's
  accessor would reach every library's add-ons, as `game_hierarchy`
  already avoids.
- `Edition.kind`: `CharField(max_length=20, choices=EditionKind, default="full")`.
- `CHECK`s: `game_kind_word` (kind in the four), `game_parent_exactly_for_addons`
  (`kind = 'main'` ⇔ `parent IS NULL`), `game_not_its_own_parent`
  (`parent <> id`), `edition_kind_word` (kind in the two).

The database admits a superset of what the rules below admit: a parent that
is itself an add-on, a foreign parent and a removed one pass the `CHECK`s and
are refused in Python, where a sentence can name the move.
`RESTRICT` guards the delete nobody calls; a whole-library purge deletes a
private add-on and its private parent in one collector pass.
`audit_library_ownership` gains `Game.parent`: a private Game whose parent
is another library's private Game is a violation, as `Game.platform` is.

## The lineage rules

`games/catalog_lineage.py`, request-free, one entry point:

```text
state_lineage(game, *, kind, parent, library) -> None
```

It sets `game.kind` and `game.parent` or raises `LineageRefused`, a
`ValidationError` carrying the field it belongs to (`kind` or `parent`) and
one sentence, a module constant. It locks the parent row and, where the
Game is persisted, reads the stored row under the lock `save_game_columns`
already holds. Rules, in order:

1. `main` with a parent: refused on `parent` ("A main game has no parent.
   Choose an add-on kind or clear the parent.").
2. An add-on kind with no parent: refused on `parent` ("An add-on names the
   game it belongs to.").
3. The parent is the Game itself: refused on `parent`.
4. The parent is not visible to the library (another library's private
   Game): refused on `parent`.
5. The parent is removed and differs from the stored parent: refused on
   `parent` ("That game is removed. Put it back before you name it."). An
   unchanged removed parent passes, so an add-on whose parent was removed
   later stays editable.
6. The parent's kind is not `main`: refused on `parent` ("An add-on belongs
   to a main game."). IGDB has no add-on of an add-on.
7. A stored `main` Game becoming an add-on while live add-ons name it:
   refused on `kind`, the sentence counting them. With rule 6 this closes
   the invariant from both sides; both lock the parent row, so a concurrent
   pair serialises.

`save_game_columns` calls it before `game.save()`, and `_game_form_refusal`
answers a `LineageRefused` onto its field. P4 calls `state_lineage` and
`state_catalog_graph` with no form (see Limits).

A removed parent does not cascade: the add-on keeps its key and reads the
parent as removed.

## Edition kind

`EditionState` gains `kind: EditionKind = EditionKind.FULL`;
`state_catalog_graph` writes it on create and on change like `name`.
`EditionRowForm` gains a `kind` `ChoiceField` beside the name, read from
storage and written through `_states()`. A shared Edition's kind is
read-only, as its name is. No rule couples an Edition's kind to anything:
a Game may hold only prerelease Editions (a demo nobody bought the game
after).

## Forms

`GameForm` (private Games only; `edit_game` resolves through
`for_library`, so a shared Game never reaches it) gains, after `sort_name`:

- `kind`, a `ChoiceField` over `GameKind`, initial `main`.
- `parent`, a `ModelChoiceField` whose queryset is `visible_to(library)`
  plus the stored parent, so an add-on whose parent was removed later
  resubmits. Widget: `SearchSelectWidget` over `GET /api/games/search` with
  `params={"kind": "main"}`. The search route gains an optional `kind`
  parameter (one of `GameKind`, else 422).
- A `<game-lineage>` custom element (`ts/elements/game-lineage.ts`) wraps
  the two rows and hides the parent row while kind is `main`, clearing its
  value on hide. With scripting off both rows show and the rules answer.

Both fields are form fields the form does not save through `Meta.fields`;
`save_game_columns` hands them to `state_lineage`.

## Reads and screens

**Game detail, an add-on.** One meta row above Original release: "Add-on
of", the parent's name linked to its page and a `Chip` naming the kind. A
removed or otherwise invisible parent renders its name with "(removed)"
and no link. A shared Game shows the same row, read-only by construction.

**Game detail, a main game.** An Add-ons section after Library:
`_game_section` on `SECTION_SURFACE_CLASS`, a `SummaryList` of
`SummaryRow`s, each the add-on's name linked, a kind `Chip`, and its
status word. It lists only add-ons the library tracks (charter: "already
added"), through `tracked_addons(library, game)` in
`games/reads/catalog_hierarchy.py`, ordered by `sort_name`, `name`, key.
No rows: the section renders nothing. No Add button.

**Game detail, Releases.** A prerelease Edition breaks the plain shape
(`_reads_plainly`), and its block heading carries a "Prerelease" `Chip`.
Release pickers need nothing: `release_label` already prints the
Edition's name ("PC · Demo · 2024").

**Games list.** The base is main games unless the filter names `kind` or
`parent` in any leaf of its tree, `NOT` included
(`GameFilter.names_lineage()`); then it is every kind and the filter
narrows. One function, `games_list_base(library, game_filter)` in a new
`games/reads/games_list.py` (the bulk act imports no view), states it, and `games_for_list` and
`bulk_games.game_scope` both read it, so a tray's "every matching row"
acts on what the list shows. `game_edit_resolution` takes keys and is
untouched. A Kind column (the label) after Status, `hidden_by_default`.
A Kind quick facet after Format.

**Links into the Games list.** Any link into the Games list whose figure
counts every kind states `kind` INCLUDES every word, through
`GameFilter.every_kind()`: `stats_links.games_played`, `games_in_month`,
and the Library page's Games count (`games/views/library.py`). The stats
link parity test reads the link through `games_list_base`, so it holds
the rule and P5's new links inherit it. The applied dot on the Kind facet
says why the list shows add-ons.

**Filters.** `GameFilter` gains `kind` (`ChoiceCriterion`, choices
`GameKind`) and `parent` (`UUIDMultiCriterion`,
`FilterField("parent__id", search_url="/api/games/search")`). Both reach
the nested builder with no further work; `kind` is quick-editable.

## Tests

- Model: the four `CHECK`s refuse through the ORM with `IntegrityError`;
  defaults read `main`/`full` on a fresh row.
- `catalog_lineage`: each rule's refusal and field; the unchanged removed
  parent passes; `main` → add-on with a removed add-on naming it passes;
  add-on → `main` clears the parent.
- Form and view: Add Game and Edit Game state a DLC with a parent; each
  refusal lands on its field; a shared Game has no edit route (existing
  404) and its kind/parent render.
- Graph: an Edition's kind round-trips through `CatalogGraphForm` and
  `state_catalog_graph`; a shared Edition's kind is refused like its name.
- Search: `kind=main` narrows; an unknown word is 422.
- Game detail: the "Add-on of" row, linked and removed; the Add-ons
  section lists tracked add-ons only and is absent when empty; the
  Prerelease chip and the broken plain shape.
- Games list: add-ons absent by default; present under a `kind` leaf,
  under `NOT kind`, under `parent`; the bulk scope matches the list; the
  Kind column and facet.
- Links: `every_kind()` on the three links; parity through
  `games_list_base`.
- Audit: a foreign parent is reported.
- Purge: `purge_user_library` removes a library holding a private add-on
  and its private parent (the `RESTRICT` claim above, run rather than
  reasoned).
- e2e: `<game-lineage>` hides and clears the parent row; picking a parent
  and saving lands on the add-on's page with the row.

`make render-pages` at both commits on one dump: the diff is the new
columns' absence on every page (all `main`/`full`), attributed.

## Limits

- **P4 calls `games/catalog_lineage.state_lineage`** and
  `games/catalog_writes.state_catalog_graph` with no form to state the 35
  DLC Games (kind `dlc`, the base Game as parent). Neither takes a form.
- A shared Game's kind and parent have no write path until #782's
  importer.
- The Games list hides add-ons as rows; the charter's "beneath its parent"
  is Game detail's Add-ons section. Nesting add-ons under their parent in
  the list is not in this issue.
- Hiding prerelease play is #1361, after #1354. The backlog (P5) and
  Before start (#1358) read `Edition.kind`; nothing in M7 does.
- #1383 redraws Game detail after this issue and P5; the sections here
  take the library kit's shapes and invent no markup.
