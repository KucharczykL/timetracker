# Raw palette in Python class strings — Implementation Plan

**Goal:** One colour guard over the Python and TS files the size guard walks; every raw palette string there is a token or a marked deliberate hue.

**Architecture:** `tests/test_color_tokens.py` reuses `guarded_files()` from `tests/test_typography_tokens.py`. The pattern gains `white|black`. Strings move to tokens; deliberate hues carry `# color-ok:`.

**Spec:** `docs/superpowers/specs/2026-10-07-issue-982-views-palette-tokens-design.md`

## Global constraints

- Iterate with focused `make test ARGS=…` under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Before commit: `make format`, `make lint-fix`, `make format-check`, `make vale`, each its own call, read by exit code.
- `icons_generated.py` is never edited by hand: `make gen-icons`.
- Inline, TDD. The guard test is the red test for Tasks 2–4.

---

### Task 1: The guard

**Files:** `tests/test_color_tokens.py`

- Import `guarded_files` (beside `REPO`, `ts_files`) from `test_typography_tokens`.
- `RAW_COLOR`: alternation of the hue branch (`-(?:HUES)-\d{2,3}(?![\w])`) and
  a white/black branch (`-(?:white|black)(?![\w-])`). Optional `/opacity`
  needs nothing: `/` is neither `\w` nor `-`.
- Self-check hits add `dark:text-white`, `bg-black/10`, `border-l-white/30`;
  misses add `text-whitesmoke`, `solid-brand`, `text-heading`.
- Replace `test_no_raw_palette_colors_in_ts` by
  `test_no_raw_palette_colors` over `guarded_files()`; skip lines holding
  `color-ok` (`# color-ok:` / `// color-ok:`).
- Keep the `ts_files()` vacuous-pass test; add one for the Python half
  (some yielded path ends `.py`).
- Docstring: scope is the size guard's set; markers in both comment forms.

Run `make test ARGS="tests/test_color_tokens.py"`: expect FAIL listing about 60 lines (37 in `icons_generated.py`). That list is the worklist.

### Task 2: Icons carry no root class

**Files:** `games/management/commands/gen_icons.py` (`_emit_node`, the `tag == "svg"` branch), `common/components/icons_generated.py` (regenerated), `common/components/primitives.py` (`Icon()` ~2915, comment block ~2860), test in `tests/test_components.py` beside the icon tests (~700–725).

- Test first: no `ICON_NODES` root carries a `class` attribute
  (`[key for key, _ in node.attributes]`; check `Element`'s attribute field name in `common/components/core.py`).
- `_emit_node`: at the root (`tag == "svg"`) drop `class` from `attributes`.
- `make gen-icons`; confirm `git diff --stat` touches only the class tuples.
- `Icon()`: drop the `key != "class"` filter only if nothing else could carry
  one; caller `class` handling stays. Reword the docstring and the comment
  block (no "overriding whatever each snippet baked in").
- Gotcha: `tests/test_components.py:713` (`w-3 h-3 rotate-180` absent) still
  passes; leave it.

### Task 3: `common/` strings

**Files:** `common/components/primitives.py`, `common/components/custom_elements.py`, `common/components/filters.py`, `common/components/domain.py`, `tests/test_components.py`, `docs/visual-conventions.md`, `CLAUDE.md`.

1. Green `ControlButton` (`_FILLED_COLOR_CLASSES["green"]`, `_SEGMENTED_COLOR_CLASSES["green"]`):
   `text-white` → `text-fg-on-success`, `hover:text-white` → `hover:text-fg-on-success`;
   the `emerald-800` lines take `# color-ok: dark success scale stops at emerald-700`.
2. Comment ~2868 naming `text-white`: reword ("the button's text colour").
3. `SplitButtonDropdown` caret: `border-l-white/30` → `border-l-current/30`.
4. `DropdownDivider`: marker on the `bg-black/10` line.
5. `filters.py` `_CHIP_STATE_CLASSES`: marker on each raw line (7).
6. `domain.py` `_STATUS_COLORS`: marker on each entry (6).
7. Remove `plain`: `ButtonVariant` literal entry (~175), `_PLAIN_VARIANT_CLASS`,
   the branch (~1024), docstring lines (~1110, ~1123), comment
   `custom_elements.py:837`; tests `test_plain_variant_is_the_navbar_nav_link_look`,
   `test_plain_variant_ignores_align`, `"plain"` in the shape loop (~1383),
   comment ~1212. `grep -rn '"plain"\|plain variant\|variant="plain"' common games tests e2e ts docs CLAUDE.md` must come back empty of the variant.
8. Docs: `docs/visual-conventions.md` §1 opt-out list (Python ones beside
   `filter-group.ts`), §6 variant list, §7 guard paragraph; CLAUDE.md
   `ControlButton` variants line drops `plain`.

Gotcha: `ruff format` may move a trailing comment off an implicitly
concatenated string line; run `make format` and re-read the dicts. Markers are
prose `make vale` reads.

### Task 4: View strings

**Files:** `games/views/game.py`, `games/views/stats_content.py`, a test in `tests/test_rendered_pages.py` or the Game detail view test file.

- `game.py:786` `text-slate-500` → `text-body-subtle`.
- `game.py:1084` drop `dark:text-slate-400`.
- `game.py:1470` and `stats_content.py:539` drop `dark:text-white` (the
  wrapper `Div` keeps `flex flex-col gap-4` on Stats; the Game detail one is left classless).
- Title span (~1082): append `text-heading` after `text-type-title font-serif`.
- `_game_section` (~862): `table if count else P(class_="text-body-subtle")[empty_message]`.
  Match the note's type role (`text-type-body`) if the sentence renders at
  body size today — check rendered size by eye.
- Test: Game detail with an empty section renders the sentence inside an
  element carrying `text-body-subtle`; the title carries `text-heading`.

Then: `make test ARGS="tests/test_color_tokens.py tests/test_components.py tests/test_rendered_pages.py tests/test_custom_elements.py"` green. `make css`.

### Task 5: Eye check

Dev server (`make dev` via preview tools; no e2e while it runs). Game detail
with sessions and with empty sections, Stats page, navbar Recent games split
button, a green button. Light and dark. Screenshot to the user; adjust on
their word. Then the docs sweep and the full gate per the skill.
