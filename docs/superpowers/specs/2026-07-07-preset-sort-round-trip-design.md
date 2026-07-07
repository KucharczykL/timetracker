# Saved filter presets round-trip sort order (#77)

## Problem

`FilterPreset` reserves a `find_filter` JSONField "for sort/pagination", but the
preset API never touches it: `save_preset` persists only `object_filter`
(criteria), and `list_presets` returns only the criteria for the client to
rebuild a `?filter=` URL. Since #68 added the `?sort=` contract, **saving a
preset drops the active sort** and reloading one always lands in the default
order — defeating the point of a saved view.

The active sort is also lost on two other interactions today, independent of
presets, because sort is not threaded through them:

- Entering the Advanced-filter builder (`builder_url_for` carries only
  `?filter=`) and applying from it (the builder's Apply re-emits only
  `?filter=`).
- Applying a quick-bar facet change (`applyUrl(applyTarget, facetFilter)` emits
  no `sort=`).

## Goal

Make presets round-trip sort, and — because the save UI only exists inside the
builder, which is a separate page with no knowledge of the list's sort — thread
sort coherently through the builder and quick-bar interactions so the active
sort survives filtering. Scope stays on the three modes that have sort maps
today (`games`, `sessions`, `purchases`); a registry makes extending to more
modes a pure addition later.

## Non-goals

- No `page`/`per_page` round-trip. The issue defers pagination persistence;
  tracked in #337 for when the pagination contract firms up.
- No new sort maps for `playevents`/`devices`/`platforms` (#335).
- No advanced builder for `devices`/`platforms` (#336).
- No model change, therefore **no migration** — `FilterPreset.find_filter`
  already exists.

## Stored shape

`find_filter` holds `{"sort": "<SortString>"}`, e.g. `{"sort": "-playtime,name"}`,
matching `FindFilter.sort` (the #74 parser field). An empty/absent sort is `{}`
(not `{"sort": ""}`), so a preset saved from the default order stores nothing
and loads in the default order.

## Design

### 1. `MODE_SORTS` registry (`games/sorting.py`)

```python
MODE_SORTS: dict[str, SortMap] = {
    "games": GAME_SORTS,
    "sessions": SESSION_SORTS,
    "purchases": PURCHASE_SORTS,
}
```

The single source of "which modes have sort." Add it to `__all__`. Placed in
`games/sorting.py` (already owns the maps) to avoid a `games.filters` ↔
`games.sorting` import cycle. No default sort is stored here — validation and
default-order fallback happen in the destination list view on load (section 4).

Contract-tested: `set(MODE_SORTS) <= set(MODE_PARSERS)` (and therefore
`FilterPreset.MODE_CHOICES`), mirroring the existing
`test_mode_parsers_cover_every_mode_choice`.

### 2. Save path — thread sort list → builder → preset

The only save UI is the builder page (`games:filter_builder`), reached from the
list via the quick bar's "Advanced filter…" segment. Thread the list's active
sort all the way to the POST:

- **`builder_url_for(mode, filter_json, sort=None)`** (`games/views/filtering.py`)
  — append `&sort=<quote(sort)>` when `sort` is truthy. Its callers
  (`game.py`, `session.py`, `purchase.py`, `playevent.py`) pass `find.sort` (the
  raw requested `?sort=`, `None` on default order). `playevent.py` has no sort
  map, so `find.sort` is always `None` there — nothing is threaded, matching the
  gate in the API.
- **`general.filter_builder`** — read `request.GET.get("sort")` and pass it to
  `FilterBuilder(..., sort=...)`.
- **`FilterBuilderProps`** (`common/components/custom_elements.py`) gains
  `sort: str`; **`FilterBuilder()`** gains a keyword-only `sort: str = ""`
  param, emitted as the element's `sort` attribute. Run `make gen-element-types`
  so `ts/generated/props.ts` regenerates.
- **`filter-builder.ts`** — read `sort` into `this.sort`; `onSavePreset` adds
  `sort: this.sort` to the payload; `onApply` passes `this.sort` through
  `applyUrl` (so applying from the builder preserves sort — fixes the latent
  round-trip loss).
- **`savePreset` / `SavePresetRequest`** (`ts/elements/presets.ts`) gain an
  optional `sort?: string`, forwarded in the POST body.
- **API `PresetIn`** (`games/api.py`) gains `sort: str | None = None`.
  **`save_preset`** stores
  `find_filter = {"sort": sort} if sort and payload.mode in MODE_SORTS else {}`
  via the `update_or_create` `defaults`. The `MODE_SORTS` gate drops sort for
  sort-less modes so no dead data is stored. `object_filter` handling is
  unchanged. The raw sort string is stored as-is; it is the user's own data,
  scoped to their presets, and re-validated on load (section 4).

### 3. Load path — emit + restore

- **`list_presets`** (`games/api.py`) adds
  `data["sort"] = (preset.find_filter or {}).get("sort", "")`.
  `PresetOption.data` is already `dict[str, str]`, so `"sort"` rides alongside
  `"filter"` as a `data-*` attribute on the option row.
- **`applyUrl(listUrl, filter, sort?)`** (`ts/elements/filter-url.ts`) — append
  `sort=<encoded>` with the correct `?`/`&` separator (accounting for whether a
  `?filter=` is already present). An empty filter + a sort must still emit
  `listUrl?sort=…`.
- **quick-filter-bar `onPresetPick`** (`ts/elements/quick-filter-bar.ts`) — read
  `detail.last.data.sort` and pass it to `applyUrl`.
- **filter-builder preset pick `onPresetLoad`** (`ts/elements/filter-builder.ts`)
  — set `this.sort = detail.last.data.sort ?? ""` when loading a preset, so a
  subsequent Apply restores the **preset's** sort rather than the origin list's.

### 4. Validation — none new

Loading a preset navigates to `list?filter=…&sort=…`. The destination list
view's existing `apply_sort` + `warn_unknown_sort` (`games/views/filtering.py`)
already drop unknown sort keys, keep valid ones, fall back to the default sort
when none remain, and queue a warning toast per dropped key. A preset whose
stored column key was renamed self-heals on load with the same UX as a
hand-typed stale `?sort=`. No preset-specific validation code is added.

### 5. Quick-bar facet-Apply preserves sort

`quick-filter-bar.ts`'s facet submit currently navigates via
`applyUrl(applyTarget, facetFilter)` with no sort, so adjusting a facet resets
the sort. The quick bar renders on the list page, so it reads the live `?sort=`
from `window.location.search` and passes it to `applyUrl`. Purely client-side;
no server plumbing. This keeps sort stable while tweaking facets, consistent
with the builder now preserving it (section 2).

## Testing

**pytest** (`tests/test_filter_presets.py` + friends):

- `save_preset` with a sort stores `find_filter == {"sort": ...}`.
- `save_preset` for a sort-less mode (e.g. `playevents`) stores
  `find_filter == {}` even if a `sort` is POSTed (gate).
- `save_preset` with no sort stores `find_filter == {}`.
- `list_presets` emits `data["sort"]` from the stored `find_filter`.
- `MODE_SORTS` keyset is a subset of `MODE_CHOICES` (contract).
- Integration: GET a list with `?sort=<stale-key>` warns and renders (this is
  existing `warn_unknown_sort` behaviour; assert it covers the preset-load path
  by exercising the built URL).

**vitest** (`ts/**/*.test.ts`):

- `applyUrl` appends `sort=` with correct separator, including the
  empty-filter + sort case.
- `savePreset` payload carries `sort`.
- quick-bar `onPresetPick` builds a URL containing the option's `data.sort`.
- filter-builder preset pick updates `this.sort`; Apply then carries it.

**e2e** (optional, `e2e/`): save a preset while sorted → load it from a
different order → assert the resulting row order.

## Follow-up issues

- #335 — Sort maps + `apply_sort` + `warn_unknown_sort` + #73 clickable headers
  for `playevents`/`devices`/`platforms`, so every list round-trips sort.
- #336 — Advanced filter builder for `devices`/`platforms` (they already have
  `parse_device_filter`/`parse_platform_filter`).
- #337 — Preset round-trip of `page`/`per_page` once the pagination contract lands.

## Verification gate

`direnv exec . make check` green (lint + format-check + mypy + ts-check + vitest
+ full pytest incl. e2e) before declaring done.
