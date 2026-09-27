# ChoiceSearchSelectWidget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `SearchSelect` form widget over a `ChoiceField`'s fixed choices (#1301).

**Architecture:** A sibling of `SearchSelectWidget` in `games/forms.py`, both on
one private base. The new widget maps `self.choices` onto `SearchSelect(options=…,
none_label=…)`; the component and its TypeScript already do the rest (#1288).

**Tech Stack:** Django forms, `common.components.SearchSelect`, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-27-issue-1301-choice-search-select-design.md`

## Global Constraints

- Step 0: rebase onto `origin/main`.
- Run everything through `make`; wrap pytest targets in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- No TypeScript change. If a test needs one, stop: the spec is wrong.
- Complete-word identifiers; named aliases for compound types
  (`type ChoiceKey = str`).
- Comments: present design only, no issue numbers.
- `make format`, `make lint-fix`, `make vale` before each commit.
- Gate: full `make check` once, at the end, on the user's word.

---

### Task 1: Base class and the widget

**Files:**
- Modify: `games/forms.py:304-395` (`SearchSelectWidget`, `SearchSelectMultiple`),
  `games/forms.py:160-175` (skip list in `apply_primitive_widget_classes`)
- Test: `tests/test_choice_search_select.py` (new)

**Interfaces:**
- Produces:
  - `_SearchSelectAdapter(forms.Widget)`: holds `placeholder`, `clearable`,
    `autofocus`; `_render(name, attrs, **component) -> SafeString` passes
    `id`, `clear_description_id`, `host_dropdown=True`, `clearable`,
    `autofocus` and the caller's keywords to `SearchSelect`;
    `value_from_datadict` returns `data.get(name)`.
  - `SearchSelectWidget(_SearchSelectAdapter)`: constructor and output unchanged.
  - `ChoiceSearchSelectWidget(_SearchSelectAdapter)`:
    `__init__(*, placeholder: str | None = None, clearable=True, autofocus=False, attrs=None)`.
  - `DEFAULT_CHOICE_PLACEHOLDER = "Choose…"`.
  - `host_choices(field: forms.ChoiceField, widget: ChoiceSearchSelectWidget) -> None`.

- [ ] **Step 1: Failing tests.** Render through a tiny `forms.Form` and
  `FormFields`, parse with the helpers `tests/test_search_select.py` already
  uses. Cases:
  - optional + `("", "Use site default (UTC)")`: none row with that label;
    `none` held for `initial=None` and for a key not in choices.
  - optional, no empty choice: no none row; unmatched value holds nothing.
  - required + `("", "---------")`: no none row, placeholder "Choose…",
    "---------" absent from the markup; caller `placeholder="Pick"` shows "Pick".
  - required, no empty choice: plain picker.
  - empty choice not first (`[("a","A"), ("", "None")]`) still reads as none.
  - selected match: `initial="b"` shows label B; `TypedChoiceField` with
    `"True"`/`"False"` keys and `initial=True` shows True's label.
  - refusals, each `pytest.raises(ValueError)` on `str(FormFields(form))`:
    `CharField(widget=ChoiceSearchSelectWidget())`; grouped choices;
    `ModelChoiceField(queryset=Device.objects.none(), widget=ChoiceSearchSelectWidget())`
    — assert the refusal fires with `django_assert_num_queries(0)`.
  - `host_choices`: widget swapped onto a built field renders its options;
    `field.required = False` then `host_choices` gives the none row.
  - round trip: `TypedChoiceField(required=False, choices=[("True","Yes"),("False","No")], coerce=lambda value: value == "True", empty_value=None)`
    cleans `{"f": "False"}` → `False`, `{"f": ""}` → `None`, `{}` → `None`.
  - `apply_primitive_widget_classes` leaves the widget's `attrs["class"]` unset.
  - `SearchSelectWidget` renders byte-identical before and after (one snapshot
    of an existing form field, e.g. `SessionForm().fields["device"]`, taken in
    this step before the refactor).
- [ ] **Step 2:** `make test-fast ARGS="tests/test_choice_search_select.py tests/test_search_select.py"` — new cases fail.
- [ ] **Step 3: Implement.**
  - Extract the base; `SearchSelectWidget.render` keeps its `none_label`
    + `is_required` refusal and calls `_render(..., search_url=…, options=None, …)`.
  - `ChoiceSearchSelectWidget.render`: refuse missing `choices`
    (`getattr(self, "choices", None) is None`) and `isinstance(self.choices, ModelChoiceIterator)`
    **before** iterating; iterate once into a list; refuse any entry whose
    label is a list/tuple (grouped); split out the `""` entry; `none_label`
    = its label when `not self.is_required`; `selected` = the option whose key
    equals `"" if value is None else str(value)`, none when the key is `""`.
  - `host_choices`: `field.widget = widget; widget.choices = field.choices; widget.is_required = field.required`.
  - Replace `SearchSelectWidget` in the skip tuple with `_SearchSelectAdapter`.
- [ ] **Step 4:** same command — pass. `make typecheck`.
- [ ] **Step 5: Commit** `feat: ChoiceSearchSelectWidget renders a field's fixed choices`.

Gotchas:
- `widget.choices` is shared across form instances (shallow `__deepcopy__`);
  never mutate it, copy into a local list.
- `ChoiceField` normalises choices; a callable arrives as
  `CallableChoiceIterator`, fine to iterate.
- `PlaythroughSelectWidget(SearchSelectWidget)` only calls the parent
  constructor with keywords; the extraction keeps that constructor's
  signature.

### Task 2: Browser coverage

**Files:**
- Create: `e2e/test_choice_search_select_e2e.py`

**Interfaces:**
- Consumes: `ChoiceSearchSelectWidget` from Task 1.

- [ ] **Step 1: Harness.** Copy the shape of `e2e/test_temporal_field_e2e.py:44-86`:
  a `forms.Form` with `with_none` (optional, `("", "No choice")`, A/B/C) and
  `without_none` (optional, no empty choice, `placeholder="Keep: mixed"`),
  both `TypedChoiceField(empty_value=None)`. GET: `render_page(... FormFields ...,
  scripts=(ModuleScript("dist/elements/search-select.js"), ModuleScript("dist/elements/drop-down.js")))`.
  POST: echo each field as `repr(cleaned_data[name])` and `name in request.POST`
  in `<p id=…>`. `@csrf_exempt`, `urlpatterns = [*base_urlpatterns, path(...)]`,
  `override_settings(ROOT_URLCONF=__name__)`.
- [ ] **Step 2: Cases.**
  - click pick B on `with_none`, submit → `'B'`, key present.
  - keyboard: focus, ↓ ↓, Enter picks the second value row (default highlight
    skips the none row), submit.
  - typed filter "c" hides A and B, keeps the none row visible.
  - × on `with_none` after a pick → box shows "No choice", submit → `None`, key present.
  - × on `without_none` after a pick → placeholder "Keep: mixed", submit →
    `None`, key absent.
  - no console errors on load.
- [ ] **Step 3:** `make ts` then `make test-e2e ARGS="e2e/test_choice_search_select_e2e.py"` — pass
  (never while `make dev` runs).
- [ ] **Step 4: Commit** `test: browser coverage for fixed-choice SearchSelect`.

### Task 3: Docs

**Files:**
- Modify: `CLAUDE.md` (the `search_select.py` bullet, one clause naming
  `ChoiceSearchSelectWidget` and `host_choices`)
- Modify: `docs/superpowers/specs/2026-09-27-issue-1301-choice-search-select-design.md` only if Task 1 or 2 contradicted it.

- [ ] **Step 1:** Edit, `make vale`, `make format-check`.
- [ ] **Step 2: Commit** `docs: fixed-choice SearchSelect`.

## Follow-up issues

None new. #1211 (Emulated), #1289 (settings adapter, uses `host_choices`),
#1292 (small enums) consume this. Comment on #1211 and #1289 with the
`host_choices` and bool-coerce rules when the PR opens.
