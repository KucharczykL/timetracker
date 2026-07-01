# Advanced Filter Builder Page Shell (#196) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble the landed nested-builder parts into a per-model `/…/filter` page (games, sessions, purchases, playevents) that prefills from `?filter=`, shows a live NL summary + result count, and applies back to the list.

**Architecture:** One dynamic Django route → a generic `render_page` view that mounts four sibling custom elements (`<filter-builder>` toolbar, `<filter-summary>`, `<filter-count>`, `<filter-group>`). The group gains prefill + `loadFilter`/`clear`/`getFilledTree`; two new self-wiring elements (`<filter-summary>`, `<filter-builder>`) listen for the group's `filter-tree-change`. An "Advanced filter →" link on each list is the entry point.

**Tech Stack:** Django 6, Python components (`common/components`), TypeScript custom elements (`ts/elements/`, compiled via `tsc` to `games/static/js/dist/`), vitest, pytest, pytest-playwright.

## Global Constraints

- **Run every command in the Nix dev shell:** prefix with `direnv exec .` (e.g. `direnv exec . make check`). A bare `make`/`pnpm`/`pytest` has no toolchain.
- **Custom elements only** — no inline JS/Alpine, no HTML-in-f-strings. Behavior in `ts/elements/<tag>.ts`; server contract is one `TypedDict` per element via `register_element(...)` in `common/components/custom_elements.py`; run `direnv exec . make gen-element-types` after any prop change (regenerates `ts/generated/props.ts`).
- **Build UI with node builders** from `common.components` (`Div`, `Span`, `A`, `StyledButton`, …); wrap trusted HTML in `Safe(...)`; group siblings with `Fragment(...)`.
- **`render_page()` not `render()`** for full pages; import from `common.layout`.
- **Never write GeneratedFields.** No new model here anyway.
- **Complete words in identifiers** (`element` not `el`, `template` not `tpl`).
- **Run `direnv exec . make ts`** after editing any `.ts` so `dist/` is fresh before e2e/serving.
- **Verification gate:** `direnv exec . make check` (lint + format + mypy + ts-check + vitest + full pytest incl. `e2e/`) must be green before the PR.
- **Codegen prop naming:** a TypedDict field `noun_singular` → HTML attribute `noun-singular` → TS prop `nounSingular`. The Python builder kwarg `noun_singular=` emits the `noun-singular` attribute (`_` → `-`).
- Branch: `feat/196-filter-builder-shell` (already created; design doc committed there).

---

## File Structure

**Create:**
- `ts/elements/filter-summary.ts` — NL summary badge element.
- `ts/elements/filter-summary.test.ts` — its vitest.
- `ts/elements/filter-builder.ts` — toolbar/orchestrator element (Apply/Clear/presets).
- `ts/elements/filter-builder.test.ts` — its vitest.
- `tests/test_filter_builder_page.py` — view/route/prefill/entry-link pytest.
- `e2e/test_filter_builder_e2e.py` — build → Apply → list narrows; preset load.

**Modify:**
- `common/components/custom_elements.py` — add `filter` to `FilterGroupProps` + thread `filter=` through the `FilterGroup` builder; add `FilterSummaryProps`/`FilterSummary` + `FilterBuilderProps`/`FilterBuilder`.
- `ts/generated/props.ts` — regenerated (do not hand-edit).
- `ts/elements/filter-group.ts` — `getFilledTree()`, `loadFilter()`, `clear()`, registry builder, prefill on connect.
- `ts/elements/filter-group.test.ts` — new-method + prefill + negated-empty-root tests.
- `common/components/filters.py` — `AdvancedFilterLink(*, url)` builder.
- `common/components/__init__.py` — export `FilterSummary`, `FilterBuilder`, `AdvancedFilterLink`.
- `games/views/general.py` — `filter_builder` view + per-model config.
- `games/urls.py` — `<str:model>/filter` route.
- `games/views/game.py`, `session.py`, `purchase.py`, `playevent.py` — render the Advanced link.
- `timetracker/urls.py` — remove the `/filter-group-demo/` route + view.

---

## Task 1: `<filter-group>` prefill + `getFilledTree`/`loadFilter`/`clear`

**Files:**
- Modify: `common/components/custom_elements.py` (FilterGroupProps + builder)
- Modify: `ts/generated/props.ts` (regenerated)
- Modify: `ts/elements/filter-group.ts`
- Test: `ts/elements/filter-group.test.ts`

**Interfaces:**
- Consumes: existing `serialize`, `deserialize(json, modelKey, registry)`, `emptyRoot()`, `fillCriteria`, `dispatchChange`, `render` in `filter-group.ts`; `MetadataRegistry`/`ModelMeta` from `filter-tree/types.ts`.
- Produces (relied on by Tasks 2–4):
  - `FilterGroupElement.getFilledTree(): GroupNode`
  - `FilterGroupElement.loadFilter(json: Record<string, unknown>): void`
  - `FilterGroupElement.clear(): void`
  - `FilterGroup(*, model, filter="")` Python builder emits a `filter` attribute.

- [ ] **Step 1: Add the `filter` prop (Python) and regenerate the reader**

In `common/components/custom_elements.py`, extend `FilterGroupProps`:

```python
class FilterGroupProps(TypedDict):
    model: str
    models: str
    # Initial ?filter= JSON, deserialized on connect so the server-rendered
    # filter is reflected on parse (comp 10, #196). Empty -> the empty-root
    # default. The client validates/normalizes; a bad blob fails open (empty).
    filter: str
```

Thread it through the builder — change its signature and the final return:

```python
def FilterGroup(*, model: str, filter: str = "") -> Node:
    ...
    return _FilterGroup(
        model=model,
        models=json.dumps(model_field_registry(model)),
        filter=filter,
    )[*templates]
```

Then regenerate:

Run: `direnv exec . make gen-element-types`
Expected: `ts/generated/props.ts` now has `filter: string;` in `FilterGroupProps` and `filter: el.getAttribute("filter") ?? "",` in `readFilterGroupProps`.

- [ ] **Step 2: Write the failing vitest**

Append to `ts/elements/filter-group.test.ts` (reuse the file's existing mount helper; if it mounts via `document.body.innerHTML = '<filter-group model="game" models=...>'`, follow that pattern — set `models` to a minimal registry with a `status` field and a `sessions` relation, and set the `filter` attribute before connecting):

```typescript
import { describe, expect, it } from "vitest";
import "./filter-group.js";
import type { FilterGroupElement } from "./filter-group.js";

// Minimal two-model registry: game.status (a plain field) + game.sessions
// (relation -> session), enough to deserialize the fixtures below.
const MODELS = JSON.stringify({
  game: {
    fields: [
      { name: "status", label: "Status", kind: "choice", nullable: false, choices: [], relations: [] },
      { name: "sessions", label: "Sessions", kind: "relation", nullable: false, choices: [],
        relations: [{ field: "sessions", label: "Sessions", model: "Session" }] },
    ],
    columns: [],
  },
  session: { fields: [], columns: [] },
});

function mountGroup(filter = ""): FilterGroupElement {
  document.body.innerHTML = "";
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  if (filter) group.setAttribute("filter", filter);
  document.body.appendChild(group);
  return group;
}

describe("filter-group comp-10 additions", () => {
  it("seeds the tree from the filter prop on connect", () => {
    const group = mountGroup(JSON.stringify({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] }));
    expect(group.serialize()).toEqual({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
  });

  it("loadFilter replaces the tree and clear empties it", () => {
    const group = mountGroup();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    expect(group.serialize()).toEqual({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    group.clear();
    expect(group.serialize()).toEqual({});
  });

  it("imports a negated-empty root without throwing (serializes to {})", () => {
    const group = mountGroup(JSON.stringify({ NOT: [{ AND: [] }] }));
    // A negated empty root is "matches all": serialize drops the empty group.
    expect(group.serialize()).toEqual({});
    expect(() => group.getFilledTree()).not.toThrow();
  });

  it("getFilledTree keeps incomplete leaves (unpruned)", () => {
    const group = mountGroup();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    const filled = group.getFilledTree();
    expect(filled.kind).toBe("group");
    expect(filled.children.length).toBe(1);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-group.test.ts`
Expected: FAIL — `group.loadFilter is not a function` / `getFilledTree is not a function` / seed assertion fails.

- [ ] **Step 4: Implement the additions in `ts/elements/filter-group.ts`**

Add to the imports from `./filter-tree/serializer.js`:

```typescript
import { deserialize, serialize } from "./filter-tree/serializer.js";
```

Add to the type imports from `./filter-tree/types.js`: `MetadataRegistry`, `ModelMeta`.

Build the registry from the already-parsed `this.models`, and add the three public methods (place `getFilledTree` next to the existing `serialize()`/`serializeForQuery()`; `fillCriteria` is already a private method — call it):

```typescript
  /** The filled-but-UNPRUNED tree (leaf values read live from widgets, incomplete
   *  leaves kept as `…` placeholders). The NL summary (#194) wants this; the count
   *  (#195) wants serializeForQuery(), which prunes. */
  getFilledTree(): GroupNode {
    return this.fillCriteria(this.tree, this.model);
  }

  /** Replace the whole tree from an OperatorFilter JSON blob (preset load / ?filter=
   *  import). Re-renders and fires filter-tree-change so summary + count refresh. */
  loadFilter(json: Record<string, unknown>): void {
    this.tree = deserialize(json, this.model, this.buildRegistry());
    this.render();
    this.dispatchChange();
  }

  /** Reset to an empty AND root. */
  clear(): void {
    this.tree = emptyRoot();
    this.render();
    this.dispatchChange();
  }

  // A name-set MetadataRegistry (what deserialize wants) projected from the richer
  // per-model ModelBundle map this element already parsed from the `models` prop.
  private buildRegistry(): MetadataRegistry {
    const registry: Record<string, ModelMeta> = {};
    for (const [key, bundle] of this.models) {
      const relations: Record<string, string> = {};
      for (const [name, meta] of bundle.fields) {
        const target = meta.relations[0]?.model;
        if (meta.kind === "relation" && target) relations[name] = target.toLowerCase();
      }
      registry[key] = { fields: new Set(bundle.fields.keys()), relations };
    }
    return registry;
  }
```

Seed from the `filter` prop in `connectedCallback`. After `this.parseModels(props.models); this.captureTemplates();` (inside the `if (!this.wired)` block, before `this.wired = true`), add a prefill from the prop — but do it once, before the first `render()`:

```typescript
      this.wired = true;
    }
    // Seed from ?filter= exactly once, before the first render, so summary/count
    // read the correct initial tree. A malformed blob fails open to the empty root.
    if (!this.seeded) {
      this.seeded = true;
      if (props.filter) {
        try {
          this.tree = deserialize(JSON.parse(props.filter), this.model, this.buildRegistry());
        } catch (error) {
          console.warn("filter-group: ignoring malformed filter prop", error);
        }
      }
    }
    this.render();
```

Add the field near the other private fields (`private wired = false;`):

```typescript
  private seeded = false;
```

- [ ] **Step 5: Run the vitest to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-group.test.ts`
Expected: PASS (all four new tests + the pre-existing suite).

- [ ] **Step 6: Type-check + build**

Run: `direnv exec . make ts-check && direnv exec . make ts`
Expected: no `tsc` errors; `games/static/js/dist/elements/filter-group.js` rebuilt.

- [ ] **Step 7: Commit**

```bash
git add common/components/custom_elements.py ts/generated/props.ts ts/elements/filter-group.ts ts/elements/filter-group.test.ts
git commit -m "feat(filters): filter-group prefill + loadFilter/clear/getFilledTree (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `<filter-summary>` element

**Files:**
- Create: `ts/elements/filter-summary.ts`
- Create: `ts/elements/filter-summary.test.ts`
- Modify: `common/components/custom_elements.py` (props + builder)
- Modify: `ts/generated/props.ts` (regenerated)
- Modify: `common/components/__init__.py` (export)

**Interfaces:**
- Consumes: `FilterGroupElement.getFilledTree()` (Task 1); `summarize`, `SummaryContext`, `SummaryModel` from `filter-tree/summary.js`; `FieldMeta`/`ComparisonColumnValue` types; `FILTER_TREE_CHANGE_EVENT`, `FilterGroupElement` from `filter-group.js`.
- Produces: `FilterSummary(*, model, model_label, models)` Python builder → `<filter-summary>` element rendering the NL readout. Relied on by Task 4's page.

- [ ] **Step 1: Register the element (Python) + regenerate**

In `common/components/custom_elements.py`, next to `FilterCountProps`/`FilterCount`:

```python
class FilterSummaryProps(TypedDict):
    model: str  # root model key, e.g. "game"
    model_label: str  # display plural noun, e.g. "Games"
    models: str  # JSON of model_field_registry(model) — same bundle as <filter-group>


register_element("filter-summary", "FilterSummary", FilterSummaryProps)
_FilterSummary = custom_element_builder("filter-summary")


def FilterSummary(*, model: str, model_label: str, models: str) -> Node:
    """Read-only natural-language readout of the current filter tree (#194, #196).

    Self-wiring like <filter-count>: watches the sibling <filter-group> for
    ``filter-tree-change`` and rewrites its text via ``summarize()``. Behavior in
    ``ts/elements/filter-summary.ts``; Media auto-attached."""
    return _FilterSummary(model=model, model_label=model_label, models=models)[
        Span(class_="text-sm text-body")[f"{model_label} (all)."]
    ]
```

(`Span` is already imported in the module; if not, add it to the `from common.components.primitives import …` line.)

Run: `direnv exec . make gen-element-types`
Expected: `readFilterSummaryProps` appears in `ts/generated/props.ts` with `model`, `modelLabel`, `models`.

- [ ] **Step 2: Write the failing vitest**

Create `ts/elements/filter-summary.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import "./filter-group.js";
import "./filter-summary.js";
import type { FilterGroupElement } from "./filter-group.js";

const MODELS = JSON.stringify({
  game: {
    fields: [
      { name: "status", label: "Status", kind: "choice", nullable: false,
        choices: [["f", "Finished"]], relations: [] },
    ],
    columns: [],
  },
});

function mount(filter = ""): { group: FilterGroupElement; summary: HTMLElement } {
  document.body.innerHTML = "";
  const summary = document.createElement("filter-summary");
  summary.setAttribute("model", "game");
  summary.setAttribute("model-label", "Games");
  summary.setAttribute("models", MODELS);
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  if (filter) group.setAttribute("filter", filter);
  document.body.appendChild(summary);
  document.body.appendChild(group);
  return { group, summary };
}

describe("<filter-summary>", () => {
  it("renders 'Games (all).' for an empty tree", () => {
    const { summary } = mount();
    expect(summary.textContent).toContain("Games (all).");
  });

  it("updates on filter-tree-change", () => {
    const { group, summary } = mount();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    expect(summary.textContent).toContain("Games where");
    expect(summary.textContent).toContain("Finished");
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-summary.test.ts`
Expected: FAIL — `filter-summary.js` does not exist / element not defined.

- [ ] **Step 4: Implement `ts/elements/filter-summary.ts`**

```typescript
import { readFilterSummaryProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
import { summarize } from "./filter-tree/summary.js";
import type { SummaryContext, SummaryModel } from "./filter-tree/summary.js";
import type { FieldMeta } from "./filter-tree/types.js";

// <filter-summary> — read-only English readout of the sibling <filter-group>'s
// current filter tree (#194 summarize(), mounted for #196). Self-wiring like
// <filter-count>: listens on document for filter-tree-change, rebuilds text from
// group.getFilledTree() (filled-but-unpruned, so incomplete leaves show "…").

const LABEL_CLASS = "text-sm text-body";

// One reachable model's bundle as it arrives in the `models` prop JSON.
interface ModelBundleJson {
  fields: FieldMeta[];
  columns?: [string, string][] | { value: string; label: string }[];
}

function isFilterGroup(element: Element): element is FilterGroupElement {
  return (
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).getFilledTree === "function"
  );
}

export class FilterSummaryElement extends HTMLElement {
  private context: SummaryContext = { modelKey: "", modelLabel: "", models: {} };
  private changeListener: ((event: Event) => void) | null = null;

  connectedCallback(): void {
    const props = readFilterSummaryProps(this);
    this.context = {
      modelKey: props.model,
      modelLabel: props.modelLabel,
      models: this.parseModels(props.models),
    };

    this.changeListener = (event: Event): void => {
      const target = event.target;
      if (target instanceof HTMLElement && isFilterGroup(target)) this.update(target);
    };
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);

    const group = document.querySelector("filter-group");
    if (group && isFilterGroup(group)) this.update(group);
  }

  disconnectedCallback(): void {
    if (this.changeListener) {
      document.removeEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
      this.changeListener = null;
    }
  }

  private parseModels(raw: string): Record<string, SummaryModel> {
    const models: Record<string, SummaryModel> = {};
    let bundles: Record<string, ModelBundleJson> = {};
    if (raw) {
      try {
        bundles = JSON.parse(raw) as Record<string, ModelBundleJson>;
      } catch {
        console.warn("filter-summary: malformed models prop");
      }
    }
    for (const [key, bundle] of Object.entries(bundles)) {
      const fields = new Map<string, FieldMeta>();
      for (const meta of bundle.fields) fields.set(meta.name, meta);
      const columns = new Map<string, string>();
      for (const column of bundle.columns ?? []) {
        if (Array.isArray(column)) columns.set(column[0], column[1]);
        else columns.set(column.value, column.label);
      }
      models[key] = { fields, columns: columns.size ? columns : undefined };
    }
    return models;
  }

  private update(group: FilterGroupElement): void {
    let label = this.querySelector("span");
    if (!label) {
      label = document.createElement("span");
      label.className = LABEL_CLASS;
      this.appendChild(label);
    }
    label.textContent = summarize(group.getFilledTree(), this.context);
  }
}

customElements.define("filter-summary", FilterSummaryElement);
```

Note: confirm `FieldMeta`, `SummaryModel`, `SummaryContext` are exported from their modules (they are — `summary.ts` exports `SummaryModel`/`SummaryContext`; `FieldMeta` is a generated/types export). If `FieldMeta` lives in `generated/props.ts` rather than `filter-tree/types.js`, import it from where `summary.ts` imports it — match that path.

- [ ] **Step 5: Run to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-summary.test.ts`
Expected: PASS.

- [ ] **Step 6: Export from `common/components/__init__.py`**

Add `FilterSummary` to the import block (alongside `FilterCount`, line ~34) and to `__all__` (alongside `"FilterCount"`, line ~267).

- [ ] **Step 7: Type-check + build + commit**

Run: `direnv exec . make ts-check && direnv exec . make ts`
Expected: clean.

```bash
git add ts/elements/filter-summary.ts ts/elements/filter-summary.test.ts common/components/custom_elements.py common/components/__init__.py ts/generated/props.ts
git commit -m "feat(filters): mount NL summary as <filter-summary> (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `<filter-builder>` toolbar element

**Files:**
- Create: `ts/elements/filter-builder.ts`
- Create: `ts/elements/filter-builder.test.ts`
- Modify: `common/components/custom_elements.py` (props + builder)
- Modify: `ts/generated/props.ts` (regenerated)
- Modify: `common/components/__init__.py` (export)

**Interfaces:**
- Consumes: `FilterGroupElement.serialize()`, `serializeForQuery()`, `loadFilter()`, `clear()` (Task 1); `FILTER_TREE_CHANGE_EVENT`; `window.fetchWithHtmxTriggers` (declared in `ts/toast.ts`).
- Produces: `FilterBuilder(*, model, mode, apply_url, preset_list_url, preset_save_url)` builder → `<filter-builder>` toolbar. Relied on by Task 4's page.

- [ ] **Step 1: Register the element (Python) + regenerate**

In `common/components/custom_elements.py`:

```python
class FilterBuilderProps(TypedDict):
    model: str  # root model key
    mode: str  # preset/list mode (plural), e.g. "games"
    apply_url: str  # list URL to navigate to on Apply
    preset_list_url: str
    preset_save_url: str


register_element("filter-builder", "FilterBuilder", FilterBuilderProps)
_FilterBuilder = custom_element_builder("filter-builder")


def FilterBuilder(
    *, model: str, mode: str, apply_url: str, preset_list_url: str, preset_save_url: str
) -> Node:
    """Toolbar/orchestrator for the nested filter builder page (#196).

    Owns [Load preset ▾] [Save as preset…] [Apply] [Clear]; drives the sibling
    <filter-group> (serialize -> navigate on Apply; loadFilter on preset pick;
    clear on Clear). Behavior in ``ts/elements/filter-builder.ts``."""
    return _FilterBuilder(
        model=model,
        mode=mode,
        apply_url=apply_url,
        preset_list_url=preset_list_url,
        preset_save_url=preset_save_url,
    )[
        Div(class_="flex flex-wrap gap-3 items-center mb-4")[
            Div(class_="relative")[
                StyledButton(color="gray", attributes=[("data-load-presets", "")])[
                    "Load preset ▾"
                ],
                Div(
                    {"data-preset-dropdown": ""},
                    class_=(
                        "hidden absolute z-10 mt-1 min-w-[12rem] rounded-lg border "
                        "border-default-medium bg-body shadow-lg"
                    ),
                )[Ul(class_="py-1")],
            ],
            Input(
                type="text",
                data_preset_name="",
                placeholder="Preset name…",
                class_=(
                    "px-3 py-2 text-sm rounded-lg border border-default-medium "
                    "bg-neutral-secondary-medium text-heading"
                ),
            ),
            StyledButton(color="gray", attributes=[("data-save-preset", "")])[
                "Save as preset…"
            ],
            StyledButton(color="blue", attributes=[("data-apply", "")])["Apply"],
            StyledButton(color="gray", attributes=[("data-clear", "")])["Clear"],
        ]
    ]
```

Confirm `Div`, `Ul`, `Input`, `StyledButton` are imported in the module (add any missing to the primitives import). `StyledButton`'s dynamic attribute goes through its positional `attributes=` — check its current signature; if `StyledButton` rejects `attributes=` (per the htpy migration it may), use a plain `Button(..., data_apply="")` with the styled classes inline, matching `_filter_action_row` in `filters.py`. **Prefer copying the exact `Button(type="button", data_…="", class_=…)` pattern from `_filter_action_row`** so the buttons match the flat bar visually.

Run: `direnv exec . make gen-element-types`
Expected: `readFilterBuilderProps` in `ts/generated/props.ts`.

- [ ] **Step 2: Write the failing vitest**

Create `ts/elements/filter-builder.test.ts`. Mock navigation by spying on a helper — the element should navigate via a small `navigate(url)` method we can stub, OR assert on a captured `location`-setter. Simplest: have `filter-builder.ts` call `this.navigate(url)` (a protected method that sets `window.location.href`), and in the test subclass/spy it. Concretely, expose the URL builder as a pure exported function and unit-test that, plus test Apply-disabled wiring:

```typescript
import { describe, expect, it, vi } from "vitest";
import "./filter-group.js";
import "./filter-builder.js";
import { applyUrl } from "./filter-builder.js";
import type { FilterGroupElement } from "./filter-group.js";

const MODELS = JSON.stringify({
  game: {
    fields: [{ name: "status", label: "Status", kind: "choice", nullable: false, choices: [], relations: [] }],
    columns: [],
  },
});

describe("applyUrl", () => {
  it("returns the bare list url for an empty filter", () => {
    expect(applyUrl("/tracker/game/list", {})).toBe("/tracker/game/list");
  });
  it("appends ?filter= for a non-empty filter", () => {
    const filter = { AND: [{ status: { modifier: "EQUALS", value: "f" } }] };
    expect(applyUrl("/tracker/game/list", filter)).toBe(
      "/tracker/game/list?filter=" + encodeURIComponent(JSON.stringify(filter)),
    );
  });
});

function mount(): { group: FilterGroupElement; builder: HTMLElement } {
  document.body.innerHTML = "";
  const builder = document.createElement("filter-builder");
  builder.setAttribute("model", "game");
  builder.setAttribute("mode", "games");
  builder.setAttribute("apply-url", "/tracker/game/list");
  builder.setAttribute("preset-list-url", "/tracker/filter/presets/list");
  builder.setAttribute("preset-save-url", "/tracker/filter/presets/save");
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  document.body.appendChild(builder);
  document.body.appendChild(group);
  return { group, builder };
}

describe("<filter-builder>", () => {
  it("Clear empties the group tree", () => {
    const { group, builder } = mount();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    (builder.querySelector("[data-clear]") as HTMLElement).click();
    expect(group.serialize()).toEqual({});
  });

  it("Apply navigates to applyUrl(serializeForQuery())", () => {
    const { builder } = mount();
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith("/tracker/game/list");
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-builder.test.ts`
Expected: FAIL — `filter-builder.js` / `applyUrl` missing.

- [ ] **Step 4: Implement `ts/elements/filter-builder.ts`**

```typescript
import { readFilterBuilderProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";

// <filter-builder> — the builder-page toolbar (#196). Owns Load/Save preset,
// Apply, Clear; drives the sibling <filter-group>. Preset load/save/delete is
// duplicated from filter-bar.ts for now (follow-up: extract to presets.ts).

export function applyUrl(listUrl: string, filter: Record<string, unknown>): string {
  if (Object.keys(filter).length === 0) return listUrl;
  return listUrl + "?filter=" + encodeURIComponent(JSON.stringify(filter));
}

function isFilterGroup(element: Element | null): element is FilterGroupElement {
  return (
    element instanceof HTMLElement &&
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).serializeForQuery === "function"
  );
}

export class FilterBuilderElement extends HTMLElement {
  private mode = "";
  private applyTarget = "";
  private presetListUrl = "";
  private presetSaveUrl = "";
  private incompleteCount = 0;
  private changeListener: ((event: Event) => void) | null = null;

  connectedCallback(): void {
    const props = readFilterBuilderProps(this);
    this.mode = props.mode;
    this.applyTarget = props.applyUrl;
    this.presetListUrl = props.presetListUrl;
    this.presetSaveUrl = props.presetSaveUrl;

    this.addEventListener("click", this.onClick);
    this.changeListener = (event: Event): void => {
      const detail = (event as CustomEvent<{ incompleteCount: number }>).detail;
      if (detail) {
        this.incompleteCount = detail.incompleteCount;
        this.syncApplyDisabled();
      }
    };
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
    this.syncApplyDisabled();
  }

  disconnectedCallback(): void {
    if (this.changeListener) {
      document.removeEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
      this.changeListener = null;
    }
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  private group(): FilterGroupElement | null {
    const found = document.querySelector("filter-group");
    return isFilterGroup(found) ? found : null;
  }

  private syncApplyDisabled(): void {
    const apply = this.querySelector<HTMLButtonElement>("[data-apply]");
    if (apply) apply.disabled = this.incompleteCount > 0;
  }

  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (target.closest("[data-apply]")) return this.onApply();
    if (target.closest("[data-clear]")) return this.group()?.clear();
    if (target.closest("[data-load-presets]")) return this.onLoadPresets();
    if (target.closest("[data-save-preset]")) return this.onSavePreset();
    const presetLink = target.closest<HTMLAnchorElement>("[data-preset-dropdown] a[href]");
    if (presetLink) {
      event.preventDefault();
      return this.onPresetPicked(presetLink);
    }
    const deleteButton = target.closest<HTMLElement>("[data-delete-preset]");
    if (deleteButton) {
      event.preventDefault();
      return this.onDeletePreset(deleteButton);
    }
  };

  private onApply(): void {
    const group = this.group();
    if (!group) return;
    this.navigate(applyUrl(this.applyTarget, group.serializeForQuery()));
  }

  private onLoadPresets(): void {
    const dropdown = this.querySelector<HTMLElement>("[data-preset-dropdown]");
    if (!dropdown) return;
    dropdown.classList.toggle("hidden");
    if (dropdown.classList.contains("hidden")) return;
    const separator = this.presetListUrl.indexOf("?") === -1 ? "?" : "&";
    fetch(this.presetListUrl + separator + "mode=" + encodeURIComponent(this.mode), {
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) throw new Error("preset list failed");
        return response.text();
      })
      .then((html) => {
        dropdown.innerHTML = html;
      })
      .catch(() => window.toast("Failed to load presets.", "error"));
  }

  // The list fragment's anchors carry ?filter=<json> in their href (see
  // list_presets). Read it out and feed the group instead of navigating.
  private onPresetPicked(anchor: HTMLAnchorElement): void {
    const raw = new URL(anchor.href, window.location.origin).searchParams.get("filter") ?? "";
    const group = this.group();
    if (!group) return;
    try {
      group.loadFilter(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
    } catch {
      window.toast("Preset is not a valid filter.", "error");
    }
    this.querySelector("[data-preset-dropdown]")?.classList.add("hidden");
  }

  private onDeletePreset(button: HTMLElement): void {
    const deleteUrl = button.getAttribute("href");
    if (!deleteUrl || !confirm("Delete this preset?")) return;
    window
      .fetchWithHtmxTriggers(deleteUrl, { method: "DELETE", credentials: "same-origin" })
      .then(() => this.onLoadPresets())
      .catch(() => window.toast("Failed to delete preset.", "error"));
  }

  private onSavePreset(): void {
    const input = this.querySelector<HTMLInputElement>("[data-preset-name]");
    const group = this.group();
    if (!input || !group) return;
    const name = input.value.trim();
    if (!name) {
      window.toast("Preset name is required.", "error");
      return;
    }
    const body = new FormData();
    body.append("name", name);
    body.append("mode", this.mode);
    body.append("filter", JSON.stringify(group.serialize()));
    window
      .fetchWithHtmxTriggers(this.presetSaveUrl, {
        method: "POST",
        body,
        credentials: "same-origin",
      })
      .then(() => {
        input.value = "";
      })
      .catch(() => window.toast("Failed to save preset.", "error"));
  }
}

customElements.define("filter-builder", FilterBuilderElement);
```

Note: `window.toast` / `window.fetchWithHtmxTriggers` typings come from `ts/toast.ts`'s global declarations — the flat `filter-bar.ts` uses both, so the ambient types already exist. CSRF: `fetchWithHtmxTriggers` sends the cookie; the save/delete endpoints require CSRF, so confirm `fetchWithHtmxTriggers` adds the `X-CSRFToken` header (it does — `filter-bar.ts` relies on it). If it does not, add the header from the `csrftoken` cookie the same way `filter-bar.ts` does.

- [ ] **Step 5: Run to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-builder.test.ts`
Expected: PASS.

- [ ] **Step 6: Export + build + commit**

Add `FilterBuilder` to `common/components/__init__.py` (import block + `__all__`).

Run: `direnv exec . make ts-check && direnv exec . make ts`
Expected: clean.

```bash
git add ts/elements/filter-builder.ts ts/elements/filter-builder.test.ts common/components/custom_elements.py common/components/__init__.py ts/generated/props.ts
git commit -m "feat(filters): <filter-builder> toolbar (apply/clear/presets) (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Backend route + `filter_builder` view + remove demo page

**Files:**
- Modify: `games/views/general.py`
- Modify: `games/urls.py`
- Modify: `timetracker/urls.py` (remove demo)
- Test: `tests/test_filter_builder_page.py`

**Interfaces:**
- Consumes: `FilterBuilder`, `FilterSummary`, `FilterCount`, `FilterGroup`, `PageHeading`, `Fragment` from `common.components`; `filter_for_model`, `model_field_registry` from `games.filters`; `render_page`.
- Produces: `general.filter_builder(request, model)` view; URL name `games:filter_builder` (arg `model`). Relied on by Task 5's entry link + e2e.

- [ ] **Step 1: Write the failing pytest**

Create `tests/test_filter_builder_page.py`:

```python
import json

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.mark.parametrize("model", ["game", "session", "purchase", "playevent"])
def test_builder_page_renders(logged_in_client, model):
    response = logged_in_client.get(reverse("games:filter_builder", args=[model]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "<filter-group" in body
    assert "<filter-builder" in body
    assert "<filter-summary" in body
    assert "<filter-count" in body


def test_builder_rejects_unknown_model(logged_in_client):
    response = logged_in_client.get(reverse("games:filter_builder", args=["nope"]))
    assert response.status_code == 404


def test_builder_prefills_filter_prop(logged_in_client):
    filter_json = json.dumps({"AND": [{"name": {"modifier": "EQUALS", "value": "Zelda"}}]})
    response = logged_in_client.get(
        reverse("games:filter_builder", args=["game"]), {"filter": filter_json}
    )
    assert response.status_code == 200
    # The raw JSON is escaped into the filter attribute; assert a distinctive token.
    assert "Zelda" in response.content.decode()


def test_builder_requires_login(client):
    response = client.get(reverse("games:filter_builder", args=["game"]))
    assert response.status_code == 302  # redirect to login
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . pytest tests/test_filter_builder_page.py -q`
Expected: FAIL — `NoReverseMatch: 'filter_builder'`.

- [ ] **Step 3: Implement the view in `games/views/general.py`**

Add imports at the top of the file (extend the existing `from common.components import …` / add one):

```python
from common.components import (
    FilterBuilder,
    FilterCount,
    FilterGroup,
    FilterSummary,
    Fragment,
    PageHeading,
)
from games.filters import filter_for_model
```

Add the per-model config and view (near the other list-adjacent views):

```python
# The four lists backed by an OperatorFilter + nested builder. Keys are model
# keys (Model._meta.model_name); `mode` is the plural preset/list mode.
_BUILDER_MODELS: dict[str, str] = {
    "game": "games",
    "session": "sessions",
    "purchase": "purchases",
    "playevent": "playevents",
}


@login_required
def filter_builder(request: HttpRequest, model: str) -> HttpResponse:
    """Advanced nested-filter builder page for one model (#196).

    Mounts the toolbar + NL summary + live count + root <filter-group>, seeded
    from ?filter=. Apply navigates back to the model's list with ?filter=.
    """
    mode = _BUILDER_MODELS.get(model)
    if mode is None:
        raise Http404(f"No filter builder for model {model!r}")

    django_model = filter_for_model(model).model  # the Django model class
    meta = django_model._meta
    label = str(meta.verbose_name_plural).title()
    filter_json = request.GET.get("filter", "")
    models_json = json.dumps(model_field_registry(model))

    content = Fragment(
        PageHeading(f"Filter {label}"),
        FilterBuilder(
            model=model,
            mode=mode,
            apply_url=reverse(f"games:list_{mode}"),
            preset_list_url=reverse("games:list_presets"),
            preset_save_url=reverse("games:save_preset"),
        ),
        FilterSummary(model=model, model_label=label, models=models_json),
        FilterCount(
            model=model,
            noun_singular=str(meta.verbose_name),
            noun_plural=str(meta.verbose_name_plural),
            endpoint=reverse("api-1.0.0:filter_count"),
        ),
        FilterGroup(model=model, filter=filter_json),
    )
    return render_page(request, content, title=f"Filter {label}")
```

Add the needed imports to `general.py`: `Http404` (`from django.http import Http404` — add to the existing django.http import), `json` (`import json` at top), and `model_field_registry` (extend the `from games.filters import …` line to include `filter_for_model, model_field_registry`).

**Check `filter_for_model(...).model`:** `OperatorFilter` subclasses may not expose `.model`. If not, resolve the Django model directly: `from django.apps import apps; django_model = apps.get_model("games", model)`. Use whichever the codebase supports (grep `class GameFilter` for a `model` attr; fall back to `apps.get_model`).

- [ ] **Step 4: Add the route in `games/urls.py`**

Add to `urlpatterns` (near the list routes), and import `general` if not already:

```python
    path("<str:model>/filter", general.filter_builder, name="filter_builder"),
```

Place it so it does not shadow more specific patterns — `<str:model>/filter` only matches a two-segment `…/filter` path; existing routes like `game/list`, `game/<int:game_id>/edit` do not end in `/filter`, so ordering is not critical, but add it after the explicit `game/…` block for readability.

- [ ] **Step 5: Run to verify the view tests pass**

Run: `direnv exec . pytest tests/test_filter_builder_page.py -q`
Expected: PASS (all 4 parametrized + unknown-model 404 + prefill + login).

- [ ] **Step 6: Remove the demo page**

In `timetracker/urls.py`, delete the DEBUG block that defines `filter_group_demo` and appends `path("filter-group-demo/", filter_group_demo)` (lines ~49–91, the comment + `from django.http import HttpResponse` + `from django.templatetags.static import static` + `from common.components import FilterGroup` that are only used by it + the function + the append). Leave the other DEBUG-only appends (admin, debug toolbar) intact.

Run: `direnv exec . make lint` (ruff will flag any now-unused import left behind)
Expected: clean (no unused-import errors).

- [ ] **Step 7: Commit**

```bash
git add games/views/general.py games/urls.py timetracker/urls.py tests/test_filter_builder_page.py
git commit -m "feat(filters): builder page route + view; drop demo page (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: "Advanced filter →" entry link on the four lists

**Files:**
- Modify: `common/components/filters.py` (`AdvancedFilterLink`)
- Modify: `common/components/__init__.py` (export)
- Modify: `games/views/game.py`, `games/views/session.py`, `games/views/purchase.py`, `games/views/playevent.py`
- Test: `tests/test_filter_builder_page.py` (extend)

**Interfaces:**
- Consumes: `reverse("games:filter_builder", args=[model])` (Task 4); each list view's existing `filter_json`.
- Produces: `AdvancedFilterLink(*, url)` builder → an `<a>` link node.

- [ ] **Step 1: Write the failing pytest (extend the Task 4 file)**

Append to `tests/test_filter_builder_page.py`:

```python
@pytest.mark.parametrize(
    "list_name, model",
    [
        ("list_games", "game"),
        ("list_sessions", "session"),
        ("list_purchases", "purchase"),
        ("list_playevents", "playevent"),
    ],
)
def test_list_has_advanced_filter_link(logged_in_client, list_name, model):
    response = logged_in_client.get(reverse(f"games:{list_name}"))
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("games:filter_builder", args=[model]) in body
    assert "Advanced filter" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `direnv exec . pytest tests/test_filter_builder_page.py::test_list_has_advanced_filter_link -q`
Expected: FAIL — the builder URL / "Advanced filter" text absent from the list pages.

- [ ] **Step 3: Implement `AdvancedFilterLink` in `common/components/filters.py`**

Add near the other small filter-bar helpers (top of the file, after imports). It builds a URL carrying the current `?filter=`:

```python
def AdvancedFilterLink(*, url: str) -> Node:
    """An 'Advanced filter →' link into the nested builder page (#196).

    `url` is the fully-formed builder URL (already carrying ?filter= when the
    list currently has one). Rendered by each list view above its FilterBar."""
    return A(
        href=url,
        class_="inline-block mb-2 text-sm text-brand hover:underline",
    )["Advanced filter →"]
```

Ensure `A` and `Node` are imported in `filters.py` (they are used elsewhere in the module; if not, add to the `from common.components.* import …` lines). Export `AdvancedFilterLink` from `common/components/__init__.py` (import block + `__all__`).

- [ ] **Step 4: Wire it into each list view**

In `games/views/game.py`, where it currently builds `content = Fragment(filter_bar, content)` (~line 161), build the link URL from the live `filter_json` and prepend it:

```python
from urllib.parse import quote  # add near the top if absent

    builder_url = reverse("games:filter_builder", args=["game"])
    if filter_json:
        builder_url = f"{builder_url}?filter={quote(filter_json)}"
    content = Fragment(AdvancedFilterLink(url=builder_url), filter_bar, content)
```

Import `AdvancedFilterLink` in the `from common.components import (…)` block. Repeat the identical pattern in:
- `games/views/session.py` — `args=["session"]`, its `filter_json`.
- `games/views/purchase.py` — `args=["purchase"]`, its `filter_json` (note purchase imports `PurchaseFilterBar` locally; add `AdvancedFilterLink` to its import).
- `games/views/playevent.py` — `args=["playevent"]`, its `filter_json`.

Each view already has a `filter_json = request.GET.get("filter", "")` (confirmed in session/purchase/playevent; game uses `filter_json` for the bar). Use that same variable.

- [ ] **Step 5: Run to verify it passes**

Run: `direnv exec . pytest tests/test_filter_builder_page.py -q`
Expected: PASS (all list-link params + the Task 4 tests).

- [ ] **Step 6: Commit**

```bash
git add common/components/filters.py common/components/__init__.py games/views/game.py games/views/session.py games/views/purchase.py games/views/playevent.py tests/test_filter_builder_page.py
git commit -m "feat(filters): 'Advanced filter' entry link on the four lists (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: End-to-end test

**Files:**
- Create: `e2e/test_filter_builder_e2e.py`

**Interfaces:**
- Consumes: the live `/tracker/game/filter` page; the `filter-group`/`filter-builder`/`filter-summary`/`filter-count` elements; a seeded game/session so a filter can narrow results.

- [ ] **Step 1: Build fresh assets (e2e serves `dist/`)**

Run: `direnv exec . make ts && direnv exec . make css`
Expected: `dist/elements/filter-builder.js`, `filter-summary.js`, `filter-group.js` present.

- [ ] **Step 2: Write the e2e test**

Create `e2e/test_filter_builder_e2e.py`. Follow the existing `e2e/` conventions (look at `e2e/test_widgets_e2e.py` for the `live_server`, login, and `page` fixtures — reuse its login helper/fixture rather than reinventing). Skeleton:

```python
import pytest
from playwright.sync_api import Page, expect

# Reuse the project's e2e login fixture/helpers from conftest; if e2e uses a
# `logged_in_page` fixture, depend on it instead of logging in inline.


@pytest.mark.e2e
def test_apply_narrows_the_game_list(logged_in_page: Page, live_server, seeded_games):
    page = logged_in_page
    page.goto(f"{live_server.url}/tracker/game/filter")

    # The builder starts with one empty leaf row (field picker). Pick a field +
    # value that matches a subset of seeded_games, then Apply.
    page.locator("filter-group [data-field-picker] ...").click()  # adapt selectors
    # ... choose status = Finished (mirror the selectors test_widgets_e2e uses) ...

    summary = page.locator("filter-summary")
    expect(summary).to_contain_text("Games where")

    count = page.locator("filter-count")
    expect(count).not_to_contain_text("Counting…")  # settles

    page.locator("filter-builder [data-apply]").click()
    expect(page).to_have_url(lambda url: "/tracker/game/list?filter=" in url)
    # Assert the results table shows fewer rows than the unfiltered list.
```

**Adapt the leaf-picking selectors to the real markup** — open `/tracker/game/filter` under `direnv exec . make dev` (or read `filter-group.ts renderGroup`) to get the exact field-picker / modifier / value selectors, and reuse the interaction helpers `test_widgets_e2e.py` already has for FilterSelect. Keep the assertion focused: after Apply, the URL carries `?filter=` and the game list is narrowed.

- [ ] **Step 3: Run the e2e test**

Run: `direnv exec . pytest e2e/test_filter_builder_e2e.py -q`
Expected: PASS (needs a system Chrome; `e2e/conftest.py` finds it).

- [ ] **Step 4: Commit**

```bash
git add e2e/test_filter_builder_e2e.py
git commit -m "test(filters): e2e build-apply-narrow on the builder page (#196)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Follow-up issues + full verification + PR

**Files:** none (process task).

- [ ] **Step 1: File the deferred follow-up issues**

```bash
gh issue create --repo KucharczykL/timetracker \
  --title "Extract shared preset load/save/delete into ts/elements/presets.ts" \
  --body "filter-bar.ts and filter-builder.ts (#196) now carry near-identical preset load/save/delete flows. Extract onto a shared ts/elements/presets.ts and wire both. Deferred from #196 to keep that PR's blast radius to new files. Part of #168."
```

(The quick-bar ↔ builder hand-off is already tracked by #197; do not duplicate it — just reference it in the PR.)

- [ ] **Step 2: Run the full verification gate**

Run: `direnv exec . make check`
Expected: green — lint, format-check, mypy, ts-check, icon/element-type drift, vitest, and the full pytest suite **including `e2e/`**. Fix anything red and re-run until clean. Do not proceed on a partial run.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/196-filter-builder-shell
gh pr create --repo KucharczykL/timetracker --base main \
  --title "feat(filters): advanced filter builder page shell (#196)" \
  --body "$(cat <<'EOF'
Assembles the nested-builder parts into a per-model /…/filter page (games, sessions, purchases, playevents): toolbar (Load/Save preset, Apply, Clear), NL summary, live count, root <filter-group> seeded from ?filter=. Apply navigates back to the list with ?filter=. An "Advanced filter →" link on each list is the entry point. Removes the DEBUG /filter-group-demo/ page (superseded).

New: <filter-summary>, <filter-builder> elements; filter-group gains getFilledTree/loadFilter/clear + a filter prefill prop.

Preset code is duplicated from filter-bar.ts for now (follow-up filed to extract ts/elements/presets.ts). Quick-bar hand-off tracked by #197.

Closes #196. Part of #168.

Design: docs/superpowers/specs/2026-07-01-issue-196-filter-builder-page-shell-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes (coverage vs spec)

- Spec §1 route+view → Task 4. §2 group additions → Task 1 (incl. negated-empty-root edge test). §3 `<filter-summary>` → Task 2. §4 `<filter-builder>` → Task 3 (preset duplication decision honored). §5 page composition → Task 4 view. §6 entry link → Task 5. §7 remove demo → Task 4 Step 6. §Testing → Tasks 1–6. §Follow-ups → Task 7.
- Type consistency: `getFilledTree`/`loadFilter`/`clear` names identical across Tasks 1→2→3; `applyUrl` used in Task 3 only; `FilterSummary`/`FilterBuilder`/`FilterCount`/`FilterGroup` builder kwargs match their `*Props` TypedDicts and the `general.py` call site (Task 4).
- Known adaptation points flagged inline (not placeholders): `filter_for_model(...).model` vs `apps.get_model` fallback (Task 4 Step 3); `StyledButton(attributes=…)` vs copying `_filter_action_row`'s `Button` pattern (Task 3 Step 1); e2e leaf-picking selectors (Task 6 Step 2); `fetchWithHtmxTriggers` CSRF header presence (Task 3 Step 4). Each says exactly how to resolve by reading a named existing file.
