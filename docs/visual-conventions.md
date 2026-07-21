# Visual conventions

Synthesis of the five read-only audits ([#399](https://github.com/KucharczykL/timetracker/issues/399)
surfaces & borders, [#400](https://github.com/KucharczykL/timetracker/issues/400) radius/spacing/widths,
[#401](https://github.com/KucharczykL/timetracker/issues/401) rail & two-pane precedents,
[#402](https://github.com/KucharczykL/timetracker/issues/402) button/badge/table conventions,
[#403](https://github.com/KucharczykL/timetracker/issues/403) type scale) run for
[#398](https://github.com/KucharczykL/timetracker/issues/398). Records the **final call per
dimension** — adopt-as-is vs normalize app-wide — and the follow-up migration issues spawned
where the call is "normalize". Full evidence (per-file counts, line references, WCAG contrast
tables) lives in the child issues; this doc keeps only the values, the calls, and the conflicts.

Primary consumer: the settings UI kit (#384). But the calls are app-wide conventions, not
settings-only.

## Headline

The app is mid-migration between styling generations. The newest components — the
**date-range picker and search select** — have already converged on one coherent language:
Flowbite semantic tokens (zero `dark:` mirrors), a single `rounded-base` (12px) radius for
controls *and* panels, `px-3 py-2.5 text-sm` control rhythm, container-query sizing. Older
layers (primitives' buttons/tables/pagination, layout.py, custom_elements.py) hand-roll raw
`gray-*` with `dark:` bookkeeping; a third, dead generation (`.responsive-table`,
indigo/slate) survives on the stats page only.

**The target aesthetic is the newest generation: "looks like the date-range picker."** Every
normalize call below converges the rest of the app toward it.

## 1. Surfaces & borders — adopt semantic tokens; normalize raw palette

**Call: the Flowbite semantic-token vocabulary is the app's surface language.** New code
(including the whole settings kit) uses tokens only; raw-palette holdouts migrate via
follow-ups. Grounds (#399): the settings-like components are already fully semantic; ~85% of
raw uses have *exact* token equivalents (mapping table in #399 §5); tokens self-adapt to dark
mode, deleting the `dark:` mirror half of every class string; and the token text system is
WCAG-AA-clean in both themes (programmatically verified, `scripts/contrast_audit.py`).

Core vocabulary:

| Role | Token |
|---|---|
| Page background | `bg-neutral-primary` |
| Card / panel surface | `bg-neutral-primary-medium` |
| Elevated surface | `bg-neutral-primary-soft` |
| Control surface / zebra-even | `bg-neutral-secondary-medium` |
| Hover surface | `hover:bg-neutral-tertiary-medium` |
| Control border + dividers | `border-default-medium` |
| Structural rules (bars) | `border-default` |
| Text | `text-heading` / `text-body` / `text-body-subtle` |
| Accent / focus / links | `brand` family (`bg-brand`, `text-fg-brand`, `focus:ring-brand`) |
| Tinted callout | `bg-brand-soft` |

Decisions folded in:

- **Status hues: adopt the Flowbite status tokens.** Destructive red → `danger` (rose) —
  also improves dark button contrast 4.76 → 6.06. Positive green → `success` (emerald) —
  but the dark fill must be emerald-700 / `success-strong`, because emerald-600 fails AA
  (3.67) just like the current green-600 (3.22). Toasts move to the same families. Visible
  hue change, accepted.
- **Frosted dark dropdown** (`bg-white dark:bg-gray-800/40` + backdrop-blur) has no token
  equivalent → **add a custom token** (`--color-surface-overlay`) in `input.css` `@theme`,
  following the `--color-brand-soft` precedent. The blur stays a utility; only the color
  pair becomes vocabulary.
- **Control borders fail the 3:1 non-text threshold by design** (industry-standard gray,
  same as Flowbite/GitHub). Accepted — but no component may rely on the border *alone* to
  delineate a control; fill + label must differ too (they do today).
- **Nested depth = zebra parity, not a ramp** (#441, filter tree). To distinguish an
  arbitrarily-deep nesting level from its neighbour, alternate the two neutral surfaces by
  `depth % 2` (`bg-neutral-secondary-medium` / `bg-neutral-primary`), depth 0 on the
  non-page surface. Adjacency reads at *any* depth with only two fixed surfaces, so contrast
  stays flat (foregrounds are tuned to the page; an accumulating shade/opacity ramp drifts
  them out of contrast). Absolute depth is carried contrast-free by indentation + a stack of
  accent rails — not the background. Reusable for any nested UI (settings tree, etc.).
- Deliberately non-semantic and staying: filter logic-chip colors (teal/orange/amber,
  documented in `filters.py`), the filter-builder categorical accents that echo them —
  the AND/OR group left-edge rails (teal/orange) and a slim hue on the relation `↳`
  arrow + label (indigo) and scope label (teal); the relation/scope cards themselves are
  neutral and follow the depth zebra. Each raw hue is `// color-ok` in
  `ts/elements/filter-group.ts`. Also game-status dot palette, `font-alien` wordmark accent.

Known AA failures in shipped UI (pagination current-page, dark thead text, dark row-hover
text) are repaired inside the token migration, not separately — see follow-ups.

## 2. Corner radius — normalize to a two-tier scale

Reality check first (#400): the radius scale is **Flowbite's, not Tailwind's** —
`rounded-sm` = `rounded-md` = 6px (alias collision), bare `rounded` = 8px, `rounded-base` =
12px, and `rounded-lg` = **16px, the largest radius in the app** (Tailwind intuition reads
the ordering backwards).

**Call: two tiers.**

- **Interactive + surfaces** — controls, rows, cards, floating panels, modals: `rounded-base`
  (12px). Already the dominant value (22 uses) and the *only* radius the newest components
  use, panels included.
- **Chips/mini** — pills, badges, checkbox, micro-highlights: bare `rounded` (8px).
- Keep `rounded-full` (radio, dots, logic chips) and the one `rounded-xs` micro-highlight
  (date-segment focus, intentionally tighter inside a 12px field).

This retires `rounded-lg` (panels, toast, ButtonGroup/pagination edge rounding → `-base`
equivalents), `rounded-md` (dead container radius + Modal), and Badge's lone `rounded-sm`.

**Conflict resolution (chip radius):** #400 left "Badge → `rounded` or the reverse — pick
once" open. **Badge moves to `rounded` (8px); Pill is the anchor** — bare `rounded` already
owns the chip tier (14 uses: Pill, search-select pills, option rows, checkbox) against
Badge's lone `rounded-sm`. Note: #402's "Pill is byte-contract-locked" rationale turned out
stale — pills are cloned from server-rendered `<template>`s, the JS never names a class, so
`_PILL_CLASS` changes propagate automatically. The dominance argument decides; the stale
in-code contract comment gets fixed in the radius follow-up.

## 3. Spacing — adopt as-is

The dominant rhythm is real and coherent (#400): **`px-3 py-2.5 text-sm`** for controls, with
the container-query compact tier (`px-3 py-2 text-xs` → `@md:px-5 @md:py-2.5 @md:text-sm`)
for buttons; gap hierarchy `gap-0.5` micro / `gap-1` intra-chip / `gap-2` icon+label /
`gap-3` form-and-bar tier / `gap-4` row tier; panel padding progression `p-2` floating →
`p-4` cards → `p-5` page surfaces; section rhythm `mb-2` headings, `mb-3`/`mb-4` blocks,
`mt-1` panel offset.

**Call: adopt.** One rule made explicit for all new code: **parents own spacing via `gap`;
components never bake margins.** The `INPUT_CLASS mb-3` is the counter-example — inside
`gap-3` forms, text inputs double-space while selects don't. Stripping it is a follow-up;
the settings kit must not inherit the pattern.

Stragglers (textarea `p-3.5`, YearPicker fixed padding, FilterBuilder preset input compact
padding + 16px radius, navbar `md:space-x-8` + `rtl:space-x-reverse`) are mechanical
follow-up items — the `mb-3` strip and these strays landed in #412.

### Control height (#436)

The container-query control tier above (`px-3 py-2 → @md:px-5 @md:py-2.5`) is **superseded**.
Every interactive row-control — `ControlButton` (all variants), native inputs/selects
(`INPUT_CLASS`/`SELECT_CLASS`), `SearchSelect`, the field picker, the String/Number filter
inputs, dropdown triggers, `YearPicker` — floors to **one shared height**:
`min-h-control` (42px, from the `--height-control` theme token).

- **`min-height`, not fixed height** — single-line controls sit at exactly 42; a multi-pill
  `SearchSelect` still grows as pills wrap.
- **No vertical padding, no `@container` step.** Content centers via the `inline-flex`
  button base or native input/select centering, so height is independent of font
  (`text-type-input` 16px vs `text-type-body` 14px) *and* of any `@container` ancestor. A
  control is 42px in every row — the old cross-row 38-vs-42 inconsistency is gone.
- **Adopted at 42 too:** pagination page links, the NOT-AND connective chips, and `Pill`
  — they read as row-controls in their contexts, so they floor to the same height. (Their
  `rounded-full` / `rounded` corners still differ from the `rounded-base` controls — a
  radius concern for #411, not a height one.)
- **Exceptions** (deliberately smaller, not row-controls): textarea (multiline) and the
  heading `Badge` sizes.
- Guarded by `tests/test_control_height.py` (token generated, size constants carry
  `min-h-control`, `py-2.5` can't creep back onto a control).

## 4. Container widths — adopt as-is (already converged)

The one sub-dimension that is already what an audit hopes to find: two constants,
universally adopted, test-pinned —

- `CONTENT_MAX_WIDTH_CLASS = "max-w-7xl"` — every page body (`ContentContainer`), navbar row.
- `FORM_MAX_WIDTH_CLASS = "max-w-xl"` — every form-shaped surface (FormContainer, Modal,
  ConfirmPage, login).

Popover widths are a coherent 3-step scale: `w-44` menus / `w-72` list-dialogs (an explicit
knob) / `w-auto` intrinsic (calendar). **Call: adopt.**

Two real findings become follow-ups: **no horizontal page gutter** (below 1280px, content
touched the viewport edge — *resolved in #413*: `PAGE_GUTTER_CLASS = "px-4 sm:px-6"` on the
shell `#main-container` and the navbar row; tables sit inside the gutter, no exemption) and
the **dead `max-w-20char` class** (its `@utility` block is commented out; the stats
name-column cap silently does nothing).

## 5. Rail / two-pane / responsive machinery — calls for #384

The app has **no `position: sticky`, no two-pane layout, no scrollspy** anywhere (#401). The
settings scaffold's layout is net-new, but nearly all *behavior* exists. Calls recorded so
#384 doesn't relitigate:

- **Page frame:** a settings page is a normal `ContentContainer` child. The rail sits below
  the overlay z-scale (z-10 popovers + the standalone combobox panel → z-20 hosted dropdown
  panels → z-40 modal → z-50 toasts): no z class. Since the navbar scrolls away, a sticky rail needs no navbar-height coupling —
  `sticky top-*` + own `max-height`/`overflow-y-auto`, offset on the existing spacing scale.
- **Pane split idiom:** viewport-breakpoint grid with arbitrary tracks —
  `grid grid-cols-1 <bp>:grid-cols-[auto_1fr]` — extending the one existing column-split
  idiom (`filters.py` comparison row). Panes declare `@container` inside, so controls
  auto-size by available width (the `@md:` = 28rem contract). The split itself stays
  viewport-driven; container-driven splits are self-referential.
- **Overlay stack** (`anchored-position` / `menu-behavior` / `drop-down` / `pop-over` /
  `modal-dialog`): reuse unchanged for every chip dropdown, flyout, or future sheet. No new
  positioning code. The `<pop-over>` host carries `self-start` so a flex parent can't stretch
  it to full width — `positionAnchored` centres the fixed panel on the host, so a stretched
  host throws the panel far off the trigger (#446). Keep it when reusing popovers in flex rows.
- **Popover trigger** (`_popover_html`, #445): by default (`tap=True`) the trigger is a real
  `<button>`, so a tap toggles it on touch (mouse hover unchanged, pointer-type gated); it is a
  toggletip (`role="tooltip"` + `aria-describedby`, no `aria-expanded`). A popover nested inside
  a caller's interactive element uses `tap=False` (hover-only `<span>`) so no `<button>` nests
  in an `<a>` — enforced globally by `tests/test_html_validity.py`. When the popover *this*
  code wraps in a link needs touch reach, extract the trigger as a sibling ellipsis-icon button
  (`⋯`, replacing the name's truncation mark) via `preface=` (see `NameWithIcon` /
  `LinkedPurchase`): the whole host still opens on hover, but only the small button is tappable,
  keeping the trigger out of the link.
- **Priority-plus overflow** (quick-filter bar): the full recipe (measure-once, reserved
  furniture, ResizeObserver+rAF, move-don't-clone into a `<drop-down>` panel) is directly
  liftable for an anchor-chip nav — but the logic is private to `QuickFilterBarElement`.
  Extract-vs-replicate is **#384's decision**, made explicitly there (extraction touches a
  load-bearing tested element).
- **Navbar collapse** is the pattern precedent (same-DOM stacked↔inline reflow), not a code
  precedent — its mechanic is legacy Flowbite `data-collapse-toggle` + raw palette +
  viewport breakpoints. New responsive behavior is custom elements + container queries.

## 6. Buttons, badges, form rows, tables — adopt the APIs; normalize the strings

Calls from #402:

- **ControlButton: adopt as-is.** Variants (filled/segmented/outline/ghost/plain),
  polymorphism (`href=` → `<a>`, `method="post"` → form submit), `@container` sizing, and
  the `DISABLED_CONTROL_CLASS`/`DISABLED_WITHIN_CLASS` contract are exactly what settings
  rows need. **No new variant, no new color.** A locked settings field = real `disabled`
  attribute + badge, not a new look. Panes that want comfortable sizing declare
  `@container`; that is the whole sizing API.
- **Badge: adopt + extend with a `tone=` parameter** (its own class table, mirroring the
  size table; `brand-soft` default so existing call sites are untouched; semantic tokens
  from day 1). `extra_class="bg-…"` overrides are indeterminate (stylesheet-order, not
  attribute-order) — hence a real parameter. Tighten `size` to a `Literal` in the same
  touch. **Pill: leave alone** — it carries JS hooks (`data-pill`, remove button, label
  slot); Badge is the static, hook-free chip and the right settings-badge base. (Pill *can*
  be restyled if ever needed — its classes live server-side only, cloned into JS pills via
  `<template>` — the in-code "byte-for-byte contract" comment overstates and gets corrected
  in the radius follow-up.)
- **Form rows: adopt the whole path** — `PrimitiveWidgetsMixin` → `FormFields` → `AddForm`
  (`gap-3` column). Settings forms subclass the mixin and inherit the control look, disabled
  state, row layout, and container upsizing for free. The `extras` mapping is the ready-made
  insertion point for source badges / help text. Normalize separately: `_FIELD_ERROR_CLASS`
  (raw red/slate, hardcoded `w-[300px]`, unstyled 16px text — three conventions violated in
  one string) and the `INPUT_CLASS mb-3` (§3).
- **Tables: settings rows are mostly not tables** — label + control + badge + help is the
  form-row shape. Where a list is genuinely tabular, echo the `StyledTable` family
  *post*-normalization (its zebra/chrome have exact token equivalents; its light-mode hover
  is currently invisible on even rows — `hover:bg-gray-50` equals the even stripe — fixed in
  the token migration by hovering to the distinct `neutral-tertiary-medium`).
  **`.responsive-table` is a dead end** (third color generation, styling-at-a-distance,
  one consumer): migrate the stats tables to `StyledTable` and delete the CSS block.

## 7. Type scale — canonical token reference

The type scale is defined by ten `text-type-*` Tailwind utilities whose size, weight,
line-height (and where applicable letter-spacing) are pinned in `common/input.css` `@theme`.
See the full design rationale in
[`docs/superpowers/specs/2026-07-19-typography-token-system-design.md`](superpowers/specs/2026-07-19-typography-token-system-design.md).

### Token table

| Token | px | Weight | Line-height | Notes |
|---|---|---|---|---|
| `text-type-title` | 30 | 700 | 2.25rem | tracking −0.025em |
| `text-type-heading` | 24 | 700 | 2rem | |
| `text-type-dialog` | 24 | 500 | 1.5rem | dialog/modal titles |
| `text-type-subheading` | 20 | 700 | 1.75rem | |
| `text-type-section` | 18 | 600 | 1.75rem | settings-kit section and field-group headings |
| `text-type-body` | 14 | 400† | 1.25rem | default body / table cells |
| `text-type-label` | 14 | 500 | 1.25rem | form labels |
| `text-type-micro` | 12 | 400† | 1rem | |
| `text-type-micro-caps` | 12 | 500 | 1rem | uppercase, tracking +0.025em |
| `text-type-input` | 16 | 400† | 1.5rem | all focusable text-entry controls |

† 400 = inherited default; these tokens emit no `font-weight` — compose `font-*` to override.

### Usage rule

**Use `text-type-*` for font size.** Compose color (`text-heading` / `text-body` /
`text-body-subtle`) and weight (`font-*`) as separate utilities. Never write a raw
`text-<size>` utility (e.g. `text-sm`, `text-xs`) in a component — the grep-guard test
`tests/test_typography_tokens.py` enforces this across `common/components/`, `common/layout.py`,
`games/forms.py`, and `games/views/`. The wordmark (`font-alien`, viewport-scaled) is the one
sanctioned exception, annotated `# type-ok: <reason>` on its line. Brand accents that keep a
non-default family (the serif game-/purchase-detail names) compose `font-serif` alongside a
size token — they are not exceptions.

**Guards scan `.py` and `ts/` (#441).** The size guard (`tests/test_typography_tokens.py`) and
the color guard (`tests/test_color_tokens.py`) walk both Python source and `ts/**/*.ts`
(excluding `*.test.ts` and `ts/generated/`), so class strings hardcoded in TS are covered too —
the whole TS layer silently drifted before #441 (raw `text-sm`, raw `gray-*`, off-tier radius;
surfaced by the filter-tree `Choose a field…` placeholder). Opt a line out with
`# type-ok:` / `// type-ok:` (size) or `// color-ok:` (a deliberate categorical hue — color
guard). The **color guard is `ts/`-only**: `common/` still carries raw palette mid-migration
(#404–#407), so a `.py` color guard belongs to those issues.

### Notes

- **Inputs are flat 16px (`text-type-input`).** All focusable text-entry controls
  (`<input>`, `<select>`, `<textarea>`) use `text-type-input` so mobile renders 16px — below
  16px, iOS Safari auto-zooms the field on focus and overflows the viewport (#427). Every
  `PrimitiveWidgetsMixin` field inherits this; a bare input outside the mixin must also use
  `text-type-input`. Do **not** work around this by locking the viewport
  (`maximum-scale` / `user-scalable=no`) — that fails WCAG 1.4.4.
- **`text-type-section` is the settings-kit section heading** introduced by #384. Its real
  consumers live in `common/components/settings_kit.py`, so it is discovered normally by
  Tailwind and needs no `@source inline` safelist.
- **`font-condensed`** (`IBM Plex Sans Condensed`) is the dense-UI font family used by
  Badge and dense list surfaces (names, `tbody`). It is separate from the `text-type-*` size
  tokens; apply it alongside the appropriate size token where space is tight and text is
  scannable.
- Leave alone: `font-serif` name accents, `font-alien` wordmark.
- `font-mono` for tabular figures (stats values, date-picker field) is a style choice, not a
  column-alignment mechanism — Plex sans/condensed digits are already tabular.

## Kit vocabulary summary (for #384)

Surfaces `neutral-primary` (page) / `neutral-primary-medium` (card) /
`neutral-secondary-medium` (controls); borders `border-default-medium` (controls, dividers) /
`border-default` (structural); text `text-heading` / `text-body` / `text-body-subtle`;
accent `brand` family; callouts `brand-soft`; status `danger`/`success`/`warning` families.
Radius `rounded-base`, chips `rounded`. Rhythm `px-3 py-2.5 text-sm`, compact tier via
`@container` + `@md:`; parent `gap`, no baked margins. Widths `CONTENT_MAX_WIDTH_CLASS` /
`FORM_MAX_WIDTH_CLASS` / `w-72` dialogs. Components: ControlButton, Badge(+tone), the
mixin→FormFields→AddForm path, StyledTable for tabular lists, the overlay stack. New color
pairings clear `scripts/contrast_audit.py` before landing.

## Follow-up migration issues (outside the epic)

Spawned at synthesis; the epic depends on the *calls* above, not on these landing.

| Issue | Content |
|---|---|
| [#404](https://github.com/KucharczykL/timetracker/issues/404) | primitives.py A: tables + pagination + stragglers → tokens; contrast repairs rider (pagination current-page, dark thead, dark row-hover); fix even-row hover; normalize `_FIELD_ERROR_CLASS` (danger tokens, `w-full`, `text-sm`) |
| [#405](https://github.com/KucharczykL/timetracker/issues/405) | primitives.py B: ControlButton color tables → tokens (red→rose, green→emerald with `success-strong` dark fill); add missing outline/ghost focus rings |
| [#406](https://github.com/KucharczykL/timetracker/issues/406) | layout.py: navbar/menu/footer → tokens; toast palette → status token families; `md:space-x-8`+`rtl:space-x-reverse`→`gap-8` (gap is direction-agnostic); nav-link radius |
| [#407](https://github.com/KucharczykL/timetracker/issues/407) | custom_elements.py: dropdown surfaces → tokens; add `--color-surface-overlay` for the frosted panel |
| [#408](https://github.com/KucharczykL/timetracker/issues/408) | filters.py: relation select → semantic + `rounded-base`; negate-off chip stays documented |
| [#409](https://github.com/KucharczykL/timetracker/issues/409) | Migrate `stats_content._table()` to StyledTable; delete `.responsive-table` (kills last indigo/slate + the 16px table generation); restore-or-drop dead `max-w-20char` |
| [#410](https://github.com/KucharczykL/timetracker/issues/410) | ✅ Done — removed the global Tailwind v3 `border-color` shim after sweeping every border-width utility; controls/dividers explicitly use `border-default-medium`, structural rules use `border-default`, and stateful borders provide their own semantic color |
| [#411](https://github.com/KucharczykL/timetracker/issues/411) | Radius normalization: segmented/pagination edges → `-base`, panels/toast/StyledTable shell → `-base`, Modal → `-base`, control strays, Badge → `rounded`; fix the stale Pill "byte-for-byte JS contract" comment (clone-from-template; also names nonexistent `search_select.js`). Also folded in: the in-scope TS radius strays (`filter-group.ts`) and the `Choose a field…` value-cell placeholder. Control-height chips/pill (#436) take `rounded-base`, not the chip tier |
| [#412](https://github.com/KucharczykL/timetracker/issues/412) | Spacing: strip `mb-3` from `INPUT_CLASS` (parents own spacing); textarea/YearPicker/FilterBuilder padding strays |
| [#413](https://github.com/KucharczykL/timetracker/issues/413) | ✅ Done — `PAGE_GUTTER_CLASS = "px-4 sm:px-6"` on `#main-container` + navbar row; tables inside the gutter (16px mobile / 24px sm+), no full-bleed exemption |
| [#414](https://github.com/KucharczykL/timetracker/issues/414) | Heading mechanism: drop unlayered `h1/h2/h3` rules, builders carry the scale; fix the four casualty sites; unify page title on `PageHeading`; one dialog-title and one micro-label spelling |
| [#415](https://github.com/KucharczykL/timetracker/issues/415) | Ship IBM Plex Sans Medium/SemiBold/Bold. `--font-condensed`: delete-call reversed — kept and applied to dense list surfaces (names, table `tbody`, `Badge`/`Pill`) |
| [#427](https://github.com/KucharczykL/timetracker/issues/427) | ✅ Partial (folded into #413 branch) — `INPUT/SELECT/TEXTAREA_CLASS` → `text-base sm:text-sm` so mobile inputs are 16px (no iOS focus-zoom). Remaining `text-sm` inputs outside the mixin (filter number, search-select, date-picker segments) deferred |

Spawned later (not at synthesis), from work on the above:

| Issue | Content |
|---|---|
| [#436](https://github.com/KucharczykL/timetracker/issues/436) | Unified control height: `--height-control` (42px) → `min-h-control`; every row-control floors to it, font- and container-independent (§3 "Control height") |
| [#441](https://github.com/KucharczykL/timetracker/issues/441) | ✅ Done — TS type-size + neutral-color drift → tokens; guards (`test_typography_tokens.py` size + new `test_color_tokens.py`) now scan `ts/**/*.ts`. Folded in: incomplete-leaf cue redesigned to a warning "!" popover; nested-group depth → zebra parity (§1); relation/scope cards decategorized (slim hue on arrow/label only). Radius strays were fixed in #411; popover flex-anchor bug in #446 |
