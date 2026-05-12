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

### 1. Inconsistent return types
`Div()`/`A()`/`Button()` return `str`, but `LinkedPurchase()`/`NameWithIcon()` return `SafeText`.
Forces callers to remember `mark_safe()` wrapping.

**Fix**: Standardize — all component functions should return the same type.

### 2. Fragile A() URL resolution
Tries `reverse(url)` first, then falls back to literal string. Uses `type(url) is str`
instead of `isinstance()`. Intentional but error-prone — a string matching a URL name
will be reversed, while one that doesn't pass through as-is.

**Fix**: Add explicit parameter like `url_name="view_game"` vs `href="/literal/path"`.

### 3. Toast XSS vulnerability
Custom string escaping for Alpine.js interpolation:
```python
safe_message = message.replace("\\", "\\\\").replace("`", "\\`")
```
Doesn't protect against all injection vectors (e.g., `})` could close the
Alpine expression early).

**Fix**: Use proper HTML escaping + JSON serialization for safe template interpolation.

### 4. No tests
Zero test coverage for the entire component system.

**Fix**: Add unit tests for each component function — basic rendering, edge cases,
and cache hit/miss verification.

### 5. Default mutable arguments
`attributes: list[HTMLAttribute] = []` is a classic Python gotcha (though harmless
here since the list is only read, never mutated in place).

**Fix**: Use `attributes: list[HTMLAttribute] | None = None` and convert to `[]`
inside the function body.
