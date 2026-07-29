# Link appearance and popover affordance

Resolves [#589](https://github.com/KucharczykL/timetracker/issues/589) and extends it into an
app-wide unification of what a link looks like.

## The problem

Two independent inconsistencies turned out to be one problem.

**Popovers.** A `Popover` has two shapes and only one advertises itself where hovering is
impossible. When the trigger *is* the content (a price, a duration), the whole value renders as
the `<button>` — tapping works, but nothing says so. When the trigger is a separate glyph
(`preface`, used because a `<button>` may not nest inside an `<a>`), an ⓘ appears, hidden on
pointer devices via `[@media(hover:none)]:inline-flex`. Measured on `/tracker/stats/2026`:
19 of the preface kind, 8 of the trigger-is-content kind, 1 standalone glyph.

**Links.** Six different looks (five of them live), none owned by a component:

| Look | Site |
|---|---|
| `font-condensed underline decoration-slate-500 sm:decoration-2` | `GameLink` |
| `underline decoration-dotted hover:decoration-solid` | `_FILTER_LINK_CLASS`, stats |
| `hover:underline decoration-dotted` | `_count_link`, stats |
| `text-brand hover:underline` | quick filter bar |
| `text-body hover:underline` | quick filter bar |
| `hover:underline` | `layout.py` — **dead code**, see PR 2 |

Plus `TableRow` force-underlines every descendant `<a>` from the outside
(`[&_a]:underline [&_a]:underline-offset-4 [&_a]:decoration-2`) — styling-at-a-distance, which
`CLAUDE.md` forbids — which in turn forces `_session_link` to carry `decoration-transparent` to
opt its icon back out.

**The two problems meet at the dotted underline**, which currently means both "navigates"
(stats filter links, count links) and "reveals more" (`PurchasePrice`, `Duration`,
`TruncatedText`). Neither can be fixed alone without picking a side.

## The rule

> **Underline = navigates. ⓘ = there's more.**

Two orthogonal signals, one meaning each, freely composable: a linked duration is underlined
text *and* an ⓘ. Dotted underline is retired from every `Popover` — once the ⓘ carries "there's
more", it has no job left there.

One documented holdout: `PriceConverted` keeps `decoration-dotted underline`, because it uses a
native `title=` tooltip rather than a `Popover` and is deliberately deferred (see follow-ups).
So dotted is retired from the popover algebra, not yet from the app. The `decoration-dotted`
JIT-safelist hack inside `_tooltip_panel` (a hidden `Span` plus an explanatory comment, present
only to keep the class compiled) is deleted with that follow-up, not with PR 1.

**Symbol carve-out.** When a popover trigger's entire visible content is a non-text symbol — an
icon, or a single-character badge like the filter builder's `!` — that symbol *is* the
affordance and gets no second glyph. A trigger mixing icon and text still gets the ⓘ, because
the icon there is decorative (a stat's category mark), not an affordance.

### What this rule forecloses

Stated explicitly, because it is the cost of the design:

- **No third "there's more" affordance.** A future component wanting a distinct passive-reveal
  treatment has to either reuse the ⓘ or break the rule. Removing this constraint means
  reintroducing a second vocabulary and re-answering "which one does this site use".
- **The underline slot is spent.** Links own it. Anything else wanting a text decoration
  (emphasis, staleness, provisional values) must use color, weight, or a badge.
- **Control-shaped links are outside the algebra entirely.** They advertise by fill, border,
  and hover surface. A control that is *only* text with no surface has no link-ness signal —
  acceptable today because none exists.

## Decisions

Each records the alternative and why it lost, since several are explicitly experiments.

### 1. The ⓘ is always visible, on every device — including desktop

Alternatives weighed:

- **Touch-only for both kinds** (closest to today). Keeps desktop visually unchanged; hover is
  a free discovery mechanism there. Rejected: a *linked* popover then has no desktop hint at
  all, since its solid underline says "navigates", not "hover for more".
- **Dotted underline on desktop for non-links, ⓘ only on touch.** Superficially the cleanest
  desktop, but **19 of the 27 stats popovers are the link kind**, so it removes 30% of the
  glyphs while paying full complexity: two vocabularies for "there's more", plus a
  `[@media(hover:none)]` split that is a proxy rather than truth (an iPad with a trackpad
  reports `hover: none`).

Chosen: always visible, both kinds. It is the only version where a new popover cannot forget,
and where desktop and touch render identically (so tests, screenshots, and docs agree).

**Accepted cost:** roughly 27 glyphs on the stats page — `12.50 EUR ⓘ` in every price cell,
`1.2 h ⓘ` in every playtime cell. This is explicitly an experiment.

**Pare-back lever:** visibility is a single module-level constant in `primitives.py`. Flipping
it from always-on to the `[@media(hover:none)]:` variant reverts every call site in one edit.

### 2. Links get a dedicated color token, not `brand`

The requirement was a color reserved for links and reused for nothing else. That rules out
`brand`, which is already the primary button fill, the current pagination page, every focus
ring, and every active state — links in brand-blue would make blue mean nothing in particular.

Measured (WCAG 2.1 via `scripts/contrast_audit.py`, APCA Lc via `common/apca.py`), worst case
across page / zebra row / hovered row, both themes:

| Candidate | WCAG worst | APCA worst |
|---|---|---|
| `brand` (blue-700 / blue-500) | 2.74 ❌ | Lc 27 |
| violet-700 / violet-300 | 5.54 ✅ | Lc 58 |
| **sky-700 / sky-200 (shipped)** | **5.32 ✅** | **Lc 72** |
| purple-700 / purple-300 | 5.78 ✅ | Lc 60 |
| indigo-700 / indigo-300 | 5.13 ✅ | Lc 54 |
| best single-value (indigo-500) | 2.25 ❌ | Lc 21 |
| — app baseline: body text | 3.96 ❌ | Lc 41 |
| — app baseline: heading | 10.31 ✅ | Lc 98 |

Three findings:

1. **One value for both themes is impossible.** The best single hue lands 4.58 light / 2.25 on
   a dark hovered row — unreadable, not merely sub-AA. One hue, two shades, exactly as every
   other token in the app already works.
2. **`brand` fails on dark hovered rows.** Pre-existing — `scripts/contrast_audit.py` already
   reports `text-fg-brand` on the dark hover surface among the failures it computes at runtime
   (there is no curated known-failure list; the script prints them). Today only the quick filter
   bar is exposed. Making links brand would spread that failure to every game name in every
   table.
3. **Every candidate beats the app's own body text on a dark hovered row** (Lc 58–60 vs Lc 41).
   The dark-hover weakness is pre-existing, not introduced here — see [#590](https://github.com/KucharczykL/timetracker/issues/590).

**Chosen after implementation: `--color-fg-link` = `sky-700` light / `sky-200` dark.**

The purple this section originally chose shipped briefly and was rejected on sight: at
`purple-700`'s chroma of 0.265 it read garish once every game name in a list carried it, and it
read as a *visited* link. Halving the chroma to an authored `oklch(45% 0.15 295)` fixed the
garishness but not the hue association, and made it the one colour in the app sitting off
Tailwind's own chroma curve — roughly 40% below purple's, which is exactly what makes a colour
look foreign beside palette hues.

The correction was to pick hue by the **app's colour temperature** rather than in isolation.
The whole UI is cool-blue: the neutrals are not achromatic (`gray-950` sits at hue 262 with
chroma 0.028) and brand is 264. Hue distance from that axis:

| candidate | hue | ° from neutral axis | verdict |
|---|---|---|---|
| **sky (chosen)** | 242.7 | **17.3** | belongs; 22° of separation from brand still reads as "not a button" |
| violet (shipped, rejected) | 295.0 | 35.0 | reads as visited; off-curve |
| cyan | 223.1 | 37.0 | looked like a guest on the real page |
| teal | 186.4 | 73.6 | ditto, more so; also spoken for by filter chips |

Both ends are palette stops, so the token moves with the palette. They are picked
*independently* — `sky-800` light read washed out on white (0.110 chroma at that depth goes
grey) while the same calmness suits the dark page, where chroma reads louder. `sky-600` carries
more colour and fails AA on the hover surface at 3.65:1. Worst measured case **5.32:1 / Lc 72**.

**Lesson for the next colour decision:** contrast ratios select the *candidates*; the app's
existing hue axis selects *among* them. Neither settles it alone — every rejection above was
made by looking at a rendered page, not a number.

APCA note: Lc 58–60 is below APCA's ~Lc 75 target for 14px body text. No non-heading text in
the app clears that bar today, so holding links alone to it would be a new standard rather than
a restored one.

### 3. Hover shifts the link color one step

Alternatives: nothing (static), or a thicker underline. Thickening moves text by a pixel and
reads as jumpy in dense tables. Static is the documented fallback if the shift is noisy.

Links keep their own color on a hovered table row — the row's `hover:text-heading` is inherited
and the anchor's own color beats it, which is why the dark-hover measurement above is the one
that matters. It passes at 5.78 / Lc 60.

### 4. Inline text links only; control-shaped links keep their own look

Underlining the navbar, pagination, or sort headers would read as broken. Controls already
advertise with fill, border, and hover surface.

The boundary is enforced by *which builder you call*, not by remembering a class. Every anchor
in the app goes through exactly one of four:

- `Link()` — inline text links inside content (new)
- `ControlButton(href=…)` — control-shaped links that already exist as buttons (exists)
- `IconLink()` — icon-only links, no underline (new; today these are bare `A` calls carrying
  ad-hoc classes, including the `decoration-transparent` opt-out that PR 2 deletes)
- `ControlLink()` — the explicit escape hatch: renders a bare `<a>` with no styling of its own,
  for chrome that owns its appearance (navbar, pagination, sort headers, settings rail,
  dropdown menu items). It adds no classes; it exists so "deliberately not a text link" is
  declared and greppable rather than inferred from absence. (new)

`ControlLink` is what makes decision 5's guard enforceable at all — see below.

### 5. Enforcement is a guard test, not convention

Alternatives:

- **Convention only.** Cheapest, and precisely how the six-look zoo arose.
- **Style `A` itself by default.** Rejected on a concrete plumbing fact: `ControlButton`
  renders its href case through the same generated `A` builder, so control-links would inherit
  the underline, and the fix (`no-underline` accumulating alongside `underline`) resolves by
  stylesheet order rather than class order. Fragile.
- **Guard with a per-file or per-function allowlist.** Rejected: brittle, and it encodes the
  current call sites rather than the rule.

Chosen: an AST walk over `common/` and `games/` failing on any anchor construction outside the
four builders above. This matches the repo's existing guard idiom (route classification
completeness, icon drift) — a new call site fails `make check` rather than review.

Two implementation constraints the walk must respect, both established by real call sites:

1. **It cannot match on `href=` as a keyword.** Three sites pass attributes positionally —
   `DropdownLinkItem` builds `A(attributes)` with `("href", url)` inside the list
   (`custom_elements.py`), as do `TruncatedText` and `ControlButton` internally. A
   keyword-only walk misses them, so the positional form becomes a silent bypass. The guard
   flags *any* `A(...)` call outside the builders, regardless of how href is passed.
2. **The builders themselves call `A`.** The allowlist is by enclosing definition (the four
   builder functions/classes), not by call shape. Aliased imports of `A` must be resolved or
   rejected outright.

### 6. `TruncatedText` keeps two visibility policies, deliberately

It renders two reveal glyphs:

- **`info`** — a real popover (multi-game purchase contents, a differing sort name). Always
  visible, per decision 1.
- **`ellipsis`** — overflow recovery, where the tooltip only repeats the visible text. Stays
  touch-only and overflow-gated.

They differ because their desktop affordances differ: **the fade mask already advertises
clipped text.** Nothing is hidden, so this is not the bug #589 filed. Stated as a rule: *a
popover advertises with the glyph; overflow advertises with the fade, and the glyph is only its
touch stand-in.* This asymmetry needs a comment at the call site or it will read as an
oversight.

## Delivery: two PRs

They share a rule but touch different code, and each carries one "we'll see how it looks" dial,
so hating one must not block the other. Order matters: PR 1 removes dotted underlines from
popover triggers, PR 2 claims the underline for links — doing PR 1 first avoids a window where
dotted still means two things.

### PR 1 — popover affordance (#589)

The **default** anatomy becomes trigger content plus a sibling ⓘ button, always visible, and
`preface` stops being a special shape. Three existing shapes survive, and the spec is explicit
that they do:

- **`tap=False`** — a hover-only `<span>` trigger, used where the host nests inside a caller's
  interactive element. Live in `NavbarLogButton`, whose `DropdownPostItem` wraps it in a
  `<button role="menuitem">`; a sibling ⓘ `<button>` there is illegal nesting. **Keeps
  suppressing the glyph.**
- **`trigger_disabled`** — the wrapper `<span role="button">` plus disabled inner button, live
  on every settings page via the theme toggle. Unchanged.
- **Symbol carve-out** — see below.

This punctures the "a new popover cannot forget" rationale in decision 1: it holds for the
default path, not for `tap=False`. Accepted, because the alternative is illegal HTML.

**The carve-out is a caller-declared parameter, not an inference.** `_popover_html` cannot
compute "is this content a symbol": content arrives as `wrapped_content: str` or as an opaque
node tree — `_stat_popover` passes `Safe(_STAT_SVGS[key])`, raw unparsed SVG, and the
incomplete badge passes `wrapped_content="!"`, a string indistinguishable from a meaningful
one-character value like a count. `Popover` gains an explicit flag (`symbol_trigger=True`)
that suppresses the glyph; the default is glyph-on, so forgetting it fails loud rather than
silent.

| Call site | Trigger content | ⓘ |
|---|---|---|
| `domain.py` `PurchasePrice` | price text | yes — loses its dotted underline |
| `domain.py` `Duration` standalone | duration text | yes — loses its dotted underline |
| `domain.py` `Duration(link=…)` | link + glyph | already present; becomes always-visible |
| `games/views/game.py` `_stat_popover` | stat icon + value | yes — text present |
| `games/views/game.py` release year | year text | yes |
| `settings_kit.py` source badge | badge text | yes |
| `theme.py` theme tip | icons only | **no** — `symbol_trigger=True` |
| `custom_elements.py` incomplete `!` badge | single symbol | **no** — `symbol_trigger=True` |

Also in PR 1, because the new anatomy breaks them:

- **`selectable_text` becomes dead** — it exists only because the price sat *inside* the
  button. With content demoted to a plain sibling, remove it.
- **`aria-describedby` must be re-homed.** Today it rides the trigger, and `describedby=False`
  opts `Duration` out (its `sr-only` text already says the value). Decide once whether the
  description attaches to the ⓘ button, the content span, or both, and state it.
- **Centralize glyph construction in `_popover_html`.** `Duration(link=…)` currently hand-rolls
  the glyph's classes in `domain.py`. The promised single-constant pare-back lever is only real
  once that markup moves.

`TruncatedText`'s `info` glyph becomes always-visible; its `ellipsis` glyph is untouched. One
coupled change: the 24px clip reservation (`[@media(hover:none)]:pe-6`) that stops text painting
under the button is currently touch-gated. For informative instances it must become
unconditional, or desktop names paint under the always-visible glyph.

### PR 2 — link unification

- `--color-fg-link` + hover shade in `input.css` `@theme`, following the `--color-brand-soft` /
  `--color-surface-overlay` precedent for custom tokens. Added to `scripts/contrast_audit.py`.
- `Link()` in `primitives.py`, owning `text-fg-link underline underline-offset-4 decoration-2`
  plus the hover shade. Exported from `common/components/__init__.py`. **It must accept merged
  caller classes** — `GameLink` keeps `font-condensed`, and `TruncatedText`'s anchor keeps its
  `inline-flex w-full min-w-0` clip layout. The node layer's class accumulation makes this work;
  the builder must not overwrite.
- `IconLink()` and `ControlLink()`, same module.
- The AST guard test.
- **Migrate to `Link()`**: `GameLink`; `_count_link` and `_FILTER_LINK_CLASS` in
  `stats_content.py`; both quick-filter-bar links; `purchase.py`'s bare game link;
  `TruncatedText(link=…)`; `Duration(link=…)`; **the status-change Edit and Delete links** in
  `games/views/game.py` — these are bare text anchors with no classes at all, so `IconLink`
  would leave them unmarked and break the rule.
- **Migrate to `ControlLink()`** (no visual change, guard compliance): navbar Home, Stats, and
  brand in `layout.py`; pagination prev/next/page in `primitives.py`; the sort header;
  the settings rail nav; `DropdownLinkItem` in `custom_elements.py`. Stats' "All-time stats"
  anchor instead becomes a real `ControlButton` — it already hand-rolls one.
- **Icon-only links** use `IconLink`: stats' play glyph.
- **Delete, don't migrate**: `NavbarPlaytime`'s `total()` url branch in `layout.py` is dead
  code — its only caller passes no urls, deliberately, because each `Duration` owns its own
  link (a popover trigger may not sit inside an `<a>`). Reviving it via `Link()` would nest a
  popover `<button>` inside an anchor. Delete the branch; the six-look table's `layout.py` row
  is not a live look.
- **Delete**: `[&_a]:underline [&_a]:underline-offset-4 [&_a]:decoration-2` from `TableRow`, and
  the `decoration-transparent` opt-out it forces on `_session_link`. Safe only given the full
  migration above — every anchor currently relying on the forced underline is covered by it.

## Testing

- Component tests: `Link()` renders the token classes *and* preserves caller-merged classes
  (`font-condensed`, the clip layout); `ControlButton(href=…)` and `ControlLink()` render no
  underline; `symbol_trigger=True` emits no ⓘ while the default does; `tap=False` emits no ⓘ.
- The AST guard over `common/` and `games/`, with a case covering the positional-attrs form
  (`A([("href", …)])`) so the bypass is proven closed.
- E2E: a desktop-viewport popover shows its ⓘ (the regression that touch-only visibility hid);
  a truncated name still shows no ellipsis button on desktop; an informative truncated name does
  not paint under its always-visible ⓘ; `NavbarLogButton`'s menu item contains no nested
  `<button>`.
- `scripts/contrast_audit.py` covers the new token in both themes across page, zebra, and hover
  surfaces.
- Gate on the full `make check` including `e2e/`.

## Documentation

`docs/visual-conventions.md` gains a link section stating the rule, the token, and both
pare-back levers. Its existing line — "Accent / focus / links | `brand` family" — is amended:
`brand` is accent and focus; links have their own token.

## Follow-ups to file

- `PriceConverted` uses a native `title=` tooltip rather than a `Popover`, so it sits outside
  this algebra entirely. Deliberately deferred. Converting it is what finally retires
  `decoration-dotted` app-wide and lets the `_tooltip_panel` JIT-safelist hack go.
- [#590](https://github.com/KucharczykL/timetracker/issues/590) — dark `--color-body`
  gray-400 → gray-300. Already filed.
