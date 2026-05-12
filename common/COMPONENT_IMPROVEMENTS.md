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

## Incomplete

### Toast XSS vulnerability
Custom string escaping for Alpine.js interpolation:
```python
safe_message = message.replace("\\", "\\\\").replace("`", "\\`")
```
Doesn't protect against all injection vectors (e.g., `})` could close the
Alpine expression early).

**Fix**: Use proper HTML escaping + JSON serialization for safe template interpolation.

### No tests
Zero test coverage for the entire component system.

**Fix**: Add unit tests for each component function — basic rendering, edge cases,
and cache hit/miss verification.

### Default mutable arguments
`attributes: list[HTMLAttribute] = []` is a classic Python gotcha (though harmless
here since the list is only read, never mutated in place).

**Fix**: Use `attributes: list[HTMLAttribute] | None = None` and convert to `[]`
inside the function body.
