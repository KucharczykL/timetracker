# Game kind and parent, Edition kind — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Game.kind`/`Game.parent` and `Edition.kind`: columns, rules, forms, Game detail, the Games list's base, facet and column, and the links into it.

**Architecture:** Two conventional catalog columns on `Game` and one on `Edition`, no events. One request-free rule module, `games/catalog_addons.py`, which the Game form's save and later P4 both call. One read, `games/reads/games_list.py`, gives the list, its bulk scope and the builder's count a single base.

**Tech stack:** Django 6, PostgreSQL 18, Python component system, TypeScript custom elements, pytest and Playwright.

**Spec:** [docs/superpowers/specs/2026-09-30-issue-1353-game-kind-and-parent-design.md](../specs/2026-09-30-issue-1353-game-kind-and-parent-design.md). Read it first; this plan names the work and does not restate its rules.

## Global constraints

- Drive everything through `make`. Wrap every pytest target in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …`,
  because other worktrees are running suites.
- Before each commit, run `make format`, `make lint-fix` and `make vale`.
- Words: `GameKind` = `main`/`dlc`/`expansion`/`standalone_expansion`; `EditionKind` = `full`/`prerelease`. "Add-on" is the person's word for any Game whose kind is not `main`.
- Refusal sentences are module constants. Tests assert them by name, never by copy.
- UI uses only the library kit's shapes (`SummaryList`, `SummaryRow`, `Chip`, `SECTION_SURFACE_CLASS`). It was approved from mockups on 2026-09-30; do not invent markup.
- Complete-word identifiers. Comments explain intent only, never history or issue numbers.
- A focused run is for iterating. The gate is the full `make check`, run once at the end (Task 7).

---

### Task 0: Rebase

- [ ] `git fetch origin && git rebase origin/main`. If M8 (#1334) landed a `0024`, this issue's migration takes the next number.

### Task 1: Schema

**Files:**
- Modify: `games/models.py` (`Game`, `Edition`, new `GameKind`, `EditionKind`, `ADDON_KINDS`)
- Create: `games/migrations/0024_game_kind_parent_edition_kind.py` (through `make makemigrations ARGS="games --name game_kind_parent_edition_kind"`)
- Modify: `games/catalog_submit.py` (`UNREACHABLE_FROM_THE_GAME_FORM`)
- Modify: `games/management/commands/audit_library_ownership.py` (a `Game.parent` loop beside `Game.platform`)
- Test: new `tests/test_game_kind_schema.py`; `tests/test_catalog_submit.py` (the constraint guard)

**Interfaces:**
- Produces:
  - `GameKind(TextChoices)` and `EditionKind(TextChoices)`, with the labels the spec's Words table gives.
  - `ADDON_KINDS: Final[frozenset[GameKind]]`.
  - `Game.kind`, `Game.parent` (`related_name="+"`, `RESTRICT`) and `Edition.kind`.
  - The `CHECK` names `game_kind_word`, `game_parent_exactly_for_addons`, `game_not_its_own_parent` and `edition_kind_word`.

**Tests:**
- Each `CHECK` raises `IntegrityError` through `Game.objects.filter(pk=…).update(…)`. Use `update`: `save()` runs `clean()`.
- A fresh `Game` reads `main`, and a fresh `Edition` reads `full`.
- `audit_library_ownership` reports a private Game whose parent is another library's private Game. It also reports a shared Game whose parent is private.
- `purge_user_library` removes a library holding a private add-on and its private parent. This proves the spec's `RESTRICT` claim by running it.
- The guard walks `CheckConstraint` as well as `UniqueConstraint`. It finds the four new names in `UNREACHABLE_FROM_THE_GAME_FORM`, with the reason "`state_addon` refuses first".

**Gotchas:**
- `Game.Meta.constraints` is a tuple of `UniqueConstraint`s. Append the three `CheckConstraint`s there, not in a second `Meta`: an abstract base's constraints would be shadowed.
- `makemigrations` runs with `--noinput`. Check the file has no data step: the defaults cover existing rows.

- [ ] Write the failing tests
- [ ] Add the columns and constraints, then make the migration
- [ ] `flock … make test ARGS="tests/test_game_kind_schema.py tests/test_catalog_submit.py -x"` passes
- [ ] Commit `feat: Game kind and parent, Edition kind columns (#1353)`

### Task 2: The add-on rules

**Files:**
- Create: `games/catalog_addons.py`
- Test: new `tests/test_catalog_addons.py`

**Interfaces:**
- Produces:
  - `state_addon(game: Game, *, kind: GameKind, parent: Game | None, library: UserLibrary) -> None`
  - `class AddonRefused(ValidationError)`, carrying `.field: Literal["kind", "parent"]`
  - Sentence constants, one per rule: `PARENT_ON_MAIN`, `ADDON_WITHOUT_PARENT`, `OWN_PARENT`, `FOREIGN_PARENT`, `REMOVED_PARENT`, `PARENT_NOT_MAIN`, and `HAS_ADDONS` (a format string holding the count).

**Behaviour** (spec, "The add-on rules"):
- It refuses outside a transaction: `transaction.get_connection().in_atomic_block` must be true.
- It locks the Game (when persisted) and the parent with `Game.objects.select_for_update().filter(pk__in=…).order_by("pk")`.
- It checks the rules in order 1–7, stopping at the first that refuses.
- Rule 4 reads the parent's `library_id` off the row, never `visible_to`.
- Rule 5 compares the new parent against the stored `parent_id`.
- Rule 7 counts `Game.objects.filter(parent=game)` on the plain manager, so removed add-ons count.
- On success it sets `game.kind` and `game.parent` and does not save.

**Tests:**
- One refusal per rule, each asserting the sentence constant and `.field`.
- The Game's own key as parent is refused by rule 3, and the Game's other state is not touched.
- An add-on whose stored parent was removed later passes when restated unchanged.
- Naming a newly removed parent is refused.
- `main` → `dlc` is refused while a removed add-on names the Game.
- An add-on → `main` with `parent=None` passes.
- A shared parent passes.
- A call outside `atomic` raises.

- [ ] Write the failing tests
- [ ] Implement
- [ ] Run the focused tests and see them pass
- [ ] Commit `feat: the add-on rules (#1353)`

### Task 3: Game form, search and `<game-addon>`

**Files:**
- Modify:
  - `games/forms.py` (`GameForm`: `kind`, `parent`, initials)
  - `games/catalog_submit.py` (`save_game_columns` calls `state_addon`; `_game_form_refusal` answers `AddonRefused` onto `.field`)
  - `games/api.py` (`search_games` gains `kind: GameKind | None = None`)
  - `games/views/game.py` (`add_game`/`edit_game` render `GameAddon` after `FormFields`)
- Create:
  - `common/components/game_addon.py` (`GameAddon()` over `custom_element`, with a `register_element` TypedDict)
  - `ts/elements/game-addon.ts` and `ts/elements/game-addon.test.ts`
- Test: `tests/test_catalog_submit.py`, `tests/test_game_form_addons.py` (new), `tests/test_search_select.py` or a new games-search API test, and `e2e/test_game_form_catalog_e2e.py`

**Interfaces:**
- Consumes: `state_addon` and `AddonRefused` from Task 2.
- Produces: `GameAddon(kind_field: str, parent_field: str) -> Node`, whose props are `{kindField, parentField}`. It is regenerated by `make gen-element-types`.

**Gotchas:**
- `kind` is `required=False`, and an empty value cleans to `GameKind.MAIN`. The existing test POSTs name no kind; spec finding 1 explains why that matters.
- The `parent` queryset is `Game.objects.visible_to(library)`, OR the stored parent by key. Both initials are set by hand beside `original_release_date`'s (`games/forms.py` `__init__`).
- The widget is `SearchSelectWidget` with `params={"kind": {"value": "main"}}` and an `options_resolver` labelling a stored parent (see `games/forms.py:427-434`).
- `save_game_columns` already holds `select_for_update` on the persisted Game. Take that lock through `state_addon`'s single ordered lock, so the order stays by key. For a new Game, lock the parent only.
- `<game-addon>` finds `closest("form")`. It hides `[data-field-row="<parentField>"]` while the kind select reads `main`, and clears the parent's SearchSelect by dispatching its clear rather than editing its inputs. It is a `ModuleScript` declared through `Media`.

**Tests:**
- Add Game states a DLC with a parent, and the row reads `dlc` and the parent.
- Each `AddonRefused` lands on its field with its sentence, and nothing is saved.
- Edit Game resubmitted untouched keeps a DLC's kind and parent.
- A POST naming no kind saves `main`.
- Edit of an add-on whose parent was removed later saves.
- `GET /api/games/search?kind=main` excludes add-ons. `kind=bogus` answers 422.
- vitest: the element hides the row on `main`, shows it otherwise, and clears on hide.
- e2e: pick DLC and a parent, save, and land on the page (Task 5's row is checked there). Wait on the redirected page before any ORM read.

- [ ] Write the failing tests
- [ ] Implement the form, the submit, the API, the element, then run `make ts`
- [ ] `flock … make test ARGS="tests/test_game_form_addons.py tests/test_catalog_submit.py -x"`, `make test-ts TS_ARGS="ts/elements/game-addon.test.ts"`, and `flock … make test-e2e ARGS="-k catalog"` all pass
- [ ] Commit `feat: state a game's kind and parent on the Game form (#1353)`

### Task 4: Edition kind through the graph

**Files:**
- Modify:
  - `games/catalog_writes.py` (`EditionState.kind`; `_written_edition` create and `update_fields`)
  - `games/catalog_form.py` (`EditionRowForm.kind`; the `_blocks_from_storage` initial; `_states()`)
  - `games/views/catalog_section.py` (the Edition block renders `kind` beside `_name_row`)
  - `games/reads/releases.py` (`edition_words`, read by `release_label`)
  - `games/views/library_cards.py` (`release_words` reads `edition_words`)
  - `games/views/game.py` (`_reads_plainly` counts a prerelease Edition as breaking the plain shape; a `Chip("Prerelease")` goes in the Releases table's Name cell)
- Test: `tests/test_state_catalog_graph.py`, `tests/test_catalog_graph_form.py`, `tests/test_catalog_hierarchy.py`, and `tests/test_release_api.py` (label)

**Interfaces:**
- Produces: `edition_words(edition: Edition) -> str`. It returns the Edition's name, else `"Prerelease"` for a prerelease Edition, else `""`.

**Tests:**
- Kind round-trips from post to row to form initial.
- A kind change alone writes.
- A shared Game's graph (kind included) is refused with `SHARED_GAME`.
- `release_label` reads "PC · Prerelease" for an unnamed prerelease Edition, and `release_words` groups it apart from the full Edition's copy.
- A lone prerelease Edition brings the Releases section, and its Name cell holds the chip.

- [ ] Write the failing tests
- [ ] Implement
- [ ] Run the focused tests (plus `e2e/test_game_form_catalog_e2e.py`, since the Edition row changed)
- [ ] Commit `feat: an Edition states full or prerelease (#1353)`

### Task 5: Game detail

**Files:**
- Modify:
  - `games/reads/catalog_hierarchy.py` (`tracked_addons`)
  - `games/views/game.py` (a `_parent_row` in `_game_header` metadata above Original release; an `_addons_section` after `_library_section` in `view_game`)
- Test: new `tests/test_game_detail_addons.py`; extend the e2e from Task 3

**Interfaces:**
- Produces: `tracked_addons(library: UserLibrary, game: Game) -> QuerySet[Game]`. It reads `Game.objects.tracked_by(library).filter(parent=game)`, ordered by `sort_name`, `name`, `pk`, and carries `tracked_status`.

**Behaviour:** `_parent_row(game, library)`:
- A parent the library tracks is linked with `get_absolute_url()`.
- A shared parent the library does not track is plain text.
- A removed parent reads "(removed)". Resolve it on the plain manager, because `visible_to` hides it.
- A kind `Chip` sits beside the name.

The Add-ons section:
- `_game_section("Add-ons", count, SummaryList(*rows), …, surface=True)`.
- Rows are dense `SummaryRow(label="", subtitle=Fragment(link, Chip(kind label), status word))`.
- When no rows exist, the section returns nothing.

**Tests:**
- The parent row in each of its three states.
- The Add-ons section lists only tracked add-ons (an untracked shared DLC is absent) and is absent on a Game with none.
- A shared add-on's page shows its row read-only.

- [ ] Write the failing tests
- [ ] Implement
- [ ] Run the focused tests
- [ ] Commit `feat: Game detail links an add-on and lists a game's add-ons (#1353)`

### Task 6: The Games list's base, filter, facet, column and links

**Files:**
- Create: `games/reads/games_list.py`
- Modify:
  - `games/filters.py` (`GameFilter.kind`, `.parent`, the `FilterField`s, `names_addon_fields()`, `every_kind()`, the `narrowing()`/`_states_a_leaf` skip, and `filter_queryset_for_library(model_name, library, game_filter=None)`)
  - `games/api.py` (`filter_count` passes the parsed filter)
  - `games/views/game.py` (`games_for_list` reads the base; a Kind column after Status, `hidden_by_default=True`, whose cell is the label)
  - `games/bulk_games.py` (`game_scope`)
  - `common/components/quick_filter.py` (`QuickFacet("kind")` after `format`)
  - `games/views/stats_links.py` (`games_played` and `games_in_month` state `every_kind()`)
  - `games/views/library.py` (the three `games:list_games` links carry the filter URL with `every_kind()`)
- Test: new `tests/test_games_list_kind.py`; `tests/test_stats_links.py` (the parity world gains a tracked `dlc` with a session and a record in `YEAR`); `tests/test_library_page_isolation.py` or the Library page's test

**Interfaces:**
- Produces:
  - `games_list_base(library: UserLibrary, game_filter: GameFilter | None) -> QuerySet[Game]`. It is `tracked_by(library)`, plus `.filter(kind=GameKind.MAIN)` unless `game_filter` names add-on fields.
  - `GameFilter.names_addon_fields() -> bool`. It walks `AND`/`OR`/`NOT` and reads `kind`/`parent` leaves and `field_comparisons` naming either.
  - `GameFilter.every_kind() -> GameFilter`, a classmethod: `kind` INCLUDES every `GameKind`.

**Gotchas:**
- `filter_queryset_for_library` is imported lazily in places; keep its two-argument calls working (`None` means the main-only base).
- The stats links are `OR` trees. A node ORs its `OR` members with its own leaves, so a top-level `kind` beside `OR` matches every game. Put the `kind` leaf on each member. The `narrowing()` skip is what keeps its sessions and records.
- The Library page count is `for_library`, and the link carries every kind. Do not change the figure.

**Tests:**
- The list hides a tracked DLC by default, and shows it under a `kind` leaf, under `NOT {kind: dlc}`, under `parent`, and under an `OR` member naming `kind`.
- `game_scope` and `/api/filter/count` both equal the list's count, with and without the leaf.
- `games_played(YEAR).narrowing()` still states sessions and records.
- Parity counts, including the DLC.
- The Kind facet renders, and the Kind column is hidden by default and toggleable.
- Every Library page link carries the clause.

- [ ] Write the failing tests
- [ ] Implement
- [ ] Run the focused tests, plus `tests/test_stats_links.py`, `tests/test_column_narrowing.py`, `tests/test_filters.py -k game`, and `e2e -k games_list`
- [ ] Commit `feat: the Games list lists main games until a filter names kind or parent (#1353)`

### Task 7: Docs, gate, render-pages, PR

- [ ] `CLAUDE.md`:
  - Models: a **Game** line naming `kind`/`parent`, `games/catalog_addons.py` and the list base. An Edition line on `kind`.
  - Filter system: `names_addon_fields` and `every_kind`.
- [ ] `docs/catalog.md`: the add-on rules (short), Edition kind, and the Add-ons section beside "What Game detail shows".
- [ ] Run `flock … make check`, reading the exit code from a log rather than grepping.
- [ ] Run `make render-pages` at `origin/main` and at HEAD on the newest dump (`make restore-dump`), then `diff -r`. Attribute every difference against the spec's Tests list. No add-on or prerelease row may appear.
- [ ] Push and open a PR against `main` that carries the spec and plan, closes #1353, and lists the render-pages attribution.

## Follow-up issues to file

None new: the Library tab's Game cell telling a demo apart is #1383's, the anonymizer's `RESTRICT` order is P4's (#723), and a shared Game's writes are #782's.
