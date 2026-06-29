# Nested Filter Builder — Implementation Plan (master, #173 / phase 2b)

> **For agentic workers:** this is a **master plan**. It fixes the cross-component contracts, build order, and cross-cutting decisions for the #168 nested filter builder. Each 2c component (#186–#196) gets its **own** bite-sized TDD plan written later, one at a time, by a subagent at execution time (REQUIRED SUB-SKILL: `superpowers:writing-plans` per component, then `superpowers:subagent-driven-development`). This doc is what those per-component plans consume so they compose.

**Goal:** Replace the flat single-model filter bar with a recursive AND/OR/¬ tree builder on per-model `/…/filter` routes, reading/writing the existing `?filter=` `OperatorFilter` JSON.

**Architecture:** Homogeneous node tree (group / leaf / comparison / relation) in TS, a recursive canonical serializer ↔ `OperatorFilter` JSON, custom-element group/leaf widgets reusing existing leaf widgets, a per-model field-metadata API + live-count API, assembled on a `render_page` builder route. The `OperatorFilter` algebra (`common/criteria.py`) already supports arbitrary nesting — this is UI + serializer + two small endpoints + one backend guard.

**Tech Stack:** Django 6, custom elements + TypeScript (`ts/` → `games/static/js/dist/`, compile-only `tsc`), django-ninja API, pytest-django, Playwright e2e.

## Deliverable of #173

The actual work product is **this plan document**, committed to `docs/superpowers/plans/2026-06-29-nested-filter-builder.md` (mirrors how 2a committed its specs). The 2c child issues #186–#196 already exist; this plan does **not** rewrite them — it fixes the shared spine they reference. No feature code is written under #173.

## Adversarial review (3 agents, folded)

A 3-agent adversarial review verified §B against the real backend and found defects, all folded above:
- **HIGH — `field_comparisons` precedence:** the backend ANDs `field_comparisons` at the *outermost* level, *after* `OR` (`criteria.py:1067-1132`); the first draft folded them into the pre-OR `&`-part, flipping results. §B3 rewritten.
- **HIGH — `LeafNode` dropped `excludes`:** set criteria carry orthogonal `value`+`excludes`; §B1/§B2 now keep it (+ strip `{id,label}`→bare id/code on export).
- **HIGH — metadata choices not uniformly enumerable:** §B4 now classifies `choice_source` (model_choices / data_driven / search / none) instead of assuming model choices.
- **MED — serializer e2e harness:** no JS test runner + no bundler, so §F adds a `test-harness.ts` module exposing `window.__filterRoundTrip`.
- **LOW — props scalar-only:** §B5 clarifies nested state rides light-DOM + `data-*` JSON, `toNode()` reads the DOM.
- Build order / scaffolding coexistence (§C/§E): reviewed, **no blockers** (separate custom-element tags, separate serialization paths).

## Decisions settled this session (beyond the 2a spec)

1. **Field-metadata transport = JSON API endpoint.** `GET /api/<model>/filter-metadata` returns the per-model registry; the builder fetches it on load. (Not inline JSON, not codegen — keeps #152 codegen out of this epic.)
2. **Serializer contract tests = Playwright + Python.** No JS test runner exists (compile-only `tsc`); adding one is out of scope. A synthetic e2e page exposes `parse`/`serialize` on `window`; Playwright feeds `?filter=` fixtures and extracts output via `page.evaluate`; Python asserts `parse_*_filter(in).to_q() == parse_*_filter(out).to_q()` against the `live_server` DB.

## Global Constraints (verbatim from spec; every component inherits these)

- **Connectives are `AND`/`OR` only. Negation is a per-node `¬` flag** (toggle-NOT), serialized as a `{NOT:[node]}` wrapper. There is **no NOT group**. `¬` costs **0 nesting depth**.
- **Canonical export:** each group → exactly one connective key (`{AND:[…]}`/`{OR:[…]}`); each child a single-key dict; leaf → `{field:{…}}`; comparison → `{field_comparisons:[{…}]}`; relation → `{rel_field:{match?, <one canonical group>}}`; `¬`-set node wrapped `{NOT:[…]}`. **Never emit a mixed node.** Empty operator lists dropped (`{AND:[]}`→`{}`). Round-trip = **logical (`to_q()`) equivalence, not byte equality**.
- **Import is faithful, not implicit-AND:** reproduce `_apply_operators` left-to-right precedence (`common/criteria.py:1067`): `criteria &= fields`, then `&= each AND`, `|= each OR`, `&= ~each NOT`, `&= field_comparisons`. So `{name, OR:[x]}` imports as `OR[name, x]`, **not** `AND(name, x)`. `{NOT:[…]}` lists map to `¬`-flagged nodes.
- **Depth: UI soft cap 5** (group-nesting; relation child = +1; leaf = depth-0; `¬` = 0). **Backend guard = 10** (≥ UI cap), raised in `from_json`.
- **Incomplete leaves** (no field / missing value / partial BETWEEN) render faded + badge and are **excluded from both the count query and Apply**; Apply disabled while any leaf incomplete. Backend `filter_from_json` fail-closed (`FilterError`) stays the net.
- **Buttons-only restructuring, no drag-and-drop:** per-node remove / duplicate / wrap-in-group (defaults to parent connective) / unwrap-flatten / ↑ / ↓.
- **Single source of truth = `?filter=` JSON.** Builder lives on a separate route; the existing flat list-page bar is **not** removed by this epic (see §E).
- Spec: `docs/superpowers/specs/2026-06-28-nested-filter-builder-design.md`; review: `…-adversarial-review.md`.

---

## A. Component → files map (the 11 sub-issues)

| # | Issue | New / Modified files | Responsibility |
|---|-------|----------------------|----------------|
| 0 | #186 | M `common/criteria.py` (`from_json` ~1143/1198/1220) | Parse-time depth guard (raise `FilterError` past 10) |
| 9 | #187 | C `common/filter_metadata.py`; M `games/filters.py` (per-filter metadata hook), `games/api.py` (endpoint) | `{name,label,kind,nullable,choices,relations}` registry + `GET /api/<model>/filter-metadata` |
| 6 | #188 | C `ts/filter/model.ts`, `ts/filter/serialize.ts`, `ts/filter/test-harness.ts` (e2e glue) | Node tree types + canonical export + faithful import |
| 1 | #189 | C `ts/elements/filter-group.ts`, `common/components/filter_builder.py` | Recursive group shell custom element |
| 2 | #190 | M filter-group element + `common/components/filter_builder.py` | Connective chip + `¬` toggle |
| 3 | #191 | C `ts/elements/filter-field-picker.ts` (or fold into leaf) | Add-criterion searchable field picker (reads #187) |
| 4 | #192 | C `ts/elements/filter-leaf.ts`; M `ts/elements/search-select.ts`, `common/components/search_select.py`, `common/components/filters.py` | Leaf row + widgets; FilterSelect self-serialize; field-comparison **leaf** variant |
| 5 | #193 | C `ts/elements/filter-relation.ts`; M `filter_builder.py` | Relation-descent + ANY/NONE/ALL accent block |
| 7 | #194 | C `ts/filter/summary.ts` | Client-side tree → English walker |
| 8 | #195 | M `games/api.py`; C count badge element | `GET /api/<model>/count?filter=` + debounced badge |
| 10 | #196 | C `games/views/filter_builder.py`, route in `games/urls.py` | `/…/filter` page shell: toolbar, presets, Apply/Clear, mounts root |

---

## B. Shared contracts (fix these first — they gate the per-component plans)

### B1. Node model — `ts/filter/model.ts`

```ts
export type Connective = "AND" | "OR";
export type Quantifier = "ANY" | "NONE" | "ALL";
export type NodeKind = "group" | "leaf" | "comparison" | "relation";

export interface BaseNode { id: string; negate: boolean; } // id = randomid for DOM keying

export interface GroupNode extends BaseNode {
  kind: "group"; connective: Connective; children: FilterNode[];
}
export interface LeafNode extends BaseNode {
  kind: "leaf"; field: string; modifier: string;
  value: unknown; value2?: unknown;   // value2 only for BETWEEN
  excludes?: unknown[];               // set criteria only: orthogonal exclude channel (_SetCriterion.excludes)
}
export interface ComparisonNode extends BaseNode {
  kind: "comparison"; left: string; right: string; modifier: string;
  granularity?: "date";               // omitted == "raw"
}
export interface RelationNode extends BaseNode {
  kind: "relation"; relation: string; match: Quantifier; child: GroupNode;
}
export type FilterNode = GroupNode | LeafNode | ComparisonNode | RelationNode;
```

`isComplete(node)` predicate (drives faded/excluded state) lives here too.

### B2. Export — `serialize(node): object` (canonical)

Recursive, per-node (not one global form pass — replaces `filter-bar.ts` `setPath`/`appendAnd`/`nest`/`readWidget`):

- **group** → `{[connective]: children.filter(isComplete).map(serialize)}`; drop empty list to `{}`.
- **leaf** → `{[field]: {value, excludes?, modifier, value2?}}` (omit `value` for `IS_NULL`/`NOT_NULL`; emit `excludes` only for set criteria when non-empty). **Set values strip display pairs**: a FilterSelect carries `{id,label}` in the DOM for rendering, but the backend wants bare ids (`MultiCriterion` → `list[int]`) or codes (`ChoiceCriterion` → `list[str]`); export emits the bare id/code list.
- **comparison** → `{field_comparisons: [{left, right, modifier, granularity?}]}`.
- **relation** → `{[relation]: {...(match!=="ANY" ? {match} : {}), ...serialize(child)}}`.
- Any node with `negate` → wrap result `{NOT: [result]}`.

### B3. Import — `parse(dict, model): GroupNode` (faithful precedence)

Mirror `_apply_operators` (`common/criteria.py:1067-1132`) **exactly**. The backend folds in this order: `q = keyed-criteria & extra_q(sub-filters/relations) & AND`, then `q |= OR`, then `q &= ~NOT`, then `q &= field_comparisons`. So `field_comparisons` and `NOT` are both at the **outermost** `&` level, applied *after* `OR` — they do **not** belong in the pre-OR `&`-part. (Adversarially verified: putting `field_comparisons` inside the OR'd part flips results, e.g. `{name, OR:[status], field_comparisons:[cmp]}` with name=F, status=T, cmp=F → backend `False`, pre-OR placement `True`.)

For a dict at one level:
1. Build `C` = AND-group of: each keyed criterion → leaf; each sub-filter field → relation node; each `AND[i]` → `parse` recursively. **No `field_comparisons` here.**
2. If `OR` present: `P = OR[C, ...each OR[j] parsed]`, else `P = C`.
3. Collect the outermost AND children: `[P, ...each NOT[k] parsed with negate=true, ...each field_comparisons[i] → comparison leaf]`. If that list has >1 element → `AND[...]`; if exactly 1 → that child (collapse). So `{NOT:[{OR:[a,b]}]}` → an `OR[a,b]` node with `negate`; `{NOT:[a,b]}` → `AND[a¬, b¬]`; `{name, OR:[x], field_comparisons:[c]}` → `AND[ OR[name,x], comparison(c) ]`.
Root is always a `GroupNode` (wrap a bare collapsed child in an `AND` group). Uses #187 metadata to pick leaf widget per field. Re-export canonicalizes the shape (round-trip = `to_q()` equivalence, not byte equality).

### B4. Field-metadata registry — `common/filter_metadata.py` + endpoint

Reuse `resolve_path_kind`/`_criterion_class_for`/`comparable_columns` (`criteria.py:880/758/1494`); **build the missing** label/choices/nullable/relations. Per field: `{name, label, kind, nullable, choices, choice_source, search_url?, modifiers: [...]}`; plus `relations: [{field, label, target}]` and `comparable_columns`.

**Choices are NOT uniformly enumerable** (adversarially confirmed) — the registry must classify each field's `choice_source`, not assume model choices:
- `model_choices` — TextChoices/constant, enumerable now: `Game.Status.choices`; `Device.DEVICE_TYPES` (class constant, not a field — read the constant); `Purchase.ownership_type` (verify source). Emit `choices: [[code,label]…]`.
- `data_driven` — a bare `CharField` with no choices (`Platform.group`): values only exist in the DB. Emit `choices: null` + a `search_url` (or a distinct-values query at metadata time; note the cache risk). Do **not** hard-code.
- `search` — M2M / FK to an unbounded set (`Purchase.games`, `platform`, `device`): `choices: null` + `search_url` (reuse the existing `/api/*/search` endpoints).
- `none` — aggregates (`session_count`, `purchase_count`): numeric, `choices: null`, modifiers-only.

`nullable` from `model._meta.get_field(name).null` where a concrete field exists (aggregates/search/computed → `false`/omit). Endpoint `GET /api/<model>/filter-metadata` (django-ninja, `auth=django_auth` is already API-wide — `games/api.py:23`), `<model>` ∈ games/sessions/purchases/playevents.

### B5. Custom-element registration

New tags via `register_element(tag, TsName, PropsTypedDict)` in `common/components/custom_elements.py` (+ `make gen-element-types`): `filter-group`, `filter-leaf`, `filter-relation`, `filter-field-picker`, `filter-count`.

**Props are scalar-only** (`_TYPE_MAP` = str/int/float/bool, `custom_elements.py:61`) — so node props carry only scalars (`negate`, `connective`, `relation`, `match`, `field`, `modifier`). Nested/complex state (the group's children, a leaf's metadata, initial value JSON) passes as **server-rendered light-DOM children** + JSON `data-*` attributes — the existing `FieldComparisonSetProps.columns: str` (a JSON string) is the precedent, not a typed prop. Group/leaf/relation init in `connectedCallback`; on Apply, the root walks the in-DOM tree calling each element's **`toNode()` hook** (a method on the element instance that **reads the DOM**, not props) to build the `FilterNode` tree, then `serialize()`.

---

## C. Build order (dependency DAG)

`0 (#186) → 9 (#187) → 6 (#188) → { 1 #189, 2 #190, 3 #191, 4 #192, 5 #193 } → { 7 #194, 8 #195 } → 10 (#196)`

- **#186, #187, #188 are foundational and strictly first** (#188 blocks 1,2,4,5,7,8; #187 blocks 3,4,5,8).
- 1–5 parallelizable once #188+#187 land. 7 (NL summary) and 8 (count) need #188(+#187). 10 assembles everything.
- Each arrow = a reviewer gate; each component is its own PR with its own TDD plan.

## D. Slot-in of existing leaves

- **DateRangePicker** (`date_range_picker.py`) + **bool radio** → **clean reuse**: already DOM-read, already take `path=`. Wrap in a leaf node; add a `toNode()` reader.
- **FilterSelect** (`search_select.py:415`) → **rework to self-serialize**: today it relies on the global `readSearchSelect` preprocessing pass (`filter-bar.ts:244`) writing `data-included/excluded/modifier` before a flat read. In a tree there is no flat pass. **#192's plan must pin the mechanism** (don't leave "on change or toNode" open): the surrounding `filter-leaf` element's `toNode()` reads the FilterSelect's committed pills/state directly from the DOM (include set + `excludes` + modifier) — no new global pass, no per-element mutable module state shared with the flat bar. The flat bar keeps its own `readSearchSelect` path untouched (separate code path, verified non-colliding — different element trees, no shared state).
- **Field-comparison** → **new single-row leaf**: reuse the permanent `_field_comparison_row` markup (`filters.py:660`), embed its own `columns` (from #187), **drop the AND/OR mode toggle** (`_fc_mode_toggle`, `filters.py:718`) — the enclosing group owns the connective. The existing `FieldComparisonSet` (with toggle) stays for the flat bar.

## E. Scaffolding-removal order (#167 `TODO(nested-builder)` debt)

The new canonical serializer (#188) **never emits** the OR-isolation wrapper or the mode-toggle shapes. **But the deletions are NOT part of 2c:**

- The old flat bar (`ts/elements/filter-bar.ts`) + `_fc_mode_toggle` + the OR-isolation branch (`filter-bar.ts:265`, `filters.py:599`) keep serving the **list-page bars**, which this epic does **not** retire. They retire only when **#197 (quick bar)** replaces the flat per-list bar.
- **Action:** file a follow-up issue "Remove #167 `TODO(nested-builder)` debt once the flat bar is retired" blocked on #197 (per the *defer = file an issue* rule). Reference `filter-bar.ts:265`, `filters.py:599-601`, `_fc_mode_toggle`.
- Within 2c, #192 lands the **new** field-comparison leaf (canonical, no toggle), used only on the builder route — the two coexist until #197.

## F. Test strategy

- **#186:** pytest — a `{session_filter:{game_filter:{…}}}` nest past depth 10 raises `FilterError`; a known cyclic hand-edited filter terminates (no hang); a legitimate depth-5 build still parses.
- **#187:** pytest — `filter-metadata` JSON shape per model: every criterion field present with label/kind/nullable + correct `choice_source`. Assert `model_choices` fields (`status`, `device.type`) carry `choices`; `data_driven` (`platform_group`) and `search`/M2M (`games`, `platform`) carry `choices: null` + `search_url`; aggregates (`session_count`) carry `choices: null`, modifiers-only. Relations list matches the declared sub-filter fields. Extend the existing `resolve_path_kind` contract guard (`test_filter_paths.py`).
- **#188 (serializer) — the spine test:** **no JS test runner exists**, so add a dedicated harness module `ts/filter/test-harness.ts` that imports `parse`+`serialize` and assigns `window.__filterRoundTrip = (json) => serialize(parse(json, model))`; a synthetic e2e page loads it via `<script type="module" src="/static/js/dist/filter/test-harness.js">` (same module-load mechanism as `e2e/test_search_select_e2e.py`; needed because `tsc` emits ES modules with no bundler — a bare `export` is unreachable from `page.evaluate` without this glue). Playwright feeds `?filter=` fixtures, reads output via `page.evaluate`; Python asserts `parse_*_filter(in).to_q() == parse_*_filter(out).to_q()` against the `live_server` DB. Fixture matrix: canonical OR · `¬`-negated group **and** leaf · relation × {ANY, NONE, ALL} · field comparison (AND + the legacy OR-isolation shape) · **`field_comparisons` + `OR` at one level** (the precedence regression from review) · set criterion with `excludes` · mixed-shape import (`{name, OR:[x]}`) · empty operator lists dropped · `{NOT:[{OR:[a,b]}]}` and `{NOT:[a,b]}`.
- **#192 widgets / #189–#193:** Python render tests (`test_components.py` style) + e2e onSwap-init (`test_widgets_e2e.py` style) — FilterSelect self-serialize, field-comparison leaf, relation accent block, group restructuring (wrap/unwrap/↑↓/duplicate/remove), depth-cap disable.
- **#195:** pytest — `count` endpoint == `to_q().count()`; incomplete-leaf excluded; error → "count unavailable" path.
- **#196 (assembly) e2e:** on `/games/filter` build a cross-model filter (`games where ANY session device=Handheld`), Apply, assert list narrows; load a preset; assert NL summary + count update; (quick-bar degrade test belongs to #197).

## G. Follow-up issues to file

- **#167-debt removal** gated on #197 (see §E) — new issue.
- Per-group counts (#198) already filed.

## H. Verification of this deliverable

- Plan committed to `docs/superpowers/plans/2026-06-29-nested-filter-builder.md`; PR closes #173.
- Each 2c issue (#186–#196) can point at §B (contracts) + §C (order) + §F (its test bullet) without re-deriving them.
- Follow-up issue (§G) created via `gh`.

## I. Execution handoff

After this plan lands, build components in §C order — **one PR per component**, each with a fresh per-component TDD plan (subagent-driven). Start with #186 (independent backend guard), then #187 + #188 (foundational), then the widget fan-out.
