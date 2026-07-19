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

1. **Mechanism:** semantic `@theme` `--text-<role>` tokens (Tailwind v4), bundling size + weight + line-height + tracking via token modifiers. Components reference `text-<role>` utilities, never raw `text-*`/`font-*`.
2. **Consolidation:** aggressive — collapse ~15 treatments to **8 role tokens**; near-duplicates snap to the nearest role, accepting minor intentional visual shifts.
3. **Inputs:** flat **16px everywhere** (`text-input`) — no responsive exception. Removes iOS focus-zoom (#427) *and* the responsive special case. Desktop inputs go 14→16px (deliberate, visible).
4. **Buttons:** de-special-cased — drop the container-query text scaling (`text-xs @md:text-sm`); buttons use `text-body`. (Button *padding* container-query is a spacing concern, out of scope.)
5. **24px pair collapsed:** `H2` headings and dialog titles share one 24px token (`text-heading`); dialog adds `text-center` as a plain utility.
6. **Rollout:** one branch / one PR, **atomic commit per phase** (P0→P3).

## The token set (8 roles)

Defined in `common/input.css` `@theme`:

| Token | Size / weight / leading | Absorbs (current → token) |
|---|---|---|
| `text-title` | 30px / 700 / tight, tracking-tight | `PageHeading`, `H1` default |
| `text-heading` | 24px / 700 | `H2` default **and** dialog titles (`DIALOG_TITLE_CLASS`; dialog adds `text-center`) |
| `text-section` | 18px / 600 | `H3` (20→18), block/section headings (the `TableHeader` caption precedent) |
| `text-body` | 14px / 400 | all `text-sm`: controls, table body, rows, error text, **buttons** |
| `text-label` | 14px / 500 | `_LABEL_CLASS` (form labels) |
| `text-micro` | 12px / 400 | meta, footer, table `thead`, help-text (new role) |
| `text-micro-caps` | 12px / 500 / uppercase, tracking-wide | `MICRO_LABEL_CLASS` |
| `text-input` | 16px / 400 | `INPUT_CLASS` / `SELECT_CLASS` / `TEXTAREA_CLASS` (flat 16) |

**Not a role — brand one-off (leave as-is):** the wordmark `text-lg sm:text-2xl lg:text-4xl font-alien` (viewport-scaled, `font-alien`). Documented as the single sanctioned exception.

**Font families (unchanged):** `--font-sans` default, `font-mono` (tabular figures), `font-serif` (two name accents), `font-alien` (wordmark), `font-condensed` (dense list surfaces, per #415). No family changes.

### Example token definition (Tailwind v4)

```css
@theme {
  --text-title: 1.875rem;
  --text-title--line-height: 2.25rem;
  --text-title--font-weight: 700;
  --text-title--letter-spacing: -0.025em;

  --text-body: 0.875rem;
  --text-body--line-height: 1.25rem;
  /* weight defaults to 400 (inherited) — no modifier needed */

  --text-input: 1rem;
  --text-input--line-height: 1.5rem;
  /* ...remaining six roles... */
}
```

`text-center`, `uppercase`, `mb-*`, `text-heading`-color etc. remain plain utilities composed alongside the role token — the token owns size/weight/leading/tracking only.

## Migration — one PR, atomic commits

### P0 — token layer (no visual change except intended)
- Add the 8 `@theme` tokens to `common/input.css`.
- Point existing #426 anchors at tokens: `H1`→`text-title`, `H2`→`text-heading`, `H3`→`text-section`, `PageHeading`→`text-title`, `DIALOG_TITLE_CLASS`→`text-heading text-center`, `MICRO_LABEL_CLASS`→`text-micro-caps`, `_LABEL_CLASS`→`text-label`, `_FIELD_ERROR_CLASS`→`text-body`.
- Rebuild CSS. Snapshot/measure key pages to confirm only intended shifts (H3 20→18, dialog weight if changed).

### P1 — body + controls sweep
- Replace raw `text-sm`/`text-xs` in `common/components/*` with `text-body`/`text-micro`.
- Button: strip `text-xs @md:text-sm` from `_CONTROL_SIZE_CLASS`; button text → `text-body`.
- Inputs: `INPUT/SELECT/TEXTAREA_CLASS` → `text-input` (16px flat). This is the desktop 14→16 change and the #427 replacement.

### P2 — legacy kill (dovetails #409)
- `.responsive-table` typography (`text-xl` headers, inherited 16px cells) → StyledTable tokens (`text-body`/`text-micro`). Coordinate with / fold #409.

### P3 — enforce
- Add a test that greps `common/components/` + `common/layout.py` for raw `text-<size>`/`font-<weight>` utilities outside the token set and the documented wordmark exception; fail on new raw usage.
- Rewrite `docs/visual-conventions.md` §7 as the canonical token reference (table + the "reference tokens, never raw utilities" rule).

## Isolation / interfaces

- **Token layer** (`@theme` in `input.css`): the one place sizes/weights are defined. Consumers depend only on token *names*, not values — a size change is a one-line edit.
- **Builders/constants** (`primitives.py`): translate semantic intent → token utility. Callers use builders (`H1`, `DialogTitle`, `PageHeading`) or role constants, never raw utilities.
- **Grep-guard test:** the enforcement boundary — makes "raw utility in a component" a test failure, not a review nit.

Each phase is independently reviewable and leaves the app green.

## Testing

- **P0/P1:** existing rendered-page + component tests must stay green (no class-string pins on the migrated utilities — verified for #413/#427; re-verify per phase). Add assertions that key builders emit the expected `text-<role>` token.
- **Visual:** measure computed `font-size`/`font-weight` at 375 / 768 / 1440px on representative pages (login, a list, a form, a modal, stats) via Playwright — confirm only the intended shifts (inputs 16px, H3 18px, button 14px flat).
- **P3:** the grep-guard test itself is the regression backstop.
- Full `make check` gates each commit.

## Risks

- **Desktop input size change (14→16px)** is the most visible shift — intended, but confirm on a dense form it doesn't unbalance labels (14) next to inputs (16). Common and usually fine.
- **`text-heading` weight for dialogs:** collapsing the 24px pair to 700 reverses #426's deliberate DialogTitle 500 (medium). If bold modal titles look heavy, dial the shared token to 600. **← confirm in review.**
- **H3 20→18** — verify no H3 site depended on the larger size.
- **Grep-guard false positives:** the wordmark and any legitimately-dynamic size need an allowlist; keep it small and documented.

## Open items for spec review

1. Shared `text-heading` weight: **700** (proposed) vs 600 vs preserving 500 for dialogs only (which would keep two 24px tokens after all).
2. `text-section` swallowing H3 (20→18) — acceptable, or keep a distinct 20px `text-subheading`?
3. Badge sizes (`text-[0.7rem]`/`text-sm`/`text-2xl`) — fold into tokens now or leave as a Badge-local scale?

## Issue coordination

- New umbrella issue tracks P0–P3.
- #403 → historical (audit reference).
- #409 → executed by P2.
- #427 → its `text-input` supersedes the interim `text-base sm:text-sm` once this lands (that interim ships first on the #413 branch).
