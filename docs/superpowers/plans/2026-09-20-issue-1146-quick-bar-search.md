# The quick bar's search field — implementation plan

> **For agentic workers:** use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans`. Steps are checkboxes.

**Goal:** give the `search` criterion a control on every list page, and repair
the two paths that answer a stated match mode with something else.

**Architecture:** four stack members, merged as one through `gh stack`. Two of
them repair defects reachable today and stand alone. The field is an input
group — a mode trigger and a text input as joined segments — leading the quick
bar's row.

**Tech stack:** Django components in `common/components/`, TypeScript custom
elements in `ts/elements/`, pytest, vitest, Playwright.

**Spec:** [the quick bar's search field](../specs/2026-09-20-issue-1146-quick-bar-search-design.md)

**Issues:** #1146 (members 1, 2, 4), #1166 (member 3).

## Global constraints

- Run everything through `make`. Never `uv run` / `pnpm` / `pytest` directly.
- Iterate with `make check-fast`; the gate is one full `make check`, under the
  shared lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- Run `make ts` after editing any `.ts`, or e2e serves stale output.
- Builders take htpy form: static attributes as kwargs, children in `[]`.
  `Input`, `Checkbox`, `ControlButton` and the other styled builders refuse
  `attributes=` / `children=`.
- A JS-bearing component declares its own `Media`; the view never threads
  `scripts=` for it.
- Colour comes from semantic tokens, never a raw palette value.
- No styling-at-a-distance: an element's appearance, state included, comes from
  its own component.
- `make vale` governs prose in docs and in comments. Do not write `fold`,
  `seam`, `delete`, `archive`, `heal` or `tombstone` in a domain sense.

## File map

| File | Responsibility |
|---|---|
| `common/components/primitives.py` | the segmented-field component and its exports |
| `common/components/__init__.py` | re-export |
| `common/criteria.py` | `search_q` states every modifier |
| `common/components/quick_filter.py` | the field in the row; `is_quick_editable` |
| `common/components/search_field.py` | the field: trigger, menu, input, prefill |
| `ts/elements/search-field.ts` | the element: mode state, menu wiring |
| `ts/elements/filter-widgets.ts` | `readStringWidget` reads a declared modifier |
| `ts/elements/quick-filter-bar.ts` | the reserve measurement |
| `games/templates/icons/*.html` | six mode marks |
| `games/filters.py`, `ts/elements/filter-tree/serializer.ts` | #1166 |

---

## Member 1 — the segmented field

### Task 1: a field built of joined members

**Files:** create `common/components/primitives.py` addition + export in
`common/components/__init__.py`; test `tests/test_components.py`.

**Interfaces — produces:**

```python
def SegmentedField(
    attrs: AttrsArg | None = None,
    *,
    leading: Node | None = None,
    field: Node,
    trailing: Node | None = None,
    **kwargs: object,
) -> Element: ...
```

Renders one flex row that carries the shared shadow and joins its members with
a negative inline start margin so the borders overlap by one pixel. The
component owns each member's rounding: leading rounds the start, trailing the
end, and a member that is absent leaves its neighbour's rounding whole.

**Why it exists:** `INPUT_CLASS` (`games/forms.py:92`) bakes `rounded-base`.
Appending `rounded-e-base` at a call site wins only by stylesheet order — the
same trap CLAUDE.md documents for `justify-*`. The rounding must be decided by
one component.

**Steps:**

- [ ] Write the failing tests in `tests/test_components.py`:
      a field with all three members rounds start/none/end in that order; a
      field with only `field` keeps `rounded-base` whole; the row states one
      shadow and the members none; the input carries `min-h-control`.
- [ ] `make test ARGS="tests/test_components.py -k segmented"` — expect failure.
- [ ] Implement beside the other styled builders in `primitives.py`; export it.
- [ ] Re-run; add to `tests/test_control_height.py`'s registry so the height
      scan covers the new control, and to whatever `tests/test_color_tokens.py`
      and `tests/test_typography_tokens.py` enumerate.
- [ ] `make check-fast`, then commit.

**Trap:** the focused member must sit above its neighbour or its ring is
clipped by the overlapping border. State that on the field, not at the call
site.

---

## Member 2 — `search_q` states every modifier

### Task 2: the reader

**Files:** modify `common/criteria.py:3263`; test `tests/test_filters.py`.

**Interfaces — unchanged signature:**

```python
def search_q(criterion: StringCriterion, *field_names: str) -> Q: ...
```

**Behaviour:** build the disjunction from the modifier's positive form; negate
the whole disjunction for a negative modifier. The exact pair reads
`iexact`, not `exact`. An empty value still states no constraint. A modifier
the field cannot state reaches here only from a stored filter and is answered
as a `FilterError`.

**Test cases (names, not transcriptions):**

- includes and excludes keep today's answers — pin against the current rows
- `is` matches a whole value in any column, and ignores case
- `is not` excludes a row whose *any* column matches, not each column separately
- `matches regex` answers a regex, and `not matches regex` its complement
- an empty value with any modifier adds no constraint (two existing tests at
  `tests/test_filters.py:5406` already pin this — keep them passing)
- a pattern PostgreSQL refuses raises `FilterError` at parse, not at execution
- `IS_NULL` raises `FilterError` rather than matching everything

**Steps:**

- [ ] Write the failing tests.
- [ ] `make test ARGS="tests/test_filters.py -k search_q"` — expect failure.
- [ ] Implement.
- [ ] Re-run, then `make test ARGS="tests/test_filters.py"` whole, because the
      seven filters' `_extra_q` all route through this function.
- [ ] `make check-fast`, commit.

**Trap:** negation wraps the OR. `~Q(a) | ~Q(b)` is true for nearly every row;
the shape is `~(Q(a) | Q(b))`.

---

## Member 3 — the builder holds `search` (#1166)

### Task 3: a filter survives a builder round trip

**Files:** `common/criteria.py:2862` (`field_metadata`), `games/filters.py:1122`
(`model_field_registry`), `ts/elements/filter-tree/serializer.ts:104`; tests
`tests/test_filters.py:5563`, `ts/elements/filter-tree/serializer.test.ts`.

**Decide first, and record the choice in #1166 before coding:** register
`search` as a pickable field, or carry an unregistered key through untouched.
The second is narrower and repairs the same loss for any future key; the first
needs an answer for what a second `search` inside a nested group would mean,
since `_extra_q` applies the top-level one only.

**Test cases:**

- a filter carrying `search` in each of the six modes reads into the builder
  and writes back byte-identical
- a filter carrying `search` beside facets and an `AND` group round-trips
- the existing assertion at `tests/test_filters.py:5563` is restated to match
  the choice, with its comment rewritten — it currently pins the defect

**Steps:**

- [ ] Write the failing vitest case in `serializer.test.ts` (read then write,
      compare) and the failing pytest case.
- [ ] `make test-ts` and `make test ARGS="tests/test_filters.py -k search"` —
      expect failure.
- [ ] Implement; repair the stale comment at `serializer.ts:114`, which claims
      parity with a backend that refuses unknown keys (`criteria.py:1768`).
- [ ] `make check-fast`, commit.

---

## Member 4 — the field

### Task 4: the six marks

**Files:** create `games/templates/icons/match-includes.html` and five
siblings; regenerate `common/components/icons_generated.py`.

Shapes: an arc enclosing a bar for `includes`, two bars for `is`, `.*` for the
regex. A negative is its positive plus a diagonal from upper left to lower
right, with a gap **drawn into the glyph path** where the diagonal crosses it.

**Steps:**

- [ ] Draw the six snippets on the 24-unit grid the existing icons use.
- [ ] `make gen-icons`; never hand-edit `icons_generated.py`.
- [ ] Check each at 16 px in both themes in a browser before committing.
- [ ] Commit both the snippets and the generated module.

**Traps:** icon slugs share a namespace with `Platform.icon`, so prefix them.
A cut-out painted in a surface colour is a halo on the trigger's hover surface
— the gap belongs in the path.

### Task 5: the field component and its element

**Files:** create `common/components/search_field.py` and
`ts/elements/search-field.ts`; register props in
`common/components/custom_elements.py`; modify `ts/elements/filter-widgets.ts`;
tests `tests/test_search_field.py`, `ts/elements/filter-widgets.test.ts`.

**Interfaces — consumes:** `SegmentedField` from Task 1, with the trigger as
`leading` and the text input as `field`.

**Interfaces — produces:**

```python
def SearchField(
    *, value: str = "", modifier: str = "INCLUDES", mode: FilterMode
) -> Node: ...
```

The root carries `filter_widget_attributes(["search"], "string")`
(`primitives.py:182`) so the bar's generic serializer reads it, **plus**
`data-modifier` holding the current mode. It declares its own `Media`. The
trigger and menu are a `<drop-down>`; the element owns the mode, rewrites
`data-modifier` and swaps the trigger's mark when a row is chosen.

**The reader's generalization** (`filter-widgets.ts:60`): `readStringWidget`
takes the modifier from `select[data-string-modifier-select]` when one exists,
otherwise from the root's `data-modifier`, otherwise `EQUALS` as now. Mirror it
in `writeStringWidget` so hydrate-then-serialize stays stable.

**Test cases:**

- the root carries path `["search"]`, kind `string`, and the stated modifier
- a prefilled value and mode render selected; the menu marks the current mode
- the trigger's accessible name states the mode (`Match mode: Excludes`)
- `readStringWidget` reads a root with `data-modifier` and no select
- `readStringWidget` still prefers the select where one exists (the builder's
  leaves must not change)
- the field with no scripting renders the input and applies on Enter
- the placeholder names what the mode reads on that list: the columns differ
  per filter (`tests/test_filters.py:5438` pins seven different lists), so a
  search on sessions reads game, platform and device names while a search on
  games reads the game's own columns

**Steps:**

- [ ] Write the failing pytest and vitest cases.
- [ ] `make test ARGS="tests/test_search_field.py"` and `make test-ts` — fail.
- [ ] Implement the component, then the element; `make gen-element-types` after
      the props change, then `make ts`.
- [ ] Re-run; `make check-fast`; commit.

**Trap:** `setupModifierToggles` reacts to a `change` on
`select[data-string-modifier-select]` and `toggleStringFilterInput` walks
`closest(".flex-col")` (`filter-widgets.ts:193`). The field renders no such
select, so the walk never starts — do not add a hidden one to "reuse" the
reader, or it will disable an unrelated input in the row.

### Task 6: the bar holds the field

**Files:** modify `common/components/quick_filter.py` (render and
`is_quick_editable:171`, its docstring, and the module docstring at `:14`),
`ts/elements/quick-filter-bar.ts:138`; tests
`tests/test_quick_filter_bar.py`, `ts/elements/quick-filter-bar.test.ts`.

**Behaviour:** the field leads the row and is never a facet, so the overflow
never holds it. `is_quick_editable` admits a top-level `search` whose modifier
is one of the six; any other modifier degrades the bar. The reserve counts
every non-facet child, the overflow host exactly once.

**Test cases:**

- a filter of facets plus a six-mode `search` is quick-editable
- a `search` in `IS_NULL` or any other modifier degrades the bar —
  this **restates** `test_search_degrades` (`tests/test_quick_filter_bar.py:79`),
  which today asserts every `search` degrades
- the round-trip guarantee still holds (`:170`) with `search` in the output
- the bar renders the field in every one of the seven modes
- the degraded pill renders no field and mounts no element
- vitest: the reserve equals furniture + overflow + gaps with a leading field,
  and the existing arithmetic at `quick-filter-bar.test.ts:307` still holds

**Steps:**

- [ ] Write the failing tests, including the restatement.
- [ ] `make test ARGS="tests/test_quick_filter_bar.py"` and `make test-ts`.
- [ ] Implement; rewrite the two docstrings that name `search` as a degrading
      key.
- [ ] `make check-fast`; commit.

**Trap:** the overflow host is already measured on its own line
(`quick-filter-bar.ts:135`). Counting "every non-facet child" naively adds it
twice and breaks the pinned arithmetic.

### Task 7: the browser

**Files:** `e2e/test_quick_filter_e2e.py`; the five synthetic harness pages
that hand-list their scripts — `e2e/test_string_filter_e2e.py:28` and its twins
in `test_boolean_filter_e2e.py`, `test_number_filter_e2e.py`,
`test_set_filter_e2e.py`, `test_date_range_picker_e2e.py`.

**Test cases:**

- typing and pressing Enter applies, and the URL carries `search`
- choosing a mode then applying carries that modifier, not `EQUALS`
- the menu opens and is operable by keyboard; Escape closes it
- at 390 px the row keeps its gutter and the field stays out of the overflow
- no console error on a page that renders the bar

**Steps:**

- [ ] Add `dist/elements/search-field.js` to each of the five harness lists, or
      the field is inert there.
- [ ] Check `e2e/test_quick_filter_e2e.py:329`, which asserts the overflow is
      hidden at 1400 px on sessions — a leading field plus a larger reserve can
      flip it. Restate it if the new arithmetic changes the answer.
- [ ] `make test-e2e ARGS="-k quick_filter"`, then the full gate.
- [ ] Commit.

---

## Assembling the stack

```bash
gh stack init
```

Members in order, each its own branch off the previous: `claude/1146-segmented-field`,
`claude/1146-search-q`, `claude/1166-builder-search`, `claude/1146-search-field`.
The spec and this plan ride on member 1.

```bash
gh stack submit
```

Then, once every member is green and reviewed, `gh stack merge` — atomic, merge
commits, so `main` never carries half the change. Never hand-roll the stack by
retargeting bases.

## The gate

Before submit, from the worktree:

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check
```

Read the exit code from the log, not a grepped line. `make check` includes
`e2e/`; `make check-fast` is for iterating and is not the gate.
