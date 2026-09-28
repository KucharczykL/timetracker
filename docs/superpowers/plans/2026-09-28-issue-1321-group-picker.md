# Group picker — implementation plan

**Spec:** [The group picker](../specs/2026-09-28-issue-1321-platform-icon-glyphs-design.md#the-group-picker)

Constraints: `make` targets only; pytest under the heavy-tests `flock`;
`make gen-element-types` + `make ts` after a props or `.ts` edit; no
e2e while `make dev` runs.

### Task 1: Literal props in the element codegen

- `common/components/custom_elements.py`: `_named_role` / `_TYPE_MAP` /
  `_reader_expr` accept `Literal["a", "b"]` of strings. Interface line
  emits `"a" | "b"`; reader emits
  `(el.getAttribute("x") ?? "") as "a" | "b"`.
- Test in the existing codegen test (`grep -rl render_props_module tests`):
  a TypedDict with a `Literal` prop renders the union and the cast.

### Task 2: `create` replaces `create_event`

- `SearchSelectProps`: drop `create_event: bool`; add
  `create: SearchSelectCreate` where
  `type SearchSelectCreate = Literal["", "post", "event", "select"]`.
  `create_url` stays, read only by `post`.
- `SearchSelect()`: new keyword `create_selects: bool = False`;
  `create_url` and `create_selects` together raise `ValueError`. It
  renders the create row and `create="post"`/`"select"`.
  `SearchSelect(create_verb=...)` passes the verb through.
- `PresetSelect`: `create="event"`.
- `ts/elements/search-select.ts`: one `createMode` from `props.create`
  (blank for filter and free-text panels). `createRowOffered` reads it.
  `commitCreate`: `event` as today; `select` upserts
  `{value: name, label: name, data: {}}`, selects it, hides the panel;
  `post` as today.
- vitest in `ts/elements/search-select.create.test.ts`: `select` mode
  selects the typed text, posts nothing, hides the row once a loaded
  label equals the query (case ignored), and Enter commits it. Update
  preset tests' fixture attribute to `create="event"`.

### Task 3: `TextSearchSelectWidget`, Group on both forms

- `games/forms.py`: `TextSearchSelectWidget(_SearchSelectAdapter)` with
  `suggestions: Sequence[str]`; renders `options` from them,
  `selected` = the value when non-empty, `create_selects=True`,
  `create_verb="Use"`. Delete `DatalistTextInput`; drop `Datalist` from
  `common/components/elements.py` and `__init__.py` if nothing else
  uses it.
- `PlatformForm.group`: the widget, suggestions from the library's
  groups (same query as `bulk_platform_edit._groups`; move that
  function to `games/reads/platform_groups.py` and import it in both).
- `BulkPlatformEditForm.group`: `UnsetWidget(TextSearchSelectWidget())`;
  the Keep placeholder goes on the inner widget's `placeholder`.
- Tests: `tests/test_bulk_platform_edit.py` (renders a search-select,
  no `<datalist>`, placeholder reads Keep), `tests/test_icon_picker.py`
  neighbour or a new `tests/test_platform_group_picker.py` (form posts
  a typed group and a suggested one).
- e2e: extend `e2e/test_bulk_platform_edit_e2e.py`: type a new group,
  press Enter on `Use “…”`, submit, the rows hold it. One on the
  Platform form.

### Task 4: docs

- `CLAUDE.md` search_select bullet: `create` modes, `select`
  included; name `TextSearchSelectWidget` beside
  `ChoiceSearchSelectWidget`.
- Full gate at the end, on the user's word.
