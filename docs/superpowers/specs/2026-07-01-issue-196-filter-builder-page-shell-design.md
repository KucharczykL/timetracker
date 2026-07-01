# Advanced filter builder page shell (#196)

**Status:** design approved 2026-07-01
**Issue:** [#196](https://github.com/KucharczykL/timetracker/issues/196) — component 10 of #168 (phase 2c).
**Parent design:** `docs/superpowers/specs/2026-06-28-nested-filter-builder-design.md` (§ "Builder page shell").

## Goal

Assemble the already-landed nested-builder parts into a real, per-model page: a
`/…/filter` route + `render_page` view for each list backed by an `OperatorFilter`
(games, sessions, purchases, playevents). The page mounts the root `<filter-group>`
plus a natural-language summary, a live result count, and a toolbar
(`[Load preset ▾] [Save as preset…] [Apply] [Clear]`). It reads `?filter=` on the way
in (prefill) and writes `?filter=` on Apply (navigate back to the list).

Nothing here is new *filtering* behaviour — every leaf/group/relation/serializer piece
already shipped (#234, #237, #239, #245, #250, #255, #260, #261). This is the assembly
plus the three small glue pieces the assembly first makes reachable.

## What already exists (reused verbatim)

- `<filter-group model= models=>` (`ts/elements/filter-group.ts`) — owns the whole node
  tree, `serialize()` / `serializeForQuery()` / `getTree()`, dispatches
  `filter-tree-change` with `{tree, incompleteCount}`.
- `<filter-count model= noun_singular= noun_plural= endpoint=>` (`ts/elements/filter-count.ts`)
  — self-wiring: listens on `document` for `filter-tree-change`, debounces, calls the
  sibling group's `serializeForQuery()`, fetches `/api/filter/count`. States
  Counting… / ≈ N / count unavailable.
- Count endpoint `GET /api/filter/count?model=&filter=` (`games/api.py`).
- `summarize(tree, context)` + `SummaryContext {modelKey, modelLabel, models}`
  (`ts/elements/filter-tree/summary.ts`) — pure, tested, **not yet mounted**.
- `deserialize(json, modelKey, registry)` (`ts/elements/filter-tree/serializer.ts`) —
  faithful import of arbitrary/legacy `?filter=` JSON to a node tree.
- Preset endpoints: `list_presets` (HTML `<ul>` fragment, `?mode=`), `save_preset`
  (POST `name`/`mode`/`filter`), `delete_preset` (DELETE), `load_preset` (redirect).
- `FilterBar` component + `filter-bar.ts` preset load/save/delete flow (the pattern the
  builder toolbar mirrors).

## New pieces

### 1. Route + view (backend)

One dynamic path in `games/urls.py` —
`path("<str:model>/filter", general.filter_builder, name="filter_builder")` — so
`reverse("games:filter_builder", args=[model])` gives the entry-point link (§6) a single
clean name. No existing route ends in `/filter`, so nothing is shadowed; the view itself
restricts `model` to the four builder models (404 otherwise), so the open pattern is not a
surface concern.

Per-model config lives in one table in the view:

```python
BuilderModel = TypedDict("BuilderModel", {"mode": str, "list_url": str,
                                          "label": str, "noun_singular": str,
                                          "noun_plural": str})
```

- `mode` — the plural preset mode (`game→games`), used for `reverse(f"games:list_{mode}")`
  (the Apply target) and the preset endpoints' `mode=`.
- `label` / `noun_*` — from `Model._meta.verbose_name` / `verbose_name_plural`
  (`label` = plural title-cased, e.g. "Games"; count nouns singular/plural).

`filter_builder`:
1. Look up the config for `model`; **404** if `model` is not one of the four.
2. Read `filter_json = request.GET.get("filter", "")` (raw JSON string, may be empty;
   passed to the group verbatim — the client deserializes/validates, the backend already
   fail-opens on bad `?filter=`).
3. Build content (§5) and `render_page(request, content, title=f"Filter {label}")`.

No new model, no new API. Login-required like every other view.

### 2. `<filter-group>` element additions

Three additions to the existing element (no prop churn beyond one new optional attr):

- **`getFilledTree(): GroupNode`** — returns `this.fillCriteria(this.tree, this.model)`
  (already private). Filled-but-**unpruned** so incomplete leaves keep their `…`
  placeholders — exactly what the summary wants (count uses `serializeForQuery()`, which
  prunes; the two consumers want different trees, so a distinct accessor is correct).
- **`loadFilter(json: Json): void`** — `this.tree = deserialize(json, this.model, registry)`
  then re-render + dispatch `filter-tree-change`. The `MetadataRegistry` is built once
  from `this.models` (each `ModelBundle.fields` → a name-set `ModelMeta`); no new server
  data. **`clear(): void`** — `this.tree = emptyRoot()`, re-render + dispatch.
- **New `filter` prop** (optional JSON string) — on `connectedCallback`, if present and
  non-empty, seed the tree via the same `deserialize` path *before* the first render, so
  the server-rendered `?filter=` is reflected on parse (summary + count read the correct
  initial tree, no upgrade-order race). Empty/absent → the current empty-root behaviour.

**Edge covered (issue #238 comment):** an imported **negated-empty-root**
(`{NOT:[{AND:[]}]}` / a root with `negate` and no children) — `renderGroup`'s empty-state
branch keys only on `children.length === 0` and drops the NOT chip. Now reachable via
`filter`/`loadFilter`. Pin it with an element test; the summary/serialize behaviour
("matches all", `serialize()→{}`) is the accepted semantics — the test asserts it doesn't
throw and round-trips, not that a NOT chip appears (there is deliberately no root NOT UI).

### 3. `<filter-summary>` element (new)

Self-wiring, same shape as `<filter-count>`. Props: `model`, `model_label`, `models`
(the same `model_field_registry` JSON the group already carries). On connect it listens on
`document` for `filter-tree-change`, finds the sibling `<filter-group>`, and on each event
(plus once on connect if the group is already upgraded) calls
`summarize(group.getFilledTree(), context)` where
`context = {modelKey: model, modelLabel: model_label, models: parsed}` — `parsed` is a
`Record<modelKey, SummaryModel>` built from the `models` prop (`fields` map + optional
`columns` map). Renders read-only text into an inner `<span>`. No debounce (pure, cheap).

Python builder `FilterSummary(*, model, model_label, models)` in `custom_elements.py`
alongside `FilterCount`; registered element `filter-summary`; initial markup a placeholder
span so there is no flash before the first event.

### 4. `<filter-builder>` element (new — toolbar/orchestrator)

Props: `model`, `mode`, `apply_url` (the list URL), `preset_list_url`, `preset_save_url`.
Renders the toolbar `[Load preset ▾] [Save as preset…] [Apply] [Clear]` (StyledButton /
ButtonGroup, in-theme). Holds a ref to the sibling `<filter-group>` (`document.querySelector`)
and tracks `incompleteCount` from `filter-tree-change`:

- **Apply** — `const q = group.serializeForQuery();` navigate to `apply_url` (bare when `q`
  is empty `{}`) else `apply_url + "?filter=" + encodeURIComponent(JSON.stringify(q))`.
  Disabled while `incompleteCount > 0`.
- **Clear** — `group.clear()`.
- **Load preset** — fetch `preset_list_url?mode=<mode>` (the existing HTML `<ul>` fragment),
  render it in the dropdown; on a preset click, read the `?filter=` param out of the
  anchor's href and call `group.loadFilter(parsed)` **instead of navigating**; delete via the
  fragment's `data-delete-preset` (DELETE), refresh the list. Toasts via
  `fetchWithHtmxTriggers`.
- **Save preset** — name input → POST `preset_save_url` with `name`, `mode`,
  `filter=JSON.stringify(group.serialize())` (structured → stored as `object_filter`);
  refresh the list on success.

**Decision (this PR):** the preset load/save/delete logic is **duplicated** in
`filter-builder.ts` (its own copy), *not* yet extracted from `filter-bar.ts` — keeps this
PR's blast radius to new files. Follow-up issue filed to extract both onto a shared
`ts/elements/presets.ts` (§8).

### 5. Page composition

`filter_builder` view content, top→bottom, as **siblings** (so each element's `Media` is
auto-collected by `Page()` walking the tree — no `scripts=`):

1. `PageHeading` "Filter <Plural>".
2. `FilterBuilder(model=, mode=, apply_url=, preset_list_url=, preset_save_url=)` — toolbar.
3. `FilterSummary(model=, model_label=, models=)`.
4. `FilterCount(model=, noun_singular=, noun_plural=, endpoint=reverse count url)`.
5. `FilterGroup(model=, filter=filter_json)` — the existing builder, now seeded.

`FilterGroup` gains a `filter=` kwarg threaded into the `filter` prop; its `models` JSON is
already built inside the builder, and both `FilterSummary` and the summary context reuse the
same `model_field_registry(model)` JSON.

### 6. Entry point

A shared `AdvancedFilterLink(*, url)` builder (in `common/components/filters.py`) renders an
"Advanced filter →" link. Each of the four list views renders it as a sibling directly above
its `FilterBar` (same `Fragment(...)` the views already compose), pointing at
`reverse("games:filter_builder", args=[model])` with the live `?filter=` appended so the
builder prefills from whatever the flat bar currently has. Rendering in the view (not
threading a prop through the five `_FilterBarBase` subclasses) keeps the three non-builder
bars untouched.

### 7. Remove the demo page

Delete the DEBUG-only `/filter-group-demo/` route + `filter_group_demo` view from
`timetracker/urls.py` — the real `/…/filter` page supersedes it as the manual-test surface.

## Testing

- **vitest** (`ts/elements/*.test.ts`):
  - `filter-group`: `getFilledTree()` returns filled-unpruned; `loadFilter()` round-trips a
    canonical blob; `clear()` empties; `filter` prop seeds on connect; **negated-empty-root**
    import doesn't throw and serializes to `{}`.
  - `filter-summary`: mounts, updates text on `filter-tree-change`, builds context from props.
  - `filter-builder`: Apply builds the right URL (empty → bare, non-empty → `?filter=`);
    Apply disabled while incomplete; Clear calls `group.clear()`; preset load feeds
    `loadFilter`; save posts the serialized tree.
- **pytest** (`tests/`):
  - four `…/filter` routes return 200 (auth'd); a non-builder model 404s.
  - `?filter=<json>` renders the `filter` prop onto `<filter-group>`.
  - each list page renders the "Advanced filter" link with the current `?filter=`.
- **e2e** (`e2e/`): on `/game/filter`, build a cross-model filter (status + a session
  relation), Apply → assert the games list narrows; load a saved preset → tree + summary +
  count update; confirm the summary and count reflect edits.

Run the full `direnv exec . make check` (incl. e2e) before the PR.

## Known limitation shipped with this PR (#263)

Prefill seeds the tree structure + field selection but **not** the leaf value widgets, so a
prefilled filter (preset / `?filter=` URL / Advanced-filter link) is not yet carried through
**Apply** or the live **count** (`serializeForQuery()` reads the live, still-blank widgets).
Building a filter from scratch and applying it works fully. Tracked in **#263** and pinned by a
`strict=xfail` e2e that flips to a hard failure when the fix lands. Discovered at integration
during this PR (the leaf widgets built in #192/#245 were write-by-user only — never hydrated
from a model); folded into #263 rather than blocking the shell.

## Follow-up issues filed

1. **#263 — hydrate leaf value widgets on prefill** (blocking follow-up; the known limitation above).
2. **#264 — extract shared preset flow** — unify `filter-bar.ts` and `filter-builder.ts`
   preset load/save/delete onto `ts/elements/presets.ts` (deferred per the blast-radius decision).
3. **Quick-bar ↔ builder hand-off** — degrade-to-pill / "Edit in builder", tracked by **#197**;
   the `advanced_url` entry point here is the first half.

## Out of scope

- Leaf value-widget hydration on prefill (**#263**, see above).
- The single-model quick bar (#197).
- Per-group count badges (#198).
- Any new criterion / widget / relation behaviour — all landed.
