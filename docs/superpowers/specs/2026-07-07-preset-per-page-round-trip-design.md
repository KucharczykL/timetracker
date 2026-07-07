# Saved filter presets round-trip page size (#337)

## Problem

Follow-up to #77, which threaded `find_filter.sort` through the preset save/load
path but **deliberately deferred pagination**. `FindFilter` already carries
`page`/`per_page`, and `FilterPreset.find_filter` is shaped to hold them, but a
saved preset still drops the active rows-per-page: reload one and you always land
at the default page size, regardless of the size you had when you saved it.

## Decision: pin `per_page`, never `page`

The issue asked whether a preset should pin a page size or just a sort
("Probably per_page only; page is transient."). We persist **`per_page` only**.
`page` is a transient scroll position — loading a preset always resets to page 1
(the navigation URL simply omits `page`, and `Paginator` defaults it). Persisting
a page number would strand a preset on "page 7" of a result set whose size later
changed.

## Stored shape

`find_filter` now holds `{"sort": "<SortString>", "per_page": <int>}`, either key
independent and optional. Mirroring the sort rule, only a **non-default** page
size is stored: a preset saved at the default size (`FindFilter.per_page`, 25)
stores no `per_page` and round-trips to the default. `per_page=0` (disable
pagination / show all) differs from the default, so it *is* stored — the
persistence test uses a default-comparison, not a truthiness check, so `0`
survives.

Unlike sort, `per_page` is **not gated on mode**: every list view paginates, so a
sort-less mode (`playevents`/`devices`/`platforms`) still pins its page size.

## Design (mirrors #77's sort threading)

The only save UI is the builder page, a separate page with no knowledge of the
list's page size, so `per_page` threads the same route sort does:

- **`builder_url_for(mode, filter_json, sort=None, per_page=None)`**
  (`games/views/filtering.py`) — appends `&per_page=<n>` only when `per_page`
  is not `None` **and** differs from `FindFilter.per_page`. The six list views
  (`game`/`session`/`purchase`/`playevent`/`device`/`platform`) pass
  `find.per_page`; the default-comparison lives in one place.
- **`general.filter_builder`** reads `request.GET.get("per_page")` and passes it
  to `FilterBuilder(..., per_page=...)`.
- **`FilterBuilderProps`** gains `per_page: str`; **`FilterBuilder()`** gains a
  keyword-only `per_page: str = ""`, emitted as the `per-page` attribute
  (`make gen-element-types` regenerates the reader).
- **`filter-builder.ts`** reads it into `this.perPage`; `onApply` passes it
  through `applyUrl`, `onSavePreset` adds `per_page` to the POST, and a preset
  pick adopts the preset's stored `per_page`.
- **`savePreset` / `SavePresetRequest`** (`ts/elements/presets.ts`) gain an
  optional `per_page?: string`.
- **API `PresetIn`** gains `per_page: str | None = None`. `save_preset` stores it
  via `_preset_per_page()` (parse int, keep only a valid non-default value).
- **`list_presets`** emits `data["per_page"]` via `_stored_per_page()` (`""` when
  none).
- **`applyUrl(listUrl, filter, sort?, perPage?)`** (`ts/elements/filter-url.ts`)
  appends `per_page=<encoded>` for any non-empty string (so `"0"` rides through);
  it never emits `page`, so loading resets to page 1.
- **quick-bar facet Apply** carries the live `?per_page=` from
  `window.location` forward (alongside the live sort), so tweaking a facet keeps
  the active page size; **quick-bar preset pick** restores the preset's stored
  `per_page`.

## Validation — one shared bound

`per_page` is re-parsed on load by the destination list view's `parse_int_param`
(`games/sorting.py`), whose forgiving `Paginator.get_page` contract degrades a
blank/garbage value to the default. A stale stored size therefore self-heals with
no preset-specific validation code, exactly as a stale sort key does through
`warn_unknown_sort`.

One value the forgiving contract does **not** absorb on its own is a *negative*
size: `Paginator(qs, -5)` slices `[0:-5]` and raises `EmptyPage`, so a negative
`?per_page=` would 500 the list. `parse_int_param` therefore takes a `minimum=0`
bound for `per_page` (a negative degrades to the default), and the preset save
path (`_preset_per_page`) reuses the same parser + bound so it never persists a
size the load path would choke on. No model change, so **no migration**.

## Testing

- **pytest** (`tests/test_filter_presets.py`, `tests/test_quick_filter_bar.py`):
  save persists a non-default size; a default size / non-integer stores nothing;
  `0` is kept; sort + per_page coexist; a sort-less mode still pins per_page;
  `list_presets` emits `data["per_page"]`; re-save clears a stale size;
  `builder_url_for` carries only a non-default size.
- **vitest**: `applyUrl` appends `per_page` (incl. the `"0"` and empty cases);
  `savePreset` forwards `per_page`; the builder's Apply/Save/preset-pick and the
  quick bar's facet-Apply/preset-pick carry it.
