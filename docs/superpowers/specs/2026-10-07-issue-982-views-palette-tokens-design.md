# Raw palette in Python class strings (#982)

## Problem

`tests/test_color_tokens.py` guards `ts/` alone. Its docstring says `common/`
is mid-migration, so a Python guard belongs to #404–#409. Those six issues are
closed. Python class strings still carry raw palette, and nothing refuses a new
one: #968 shipped `text-black dark:text-slate-300` in a view and a person caught
it.

The issue listed eleven strings. The purchase wave rewrote
`games/views/purchase.py` and `ContentContainer` is gone, so four remain in
`games/views/`, plus stragglers in `common/components/` the token migration left.

## Decisions

### One guarded set for size and colour

The size guard (`tests/test_typography_tokens.py`) already walks `GUARDED`
(`common/components`, `common/layout.py`, `games/forms.py`, `games/views`) and
`ts/` through `guarded_files()`. The colour guard walks the same set. One list
states which files carry class strings; a second list would drift from it. A
scan of every `.py` in `games/`, `common/` and `timetracker/` (migrations and
`icons_generated.py` aside) finds no raw palette outside `GUARDED`, so the set
needs no widening.

### The pattern also matches white and black

`RAW_COLOR` requires a numeric stop, so `dark:text-white` passes it. That is the
shape of two of the four view strings. The pattern gains `white|black` with no
stop and an optional `/opacity`. The self-check states both.

### Generated icons carry no class

`common/components/icons_generated.py` sits inside `common/components`, and 35
of its 68 root `<svg>` nodes carry `text-black dark:text-white` and two more
carry `dark:text-white`, copied from the snippets in `games/templates/icons/`. The class is dead: `Icon()` drops a
snippet's root `class` and states `ICON_BASE_CLASS` instead. `gen_icons` drops
the root `class` when it compiles a snippet, so the generated file holds none,
and `Icon()` stops filtering for it. No marker goes into a generated file.
`make check` runs `gen_icons --check`, so the regenerated file ships in the
same change. The comment above `ICON_BASE_CLASS` and the `Icon()` docstring
describe the filter and are reworded.

### Opt-out is `# color-ok: <reason>` per line

Same marker as `ts/`, Python comment form, same as `# type-ok:`. A line inside a
multi-line string carries its own marker. One rule, no block form: the guard
reads lines. Deliberate hues opt out:

- `common/components/filters.py` chip states (teal/orange/amber). §1 of
  `docs/visual-conventions.md` names them as staying.
- `common/components/domain.py` status dots. §1 names them as staying.
- `common/components/primitives.py` green `ControlButton`, filled and
  segmented: `dark:hover:*-emerald-800` has no token, because the dark success
  scale stops at `success-strong` (emerald-700).
- `common/components/custom_elements.py` `DropdownDivider`: translucent black
  hairline over a white highlight, an engraving rather than a surface colour.

### Exact tokens where one exists

- Green `ControlButton`: `text-white` → `text-fg-on-success`,
  `hover:text-white` → `hover:text-fg-on-success`. Both are white
  (`common/input.css`).
- `SplitButtonDropdown` filled caret: `border-l-white/30` →
  `border-l-current/30`. The hairline follows the caret's own text colour. Every
  filled colour but gray puts white text on the fill, so the one caller (the
  navbar's green Recent games) does not change. A gray filled caret would take
  a heading-coloured hairline; no caller passes gray.
- A comment in `primitives.py` names `text-white` in prose; it is reworded.

### The `plain` button variant is removed

`ControlButton(variant="plain")` has no caller in `common/`, `games/` or `ts/`.
The navbar's links use `_NAV_LINK_CLASS` in `common/layout.py`, already
tokenised. The variant, its class string, its branch and its docstring lines
go. In `tests/test_components.py` the two `plain` tests go, the shape loop
drops `"plain"` from its tuple, and a comment naming it is reworded. The
comment in `custom_elements.py` that names it, the variant list in
`docs/visual-conventions.md` §6 and CLAUDE.md's `ControlButton` list drop it.
`ButtonVariant` is not an element prop, so no TypeScript changes.

### View strings

- `game.py` status history `Li(class_="text-slate-500")` → `text-body-subtle`
  (gray-500 / gray-400).
- `game.py` stats row `dark:text-slate-400` → dropped; it inherits `text-body`,
  gray-400 in dark.
- `game.py` and `stats_content.py` page wrappers `dark:text-white` → dropped
  (user's choice). `Body` carries `text-body`, so both pages read like every
  other page. An element there that is a heading and states no colour takes
  `text-heading` itself. On Game detail that is the title
  (`_game_header`), which also moves light from gray-600 to gray-900; the
  class is appended, because `tests/test_rendered_pages.py` pins
  `text-type-title font-serif`. The empty-section sentence is a bare `str`
  in `_game_section`; that one function wraps it in a `P` with
  `text-body-subtle`, as the section note beside it does. A table cell's
  "No releases yet." stays a cell. Table cells on both pages state no
  colour, so in dark every cell value moves from white to gray-400, as on
  every list page. That is the intended outcome. Both pages are checked by
  eye in the dev server, both themes, before the gate.

### Docs

`docs/visual-conventions.md` contradicts itself in §7: one line says the colour
guard walks Python and `ts/`, the next says `ts/` alone. §7 now says both guards
walk one set and names `# color-ok:`; §1 lists the Python opt-outs beside
`filter-group.ts`. The docstring of `tests/test_color_tokens.py` follows.

## Tests

- Self-check: `dark:text-white`, `bg-black/10`, `border-l-white/30` match; `text-heading`,
  `solid-brand`, `text-whitesmoke` do not. White and black end at
  `(?![\w-])`, so a longer name never matches and `/opacity` still does.
- `test_no_raw_palette_colors` over `guarded_files()`, replacing the `ts/`-only
  test. Vacuous-pass guard kept for both halves.
- `tests/test_components.py` loses the `plain` tests and the loop entry.
  `tests/test_custom_elements.py` pins `bg-black/10` on the divider, which
  keeps it under its marker.
- A `gen_icons` test: no generated root node carries `class`.
- `# color-ok:` reasons are comments `make vale` reads; they use no refused
  word.
- Known gap: arbitrary values (`bg-[#fff]`) pass the pattern. None exist.

## Follow-up issues to file

None. The scan found nothing outside the guarded set.
