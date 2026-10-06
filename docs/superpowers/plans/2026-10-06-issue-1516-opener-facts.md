# Opener facts implementation plan

**Goal:** A form opened with facts its opener knows states them instead of asking.

**Architecture:** Query parameter per field → `OpenerFactsMixin.state_opener_facts` fixes the field
(`disabled`, statement recorded on the form) → `FormFields` renders a `<dl>` stated row and writes the
hidden carrier itself. Picker + carries field-sourced
params rewritten client-side.

**Spec:** `docs/superpowers/specs/2026-10-06-issue-1516-opener-facts-design.md`

## Global constraints

- Every pytest target under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Before each commit: `make format`, `make lint-fix`, `make format-check`, `make vale`, read by exit code.
- Logger `games.opener_facts`; value logged as `repr`, cut to 80 chars.
- Run `make ts` after `.ts` edits; `make gen-element-types` after a props TypedDict change.
- Complete-word identifiers; PEP 695 aliases for roles (`type FieldName = str`).

---

### Task 1: The mechanism

**Files:**
- Create: `common/opener_facts.py`
- Modify: `common/returns.py` (`action_url(..., facts=None)`)
- Test: `tests/test_opener_facts.py`, `tests/test_returns*.py` (whichever covers `action_url`)

**Interfaces (produces):**
- `type FieldName = str`; `type StatedFacts = Mapping[FieldName, object]`
- `type Statement = str`; `type RefusalSentence = str`
- `class OpenerFactsMixin`: `opener_fields: ClassVar[tuple[FieldName, ...]] = ()`;
  `stated_facts: dict[FieldName, object]`; `statements: dict[FieldName, Statement | None]`
  (None = implied, no row); `refused_facts: dict[FieldName, RefusalSentence]`;
  `state_opener_facts(self, facts: Mapping[str, str] | QueryDict | None) -> None`;
  `fix_field(self, name, value, *, statement: Statement | None = None) -> None`.
- `refusal_sentence(label) -> RefusalSentence`: "The link named a {label} this form cannot use. Pick one."
  (label lowercased).
- `action_url(viewname, *args, origin, facts: Mapping[FieldName, str] | None = None, **kwargs)`.

**Logic:**
- Read key `self.add_prefix(name)`; `QueryDict.getlist` (plain Mapping: one value). ≠1 value or `""` → malformed.
- `ModelChoiceField`: `parse_uuidv7(raw)` (ValueError → malformed); `field.queryset.filter(pk=key).first()`
  (the field's own queryset); `None` → unbound form: WARNING + `raise Http404`; bound form: record in
  `refused_facts`, no log, leave field editable (posted value hits `invalid_choice`).
  Statement `field.label_from_instance(row)`.
- Other field: `field.clean(raw)`; `ValidationError` → malformed. Statement: `dict(field.choices)[value]`
  for a choice field, else `str(value)`.
- Malformed → WARNING, field untouched (declared `initial` still applies), entry in `refused_facts`.
- Guard: raise `RuntimeError` if `name in self._bound_fields_cache`.
- `fix_field`: `self.initial[name] = value`, `field.disabled = True`, `stated_facts[name] = value`,
  `statements[name] = statement`. No widget swap.
- `action_url`: build query dict `{**facts, origin?}`; append even if origin None.

**Tests:** fixed+stated; undeclared param ignored; empty/two values/unknown word/non-v7 text → field
untouched + WARNING + `refused_facts` (use `capture_games_logger`); unknown v7 id and foreign
library's row → 404 unbound; same on a bound form → no 404, `invalid_choice` on the field, other
cleaned values intact; bound POST with tampered value cleans to the fact; cache guard raises; `action_url` facts with and without origin. Use a tiny test-local Form subclass over
`Game.objects.for_library(...)` and a `ChoiceField`.

- [ ] failing tests → implement → green (`make test ARGS="tests/test_opener_facts.py"`) → commit.

### Task 2: `FormFields` stated row

**Files:** Modify `common/components/primitives.py` (`_form_field_row`, `_grouped_form_fields`,
`FormFields`); test `tests/test_form_fields*.py` (find the existing FormFields tests; else
`tests/test_opener_facts.py`).

**Logic:**
- `statements = getattr(form, "statements", {})`; `refused = getattr(form, "refused_facts", {})`.
- Plain path: test `name in statements` before `is_hidden`; statement str → `_stated_row(field,
  statement)`; statement None → `_fact_carrier(field)` with the hidden fields.
- Grouped path: `group_fields` keeps stated fields (row) and drops silent ones; hidden list adds
  silent carriers.
- `_fact_carrier(field)`: `Input(type="hidden", name=field.html_name, value=...)` — never
  `str(field)` (Django stamps `disabled`). Value through `field.field.prepare_value(field.value())`.
- `_stated_row`: wrapper `Div(data_field_row=name)[Dl[Dt(class_=FORM_LABEL_CLASS)[label],
  Dd(class_="text-type-body text-heading")[statement]], carrier, FieldErrors]`.
- Refused fact: its row's `after_control` gains `P(class_="text-type-body text-body")[sentence]`
  (merge with an existing presentation via `replace`).
- Silent fixed field errors appended to the non-field errors block.
- Gotcha: `Dl`/`Dt`/`Dd` may be missing from the builder whitelist — add them in `primitives.py`
  and export. `common/opener_facts.py` imports only Django.

**Tests:** plain and grouped render the row in field order with dt label, dd statement, hidden
input without `disabled` carrying the value; empty group with only a stated field still renders;
silent fact renders no row but its carrier; refused fact sentence after its control; errors on a
stated field show in its row; errors on a silent one in non-field errors; `test_html_validity`
stays green.

- [ ] failing → implement → green → commit.

### Task 3: + carries params (`DialogCreate.params`)

**Files:**
- Modify: `common/components/search_select.py` (`DialogCreate.params: ParamSources | None = None`,
  last field; `_dialog_create_link` joins literal sources with `urlencode`; `SearchSelect` passes
  field sources as prop `dialog_create_params`)
- Modify: `common/components/custom_elements.py` (`SearchSelectProps.dialog_create_params: SearchSelectParams`)
- Modify: `ts/elements/search-select.ts` (parse with `parseParams(props.dialogCreateParams)`; on
  connect + one form-level `input`/`change` listener filtered by `event.target.name ∈ sources`,
  rewrite `[data-search-select ...]` + link's `href` via `new URL`: set resolved, delete blank, keep
  rest; same `<a>`; remove listener on disconnect)
- Regenerate: `make gen-element-types`
- Tests: `tests/test_search_select.py` (href with literal; prop present only with field sources;
  positional `DialogCreate(url, label)` still valid), `ts/elements/search-select.dialog-create.test.ts`
  (query follows field typing, blank deletes, literal kept, same element).

**Gotcha:** find how the + is located in TS (marker from `_dialog_create_link`; add a
`data-search-select-dialog-create` attribute if none). Keep a widget's `dialog_create=` passthrough
in `games/forms.py` unchanged. Rewrite on every connect (form-dialog re-inserts content); vitest
covers a disconnect + re-insert.

- [ ] failing → implement → `make ts` → `make test-ts TS_ARGS=...` + focused pytest → commit.

### Task 4: Add game from "Add-on of"

**Files:** `games/forms.py` (`GameForm(OpenerFactsMixin, ...)`, `opener_fields = ("kind",)`, `facts=`
kwarg; after stating: kind not in `ADDON_KINDS` → `fix_field("parent", None)`; `NEW_MAIN_GAME`;
parent widget uses it), `games/views/game.py` (`add_game` passes `facts=request.GET`; skip
`GameAddon` when `"kind" in form.stated_facts`; title via `_add_game_title(form, request.GET)`),
`edit_game` unchanged (no facts).
Tests: `tests/test_dialog_create_pages.py` (+ href/label for parent on add/edit game:
`add_game?kind=main`, "New main game"), new `tests/test_add_game_opener_facts.py` (kind row, no
parent row, no `game-addon`, title with/without `addon`, `addon` cut to 255, posted `kind=dlc`
ignored → saved main game with no parent, `?kind=dlc` states DLC and keeps the parent picker,
`addon` with newline/tab/control chars → single-spaced title).
`_add_game_title`: control chars → space, collapse whitespace, strip, cut to 255.
Edit views never pass `facts=`; test that `edit_game?kind=main` on a DLC keeps Kind editable.

**Gotcha:** GameForm's base order `_LibraryBoundConstraintValidationMixin, PrimitiveWidgetsMixin`
— put `OpenerFactsMixin` where its method is reachable; `state_opener_facts` call at end of
`__init__`, after `order_fields` and before the edit-initial block (no `self[name]` there).

- [ ] failing → implement → green → commit.

### Task 5: Chained routes become facts

**Files:**
- `games/urls.py`: remove `add_playthrough_for_game`, `add_session_for_game`, `add_library_entry`
  (keep `add_library_entry_now`).
- `games/views/returns.py`: drop the three names.
- No `facts=` on any edit view (`edit_session`, `edit_playthrough`, `edit_library_entry`).
- `games/forms.py` `SessionForm`: mixin, `opener_fields=("game",)`, `facts=`; when game stated and
  unbound: `initial["playthrough"]` = `sole_ordinary_run(...)` pk if not given; game widget's
  autofocus gone → `device` widget autofocus.
- `games/forms.py` `PlaythroughForm`: mixin, `("game",)`; drop `offered_game`; gate
  `also_mark_played` from the stated game; dates seeding stays in view (`_seeded_run`) reading
  `form.stated_facts` while unbound — or move `_seeded_run` into `games/reads` if a form import from
  views would cycle.
- `games/entry_forms.py` `EntryAddForm`: always build `game` field; mixin `("game",)`; release
  params `{"game_id": {"field": add_prefix("game")}}`; create rule = stated game ? owned : True;
  default Release initial from stated game; drop `game=` / `self.game`; `clean()` reads
  `cleaned.get("game")`.
- Views: `games/views/session.py` `add_session`, `games/views/playthrough.py` `add_playthrough`,
  `games/views/library_entry.py` (`_add` takes no game; `add_library_entry` removed; title
  "Add to library"; `game=` lambda reads `form.stated_facts.get("game")` or cleaned).
- Callers → `action_url(..., facts={"game": str(game.id)})`: `games/views/game.py` (~443, 616,
  629, 717), `games/views/library_cards.py:154`.
- Tests to update (grep `add_session_for_game|add_playthrough_for_game|add_library_entry\b`):
  test_dialog_create_pages, test_library_page_isolation (404 via `?game=` foreign id),
  test_form_dialog_results (continue target `add_to_library`), test_rendered_pages,
  test_session_form_derivation, test_returns_views, test_library_entry_views, test_html_validity,
  test_game_detail_links, test_user_preference_consumers, test_playthrough_view_cutover,
  test_library_section; e2e: test_dropdown_host_order, test_search_select_clear,
  test_search_select_create (190-215 → plain `add_session`), test_purchase, test_widgets,
  test_touch_targets.
- New consumer tests: each page with/without `?game=` (row vs picker), sole-run seed, device
  autofocus, played gate on already-played game, Release create row absent for a shared game,
  Cancel → game page.

- [ ] failing → implement → `make check-fast` → commit.

### Task 6: e2e for the issue

**File:** `e2e/test_dialog_create_e2e.py`: type DLC name, pick Kind DLC, press + "New main game";
stacked dialog title "Add the main game of <name>", no Kind select, Kind row "Main game"; fill name
+ release platform as existing test does; save; parent picker holds new game; submit DLC; DB has
DLC with that parent. Update the existing test's "New game" locator.

- [ ] `make test-e2e ARGS="-k dialog_create"` → commit.

### Task 7: Follow-ups and wave

- `gh issue create` the two spec follow-ups (Part of #1485 / related).
- Comment on #1385 (forms it converts inherit `facts=`) and #1514 (title now distinct).

## Gotchas

- `BoundField.initial` is cached; never touch `self[name]` before `state_opener_facts`.
- `UUIDv7Field` refuses v4 UUIDs; tests use real game ids.
- `apply_primitive_widget_classes` already ran; the hidden widget needs no classes.
- Dialog link same-URL detection keeps the query; fine.
