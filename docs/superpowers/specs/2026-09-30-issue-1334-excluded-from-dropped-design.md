# Excluded from dropped figures

Issue [#1334](https://github.com/KucharczykL/timetracker/issues/1334), member
M8 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## Rule

No fact stated for one figure decides another. `excluded_from_unfinished`
leaves a game out of the unfinished figures only. `excluded_from_dropped`
leaves a game out of the dropped figures only.

## The fact

- `PlayerGame.excluded_from_dropped`, `BooleanField(default=False)`, in a
  migration of its own. No backfill (see Decisions). P4
  states it beside `excluded_from_unfinished` on every game with an infinite
  purchase.
- Event `library.playergame.excluded_from_dropped_changed`, payload
  `{"excluded_from_dropped": bool}`, strict schema, sibling of
  `excluded_from_unfinished_changed`. Projector `PlayerGames` amends the column.
- `RecordPlayerGameFacts` gains a fourth `bool | None` field. Event order:
  status, mastered, unfinished, dropped. `None` for all four is refused at
  construction.
- `FINGERPRINT_VERSION` becomes 3: the field set is part of each digest.
- `record_facts`, `record_facts_for_request` take the fourth fact.
- `BatchFactChanges` reads the fourth fact, so the bulk Edit Undo restores it.
- `PINNED_DEFAULTS["games.PlayerGame"]` (`tests/test_projection_model.py`)
  gains `excluded_from_dropped: False`.
- `create_tracked_game` (`tests/tracked_games.py`, `e2e/tracked_games.py`)
  takes `excluded_from_dropped`.

## Statistics

`compute_stats` leaves a purchase out of `unfinished` when one of its games
states `excluded_from_unfinished`, and out of `dropped` when one of its games
states `excluded_from_dropped`. `dropped_percentage` follows `dropped_count`.
`stats_links._holding_no_excluded_game(field)` takes the fact name, and
`purchases_dropped` / `purchases_unfinished` each name their own. The parity
test covers both facts, each moving its own figure and not the other.

## Filter, list, sort

- `GameFilter.excluded_from_dropped`, a `BoolCriterion` over
  `tracked__excluded_from_dropped`, `metadata_lookup`
  `player_games__excluded_from_dropped`.
- `tracked_by` annotates `tracked_excluded_from_dropped`; the `Game`
  TYPE_CHECKING annotations gain it.
- `GAME_SORTS["dropped_figures"]`.
- Games list column "Dropped figures", key `dropped_figures`, hidden by
  default, sortable; its cell reads `Excluded` or nothing.

## The Visibility group

The two flags state what a game is left out of. Every surface that states or
shows them groups them under "Visibility", so a later flag joins one place.

- **Game form**: `FormFields(..., groups=...)` with a legend-hidden group
  "Game" for the game's own fields and a "Visibility" group, description
  "Leave this game out of:", checkboxes labelled "Unfinished lists" and
  "Dropped figures". `GAME_FORM_GROUPS` is shared by Add Game and Edit Game.
  `FormFields` refuses a group naming a field the form lacks, so the bulk form
  cannot reuse it.
- **Bulk Edit**: `BulkGameEditForm` renders a legend-hidden "Facts" group
  (status, mastered) and a "Visibility" group, description "Leave these games
  out of:". Fields "Unfinished lists" and "Dropped figures", choices
  "Excluded from …" / "Included in …". The preview gains a "Dropped figures"
  column. `VISIBILITY_FIELDS` names the two fields once, for both forms.
- **Game detail**: the Status row keeps status and mastered. A "Visibility"
  meta row, present only when one flag is set, reads "Left out of" followed by
  the set flags joined by ", " ("unfinished lists", "dropped figures").
- **Quick bar**: one "Visibility" facet, last in the games list (where the
  unfinished facet sits today), whose panel holds a True/False radio pair per
  member field. Members are labelled "Unfinished lists" and "Dropped figures",
  the words every other surface uses.

### The grouped facet

`QuickFacetGroup(label, members: tuple[QuickFacet, ...])` beside
`QuickFacet`. Both expose `fields: tuple[AttrName, ...]` — a plain facet
answers `(field,)`. `QUICK_FACETS` holds either. `quick_facet_fields(mode)`
answers the flat field set that `is_quick_editable` and the tests read. The
group renders one `ComboboxDropdown`, id `quick-<label slug>-dropdown`, whose
content is one `Fieldset` per member: a `Legend` with the member's label, then
its `field_widget(layout="panel")`, so each True/False pair has an accessible
name. It is applied when any member field is in the filter.

Callers of `facet.field` move to `fields` or `quick_facet_fields`:
`QuickFilterBar.render`, `tests/test_filter_paths.py` (its widget count reads
the field count, not the facet count), `tests/test_quick_filter_bar.py` (label,
id and order pins), `tests/test_games_access.py`,
`tests/test_session_reclassification_views.py`. `common/components/__init__.py`
exports `QuickFacetGroup` and `quick_facet_fields`. The TypeScript bar
needs no change: it serializes every `data-path` widget in the form and
spills whole `[data-quick-facet]` nodes.

A group admits only member kinds whose panel widget stacks (bool, number,
string). `QuickFacetGroup` cannot see kinds at import: `quick_filter.py`
imports `games.filters` inside functions only. `_facet` refuses a set or date
member at render time with `ValueError`, and `QuickFacetsContractTest` walks
every group so the refusal fails the suite, not a page.

## Decisions

- **No backfill.** The wave's issue comment on #1334 states nothing starts
  excluded. Since #1315 (2026-09-28) `excluded_from_unfinished` also hid a
  game from the dropped figures; after this change such a game counts in them
  again until the person states the second flag. The flags are two
  statements, and a pass that infers one from the other breaks the wave's
  rule. The remedy is two clicks: filter the Games list on Unfinished lists,
  select all, bulk Edit Dropped figures. The PR body says so.
- **Grouping is UI, approved by the user** (2026-09-30).
- **Collision with M7** (#1353, PR #1390): both add migration 0024, both edit
  `GameForm.field_order`, `QUICK_FACETS["games"]`, the facet ORDERS pin,
  `tests/test_stats_links.py` and `e2e/test_game_form_catalog_e2e.py`. The
  second to merge renumbers and puts `kind`/`parent` in the game form's
  untitled group, ahead of Visibility.

## Docs

These state the retired rule or enumerate the facts, and change with it:
`docs/STATUSES.md` (the Dropped rule and the summary row), `CLAUDE.md` (the
bulk Edit's fact list), the #1315 spec (its statistics section and its
pointer to this issue), the `games/bulk_game_edit.py` module docstring,
`NOTHING_STATED` and the `GameEditStatement` refusal.

## Tests

- `tests/test_playergame_command.py`: the fourth fact's append, skip,
  `Unchanged`, construction refusal; the untouched-columns list and the
  all-facts event order grow; a key recorded at version 2 replays.
- `tests/test_playergame_events.py`: payload validation.
- `tests/test_playergame_projection.py`, `tests/test_projection_replay_gate.py`:
  projection and replay; `build_stream` states the dropped flag on and off; the
  pinned missing-type count moves by one.
- `tests/test_stats_links.py`: parity per fact, per year and all time; each
  fact moves only its own figure. `test_an_excluded_game_leaves_unfinished_and_dropped`
  and its parametrised sibling pin the old rule and are rewritten.
- `tests/test_bulk_game_edit.py`: state, Undo, decode of the new key, groups;
  `NOTHING_STATED` names four facts; positional `GameEditStatement` calls take
  a fourth argument; the preview heading pin grows.
- `tests/test_excluded_from_dropped.py`: filter, column, sort, detail row.
  `tests/test_excluded_from_unfinished.py` moves its detail assertion from the
  Status row to the Visibility row.
- `tests/test_quick_filter_bar.py`: grouped facet renders both widgets, applied
  dot, round-trip editability.
- `tests/test_game_form_page.py`, `e2e/test_game_form_catalog_e2e.py`: the
  Visibility fieldset on the form.
- e2e: the Visibility facet applies a filter.

## Follow-up issues to file

None.
