# Issue #1334 plan: excluded from dropped figures

Spec: [design](../specs/2026-09-30-issue-1334-excluded-from-dropped-design.md).
TDD per task. Iterate with focused `make test ARGS=…` under the shared lock.

## Task 1 — the fact

Files: `games/models.py` (column, TYPE_CHECKING annotation, `tracked_by`
annotation), `games/migrations/0024_playergame_excluded_from_dropped.py`
(`make makemigrations ARGS="games --name playergame_excluded_from_dropped"`),
`games/events/playergame.py` (payload + `PLAYERGAME_EXCLUDED_FROM_DROPPED_CHANGED`),
`games/projectors/playergame.py`, `games/commands/playergame.py` (fourth
field, `__post_init__`, `build`), `games/events/idempotency.py` (version 3,
comment), `games/writes/playergame.py`, `games/views/playergame_writes.py`,
`tests/tracked_games.py`, `e2e/tracked_games.py`.

Tests first: `tests/test_playergame_events.py` (registered, validates, refuses
string/missing), `tests/test_playergame_command.py` (append, skip held,
`Unchanged`, all-four order, untouched columns, v2 key replays),
`tests/test_playergame_projection.py`, `tests/test_projection_model.py`
(`PINNED_DEFAULTS`), `tests/test_projection_replay_gate.py` (stream on/off
pair, pinned count 49 → 50).

Gotcha: `makemigrations` via make (it passes `--noinput`).

## Task 2 — statistics and links

Files: `games/views/stats_data.py` (`_games_excluded_from(library, field)` or
two helpers; `unfinished` reads unfinished, `dropped` reads dropped),
`games/views/stats_links.py` (`_holding_no_excluded_game(field)`).

Tests: rewrite `tests/test_stats_links.py`
`test_an_excluded_game_leaves_unfinished_and_dropped` and its parametrised
sibling into: each flag moves only its own figure; parity per year and
all-time for each.

## Task 3 — filter, column, sort, detail

Files: `games/filters.py` (`excluded_from_dropped` field + `FilterField`),
`games/sorting.py` (`dropped_figures`), `games/views/game.py`
(`game_list_columns`, row cell, detail: Status row loses the unfinished text;
new `_visibility_row(game)` meta row after Status, only when a flag is set).

Tests: new `tests/test_excluded_from_dropped.py` (filter, column hidden by
default, sort, detail row wording for one / both / none);
`tests/test_excluded_from_unfinished.py` detail assertion moves to the
Visibility row.

## Task 4 — Game form Visibility group

Files: `games/forms.py` (`VISIBILITY_FIELDS`, `excluded_from_dropped`
checkbox, relabel both "Unfinished lists"/"Dropped figures", `field_order`,
initial, `GAME_FORM_GROUPS`), `games/views/game.py` (both `FormFields` calls
take `groups=GAME_FORM_GROUPS`; both `record_facts_for_request` calls pass
the fourth fact).

Tests: `tests/test_game_form_page.py` (fieldset with legend Visibility holding
both checkboxes; save states each flag); `e2e/test_game_form_catalog_e2e.py`
labels.

## Task 5 — bulk Edit

Files: `games/bulk_game_edit.py` (docstring, `GameEditJson`, `NOTHING_STATED`,
`GameEditStatement` fourth field + encode/decode, `_DROPPED_CHOICES`,
form field + placeholder loop + clean + statement, groups in `offer_edit`,
`_state`, `edit_back` restatement + `log_overwrite` loop, preview column),
`games/reads/playergame_facts.py` (`_DROPPED` fact, `BatchFactChanges`).

Tests: `tests/test_bulk_game_edit.py` (state, Undo, decode, NOTHING_STATED,
positional calls, preview headings, groups render).

## Task 6 — grouped quick facet

Files: `common/components/quick_filter.py` (`QuickFacet.fields` property,
`QuickFacetGroup`, `quick_facet_fields(mode)`, `_facet` dispatch +
`_facet_group`, render-time kind refusal, `QUICK_FACETS["games"]` last entry
`QuickFacetGroup("Visibility", (QuickFacet("excluded_from_unfinished",
"Unfinished lists"), QuickFacet("excluded_from_dropped", "Dropped figures")))`),
`common/components/__init__.py` exports.

Tests: `tests/test_quick_filter_bar.py` (label/id/order pins over groups;
group renders two fieldsets with legends; applied when either member stated;
contract walks group member kinds; round trip), `tests/test_filter_paths.py`,
`tests/test_games_access.py`, `tests/test_session_reclassification_views.py`
use `quick_facet_fields`. e2e: Visibility facet applies
`excluded_from_dropped` (add to an existing quick bar e2e file).

## Task 7 — docs

`docs/STATUSES.md`, `CLAUDE.md`, #1315 spec, and the wave doc's M8 row.
Then the docs sweep (skill step 8) and full `make check`.

## Gotchas

- M7 (PR #1390) also takes migration 0024; renumber on rebase if it lands
  first, and put `kind`/`parent` into the "Game" group.
- `FormFields` renders groups before ungrouped fields: every visible game
  form field must sit in a group.
- Zone-sensitive stats tests: seed at `library_noon`.
