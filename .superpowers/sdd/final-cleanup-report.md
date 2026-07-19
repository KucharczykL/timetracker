# Final-review cleanup report

Branch: `feat/typography-token-system`

## Fix 1 — M1: raw `text-sm` on all-time stats button

**File:** `games/views/stats_content.py`, line 134 (`alltime_classes`)

Before:
```
"inline-flex items-center rounded-base px-4 py-2 mr-3 text-sm font-medium "
```

After:
```
"inline-flex items-center rounded-base px-4 py-2 mr-3 text-type-body font-medium "
```

`text-type-body` = 14px, same rendered size as `text-sm` in this project's Tailwind v4 config. This aligns the all-time nav button with the P2 table migration already applied to the rest of `stats_content.py`. The grep-guard does not scan `games/views/` so this is purely a consistency fix; no guard regression.

## Fix 2 — §7 weight footnote in visual-conventions.md

**File:** `docs/visual-conventions.md`, §7 token table

Three tokens (`text-type-body`, `text-type-micro`, `text-type-input`) list weight 400 but emit **no `font-weight` declaration** — they rely on the inherited browser default of 400. Added dagger (†) to each of those three weight cells and a one-line footnote immediately below the table:

> † 400 = inherited default; these tokens emit no `font-weight` — compose `font-*` to override.

No other prose changed.

## Test output

```
4 passed, 50 deselected in 1.08s
```

Tests run: `tests/test_rendered_pages.py -k stats` + `tests/test_typography_tokens.py`. All green. `make css` completed in 126ms without errors.
