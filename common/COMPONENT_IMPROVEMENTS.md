# Suggested Improvements to common/components.py

## Completed

### Caching on template rendering
- Added `functools.lru_cache` on `_render_cached()` wrapper around `render_to_string`
- Cache key: `(template_path, json.dumps(context, sort_keys=True))` — deterministic and unique
- `maxsize=4096` in production, disabled entirely in DEBUG mode (so template changes are reflected immediately)
- Only caches `template` path calls; `tag_name` calls are already nanosecond string ops
- Verified working: identical calls return identical output, different inputs produce separate cache entries

## Pending

### 1. Non-deterministic IDs
`randomid()` uses `random.choices()` producing unique IDs every call. Breaks:
- Caching (can't cache Popover output because IDs change between requests)
- Page consistency (same content produces different HTML across requests)
- Thread safety of the `random` module for ID generation

**Fix**: Replace with `hashlib.sha1(content_hash.encode()).hexdigest()[:10]` based on deterministic content hash.

### 2. Inconsistent return types
`Div()`/`A()`/`Button()` return `str`, but `LinkedPurchase()`/`NameWithIcon()` return `SafeText`.
Forces callers to remember `mark_safe()` wrapping.

**Fix**: Standardize — all component functions should return the same type.

### 3. Fragile A() URL resolution
Tries `reverse(url)` first, then falls back to literal string. Uses `type(url) is str`
instead of `isinstance()`. Intentional but error-prone — a string matching a URL name
will be reversed, while one that doesn't pass through as-is.

**Fix**: Add explicit parameter like `url_name="view_game"` vs `href="/literal/path"`.

### 4. Toast XSS vulnerability
Custom string escaping for Alpine.js interpolation:
```python
safe_message = message.replace("\\", "\\\\").replace("`", "\\`")
```
Doesn't protect against all injection vectors (e.g., `})` could close the
Alpine expression early).

**Fix**: Use proper HTML escaping + JSON serialization for safe template interpolation.

### 5. No tests
Zero test coverage for the entire component system.

**Fix**: Add unit tests for each component function — basic rendering, edge cases,
and cache hit/miss verification.

### 6. Default mutable arguments
`attributes: list[HTMLAttribute] = []` is a classic Python gotcha (though harmless
here since the list is only read, never mutated in place).

**Fix**: Use `attributes: list[HTMLAttribute] | None = None` and convert to `[]`
inside the function body.
