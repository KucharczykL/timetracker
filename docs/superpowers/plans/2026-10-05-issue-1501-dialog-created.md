# Plan: a dialog hands a created row to its picker (#1501)

Spec: `docs/superpowers/specs/2026-10-05-issue-1501-dialog-created-design.md`.
Implementation inline, TDD per task.

## Task 1 — server answer

- `common/components/form_dialog.py`: `CreatedOption` (value, label: str;
  data: dict[str, str]), `CreatedAnswer` (kind "created", url, messages,
  option); `RedirectAnswer = DoneAnswer | CreatedAnswer | ContinueAnswer`.
- `games/management/commands/gen_element_types.py`: generated module holds
  the new interfaces (check `_union_members` picks them via the alias).
- `common/form_dialog.py`: `created_row(response, option) -> response`
  sets an attribute (`form_dialog_created`); `created_option(response)`
  reads it.
- `games/form_dialog_middleware.py`: after `dialog_result`, a `DoneAnswer`
  plus a tag becomes `CreatedAnswer` (same url, messages).
- Tests (`tests/test_form_dialog_results.py`, `tests/test_form_dialog.py`):
  tagged → created on READ_ONLY; tagged → continue elsewhere; untagged →
  done; non-dialog → redirect untouched; generated module contains
  `kind: "created";` and `interface CreatedOption`.

## Task 2 — game option and add_game

- `games/forms.py`: `game_option(game) -> SearchSelectOption` (str value);
  `_game_options` and `games/api.py:search_games` use it.
- `games/views/game.py:add_game`: final redirect wrapped in
  `created_row(..., game_option(game))`.
- Tests: dialog-mode POST of add_game answers created with the game's
  option; the API JSON row equals `game_option` JSON.

## Task 3 — picker link

- `common/components/search_select.py`: `DialogCreate(url: StrOrPromise,
  label: str)`; `SearchSelect(dialog_create=...)` renders
  `ControlButton(form_dialog_link(), href=str(url), variant="ghost",
  size="compact", aria_label, title, class_=...)[Icon("plus")]` after ×,
  before marker; `peer` on input when × or link.
- `games/forms.py`: `SearchSelectWidget(dialog_create=...)` passes through.
- Consumers: `SessionForm.game`, `EntryAddForm` game field,
  `GameForm.parent`, `PlaythroughForm.game` with
  `DialogCreate(reverse_lazy("games:add_game"), "New game")` (a shared
  constant `NEW_GAME` in `games/forms.py`).
- Check icon `plus` exists in `games/templates/icons`; else add + `make gen-icons`.
- Tests (`tests/test_search_select.py` + form render tests): link markup,
  order, peer with clearable=False; each of the four form pages renders it.

## Task 4 — client

- `ts/elements/form-dialog/answer.ts`: `created` kind, `isCreated` checks
  option fields; `Answer` gains `{kind:"created", url, messages, option}`.
- `routes.ts`: `routeOpen` created → as done; `routeSubmit` created →
  `{kind:"created", option, fallback: <done route>}`.
- `events.ts`: `FORM_DIALOG_CREATED = "form-dialog:created"` + detail type.
- `form-dialog.ts`: `OpenDialog.openerElement`; `wrote` includes created
  but pre-route stale skips it; created route: dispatch on connected
  opener element; taken → `entry.settled`/clear submitting, close,
  showToasts, stale iff opener inside a lower dialog's body; else route
  fallback. `closed()` ignores submitting when settled.
- `toast-stack.ts`: `postBehindModal` treats created as done.
- `search-select.ts`: listener on container for `FORM_DIALOG_CREATED`
  (target inside container, input not disabled) → upsertOption +
  selectOption(emit) + preventDefault; remove on disconnect if the
  element has a teardown.
- vitest: answer.test.ts, routes.test.ts, a form-dialog test for
  dispatch/taken/not-taken/stale (check existing test harness for the
  element; else add one), search-select test for accepting.

## Task 5 — e2e

- `e2e/test_form_dialog_created_e2e.py`: Add session → note typed → +
  → Add game dialog → fill name/platform → save → picker hidden input
  holds new id, run picker holds placeholder run, note kept. Nested:
  Add game page → "Add-on of" + → nested Add game → save → parent picker
  holds it.

## Gotchas

- `make ts` after TS edits before e2e; never e2e while `make dev` runs.
- Run tests under the shared flock.
- `make format`, `make lint-fix`, `make format-check`, `make vale` before commit.
