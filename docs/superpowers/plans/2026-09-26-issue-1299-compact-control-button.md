# A compact ControlButton — Implementation Plan

**Goal:** `ControlButton(size="compact")` replaces every hand-rolled box button.

**Spec:** `docs/superpowers/specs/2026-09-26-issue-1299-compact-control-button-design.md`.

## Global constraints

- Every size and tone string is a literal (Tailwind scans source).
- No two classes in one rendered string set one property.
- `SHAPE_CLASSES` and the generated TS stay byte-identical.
- Comments ≤7 words; complete-word identifiers; "remove", never "delete" in prose.
- Pytest under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`; no e2e while `make dev` runs.

### Task 1: size and tone in `control_button_class`

**Files:** `common/components/primitives.py`, `common/components/__init__.py`, `tests/test_control_height.py`, `tests/test_components.py`.

- `type ButtonSize = Literal["control", "compact"]`; `_SIZE_CLASSES`; `COMPACT_SHAPE_CLASSES`.
- Take `CONTROL_SIZE_CLASS` out of the four variant strings; `control_button_class(..., size=)` appends it.
- Ghost: `_GHOST_STILL_CLASS` + `_GHOST_TONE_CLASSES[(size, color is red)]`.
- `ControlButton(size=)`, kept as a look-fact beside shape (so `with_shape` keeps it).
- Docstring and CLAUDE.md bullet.
- Tests (fail first): compact string; shapes per size; red tone; a property-collision check over every (variant, color, size, shape); `test_control_height` asks control size only; `make gen-element-types` leaves `ts/generated/*` unchanged (`git diff --exit-code`).

### Task 2: the moved buttons

**Files:** `common/components/search_select.py`, `date_picker.py`, `date_range_picker.py`, `date_time_picker.py`, `filters.py`, `primitives.py` (YearPicker), `games/views/catalog_section.py` (no code; its test), tests.

- Clear ×: `ControlButton(variant="ghost", size="compact", class_="ml-auto -mr-1 shrink-0 peer-disabled:hidden", …)`; keep `hidden`, `aria-describedby`, `data-search-select-clear`.
- `_row_action`: compact ghost, red for remove, `class_="-my-1.5"`.
- Toggles/copy: compact ghost; `ms-auto` stays a caller class.
- Comparison remove: compact ghost red.
- YearPicker toggle: `ControlButton(color="blue" if year else "gray")`; drop chevron `ms-2`.
- Gotcha: `ControlButton` is a component; `Dropdown` stamping wants an `Element` — use `.as_element()` where a builder stamps it.
- Tests: each site renders the compact classes; row-action hooks and `tabindex="-1"` kept.

### Task 3: `AvatarButton` and the guard

**Files:** `common/components/navigation.py` (or `primitives.py`), `__init__.py`, `tests/test_button_guard.py` (new).

- Move the account trigger into `AvatarButton(*, initials, username)`.
- AST walk over `common/`, `games/`: refuse `Button(...)` (any alias of `common.components.elements.Button`) and `Element("button", ...)` outside the allow list (function qualnames).
- Test that the allow list names only existing functions.

### Task 4: verify

- `make test-ts`, focused pytest, then e2e: row 36px, clear × and toggles 32px, date-time field in its column.
- Before/after screenshots (picker rows, date-time field, year picker, catalog red ghost), both themes.
- `make format`, `make lint-fix`, `make vale`, full `flock … make check` with the dev server stopped.
