# Uncommitted single-select combobox cue (issue #450)

Date: 2026-07-20
Issue: #450 — follow-up to #443 / PR #449.

## Problem

Under the pick-only contract (#449), the first edit of a committed single-select
clears the hidden input immediately (`search-select.ts` input handler:
`pills.innerHTML = ""` + `emitChange(null)`), and blur never rewrites the box
text. The box can therefore display text that looks exactly like a committed
label while the form value is empty:

- Nullable fields (Device, Platform): the form silently saves NULL.
- Required fields (session Game, DLC related_game): validation error on save,
  typed text lost on redisplay.

A screen reader user is hit hardest: the combobox reads back its text either
way, so there is no channel at all through which to learn the value was
dropped.

## Decision

Flag the anomalous state — non-empty box text with no committed value — through
two independent channels: a wordless visual "draft" motif for sighted users and
a permanently screen-reader-only status text for assistive tech. The healthy
committed state stays pixel-identical to today.

Design discussion (2026-07-20) considered and rejected: a committed-state ✓
badge (permanent chrome, dies in forced-colors mode, needs an sr-only shadow
copy), a bare green check (reads as "validation passed"), a visible
"not selected" text hint (visual clutter; the sr-only + wordless split was
preferred), a dotted underline (reads as a spellcheck squiggle), and rendering
the committed value as a multiselect-style pill (reverses the #449 label-in-box
contract).

## Scope

| Site | Gets the cue? |
| --- | --- |
| Form single-selects via `SearchSelectWidget` (~7 fields: Game, Device, Platform, related_game, purchase platform, …) | yes — via the adapter, one place |
| Filter builder field picker | no |
| Field-comparison column pickers | no |
| Preset picker (`PresetSelect`, separate markup) | structurally unaffected |
| Multi-select / filter-mode widgets | out of scope (pills already signal state) |

Mechanism: new keyword `committed_marker: bool = False` on the `SearchSelect`
component (`common/components/search_select.py`). `SearchSelectWidget`
(`games/forms.py`) passes `committed_marker=True` for its single-select
renders. Any individual site can be flipped later via the kwarg.

## Behavior contract

The widget is **uncommitted** when the search box holds non-empty text and
`[data-search-select-pills]` holds no hidden input. State transitions:

- Committed → first edit keystroke: value is dropped (existing #449 behavior);
  container gains `data-uncommitted`; status span text is set.
- Pick (click / Enter / `setSelected`): attribute removed; status span emptied.
- Clear (empty box, blur-deselect, `_searchSelectClear`): attribute removed
  (box is empty — placeholder shows; no cue).
- Initial render: server never renders the attribute (a committed selection or
  an empty box are the only server-render states).

Empty box + no value shows no cue: the placeholder already communicates
"nothing here". The cue exists only when text could masquerade as a value.

## Visual cue (CSS only, gated on `[data-uncommitted]`)

All three cues are shape-based (WCAG 1.4.1 — never color-alone) and survive
forced-colors mode; all three disappear while the widget is focused, because
the existing `focus-within:border-brand` + ring overrides the border and a
`:focus-within` rule hides the marker span — the user is mid-pick, the cue is
for the at-rest trap.

1. **Box text**: muted + italic. Reuses the existing placeholder color token
   (`text-body`) — already APCA-audited, and carries the right semantics: the
   text reads like a placeholder because that is effectively what it is.
2. **Field border**: dashed (same width/color slot, `border-style` change
   only) — the whole-field "draft" frame.
3. **Pencil glyph**: `Icon("edit")` (already in the icon set, `currentColor`)
   in the marker span at the right edge of the flex row, muted, `aria-hidden`.
   Long text wraps it to a second row and the field grows via `min-h`, same as
   multiselect pill wrapping.

## Assistive channel

The marker span contains (alongside the aria-hidden glyph) a **permanently
sr-only** text node: "No option selected". Wiring:

- `role="status"` on the sr-only element: the committed→uncommitted transition
  happens mid-typing, and a polite live region announces it as it happens. JS
  fills/empties the text content on transition (an always-present static text
  would never fire; content must change).
- `aria-describedby` from the combobox `<input>` to the sr-only element: every
  subsequent focus of the field re-announces the state. The id must be
  JS-assigned at init (never server-rendered) — the filter builder clones
  whole `<search-select>` prototypes, same reason as the listbox ids (#154).

No visual/ARIA coupling: the sr-only element never becomes visible, the visual
cues carry no text. The `:focus-within` visual suppression therefore cannot
break the announcement (the element stays in the accessibility tree).

## Server rendering

When `committed_marker=True` and the widget is single-select, `SearchSelect`
renders the marker span (glyph + empty sr-only status node) as a child of the
container, after the search input. When the kwarg is off (default) the span is
absent and the JS state attribute is inert — zero behavior change for filter
builder, comparison pickers, and preset picker even though they share the JS.

The JS toggles `data-uncommitted` only for form-mode single-selects
(`!multi && !filter` — the only mode where a committed hidden input is the
state; filter widgets have no hidden inputs and would always read as
uncommitted). The CSS + rendered span make it visible; the sr-only status text
is only wired (describedby + content updates) when the span exists.

## Testing

- **Vitest** (`ts/elements/search-select.single-select.test.ts` +
  `search-select.aria.test.ts`): attribute lifecycle across the transitions
  above; status span content set/emptied; `aria-describedby` id assignment and
  uniqueness across clones; no attribute churn for multi/filter modes.
- **Python** (`tests/test_search_select.py`, `tests/test_components.py`):
  marker span rendered iff `committed_marker=True` and single-select;
  `SearchSelectWidget` passes the kwarg; filter/preset markup unchanged.
- **e2e** (`e2e/test_search_select_e2e.py`): the #450 scenario — commit Device,
  re-type the same label without picking, assert `data-uncommitted` present and
  dashed border computed style at rest; pick again → cue gone. Existing #449
  suite must stay green untouched (committed state is pixel-identical).

## Out of scope

- Any change to commit/clear semantics (#449 contract is untouched).
- Blocking or warning on form submit — the cue is informational only.
- Filter builder / comparison picker adoption (flip the kwarg later if wanted).
