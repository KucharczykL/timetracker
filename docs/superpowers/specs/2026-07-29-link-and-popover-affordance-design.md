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

**Links.** Six different looks, none of them owned by a component:

| Look | Site |
|---|---|
| `font-condensed underline decoration-slate-500 sm:decoration-2` | `GameLink` |
| `underline decoration-dotted hover:decoration-solid` | `_FILTER_LINK_CLASS`, stats |
| `hover:underline decoration-dotted` | `_count_link`, stats |
| `text-brand hover:underline` | quick filter bar |
| `text-body hover:underline` | quick filter bar |
| `hover:underline` | `layout.py` |

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
text *and* an ⓘ. Dotted underline is retired app-wide — once the ⓘ carries "there's more", it
has no job left.

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
| **purple-700 / purple-300** | **5.78 ✅** | **Lc 60** |
| indigo-700 / indigo-300 | 5.13 ✅ | Lc 54 |
| best single-value (indigo-500) | 2.25 ❌ | Lc 21 |
| — app baseline: body text | 3.96 ❌ | Lc 41 |
| — app baseline: heading | 10.31 ✅ | Lc 98 |

Three findings:

1. **One value for both themes is impossible.** The best single hue lands 4.58 light / 2.25 on
   a dark hovered row — unreadable, not merely sub-AA. One hue, two shades, exactly as every
   other token in the app already works.
2. **`brand` fails on dark hovered rows.** Pre-existing (it is already in the audit's
   known-failure list for `text-fg-brand`), but today only the quick filter bar is exposed.
   Making links brand would spread that failure to every game name in every table.
3. **Every candidate beats the app's own body text on a dark hovered row** (Lc 58–60 vs Lc 41).
   The dark-hover weakness is pre-existing, not introduced here — see [#590](https://github.com/KucharczykL/timetracker/issues/590).

Chosen: `--color-fg-link` = `purple-700` light / `purple-300` dark. Purple is unused as a token
today (the `replaying` status dot is purple-500 — a filled dot, a different shape class), and
it is already the browser's own link vocabulary, so it does not read as alien.

**Fallback, if it reads garish:** a custom low-chroma pair at roughly half the palette chroma,
`oklch(45% 0.15 295)` / `oklch(80% 0.10 295)`. Tailwind's purple-700 sits at chroma 0.265 while
the app's text tokens are near-neutral, so this is the direct lever. Second fallback: color the
underline only (`decoration-fg-link`) and let the text inherit body color — near-zero page
rash, weaker signal.

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

The boundary is enforced by *which builder you call*, not by remembering a class:

- `Link()` — inline text links inside content (new)
- `ControlButton(href=…)` — control-shaped links (exists)
- `IconLink()` — icon-only links, no underline (new; today these are bare `A` calls carrying
  ad-hoc classes, including the `decoration-transparent` opt-out that PR 2 deletes)

### 5. Enforcement is a guard test, not convention

Alternatives:

- **Convention only.** Cheapest, and precisely how the six-look zoo arose.
- **Style `A` itself by default.** Rejected on a concrete plumbing fact: `ControlButton`
  renders its href case through the same generated `A` builder, so control-links would inherit
  the underline, and the fix (`no-underline` accumulating alongside `underline`) resolves by
  stylesheet order rather than class order. Fragile.

Chosen: an AST walk over `common/` and `games/` failing on any `A(href=…)` outside `Link`,
`ControlButton`, and `IconLink`. This matches the repo's existing guard idiom (route
classification completeness, icon drift) — a new call site fails `make check` rather than
review.

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

`_popover_html` collapses to one anatomy: trigger content plus a sibling ⓘ button, always
visible. `preface` stops being a special shape.

| Call site | Trigger content | ⓘ |
|---|---|---|
| `domain.py` `PurchasePrice` | price text | yes — loses its dotted underline |
| `domain.py` `Duration` standalone | duration text | yes — loses its dotted underline |
| `domain.py` `Duration(link=…)` | link + glyph | already present; becomes always-visible |
| `games/views/game.py` `_stat_popover` | stat icon + value | yes — text present |
| `games/views/game.py` release year | year text | yes |
| `settings_kit.py` source badge | badge text | yes |
| `theme.py` theme tip | icons only | **no** — symbol carve-out |
| `custom_elements.py` incomplete `!` badge | single symbol | **no** — symbol carve-out |

`TruncatedText`'s `info` glyph becomes always-visible; its `ellipsis` glyph is untouched.

### PR 2 — link unification

- `--color-fg-link` + hover shade in `input.css` `@theme`, following the `--color-brand-soft` /
  `--color-surface-overlay` precedent for custom tokens. Added to `scripts/contrast_audit.py`.
- `Link()` in `primitives.py`, owning `text-fg-link underline underline-offset-4 decoration-2`
  plus the hover shade. Exported from `common/components/__init__.py`.
- The AST guard test.
- **Migrate to `Link()`**: `GameLink`; `_count_link` and `_FILTER_LINK_CLASS` in
  `stats_content.py`; `layout.py`'s model-count link; both quick-filter-bar links;
  `purchase.py`'s bare game link; `TruncatedText(link=…)`; `Duration(link=…)`.
- **Stay control-shaped**: navbar, footer, and brand in `layout.py`; pagination and sort headers
  in `primitives.py`; the settings rail nav; `_view_all_button`. Stats' "All-time stats" anchor
  becomes a real `ControlButton` — it already hand-rolls one.
- **Icon-only links** use `IconLink`: stats' play glyph, the status-change edit and
  delete links.
- **Delete**: `[&_a]:underline [&_a]:underline-offset-4 [&_a]:decoration-2` from `TableRow`, and
  the `decoration-transparent` opt-out it forces on `_session_link`.

## Testing

- Component tests: `Link()` renders the token classes; `ControlButton(href=…)` renders no
  underline; the symbol carve-out emits no ⓘ for an icon-only and a single-character trigger,
  and does emit one for icon+text.
- The AST guard over `common/` and `games/`.
- E2E: a desktop-viewport popover shows its ⓘ (the regression that touch-only visibility hid);
  a truncated name still shows no ellipsis button on desktop.
- `scripts/contrast_audit.py` covers the new token in both themes across page, zebra, and hover
  surfaces.
- Gate on the full `make check` including `e2e/`.

## Documentation

`docs/visual-conventions.md` gains a link section stating the rule, the token, and both
pare-back levers. Its existing line — "Accent / focus / links | `brand` family" — is amended:
`brand` is accent and focus; links have their own token.

## Follow-ups to file

- `PriceConverted` uses a native `title=` tooltip rather than a `Popover`, so it sits outside
  this algebra entirely. Deliberately deferred.
- [#590](https://github.com/KucharczykL/timetracker/issues/590) — dark `--color-body`
  gray-400 → gray-300. Already filed.
