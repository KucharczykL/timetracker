# Typography token system — design

**Date:** 2026-07-19
**Status:** approved design, pre-implementation
**Supersedes/absorbs:** type slices of #403 (audit), #409 (legacy table type), #427 (input size → `text-input`)
**Builds on:** #426/#414 (heading mechanism + DialogTitle/MICRO_LABEL already landed)

## Context

The app's typography is applied as **raw Tailwind utilities scattered across components** (`text-sm`, `text-3xl`, `font-medium`, …) with no single source of truth. The #403 audit inventoried ~15 distinct type treatments, many accidental (three dialog-title spellings, duplicate page titles). #426 (merged, #414) already fixed the worst *mechanism* bugs — dropped the unlayered `h1/h2/h3` rules, unified dialog titles on `DialogTitle`/`DIALOG_TITLE_CLASS`, unified micro-labels on `MICRO_LABEL_CLASS`, unified page titles on `PageHeading`, and the real weight files (Medium/SemiBold/Bold) are shipped and wired.

What #426 did **not** do: introduce a semantic layer. The canonical treatments still live as raw utility strings baked into builders and one-off constants. This is a problem now because the settings UI-kit work (#381/#384) will add a wave of new form fields and surfaces; without a token layer, each new surface re-picks raw utilities and the drift returns.

**Goal:** promote typography into semantic `@theme` role tokens as the single source of truth, migrate the whole app to reference them, and enforce the convention — so new surfaces inherit correct type for free.

**Non-goals:** colors (#399), spacing (#400/#412), radius (#411) — separate concerns with their own issues. This spec is typography only: families, sizes, weights, line-height, and per-role definitions.

## Decisions (locked during brainstorming)

1. **Mechanism:** semantic `@theme` `--text-type-<role>` tokens (Tailwind v4), bundling size + weight + line-height + tracking via token modifiers. Components reference `text-type-<role>` utilities for size, never raw `text-<size>`.
2. **Consolidation:** aggressive — collapse ~15 treatments to **10 role tokens** (dialog and H3 kept distinct per review); near-duplicates snap to the nearest role, accepting minor intentional visual shifts.
3. **Inputs:** flat **16px everywhere** (`text-type-input`) — no responsive exception. Removes iOS focus-zoom (#427) *and* the responsive special case. Desktop inputs go 14→16px (deliberate, visible).
4. **Buttons:** de-special-cased — drop the container-query text scaling (`text-xs @md:text-sm`); buttons use `text-type-body` for size + keep composed `font-medium`. (Button *padding* container-query is a spacing concern, out of scope.)
5. **24px pair collapsed:** `H2` headings and dialog titles share one 24px token (`text-type-heading`); dialog adds `text-center` as a plain utility.
6. **Naming:** all role tokens prefixed `text-type-*` to avoid the `text-heading`/`text-body` color-utility collision (see token set).
7. **Rollout:** one branch / one PR, **atomic commit per phase** (P0→P3).

## The token set (10 roles)

**Naming — all roles are prefixed `text-type-*`.** This is not cosmetic: Flowbite's theme defines `--color-heading`/`--color-body`, and Tailwind resolves a bare `text-heading`/`text-body` to **color** when both a `--color-*` and `--text-*` token share the name — silently dropping the font-size (verified empirically against the repo's Tailwind v4.1.18; no build error). The codebase has ~94 uses of `text-heading`/`text-body` as color utilities (incl. inside `_LABEL_CLASS`, `DIALOG_TITLE_CLASS`, and `INPUT_CLASS`'s `placeholder:text-body`). Prefixing every role with `type-` sidesteps the collision entirely and makes the P3 grep-guard trivial (require `text-type-*`, ban bare `text-<size>`).

Defined in `common/input.css` `@theme`. **10 roles** (dialog kept separate from H2; H3 kept distinct — see resolved decisions):

| Token | Size / weight / leading | Absorbs (current → token) |
|---|---|---|
| `text-type-title` | 30px / 700 / tight, tracking-tight | `PageHeading`, `H1` default |
| `text-type-heading` | 24px / 700 | `H2` default |
| `text-type-dialog` | 24px / 500 | dialog/modal titles (`DIALOG_TITLE_CLASS`; adds `text-center`) — keeps #426's medium weight |
| `text-type-subheading` | 20px / 700 | `H3` default |
| `text-type-section` | 18px / 600 | block/section headings (the `TableHeader` caption precedent) |
| `text-type-body` | 14px / 400 | all `text-sm`: controls, table body, rows, error text, **buttons** (size only — see button-weight note) |
| `text-type-label` | 14px / 500 | `_LABEL_CLASS` (form labels) |
| `text-type-micro` | 12px / 400 | meta, footer, table `thead`, help-text (new role) |
| `text-type-micro-caps` | 12px / 500 / uppercase, tracking-wide | `MICRO_LABEL_CLASS` |
| `text-type-input` | 16px / 400 | `INPUT_CLASS` / `SELECT_CLASS` / `TEXTAREA_CLASS` (flat 16) |

**Badge** folds into these for **size** — sm→`text-type-micro` (12), base→`text-type-body` (14), lg→`text-type-heading` (24) — and keeps its composed `font-semibold`. No Badge-local scale, no `# type-ok` marker needed.

**Tokens own size + weight + leading + tracking only — never color.** Color stays on the existing `text-heading`/`text-body`/`text-body-subtle` color utilities, composed alongside the type token (e.g. a label is `text-type-label text-heading`). The two namespaces coexist precisely because the type roles are prefixed.

**Button weight:** `_CONTROL_BASE_CLASS` bakes `font-medium` (500). Buttons take `text-type-body` for **size** and keep `font-medium` composed as a weight utility — the token sets 14px, the utility keeps 500. The grep-guard allows `font-*` composition (see P3), so this is legal and needs no separate control role.

**Not a role — brand one-off (leave as-is):** the wordmark `text-lg sm:text-2xl lg:text-4xl font-alien` (viewport-scaled, `font-alien`). The single sanctioned raw-size exception; carries a `# type-ok` allowlist marker for the guard.

**Font families (unchanged):** `--font-sans` default, `font-mono` (tabular figures), `font-serif` (two name accents), `font-alien` (wordmark), `font-condensed` (dense list surfaces, per #415). No family changes.

### Example token definition (Tailwind v4)

```css
@theme {
  --text-type-title: 1.875rem;
  --text-type-title--line-height: 2.25rem;
  --text-type-title--font-weight: 700;
  --text-type-title--letter-spacing: -0.025em;

  --text-type-body: 0.875rem;
  --text-type-body--line-height: 1.25rem;
  /* weight defaults to 400 (inherited) — no modifier needed */

  --text-type-input: 1rem;
  --text-type-input--line-height: 1.5rem;
  /* ...remaining five roles... */
}
```

`text-center`, `uppercase`, `mb-*`, and the `text-heading`/`text-body` **color** utilities remain plain utilities composed alongside the role token — the type token owns size/weight/leading/tracking only.

## Migration — one PR, atomic commits

### P0 — token layer (no visual change except intended)
- Add the 10 `text-type-*` `@theme` tokens to `common/input.css`.
- Point existing #426 anchors at tokens: `H1`→`text-type-title`, `H2`→`text-type-heading`, `H3`→`text-type-subheading`, `PageHeading`→`text-type-title`, `DIALOG_TITLE_CLASS`→`text-type-dialog text-center`, `MICRO_LABEL_CLASS`→`text-type-micro-caps`, `_LABEL_CLASS`→`text-type-label` (keeps its `text-heading` color), `_FIELD_ERROR_CLASS`→`text-type-body`.
- **Intended P0 shifts to record before review** (deliberate, small): `PageHeading` leading-none vs H1's default 2.25rem leading (one shifts — pick and bake into `text-type-title`); `DIALOG_TITLE_CLASS` leading-6 (~1.0) → `text-type-dialog`'s leading (bake leading-6 into the token to avoid taller multi-line dialog titles). H3 and dialog **weights/sizes are preserved** (kept as distinct tokens), so no shift there.
- **Update the 1 test pin P0 breaks:** `tests/test_rendered_pages.py:255` pins the full `_LABEL_CLASS` string.
- Rebuild CSS. Snapshot/measure key pages to confirm only the listed shifts.

### P1 — body + controls sweep
- Replace raw `text-sm`/`text-xs` (size only) in `common/components/*` with `text-type-body`/`text-type-micro`; leave composed `font-*`/color utilities.
- Button: strip `text-xs @md:text-sm` from `_CONTROL_SIZE_CLASS`; button size → `text-type-body`; **keep the `font-medium`** from `_CONTROL_BASE_CLASS` composed.
- Inputs: `INPUT/SELECT/TEXTAREA_CLASS` (in `games/forms.py`) → `text-type-input` (16px flat). Replaces the interim `text-base sm:text-sm` (#427, now on `main`).
- **Update the 2 test pins P1 breaks:** `tests/test_components.py:916` (button CQ `text-xs`/`@md:text-sm`), `tests/test_search_select.py:913` (`class="block text-sm"`).

### P2 — legacy kill (dovetails #409)
- `.responsive-table` typography (`text-xl` headers, inherited 16px cells) → StyledTable tokens (`text-type-body`/`text-type-micro`). Coordinate with / fold #409.

### P3 — enforce
- Add a test that greps for raw **size** utilities (`text-xs|sm|base|lg|xl|2xl|...` and arbitrary `text-[...]`) — **not** `font-*`, which stays legal for weight-only emphasis composition. Allow a per-line `# type-ok: <reason>` marker for the sanctioned exceptions (wordmark, Badge-local scale).
- **Scope:** `common/components/`, `common/layout.py`, **and** `games/forms.py` — plus wherever the #381/#384 settings surfaces land (the work this system exists to protect). Widen as those files appear.
- Rewrite `docs/visual-conventions.md` §7 as the canonical token reference (table + the "reference type tokens for size, never raw `text-<size>`" rule).

## Isolation / interfaces

- **Token layer** (`@theme` in `input.css`): the one place sizes/weights are defined. Consumers depend only on token *names*, not values — a size change is a one-line edit.
- **Builders/constants** (`primitives.py`): translate semantic intent → token utility. Callers use builders (`H1`, `DialogTitle`, `PageHeading`) or role constants, never raw utilities.
- **Grep-guard test:** the enforcement boundary — makes "raw size utility in a component" a test failure, not a review nit.

Each phase is independently reviewable and leaves the app green.

## Testing

- **Test pins to update in-commit** (existing tests DO pin migrated utilities — the earlier "no pins" assumption was wrong): P0 breaks `test_rendered_pages.py:255` (`_LABEL_CLASS`); P1 breaks `test_components.py:916` (button CQ) and `test_search_select.py:913` (`block text-sm`). Update each in the phase that changes it.
- Add assertions that key builders emit the expected `text-type-*` token.
- **Visual:** measure computed `font-size`/`font-weight` at 375 / 768 / 1440px on representative pages (login, a list, a form, a modal, stats) via Playwright — confirm only the listed shifts (inputs 16px flat, H3 18px/600, button 14px+medium, dialog leading/weight).
- **P3:** the grep-guard test itself is the regression backstop.
- Full `make check` gates each commit.

## Risks

- **Namespace collision (resolved by design):** `text-heading`/`text-body` are color utilities; the `text-type-*` prefix avoids it. A tempting "fix" that makes a size token win the bare name would turn `placeholder:text-body` into a placeholder font-size and lose its gray — do not un-prefix.
- **Desktop input size change (14→16px)** — the most visible shift. Intended; confirm on a dense form that 14px labels next to 16px inputs read fine. Common and usually fine.
- **Button size 12→14 in compact contexts:** removing the CQ text scaling makes table/segmented-group buttons render 14px text while their CQ *padding* stays compact — dense tables get visibly larger button text in unchanged padding. Eyeball a dense list.
- **P1 ↔ #427 sequencing:** `text-type-input` replaces the `text-base sm:text-sm` now on `main`; rebase this branch on `main` first so P1 edits the merged interim, not the pre-#427 `text-sm`.
- **Grep-guard tuning:** size-only + `# type-ok` allowlist keeps it from flagging legitimate weight-only emphasis (wordmark, Badge, serif accents, filter chips, stats numbers).

## Resolved decisions (review complete)

1. **Dialog vs H2:** kept as two distinct 24px tokens — `text-type-heading` (700, H2) and `text-type-dialog` (500, modal titles). Preserves #426's medium dialog weight. No collapse.
2. **H3:** kept distinct as `text-type-subheading` (20/700). No shrink to section. `text-type-section` (18/600) is for block/section headings only.
3. **Badge:** folds into type tokens for size (sm→micro, base→body, lg→heading), keeps composed `font-semibold`. No Badge-local scale.
4. **Stale comment:** fix `input.css`'s `--font-condensed` "no current uses" note (Badge/dense surfaces use it) while in the file.

## Issue coordination

- New umbrella issue tracks P0–P3.
- #403 → historical (audit reference).
- #409 → executed by P2.
- #427 → already partially shipped on `main` (interim `text-base sm:text-sm`); P1's `text-type-input` (16px flat) supersedes it.
