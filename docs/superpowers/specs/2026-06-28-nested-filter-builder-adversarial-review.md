# Nested Filter Builder — Adversarial Review

**Reviews:** serialization round-trip, UX coherence, component/reuse feasibility (3 parallel
adversarial agents) + empirical verification via Django shell.
**Subject:** `2026-06-28-nested-filter-builder-design.md` (#172).
**Date:** 2026-06-28

Each finding: claim → verdict (verified against `common/criteria.py` + a live Django shell
repro) → resolution folded into the spec.

## Empirical verification (the decisive evidence)

Ran the canonical and mixed forms through `GameFilter.to_q()` against the real DB (817 games):

| JSON | resulting WHERE | count |
|------|-----------------|-------|
| `Q() \| Q(status="f")` | `(AND: status='f')` | 188 |
| canonical `{"OR":[{status:f},{status:p}]}` | `(AND:(OR: status in[f], status in[p]))` | 271 |
| wrapped `{"AND":[{"OR":[…]}]}` | identical | 271 |
| mixed `{"name":"zzz","OR":[{status:f}]}` | `(OR: name='zzz', status in[f])` | — |

**Key result:** the dreaded `Q() \| Q(x)` match-all poisoning **does not occur** — Django
absorbs the empty `Q()` in an OR, so `Q() \| Q(x)` == `Q(x)`. The **canonical single-connective
OR form evaluates identically to the OR-isolation-wrapper form** (both 271). So the design's
canonical export is **correct**, and the transitional OR-isolation wrapper is genuinely
droppable. The serialization reviewer's "fundamental architectural mismatch" verdict was wrong
*for canonical output*; the real defect is narrower (import only) — below.

## CONFIRMED defects → resolutions

### 1. Import normalization was wrong (spec fix) — **HIGH**
A mixed dict does **not** mean "implicit AND group." Per `_apply_operators` (criteria.py:1080)
+ verified: a node evaluates `criteria &= …`, then `&= AND_i`, then `|= OR_j`, then `&= ~NOT_k`
left-to-right. So `{name, OR:[x]}` = `name OR x`, not `AND(name, x)`.
**Resolution:** rewrite the import section — the importer must reproduce this exact left-assoc
precedence as an explicit nested tree (build the `&`-part as an AND group, OR it under an
OR group if `OR` present, then AND the negated `NOT` children). The builder's own *export* stays
canonical (single-connective nodes); only *import of arbitrary/legacy JSON* needs the faithful
reading. In practice the app never emits mixed nodes (the OR-isolation wrapper kept OR isolated),
so this matters for hand-edited / shared URLs.

### 2. NOT-group silent semantic shift → **toggle-NOT model** — **HIGH**
Backend `{NOT:[a,b]}` = `~a AND ~b` ("none of"). Modeling NOT as a *connective* (a list of
children) makes a 2nd child silently change the group's meaning. A unary NOT group was the first
fix considered; the chosen fix drops NOT-as-connective entirely.
**Resolution (decided with the user):** **toggle-NOT** — connectives are only `AND`/`OR`; every
node (group and leaf) carries an independent **`¬` flag** that inverts it (Qui's model). No NOT
*group* exists, so the multi-child ambiguity is structurally impossible, and negation costs **0
nesting depth** (a flag, not a wrapper node) — which also eases the depth cap. On export a `¬`-set
node wraps as `{NOT:[node]}` (`¬OR[a,b]` → `{NOT:[{OR:[a,b]}]}` = `~a ∧ ~b`, verified). Import maps
a backend `{NOT:[…]}` list to nodes with `¬` set (`{NOT:[{OR:[a,b]}]}` → an `OR[a,b]` node with
`¬`; multi-child `{NOT:[a,b]}` → `AND[a¬, b¬]`). Leaf "is-not" modifier remains a harmless second
route. Tradeoff accepted: every group shows two controls (connective + `¬`) — a tiny price vs the
unary machinery (auto-wrap on switch, NOT-footer special-casing, extra nesting).

### 3. Missing unwrap/outdent restructuring — **MEDIUM**
Spec listed `wrap in group` but no inverse, and `↑/↓` only reorder within a group.
**Resolution:** add **unwrap/flatten** (dissolve a group, splice its children into the parent
when connectives are compatible) to the per-node controls; define `wrap in group` to default the
new wrapper to the parent's connective. Cross-branch move (leaf → non-sibling group two levels up)
is an accepted limitation of the buttons-only model — done via remove + re-add; documented, not
solved with DnD.

### 4. Depth accounting undefined — **MEDIUM**
"Soft cap 5" never said what counts.
**Resolution:** the cap counts **group-nesting depth**; a relation-descent's child group is **+1
level**. A criterion leaf is depth-0 (terminates). Document the budget (e.g. `games → ANY session
→ OR[2 devices]` = depth 3). Cap stays 5 for readability; the *backend* guard (#9 below) is set
higher and is the real safety bound.

### 5. Leaf field-change behavior undefined — **MEDIUM**
**Resolution:** on field change → reset modifier to the first valid one for the new criterion
type, **clear** the value widget (no silent type-coercion), and mark the leaf incomplete until a
value is entered. Replacing the value widget flushes old DOM (no stale hidden state).

### 6. Live-count / NL-summary staleness — **MEDIUM**
NL summary is live; count is debounced — they diverge mid-edit, and incomplete leaves muddy both.
**Resolution:** incomplete leaves are **excluded** from both the count query and Apply (and
rendered faded with an "incomplete" badge). The count badge shows a **"counting…"** state while
debounced/in-flight, and an explicit **"count unavailable"** on endpoint error (never a bare 0).

### 7. Component reuse reality — **MEDIUM**
- `DateRangeFilter`, bool radio → **clean reuse** (pure DOM-read serialization, no preprocessing).
- `FilterSelect` → **needs rework**: today it serializes via a global `readSearchSelect`
  preprocessing pass (`filter-bar.ts:244`) that writes `data-*` then a flat read. In a recursive
  tree there is no flat form — leaf widgets must **self-serialize** (write their value on change,
  or expose a per-node serialize hook the group calls).
- single field-comparison row → **needs a leaf variant**: the row depends on a `columns` array
  supplied by the `FieldComparisonSet` container and on that container owning the AND/OR mode. As
  a tree leaf it must embed its own `columns` and drop the mode toggle (the enclosing group owns
  the connective now).

### 8. Component 9 (field metadata) is ~40% there — **MEDIUM**
`resolve_path_kind`, `_criterion_class_for`, `comparable_columns` exist; **missing**: a per-model
field-list returning `{name, label, kind, nullable, choices, relations}`. This is exactly the
field-metadata registry the #168 comment flagged. Component 9 must **build** it (cross-ref #161
FilterField + #157 criterion-type metadata); it then also feeds #152.

### 9. Backend has NO recursion/cycle guard — **HIGH (new backend prereq)**
Relation fields cycle (`GameFilter.session_filter ↔ SessionFilter.game_filter`, confirmed) and
`from_json`/`to_q` enforce no depth limit. A hand-edited / shared `?filter=` with a cycle
infinite-loops → server DoS. Independent of the UI but made reachable by it.
**Resolution:** add a parse-time depth/cycle guard in `OperatorFilter.from_json` (raise
`FilterError` past a max depth, e.g. 10). **File as its own backend issue**, prerequisite to
shipping the builder.

### 10. Live-count endpoints don't exist — **LOW**
Only `parse_*_filter` exist; component 8 must add per-model count views
(`parse → to_q().count()`).

## NON-defects (clarified, no change of substance)

- **field_comparisons stored as a single array** (`{field_comparisons:[c1,c2]}`), not multiple
  dicts. The homogeneous tree models each comparison as its own leaf → exports each as a single-key
  `{field_comparisons:[c]}` child (AND-combined, equivalent). Import splits an N-element array into
  N sibling comparison leaves.
- **`match` coexisting with a connective on one sub-filter dict** is by design and unambiguous: a
  relation node's child is exactly **one** canonical group, so its sub-filter dict carries `match`
  + exactly one connective key. The builder never emits multiple operator families on a relation
  sub-filter.
- **Empty sub-filter** (`{session_filter:{match:NONE}}`) is a **feature**: "has zero related rows"
  (NONE) / "has ≥1 related row" (ANY). Documented, not an error.
- **Empty operator lists dropped on export** (`{AND:[]}`→`{}`): round-trip is **logical
  equivalence**, not byte equality. Stated explicitly.

## Net

The design's spine — homogeneous tree + canonical single-connective serializer — is **verified
sound** (the headline "breaks" was disproven empirically). The review's real yield: a corrected
import rule, toggle-NOT, an unwrap control, defined depth/field-change/staleness semantics, an
honest component build-order (metadata + serializer are foundational; FilterSelect & the
comparison row need rework), and one genuinely important new backend prereq — the recursion/cycle
guard. All folded into the updated spec.
