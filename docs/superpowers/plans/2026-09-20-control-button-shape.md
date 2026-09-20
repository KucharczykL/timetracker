# ControlButton shape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `ControlButton` a `shape` parameter so every button states its own corners, and no call site states rounding by class.

**Architecture:** `control_button_class()` emits exactly one `rounded-*`, chosen by a new `shape` argument; no variant string holds one. Joined rows (ButtonGroup, PageTabs, SplitButtonDropdown, the calendar's day grid) state each member's shape from the position they already know, replacing four parent selectors and one client-side override. A refusal in `ControlButton.__init__` makes "no caller states a corner" checked rather than documented.

**Tech Stack:** Python 3.14, Django 6, the `common/components` node system, Tailwind 4, TypeScript compiled per-module to `games/static/js/dist/`, vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-issue-1170-control-button-shape-design.md` — read it first. It carries the reasoning; this plan carries the moves.

## Global Constraints

- Work only in the worktree `/home/lukas/git/timetracker/.claude/worktrees/game-form-release-date-autofill-cc4ed5`. Never `cd` to the repo root.
- Everything through `make`. No `direnv exec .`, no raw `uv run` / `pnpm` / `pytest`.
- Never bare `git stash` / `git stash pop` — the stash stack is shared across worktrees.
- Iterate with `make check-fast`. The gate before any push is a full `make check`, wrapped: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`. Read the exit code from a log, never a grepped tail.
- Never run e2e while `make dev` is up.
- `ts/generated/` and `games/static/js/dist/` are gitignored. Run `make gen-element-types` after changing a published constant; never commit the output.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Merging is the user's word alone. Finishing a task does not authorize it.

## The stack

Four branches on top of `claude/game-form-release-date-autofill-cc4ed5` (PR #1168). Each is one `gh stack add <branch>` from the tip of the previous one, and each ends green on its own.

| Member | Branch | Deliverable |
|---|---|---|
| 1 | `claude/control-button-shape-1170` | the parameter, the six standalone sites, the refusal |
| 2 | `claude/split-button-shape-1170` | SplitButtonDropdown states both its ends |
| 3 | `claude/joined-rows-shape-1170` | ButtonGroup and PageTabs, the four selectors go |
| 4 | `claude/calendar-shape-1170` | the day grid states its own square |

Member 1's branch already exists and holds the spec commits.

## File structure

| File | Responsibility | Member |
|---|---|---|
| `common/components/primitives.py` | `ButtonShape`, `_SHAPE_CLASSES`, `shaped()`, `control_button_class`, `ControlButton`, `ButtonGroup`, `PageTabs`, `SelectionToggle` | 1, 3 |
| `common/components/__init__.py` | export `ButtonShape` | 1 |
| `common/components/custom_elements.py` | value selector, sheet dismiss, `SplitButtonDropdown` | 1, 2 |
| `common/components/sectioned_page.py` | section nav trigger | 1 |
| `common/components/library_kit.py` | row actions trigger | 1 |
| `common/components/temporal_field.py` | the copy button | 1 |
| `common/layout.py` | Log game split primary | 1, 2 |
| `games/views/game.py` | Played N times split primary | 1, 2 |
| `common/components/date_range_picker.py` | `CALENDAR_DAY_CLASSES` built square | 4 |
| `games/management/commands/gen_element_types.py` | publish `_SHAPE_CLASSES` | 4 |
| `ts/elements/date-calendar-core.ts` | `dayVariantClass` takes a shape | 4 |
| `ts/elements/date-range-picker.ts` | day cell states its shape | 4 |

---

### Task 1: The parameter and the invariant

**Branch:** `claude/control-button-shape-1170` (exists, currently at the spec commits)

**Files:**
- Modify: `common/components/primitives.py` — `ButtonShape`/`_SHAPE_CLASSES` beside `ButtonAlign`/`_ALIGN_CLASSES` (~line 781); `control_button_class` (~892); `ControlButton.__init__` (~969)
- Modify: `common/components/__init__.py` — export `ButtonShape`
- Test: `tests/test_components.py`

**Interfaces — Produces:**
- `type ButtonShape = Literal["full", "start", "end", "square"]`
- `_SHAPE_CLASSES: dict[ButtonShape, str]` mapping to `rounded-base` / `rounded-s-base` / `rounded-e-base` / `""`
- `control_button_class(*, color=..., variant=..., align=..., shape: ButtonShape = "full") -> str`
- `ControlButton(..., shape: ButtonShape = "full", ...)`

- [ ] **Step 1: Write the failing invariant test**

In `tests/test_components.py`, beside the existing `control_button_class` tests. It must fail today for `outline` and `segmented` (no class) and for `start`/`end`/`square` on every variant.

```python
def test_every_variant_and_shape_emits_exactly_its_shape_class(self):
    """A button states one corner set: the variant never adds a second and
    never omits the first. Nothing else in the suite would catch either."""
    from common.components.primitives import _SHAPE_CLASSES, control_button_class

    for variant in ("filled", "segmented", "outline", "ghost", "plain"):
        for shape, expected in _SHAPE_CLASSES.items():
            with self.subTest(variant=variant, shape=shape):
                emitted = {
                    word
                    for word in control_button_class(
                        variant=variant, shape=shape
                    ).split()
                    if word.startswith("rounded-")
                }
                self.assertEqual(emitted, set(expected.split()))
```

- [ ] **Step 2: Run it and watch it fail**

`make test-fast ARGS="tests/test_components.py -k every_variant_and_shape -x"`
Expected: FAIL — `control_button_class() got an unexpected keyword argument 'shape'`.

- [ ] **Step 3: Add the type and the table**

Beside `_ALIGN_CLASSES` in `common/components/primitives.py`. Give `ButtonShape` a `# e.g. "start"` comment in the style of the neighbouring aliases, and say in one line that the table states corners and never a radius.

- [ ] **Step 4: Take the rounding out of the three variant strings**

Remove `rounded-base` from `_FILLED_VARIANT_CLASS`, `_GHOST_VARIANT_CLASS` and `_PLAIN_VARIANT_CLASS`. Leave `_OUTLINE_VARIANT_CLASS` and `_SEGMENTED_VARIANT_CLASS` alone — they hold none.

- [ ] **Step 5: Append the shape in `control_button_class`**

Add the keyword-only `shape: ButtonShape = "full"`. Append `_SHAPE_CLASSES[shape]` to `parts` **only when it is non-empty**, so `square` leaves no trailing space in the `" ".join(parts)` — two exact-equality assertions in `tests/test_year_picker.py` and `tests/test_rendered_pages.py` compare these strings. The `plain` early return takes the shape too, appended to `_PLAIN_VARIANT_CLASS`.

- [ ] **Step 6: Thread it through `ControlButton.__init__`**

Add `shape: ButtonShape = "full"` beside `align` and pass it to `control_button_class`.

- [ ] **Step 7: Run the invariant test**

`make test-fast ARGS="tests/test_components.py -k every_variant_and_shape -x"`
Expected: PASS.

- [ ] **Step 8: Commit**

`feat: a button states its own corners`

---

### Task 2: The six standalone sites, and ButtonGroup's holding line

**Files:**
- Modify: `common/components/custom_elements.py` (value selector ~1294, sheet dismiss ~1082), `common/components/sectioned_page.py` (~124), `common/components/library_kit.py` (~216), `common/components/primitives.py` (`SelectionToggle` ~2646, `ButtonGroup` ~1113), `common/components/temporal_field.py` (~86)
- Test: `tests/test_components.py`

**Interfaces — Consumes:** `ControlButton(shape=...)` from Task 1.

- [ ] **Step 1: Drop the class from all six**

Each site loses its `rounded-base` and takes the `full` default — so it passes nothing. Four are `outline`; two (`sheet dismiss`, `library_kit` row actions) are `ghost` and their class was redundant already. Keep every other class the site carries (`w-full`, `py-2`, `focus:ring-inset`, `shrink-0`, `ms-auto`, `p-2`).

Delete the two now-false comments: the one above `SelectionToggle`'s class and the one above the copy button's in `temporal_field.py`. Both say outline bakes no shape.

- [ ] **Step 2: Give ButtonGroup its holding line**

In `ButtonGroup`, pass `shape="square"` to every member `ControlButton`. Without it, a member takes the `full` default and every middle button in a row rounds — Task 1 removed nothing from `_SEGMENTED_VARIANT_CLASS`, but the default now adds one. The parent selectors stay until Task 6.

Comment it as temporary: the row still rounds its own ends from the parent, and the member states no corner of its own yet.

- [ ] **Step 3: Run the component and page suites**

`make test-fast ARGS="tests/test_components.py tests/test_custom_elements.py tests/test_rendered_pages.py tests/test_quick_filter_bar.py"`
Expected: PASS. `tests/test_quick_filter_bar.py` finds a group by the exact opening `class="inline-flex rounded-base shadow-xs` — if it fails, `_GROUP_ENDS_CLASS`'s leading token order moved and must go back.

- [ ] **Step 4: Commit**

`refactor: six buttons stop stating their corners`

---

### Task 3: The split button's four sites, and the one visible change

**Files:**
- Modify: `common/components/custom_elements.py` (`SplitButtonDropdown` carets ~1209 and ~1213), `games/views/game.py` (~541), `common/layout.py` (~144)
- Test: `tests/test_rendered_pages.py`

- [ ] **Step 1: Flip the assertion that pins 16px**

`tests/test_rendered_pages.py` asserts `rounded-s-lg` for the Played N times button. Change it to `rounded-s-base` and run it — it must FAIL before the source moves.

`make test-fast ARGS="tests/test_rendered_pages.py -k rounded -x"`

- [ ] **Step 2: Move the four sites**

Both carets take `shape="end"`; the filled one drops `rounded-s-none` entirely, because a shape replaces rather than overrides. Both primaries take `shape="start"`: `games/views/game.py` drops `rounded-s-lg` (the 16px straggler #411 missed) and `common/layout.py` drops `rounded-s-base rounded-e-none`.

These stay caller-stated for now. Task 5 moves the knowledge into the builder.

- [ ] **Step 3: Rerun and confirm PASS**

- [ ] **Step 4: See it**

Start the server, open Game detail for a game with playthroughs, and screenshot the Played N times split button. Both halves must show the same 12px radius. Class names are not evidence here — a previous pass on this component shipped a 16px/12px mismatch that every test agreed with.

- [ ] **Step 5: Commit**

`fix: the split button rounds both halves alike`

---

### Task 4: Nothing states a corner by class

**Files:**
- Modify: `common/components/primitives.py` — `ControlButton.__init__`
- Test: `tests/test_components.py`

This lands last in member 1, once no caller states a corner. Landing it earlier breaks the sites Tasks 2 and 3 have not reached yet.

- [ ] **Step 1: Write the failing test**

```python
def test_a_caller_cannot_state_a_corner_by_class(self):
    """The parameter is the only way in. A caller class and a baked class
    both set the radius, and the stylesheet decides which wins, so the
    rule has to be refused rather than written down."""
    from common.components import ControlButton

    with self.assertRaises(TypeError) as refusal:
        ControlButton(class_="rounded-e-lg", variant="outline")["x"]
    self.assertIn("shape", str(refusal.exception))

    with self.assertRaises(TypeError):
        ControlButton([("class", "ms-auto rounded-base")])["x"]
```

- [ ] **Step 2: Run it and watch it fail** — both calls succeed today.

- [ ] **Step 3: Refuse it**

In `ControlButton.__init__`, after the attributes are merged, scan every `class` value for a `rounded-` word and raise `TypeError` naming the offending class and telling the caller to pass `shape=` instead. Raise where the caller that forgot is still on the stack, in the style of the existing `method="post"` csrf refusal.

- [ ] **Step 4: Fix the one test that now refuses**

`tests/test_components.py` builds an outline button with `rounded-e-lg` to prove a caller class survives. Rewrite it as `shape="end"` asserting `rounded-e-base`, and say in its docstring that the caller-class route is now refused.

- [ ] **Step 5: Gate and push member 1**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check 2>&1 | tee /tmp/check-m1.log; echo "EXIT=$?"
```
Read `EXIT` from the log. Then `gh stack submit`.

- [ ] **Step 6: Commit**

`feat: a caller states a corner only as a shape`

---

### Task 5: The split button states both its ends

**Branch:** `gh stack add claude/split-button-shape-1170`

**Files:**
- Modify: `common/components/custom_elements.py` — `SplitButtonDropdown` (~1180-1235)
- Modify: `common/components/primitives.py` — `ControlButton.with_shape()`
- Modify: `games/views/game.py`, `common/layout.py` — drop `shape="start"`
- Test: `tests/test_custom_elements.py`

**Interfaces — Produces:** `ControlButton.with_shape(shape: ButtonShape) -> ControlButton`, a clone that rebuilds the class attribute. `SplitButtonDropdown(primary: ControlButton, ...)`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_split_button_states_its_primary_shape(self):
    """A caller that had to remember `start` would render a primary rounded
    on four corners with a notch at the join, and nothing would say so."""
    from common.components import ControlButton, SplitButtonDropdown

    html = str(
        SplitButtonDropdown(
            primary=ControlButton(variant="outline")["Played 3 times"],
            id="played-1",
            aria_label="Playthrough actions",
            items=[],
        )
    )
    self.assertIn("rounded-s-base", html)
    self.assertIn("rounded-e-base", html)
    self.assertNotIn("rounded-base ", html.split("<a")[-1])
```

- [ ] **Step 2: Run it and watch it fail** — the primary today carries whatever the caller gave it, and this one gave nothing.

- [ ] **Step 3: Add the clone**

`ControlButton.with_shape(shape)` follows `__getitem__`: a new instance via `__new__`, `__dict__` copied, `_tree_cache` popped, and `_merged_attributes` rebuilt with a fresh `control_button_class(...)`. It must remember the `color`, `variant` and `align` it was built with, so store those on the instance in `__init__` rather than re-deriving them from the rendered class string.

- [ ] **Step 4: Type `primary` and shape it**

`SplitButtonDropdown`'s `primary` becomes `ControlButton`, and the builder calls `primary.with_shape("start")`. The carets take `shape="end"` as they already do.

Rewrite the docstring paragraph that explains which corners a filled caret must zero — it describes a rule that no longer exists.

- [ ] **Step 5: Fix the existing test that passes a Span**

`tests/test_custom_elements.py` passes `Span(class_="rounded-s-base")` as the primary. Build a `ControlButton` with no shape instead, and assert the builder supplied `rounded-s-base`.

- [ ] **Step 6: Drop `shape="start"` from both callers**

`games/views/game.py` and `common/layout.py` pass a bare `ControlButton` again.

- [ ] **Step 7: Gate, push, submit**

`make check-fast` first, then the full gate under `flock`, then `gh stack submit`.

- [ ] **Step 8: Commit**

`refactor: the split button owns both its ends`

---

### Task 6: The joined rows state their members' shapes

**Branch:** `gh stack add claude/joined-rows-shape-1170`

**Files:**
- Modify: `common/components/primitives.py` — `shaped()`, `_GROUP_ENDS_CLASS` (~1071), `ButtonGroup` (~1079-1145), `PageTabs` (~1169-1183)
- Modify: `ts/elements/date-range-picker.ts` — the comment at ~286-305
- Test: `tests/test_components.py`

**Interfaces — Produces:** `shaped[T](members: Sequence[T]) -> Iterator[tuple[ButtonShape, T]]`

- [ ] **Step 1: Write the failing tests**

Three cases, and the post-member case that the second selector pair exists for today:

```python
def test_a_joined_row_states_each_member_shape(self):
    """One member rounds both ends; the middle of three rounds neither."""
    from common.components.primitives import shaped

    self.assertEqual([shape for shape, _ in shaped(["a"])], ["full"])
    self.assertEqual([shape for shape, _ in shaped(["a", "b"])], ["start", "end"])
    self.assertEqual(
        [shape for shape, _ in shaped(["a", "b", "c"])],
        ["start", "square", "end"],
    )
    self.assertEqual(list(shaped([])), [])

def test_a_post_member_states_its_shape_on_its_button(self):
    """The form around a post member has inline-flex and nothing else — no
    border, no background — so the radius belongs on the button inside it."""
    from common.components import ButtonGroup

    html = str(
        ButtonGroup([
            {"slot": "First", "href": "/a"},
            {"slot": "Stop", "method": "post", "action": "/b", "csrf_token": "t"},
        ])
    )
    form = html[html.index("<form") :]
    self.assertNotIn("rounded-e-base", form[: form.index("<button")])
    self.assertIn("rounded-e-base", form[form.index("<button") :])

def test_a_skipped_member_is_not_an_end(self):
    """Entries with no slot are dropped before the row is counted — the
    game header emits empty dicts for members a state hides."""
    from common.components import ButtonGroup

    html = str(ButtonGroup([{}, {"slot": "Only", "href": "/a"}]))
    self.assertIn("rounded-base", html[html.index("<a") :])
```

- [ ] **Step 2: Run them and watch them fail** — `shaped` does not exist.

- [ ] **Step 3: Write `shaped`**

A generator over a `Sequence`, yielding `(shape, member)`. Empty yields nothing; one yields `full`. Import `Sequence` and `Iterator` from `collections.abc`. No call site holds an index or a count — that is the whole point of the signature.

- [ ] **Step 4: Rewrite ButtonGroup's loop**

Filter slot-less entries into a list first, then iterate `shaped(...)` over it, passing each shape to its `ControlButton` in place of Task 2's `shape="square"`. The filter predicate stays exactly `if not member or not member.get("slot", "")`.

- [ ] **Step 5: Take the four selectors out**

`_GROUP_ENDS_CLASS` keeps `inline-flex rounded-base shadow-xs` in that exact order and loses its two child selectors; `ButtonGroup`'s own `Div` loses the two `_button` descendant ones. Rewrite the comment that calls this the one documented styling-at-a-distance exception: the mechanism had already failed twice — once needing a second selector pair for form members, once unable to reach the split caret inside its `<drop-down>` wrapper.

- [ ] **Step 6: Shape the tabs**

`PageTabs` composes a class per tab already. Iterate `shaped(tabs)` and add `_SHAPE_CLASSES[shape]` to each tab's class string. This is not optional: the tabs take every corner they have from the selectors Step 5 removed, so skipping it ships square tabs on the Playtime page and the game sections.

- [ ] **Step 7: Rewrite the TypeScript comment**

`ts/elements/date-range-picker.ts` states that a member cannot know its own position and that removing one override is not worth a parameter on a shared primitive. Both are now false. Leave the code — Task 7 changes it.

- [ ] **Step 8: Run the suites, then look at the pages**

`make test-fast ARGS="tests/test_components.py tests/test_quick_filter_bar.py tests/test_playtime_page.py tests/test_rendered_pages.py"`

Then screenshot a page holding a `ButtonGroup` (a game header) and one holding `PageTabs` (Playtime). Both must be pixel-unchanged. This task's whole claim is zero visual difference, and only the screen can say so.

- [ ] **Step 9: Gate, push, submit, commit**

`refactor: a joined row states its members' corners`

---

### Task 7: The calendar states its own square

**Branch:** `gh stack add claude/calendar-shape-1170`

**Files:**
- Modify: `common/components/date_range_picker.py` — `CALENDAR_DAY_CLASSES` (~104-121)
- Modify: `games/management/commands/gen_element_types.py` — a fifth `TsConstant` (~98)
- Modify: `ts/elements/date-calendar-core.ts` — `dayVariantClass` (~35)
- Modify: `ts/elements/date-range-picker.ts` — `dayCellClass` (~273-320)
- Test: `tests/test_date_range_picker.py`, `ts/elements/date-range-picker.test.ts`

**Interfaces — Produces:** `BUTTON_SHAPE_CLASSES` in `ts/generated/calendar-classes.ts`; `dayVariantClass(variant: DayVariant, shape?: ButtonShape)`.

- [ ] **Step 1: Flip the Python test**

`tests/test_date_range_picker.py::test_every_day_variant_is_rounded` asserts `rounded-base` in every variant. It becomes `test_every_day_variant_is_square`, asserting no `rounded-` word appears in any variant. Keep its docstring's reasoning — rounding, fill and dimming stay orthogonal — and add that the corner now comes from the client, which is the only thing that knows where a run ends.

Run it; it must FAIL.

- [ ] **Step 2: Build the four variants square**

Every `control_button_class(...)` call in `CALENDAR_DAY_CLASSES` takes `shape="square"`. Rerun; PASS.

- [ ] **Step 3: Publish the table**

Add `TsConstant("BUTTON_SHAPE_CLASSES", dict[str, str], _SHAPE_CLASSES)` to the `calendar-classes.ts` target in `gen_element_types.py`, importing `_SHAPE_CLASSES` from `common.components.primitives`. Run `make gen-element-types` and read the generated file to confirm all four keys arrived, `square` among them as an empty string.

- [ ] **Step 4: Write the failing vitest**

In `ts/elements/date-range-picker.test.ts`. Every cell carries exactly one rounding: a day inside a run is square, each endpoint rounds the edge away from the run, a day outside rounds fully.

```ts
it("gives every day cell exactly one corner set", () => {
  const rounding = (classes: string) =>
    classes.split(" ").filter((word) => word.startsWith("rounded-"));

  expect(rounding(dayVariantClass("default"))).toEqual(["rounded-base"]);
  expect(rounding(dayVariantClass("default", "square"))).toEqual([]);
  expect(rounding(dayVariantClass("selected", "start"))).toEqual([
    "rounded-s-base",
  ]);
});
```

- [ ] **Step 5: Take the shape in `dayVariantClass`**

`dayVariantClass(variant, shape: ButtonShape = "full")` appends `BUTTON_SHAPE_CLASSES[shape]` when non-empty. The single-date picker's two calls in `date-calendar-core.ts` pass nothing and keep `full`.

- [ ] **Step 6: Make the range picker additive**

In `dayCellClass`, replace the three pushes with the shape the same branches already decide:

| Today | Shape |
|---|---|
| interior day pushes `rounded-none` | `square` |
| `isoString === track[0]` pushes `rounded-e-none` | `start` |
| `isoString === track[1]` pushes `rounded-s-none` | `end` |
| no track | `full` |

Compute the shape first, pass it to `dayVariantClass(variant, shape)`, and keep the track's own `track[2]` push — that is fill, not a corner. Rewrite the comment block: it now says the client states the corner because a range is defined by data, wrapping across week rows, so the run's ends are not the grid's ends.

- [ ] **Step 7: Run vitest and the Python suite**

`make test-ts` then `make test-fast ARGS="tests/test_date_range_picker.py tests/test_year_picker.py"`.

- [ ] **Step 8: See a selected range**

Open a page with a date range filter, select a run spanning two week rows, and screenshot it. The interior days must read as one continuous bar with square joins, and both endpoints must round only their outer edge. A run that wraps is the case the whole exemption argument was about.

- [ ] **Step 9: Gate, push, submit, commit**

`refactor: the calendar states its own corners`

---

## Closing out

- [ ] `gh stack view` shows five members, PR #1168 at the bottom.
- [ ] Comment on #1170 naming what landed and that #1177 (the `plain` variant with no caller) came out of it.
- [ ] Do not merge. `gh stack merge` is atomic and takes every member below the one picked — the user says when.
