# Suggested Improvements to common/components.py

## Completed

### Caching on template rendering
- Added `functools.lru_cache` on `_render_cached()` wrapper around `render_to_string`
- Cache key: `(template_path, json.dumps(context, sort_keys=True))` — deterministic and unique
- `maxsize=4096` in production, disabled entirely in DEBUG mode (so template changes are reflected immediately)
- Only caches `template` path calls; `tag_name` calls are already nanosecond string ops
- Verified working: identical calls return identical output, different inputs produce separate cache entries

### Non-deterministic IDs
`randomid()` was replaced with `hashlib.sha1(content_hash.encode()).hexdigest()[:10]` for deterministic ID generation.
- `Popover()` passes content hash (`wrapped_content:popover_content:wrapped_classes`) so IDs are deterministic per unique content
- `games/templatetags/randomid.py` uses the same hash-based approach
- Fixes: caching (Popover output now cacheable), page consistency, thread safety

### Inconsistent return types
All component functions now return `SafeText` and are annotated accordingly. Redundant `mark_safe()` wrappers removed from `LinkedPurchase()` and `NameWithIcon()`.

### Fragile A() URL resolution
Replaced single `url` parameter with explicit `url_name` (URL pattern name resolved via `reverse()`) and `href` (literal path). Removed dead `Callable` type hint. `reverse()` now raises `NoReverseMatch` instead of silently falling back to literal text. Added mutual exclusion check — providing both parameters raises `ValueError`. Updated all 10 call sites across 6 view files and internal callers (`LinkedPurchase()`, `NameWithIcon()`).

### Toast XSS vulnerability
The vulnerable `Toast()` component (which used unsafe string escaping for
Alpine.js interpolation) had no callers and was deleted entirely. Toast display
is handled by the existing event-driven pipeline: middleware → `HX-Trigger`
headers → `show-toast` CustomEvent → Alpine store.

### Default mutable arguments
All functions with mutable defaults (`attributes` and `children`) changed from `= []` to `| None = None` with `or []` conversion in the body.

What was fixed: `attributes: list[HTMLAttribute] = []` and `children: list[HTMLTag] | HTMLTag = []` are a classic Python gotcha — the default is shared across all callers and could silently corrupt state if ever mutated in place. Changed 8 functions (`Component`, `Popover`, `A`, `Button`, `Div`, `Input`, `Form`, `Icon`) to use the `None` sentinel pattern, preventing future bugs and eliminating linter warnings.

### NameWithIcon dead code and untestable design
The `NameWithIcon()` function had a `platform` parameter that was immediately overwritten by `platform = None` and never used (dead code). The function mixed data lookup (database queries via IDs) with rendering, making it untestable.

**Fix**: Refactored `NameWithIcon()` to follow the `LinkedPurchase` pattern — accepts model objects (`Game`, `Session`) instead of IDs. Extracted `_resolve_name_with_icon()` helper for testable computation logic (name resolution, platform extraction, link creation). Fixed bug where `platform` was not extracted when `session` parameter was passed. Removed dead `platform` parameter from the public API. Updated all 3 production call sites (already using model objects). Added 10 unit tests for `_resolve_name_with_icon()` covering session override, custom names, linkify behavior, platform resolution, and edge cases. Updated 6 integration tests to use model-based parameters.

### No tests
Zero test coverage for the entire component system.

**Fix**: Add unit tests for each component function — basic rendering, edge cases,
and cache hit/miss verification.

**Done**: 96 unit tests covering all component functions (`Component`, `randomid`, `Popover`, `PopoverTruncated`, `A`, `Button`, `Div`, `Icon`, `Form`, `Input`, `NameWithIcon`, `LinkedPurchase`, `PurchasePrice`, `_render_cached`, `enable_cache`). Includes template rendering, deterministic ID generation, LRU cache behavior, HTML output validation, edge cases, error handling, and model-dependent integration tests.
