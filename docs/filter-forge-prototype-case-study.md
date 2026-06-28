# Filter Forge Prototype: UI/UX & Schema Case Study

This case study analyzes **Filter Forge**, a conceptual UI prototype for a filter builder. Unlike the production-ready code found in the Qui repository, this prototype is a single-file React "Design Component" built for rapid iteration. Consequently, its code-quality is lower (using inline styles and simplified native HTML5 drag-and-drop rather than robust libraries). However, it explores several highly relevant conceptual and UX paradigms that align perfectly with the relational complexity of **Timetracker's** data model.

---

## 1. Schema-Driven Relational Filtering (The AST)

The most significant learning from the prototype is how it natively incorporates SQL/Django-style cross-entity relationships directly into the AST, rather than flattening them.

### Relational AST Nodes
Instead of only having `Group` (AND/OR) and `Condition` (leaf) nodes, the prototype introduces a third structural node: the `Relation`.

```javascript
// A "Relation" node acts as a bridge from the current Model to a target Model.
{
  id: 'n1_a2b3',
  kind: 'relation',
  relation: 'sessions', // e.g., Game -> Sessions
  quantifier: 'ANY',    // 'ANY', 'ALL', 'NONE', 'COUNT'
  count: { op: 'gte', n: 3 }, // Only used if quantifier === 'COUNT'
  child: { ... }        // A nested Group/Condition evaluated in the *target* model's context
}
```

**Why this matters for Timetracker:** 
Timetracker's data is highly normalized (`Game` -> `Session` -> `Device`, or `Game` -> `Purchase`). Users frequently need cross-entity filters (e.g., "Games that have at least 3 sessions where the device was 'Handheld'").
- The prototype's `quantifier` logic translates directly to Django's ORM:
  - `ANY` -> `filter(sessions__device__type='Handheld')`
  - `NONE` -> `exclude(sessions__device__type='Handheld')`
  - `COUNT` -> `annotate(c=Count('sessions', filter=Q(device__type='Handheld'))).filter(c__gte=3)`

### First-Class "NOT" Groups
While Qui toggled a `Negate` boolean on individual leaf conditions, Filter Forge places `NOT` directly as a Group connective (`AND`, `OR`, `NOT`). This allows users to wrap entire trees of logic in an exclusion block, matching Django's `~Q(...)` behavior cleanly.

---

## 2. Advanced UX Patterns

The prototype compensates for the cognitive load of nested queries by utilizing several feedback mechanisms:

### A. Context-Switching Visuals ("↳ INTO")
When navigating across a relation (e.g., filtering `Games` based on their `Sessions`), the UI wraps the sub-conditions in a distinct visual block header:
`↳ INTO [ ANY ] of the [ Sessions ] [ Session ] where`
This makes it explicit to the user that the fields available inside this block belong to the target model (`Session`), preventing confusion between a Game's `playtime` and a Session's `duration`.

### B. Natural Language Translation
Nested trees are hard to read at a glance. The prototype recursively walks the AST on every keystroke to generate a plain-English translation of the entire filter tree.
*Example output:* `"Games where status is Finished and (playtime ≥ 20h or any sessions where duration ≥ 2h) and not (any purchases where ownership is Trial)."`
For Timetracker, providing a read-only natural language summary at the top of the filter builder acts as an immediate sanity-check for the user.

### C. Live Selectivity & Count Estimation
The prototype maintains a mock "selectivity" algorithm to estimate how many records the current filter will return. 
While the math in the prototype is fake (hash-based determinism), the UX pattern is powerful: next to every `AND/OR` group, it displays a badge like `≈ 1,432 games`. 
**Implementation in Timetracker:** In a real Django application, firing a live `COUNT(*)` query on every keystroke is too expensive. However, this could be achieved by debouncing the input or running an asynchronous `EXPLAIN` / lightweight count query to provide live feedback on filter strictness without a full page reload.

---

## 3. Structural Learnings vs. Qui

Comparing this prototype against the production-grade Qui case study highlights different priorities:

| Feature | Qui (Production) | Filter Forge (Prototype) | Timetracker Applicability |
| :--- | :--- | :--- | :--- |
| **Cross-Entity** | Handled implicitly via custom field names (e.g., `TRACKER_STATUS`). | Explicit `Relation` nodes with quantifiers context-switching to new tables. | **Filter Forge.** Timetracker relies heavily on `Game` <-> `Session` cross-filtering. |
| **Drag & Drop** | `@dnd-kit/core` with precise tree-path math. | HTML5 `draggable` with naive parent-swapping. | **Qui.** Native HTML5 DND is notoriously fragile for deeply nested trees. |
| **Negation** | Per-leaf `Negate` boolean toggle. | `NOT` acts as a first-class group connective. | **Filter Forge.** Group-level `~Q` negation is more powerful in Django. |
| **Range Inputs** | Dedicated `minValue` and `maxValue` DB columns. | Inline arrays (`[0, 10]`) mapped to two inputs. | **Qui.** Explicit DB columns are safer than arrays in JSON serialization. |

### Conclusion for Timetracker (Issue #171)
The ideal filter builder for Timetracker should combine the **robust technical foundation of Qui** (explicit schemas, proper DND libraries, discrete boundary states) with the **relational schemas and UX patterns of Filter Forge** (Natural Language readouts, explicit cross-entity `Relation` nodes with aggregations, and potentially live-count debouncing).
