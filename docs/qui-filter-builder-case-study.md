# Qui Filter Builder (Workflow Editor) UI & Backend Design Case Study

This case study analyzes the architecture of the nested filter builder and automation rule-evaluation system in **Qui** (a modern Web UI for autobrr/qBittorrent orchestration). It details how Qui represents, constructs, edits, and evaluates nested logic trees, providing a direct architectural template for implementing a similar feature builder in **Timetracker**.

---

## 1. Architectural Overview & Data Model (The AST)

Qui represents its nested query filters as an **Abstract Syntax Tree (AST)** serialized to and from a JSON column in SQL. Instead of a single top-level filter, Qui associates conditions with **individual actions** (e.g., pause, resume, delete, category, tag) within an automation rule. This allows independent logic trees to govern different actions on the same torrent.

### Backend Data Structure (Go)
*Source: `internal/models/automation.go`*

```go
// RuleCondition represents a node in the nested AST.
type RuleCondition struct {
	Field      ConditionField    `json:"field,omitempty"`
	Operator   ConditionOperator `json:"operator"`
	GroupID    string            `json:"groupId,omitempty"`  // Used for grouping queries (e.g. Group Size)
	Value      string            `json:"value,omitempty"`    // Stored string representation of values
	MinValue   *float64          `json:"minValue,omitempty"` // High-precision min boundary for BETWEEN operator
	MaxValue   *float64          `json:"maxValue,omitempty"` // High-precision max boundary for BETWEEN operator
	Regex      bool              `json:"regex,omitempty"`    // Toggle case-insensitive substring regex matching
	Negate     bool              `json:"negate,omitempty"`   // Toggles "NOT" inversion on this node
	Conditions []*RuleCondition  `json:"conditions,omitempty"` // Child nodes (if this node is an AND/OR group)
	Compiled   *regexp.Regexp    `json:"-"`                  // In-memory compiled regex pointer (ignored in JSON)
}

// IsGroup returns true if this condition acts as a parent container.
func (c *RuleCondition) IsGroup() bool {
	return len(c.Conditions) > 0 && (c.Operator == OperatorAnd || c.Operator == OperatorOr)
}
```

### Core Schema Constants

1. **Condition Fields (`ConditionField`)**: Over 60 fields representing torrent properties:
   - **String fields**: `NAME`, `HASH`, `CATEGORY`, `TAGS`, `SAVE_PATH`, etc.
   - **Numeric fields (bytes)**: `SIZE`, `FREE_SPACE`, `DOWNLOADED`, `UPLOADED`.
   - **Time durations**: `ADDED_ON` (evaluated as seconds since addition), `SEEDING_TIME`, `ETA`.
   - **Boolean states**: `PRIVATE`, `IS_UNREGISTERED`, `HAS_MISSING_FILES`, `EXISTS_ON_OTHER_INSTANCE`.
   - **System environment**: `SYSTEM_HOUR`, `SYSTEM_DAY_OF_WEEK`.
2. **Logical & Comparison Operators (`ConditionOperator`)**:
   - **Logical Groups**: `AND`, `OR`.
   - **Text comparisons**: `EQUAL`, `NOT_EQUAL`, `CONTAINS`, `NOT_CONTAINS`, `STARTS_WITH`, `ENDS_WITH`, `MATCHES` (regex).
   - **Numeric/Date comparisons**: `=`, `!=`, `>`, `>=`, `<`, `<=`, `BETWEEN`.
   - **Cross-entity lookups**: `EXISTS_IN`, `CONTAINS_IN` (checks for matches inside a separate category).

---

## 2. Backend Evaluation Engine (Go)

Evaluating complex nested logic on large lists (10,000+ torrents) can easily become a CPU and database bottleneck. Qui solves this with a **pre-computed indexing pattern** and a **recursive evaluator**.

### Pre-computed Context (`EvalContext`)
*Source: `internal/services/automations/evaluator.go`*

Before evaluating an automation rule, Qui constructs a lightweight, thread-safe `EvalContext`. Instead of issuing SQL queries or making network calls inside the loop, the engine builds O(1) in-memory indexes upfront:

```go
type EvalContext struct {
	UnregisteredSet         map[string]struct{}                  // Fast hash lookup for dead torrents
	HardlinkScopeByHash     map[string]string                    // Cached filesystem state (none, torrents_only, etc.)
	CategoryIndex           map[string]map[string]map[string]struct{} // Category -> Lowercased Name -> Set of hashes (EXISTS_IN)
	CategoryNames           map[string][]categoryEntry           // Category -> Pre-normalized names (CONTAINS_IN)
	NowUnix                 int64                                // Frozen timestamp for consistent duration checks
	// ... Other cached sets for cross-instance and cross-seed indicators
}
```

### Recursive Evaluation
*Source: `internal/services/automations/evaluator.go`*

Evaluation walks the AST recursively. Regular expressions are compiled lazily and cached on the condition struct thread-safely.

```go
func EvaluateConditionWithContext(cond *RuleCondition, torrent qbt.Torrent, ctx *EvalContext, depth int) bool {
	if cond == nil || depth > maxConditionDepth { // Safety recursion guard (max depth = 20)
		return false
	}

	// 1. Compile Regex Lazily if needed (cached on the pointer)
	if cond.Regex || cond.Operator == OperatorMatches {
		_ = cond.CompileRegex()
	}

	var result bool

	// 2. Handle Logical Groups (AND/OR)
	if cond.IsGroup() {
		switch cond.Operator {
		case OperatorOr:
			for _, child := range cond.Conditions {
				if EvaluateConditionWithContext(child, torrent, ctx, depth+1) {
					result = true
					break
				}
			}
		case OperatorAnd:
			result = true
			for _, child := range cond.Conditions {
				if !EvaluateConditionWithContext(child, torrent, ctx, depth+1) {
					result = false
					break
				}
			}
		}
	} else {
		// 3. Leaf Condition: Evaluate concrete field using type-specific comparators
		result = evaluateLeaf(cond, torrent, ctx)
	}

	// 4. Invert result if Negate ("NOT") is toggled
	if cond.Negate {
		result = !result
	}

	return result
}
```

### Key Comparison Patterns
- **Time/Age Fields**: Timestamps (like `AddedOn`) are converted to ages: `ageSeconds = max(nowUnix - timestamp, 0)` and evaluated as integers.
- **Between Operators**: Uses explicit `minValue` and `maxValue` comparisons: `value >= *cond.MinValue && value <= *cond.MaxValue` instead of parsing strings.
- **Sub-Category Search (`EXISTS_IN`)**: Performs an O(1) key check on the pre-computed `CategoryIndex` to see if a torrent with the exact same name resides in a different category.

---

## 3. Frontend Architecture (React / TypeScript)

The UI is built with a highly flexible tree-builder powered by `@dnd-kit/core` and `@dnd-kit/sortable` for fluid drag-and-drop node manipulation.

### Tree Components Hierarchy
1. `QueryBuilder` (Root Orchestrator):
   - Configures the pointer and keyboard sensor inputs.
   - Instantiates the root `ConditionGroup`.
   - Manages client-side IDs (`clientId`), ensuring every node has a stable unique identifier during editing.
2. `ConditionGroup` (Group Node):
   - Renders its logical operator (`AND` or `OR`) as a colored button.
   - Recursively maps child conditions, interleaving a `<DropZone />` component between each child slot.
   - Provides options to "Add Condition" or "Add Group" (limited to a depth of 5).
3. `LeafCondition` (Terminal Filter Leaf):
   - Renders field comboboxes, operator selectors, and type-specific value input controls.
   - Hosts toggles for Negation (`NOT` toggle) and Regex.

---

## 4. Smart Frontend UX Patterns

### A. Non-Flicker Unit Handling (Separate Local State)
Raw values on the backend are always stored in standard base units (seconds for durations, bytes for sizes, bytes/sec for speeds). Showing large integers is bad UX, but converting directly from values causes severe cursor and state flickering on input. 

**Solution:** `LeafCondition` tracks preferred input units in local component state (`durationUnit`, `bytesUnit`, `speedUnit`) separately from the serialized `condition.value`.

```typescript
// Initialized by detecting magnitude of existing value, defaults to MiB or Minutes
const [bytesUnit, setBytesUnit] = useState<number>(() =>
  detectBytesUnit(parseFloat(condition.value ?? "0") || 0)
);

const handleBytesChange = (inputValue: string, unit: number) => {
  setBytesUnit(unit); // Local preference stored
  if (inputValue === "") {
    onChange({ ...condition, value: "" });
  } else {
    const numValue = parseFloat(inputValue) || 0;
    const bytes = Math.round(numValue * unit); // Convert back to base unit for storage
    onChange({ ...condition, value: String(bytes) });
  }
};
```

### B. Double-Input Range Rendering (`BETWEEN` Operator)
Instead of overloading a single text string (like `"100-500"`), the front-end dynamically renders **two** inline text inputs alongside the unit selector if the operator is toggled to `BETWEEN`. It binds directly to the backend's structured `minValue` and `maxValue` float properties:

```tsx
{condition.operator === "BETWEEN" ? (
  <div className="flex items-center gap-1">
    <Input
      type="number"
      value={betweenBytesDisplay.minValue}
      onChange={(e) => handleBetweenBytesChange(e.target.value, betweenBytesDisplay.maxValue, betweenBytesDisplay.unit)}
      placeholder="Min"
    />
    <span className="text-muted-foreground">-</span>
    <Input
      type="number"
      value={betweenBytesDisplay.maxValue}
      onChange={(e) => handleBetweenBytesChange(betweenBytesDisplay.minValue, e.target.value, betweenBytesDisplay.unit)}
      placeholder="Max"
    />
  </div>
) : (
  <Input value={condition.value} ... />
)}
```

### C. Drag-and-Drop Tree Traversal Algorithms
Because trees can be highly nested, moving elements requires precise paths. Qui's `QueryBuilder.tsx` provides generic recursive helper utilities to traverse, modify, and clean the AST client-side:

- **`ensureClientIdsDeep(node)`**: Recursively walks an imported/saved condition tree to guarantee that a unique `clientId` exists on all nodes before rendering.
- **`findPathByClientId(root, targetId)`**: Resolves a unique client ID into an index-based numerical path, e.g., `[0, 2, 1]` (first child, third child, second grandchild), simplifying coordinate math.
- **`moveNodeToPathIndex(root, sourcePath, targetParentPath, targetIndex)`**: Clones the tree, detaches the source node, adjusts target coordinates dynamically to account for the detachment, and splices the node back into its new position.
- **`pruneEmptyGroups(root)`**: Recursively walks the tree, removing any subgroups that have had all of their conditions deleted, keeping the JSON payloads lean.

---

## 5. Architectural Recommendations for Timetracker

To adapt this high-signal design from Qui into Timetracker for issue **#171**:

### Backend Design (Python/Django)
1. **Model Representation**: Use a JSON field (`models.JSONField`) on the target database table to store the condition tree.
2. **Structured Leaves**: Adopt Qui's layout of explicit, optional boundaries (`minValue`, `maxValue` as Floats) for range filters. Avoid overloading the `value` string field.
3. **Lazy Compilation**: If compiling string logic, cache regex/compiled logic as non-serialized private variables on your evaluation model to keep sequential scans fast.
4. **Execution Indexing**: When running filters on a collection of timetracking sessions/entities, construct a `CriteriaContext` dictionary of precomputed sets (e.g., active task tags, project boundaries) before entering the loop to ensure O(1) lookups.

### Frontend Design (Vanilla CSS / Custom Elements)
1. **Dynamic Inputs**: Build dynamic input components. Selecting a field should change the comparison inputs:
   - *Time tracking fields* (e.g. Duration): Render double-inputs for ranges, paired with unit dropdowns (Minutes, Hours).
   - *Category/Project fields*: Fetch available options and render searchable dropdowns.
   - *Date ranges*: Provide a range calendar picker.
2. **Deep Nesting Visuals**: Port Qui's alternate coloring formula:
   ```css
   /* Alternating backgrounds based on nesting depth helps users read complex logic */
   .group-depth-even { background: rgba(var(--color-primary), 0.05); }
   .group-depth-odd { background: rgba(var(--color-secondary), 0.05); }
   ```
3. **Logical Simplification**: Force root nodes to have a default `AND` group; restrict maximum recursive nesting depth to 3 or 5 layers to keep UI layout manageable.
