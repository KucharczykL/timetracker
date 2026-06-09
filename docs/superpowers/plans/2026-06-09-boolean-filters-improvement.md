# Boolean Filters Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the boolean criterion filters from a single checkbox (representing True/Not set) to a 2-radio-button UI representing True, False, and Unset states across all filter bars.

**Architecture:** 
1. Generalize `_filter_checkbox` into a filter-agnostic `Checkbox` component and introduce a `Radio` component in `common/components/primitives.py`.
2. Implement a nullable boolean filter JSON parsing helper `_parse_bool_nullable` and a component helper `_filter_boolean_radio` in `common/components/filters.py`.
3. Update `GameFilterBar`, `SessionFilterBar`, and `PurchaseFilterBar` in `common/components/filters.py` to leverage these new helpers.
4. Enhance `games/static/js/filter_bar.js` with deselectable radio toggling behavior and updated checked-radio state serialization.

**Tech Stack:** Python, Django, vanilla JavaScript, HTML.

---

### Task 1: Generalize Checkbox and Introduce Radio in Primitives

**Files:**
- Modify: `common/components/primitives.py`

- [ ] **Step 1: Write the failing test for the new Checkbox and Radio primitives**

Create a new test class `ComponentPrimitivesTest` in `tests/test_components.py` (or verify where to append) to check the output of `Checkbox` and `Radio`.
Add the following code to `tests/test_components.py`:

```python
from common.components.primitives import Checkbox, Radio

class ComponentPrimitivesTest(SimpleTestCase):
    def test_checkbox_primitive(self):
        html = Checkbox(name="test-check", label="Accept Terms", checked=True, value="yes")
        self.assertIn('type="checkbox"', html)
        self.assertIn('name="test-check"', html)
        self.assertIn('value="yes"', html)
        self.assertIn('checked="true"', html)
        self.assertIn("Accept Terms", html)

    def test_radio_primitive(self):
        html = Radio(name="test-radio", label="Option A", checked=False, value="A")
        self.assertIn('type="radio"', html)
        self.assertIn('name="test-radio"', html)
        self.assertIn('value="A"', html)
        self.assertNotIn('checked="true"', html)
        self.assertIn("Option A", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_components.py -k ComponentPrimitivesTest`
Expected output: Failures/errors due to `Checkbox` and `Radio` not being defined/imported.

- [ ] **Step 3: Implement Checkbox and Radio in `common/components/primitives.py`**

Open `common/components/primitives.py` and find the other basic primitives (e.g. `Input`, `Label`). Add the following implementations and ensure they are exported / added to imports/exports:

```python
def Checkbox(
    name: str,
    label: str,
    checked: bool = False,
    value: str = "1",
    attributes: list[HTMLAttribute] | None = None,
) -> SafeText:
    """A filter-agnostic Checkbox component."""
    attributes = attributes or []
    input_attrs = [
        ("name", name),
        ("value", value),
        ("class", "rounded border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand"),
    ] + attributes
    if checked:
        input_attrs.append(("checked", "true"))
    
    return Label(
        attributes=[("class", "flex items-center gap-2 text-sm text-heading cursor-pointer")],
        children=[
            Input(type="checkbox", attributes=input_attrs),
            label,
        ],
    )


def Radio(
    name: str,
    label: str,
    checked: bool = False,
    value: str = "",
    attributes: list[HTMLAttribute] | None = None,
) -> SafeText:
    """A filter-agnostic Radio component."""
    attributes = attributes or []
    input_attrs = [
        ("name", name),
        ("value", value),
        ("class", "rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand"),
    ] + attributes
    if checked:
        input_attrs.append(("checked", "true"))
        
    return Label(
        attributes=[("class", "flex items-center gap-1.5 text-sm text-heading cursor-pointer")],
        children=[
            Input(type="radio", attributes=input_attrs),
            label,
        ],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_components.py -k ComponentPrimitivesTest`
Expected output: `2 passed`

- [ ] **Step 5: Commit**

Run:
```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "refactor: generalize Checkbox and add Radio primitive component"
```

---

### Task 2: Implement Filter Parsers & Helpers in filters.py

**Files:**
- Modify: `common/components/filters.py`
- Modify: `tests/test_filter_helpers.py`

- [ ] **Step 1: Write failing unit tests for `_parse_bool_nullable` in `tests/test_filter_helpers.py`**

Add a new test class `ParseBoolNullableTest` to `tests/test_filter_helpers.py`:

```python
from common.components.filters import _parse_bool_nullable

class ParseBoolNullableTest(SimpleTestCase):
    def test_missing_key(self):
        self.assertIsNone(_parse_bool_nullable({}, "field"))

    def test_null_value(self):
        self.assertIsNone(_parse_bool_nullable({"field": None}, "field"))
        self.assertIsNone(_parse_bool_nullable({"field": {}}, "field"))

    def test_boolean_values(self):
        self.assertTrue(_parse_bool_nullable({"field": {"value": True}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": False}}, "field"))

    def test_string_values(self):
        self.assertTrue(_parse_bool_nullable({"field": {"value": "true"}}, "field"))
        self.assertTrue(_parse_bool_nullable({"field": {"value": "1"}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": "false"}}, "field"))
        self.assertFalse(_parse_bool_nullable({"field": {"value": "0"}}, "field"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_filter_helpers.py -k ParseBoolNullableTest`
Expected output: Failures/errors due to `_parse_bool_nullable` not found.

- [ ] **Step 3: Implement `_parse_bool_nullable` and `_filter_boolean_radio` in `common/components/filters.py`**

1. Import `Checkbox` and `Radio` from `common.components.primitives` at the top of `common/components/filters.py`.
2. Define `_FILTER_RADIO_CLASS` and add `_parse_bool_nullable`.
3. Create `_filter_boolean_radio`.
4. Refactor `_filter_checkbox` to use `Checkbox` instead of raw `Label` and `Input`.

Code to implement:
```python
_FILTER_RADIO_CLASS = (
    "rounded-full border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)

def _parse_bool_nullable(existing: dict, key: str) -> bool | None:
    """Extract a nullable boolean value from a filter criterion."""
    if key not in existing:
        return None
    field = existing[key]
    if not isinstance(field, dict):
        return None
    val = field.get("value")
    if val is None:
        return None
    if isinstance(val, str):
        if val.lower() in ("true", "1", "yes"):
            return True
        if val.lower() in ("false", "0", "no"):
            return False
    return bool(val)


def _filter_checkbox(name: str, label: str, checked: bool) -> SafeText:
    """Thin adapter mapping legacy checkbox filters to the generalized Checkbox primitive."""
    return Checkbox(name=name, label=label, checked=checked)


def _filter_boolean_radio(name: str, label: str, value: bool | None) -> SafeText:
    """Renders a filter-specific boolean radio button group with 'True' and 'False' options."""
    return Div(
        attributes=[("class", "flex flex-col gap-1")],
        children=[
            Span(
                attributes=[("class", _FILTER_LABEL_CLASS)],
                children=[label],
            ),
            Div(
                attributes=[("class", "flex items-center gap-4 h-9")],
                children=[
                    Radio(name=name, label="True", checked=value is True, value="true"),
                    Radio(name=name, label="False", checked=value is False, value="false"),
                ],
            ),
        ],
    )
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `pytest tests/test_filter_helpers.py`
Expected output: All helper tests passed (including `ParseBoolNullableTest`).

- [ ] **Step 5: Commit**

Run:
```bash
git add common/components/filters.py tests/test_filter_helpers.py
git commit -m "feat: implement _parse_bool_nullable and _filter_boolean_radio helper"
```

---

### Task 3: Replace Single Checkboxes with Radio Groups in Filter Bars

**Files:**
- Modify: `common/components/filters.py`

- [ ] **Step 1: Update GameFilterBar**

In `common/components/filters.py` inside `GameFilterBar`:
1. Parse using `_parse_bool_nullable` instead of `_parse_bool` for:
   - `mastered_value`
   - `purchase_refunded_value`
   - `purchase_infinite_value`
   - `session_emulated_value`
2. Update the fields list to replace `_filter_checkbox` with `_filter_boolean_radio`, changing the wrapper div to have `gap-6` for better horizontal radio button spacing.

Code snippet modification:
```python
    # Parsing:
    mastered_value = _parse_bool_nullable(existing, "mastered")
    # ...
    purchase_refunded_value = _parse_bool_nullable(existing, "purchase_refunded")
    purchase_infinite_value = _parse_bool_nullable(existing, "purchase_infinite")
    session_emulated_value = _parse_bool_nullable(existing, "session_emulated")

    # Rendering (in fields):
        Div(
            attributes=[("class", "flex items-end gap-6 mb-4 flex-wrap")],
            children=[
                _filter_boolean_radio("filter-mastered", "Mastered", mastered_value),
                _filter_boolean_radio(
                    "filter-purchase-refunded", "Refunded", purchase_refunded_value
                ),
                _filter_boolean_radio(
                    "filter-purchase-infinite", "Infinite", purchase_infinite_value
                ),
                _filter_boolean_radio(
                    "filter-session-emulated", "Emulated", session_emulated_value
                ),
            ],
        ),
```

- [ ] **Step 2: Update SessionFilterBar**

In `common/components/filters.py` inside `SessionFilterBar`:
1. Parse using `_parse_bool_nullable` for:
   - `emulated_value`
   - `is_active_value`
2. Update the fields to replace `_filter_checkbox` with `_filter_boolean_radio`.

Code snippet modification:
```python
    # Parsing:
    emulated_value = _parse_bool_nullable(existing, "emulated")
    is_active_value = _parse_bool_nullable(existing, "is_active")

    # Rendering (in fields):
        Div(
            attributes=[("class", "flex gap-6 mb-4")],
            children=[
                _filter_boolean_radio("filter-emulated", "Emulated", emulated_value),
                _filter_boolean_radio("filter-active", "Active", is_active_value),
            ],
        ),
```

- [ ] **Step 3: Update PurchaseFilterBar**

In `common/components/filters.py` inside `PurchaseFilterBar`:
1. Parse using `_parse_bool_nullable` for:
   - `is_refunded_value`
   - `infinite_value`
   - `needs_price_update_value`
2. Update the fields to replace `_filter_checkbox` with `_filter_boolean_radio`.

Code snippet modification:
```python
    # Parsing:
    is_refunded_value = _parse_bool_nullable(existing, "is_refunded")
    infinite_value = _parse_bool_nullable(existing, "infinite")
    needs_price_update_value = _parse_bool_nullable(existing, "needs_price_update")

    # Rendering (in fields):
                Div(
                    attributes=[("class", "flex flex-col items-start gap-4 mb-4")],
                    children=[
                        _filter_boolean_radio(
                            "filter-refunded", "Refunded", is_refunded_value
                        ),
                        _filter_boolean_radio("filter-infinite", "Infinite", infinite_value),
                        _filter_boolean_radio(
                            "filter-needs-price-update",
                            "Needs Price Update",
                            needs_price_update_value,
                        ),
                    ],
                ),
```

- [ ] **Step 4: Run component tests to verify output**

Run: `pytest tests/test_filter_bars.py`
Expected output: Since we only changed the internal input type from checkbox to radio but kept the `name="..."` attribute intact, the tests asserting name occurrences should still pass!

- [ ] **Step 5: Commit**

Run:
```bash
git add common/components/filters.py
git commit -m "feat: replace single boolean checkboxes with radio groups in all FilterBars"
```

---

### Task 4: Frontend Behavior and Serialization in JS

**Files:**
- Modify: `games/static/js/filter_bar.js`

- [ ] **Step 1: Update Radio Serialization in `buildFilterJSON`**

In `games/static/js/filter_bar.js`, locate the `// 2. Boolean Fields (Checkboxes)` section.
Update the loop to check for `:checked` radio options:

```javascript
    // 2. Boolean Fields (Radio Button Groups)
    var booleanFields = [
      { name: "filter-mastered", key: "mastered" },
      { name: "filter-emulated", key: "emulated" },
      { name: "filter-active", key: "is_active" },
      { name: "filter-refunded", key: "is_refunded" },
      { name: "filter-infinite", key: "infinite" },
      { name: "filter-needs-price-update", key: "needs_price_update" },
      { name: "filter-purchase-refunded", key: "purchase_refunded" },
      { name: "filter-purchase-infinite", key: "purchase_infinite" },
      { name: "filter-session-emulated", key: "session_emulated" }
    ];
    booleanFields.forEach(function (bf) {
      var el = form.querySelector('[name="' + bf.name + '"]:checked');
      if (el) {
        var val = el.value === "true";
        filter[bf.key] = criterion(val, null, "EQUALS");
      }
    });
```

- [ ] **Step 2: Add click-to-deselect functionality for radios**

In `games/static/js/filter_bar.js`, add `setupDeselectableRadios` and call it inside `DOMContentLoaded`:

```javascript
  /**
   * Enable deselect-on-click behavior for filter radio buttons.
   */
  function setupDeselectableRadios() {
    document.querySelectorAll('input[type="radio"]').forEach(function (radio) {
      radio.addEventListener('click', function (e) {
        if (this.wasChecked) {
          this.checked = false;
          this.wasChecked = false;
          this.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
          var name = this.getAttribute('name');
          if (name) {
            document.querySelectorAll('input[type="radio"][name="' + name + '"]').forEach(function (r) {
              r.wasChecked = false;
            });
          }
          this.wasChecked = true;
        }
      });
      if (radio.checked) {
        radio.wasChecked = true;
      }
    });
  }
```

Locate the `document.addEventListener("DOMContentLoaded", ...)` callback at the bottom of the file and update it:
```javascript
  document.addEventListener("DOMContentLoaded", function () {
    injectSearchInputs();
    setupDeselectableRadios();
    loadPresets();
  });
```

- [ ] **Step 3: Run existing frontend / component tests to verify no syntax errors or simple breaks**

Run: `pytest tests/test_filter_bars.py`
Expected output: PASS

- [ ] **Step 4: Commit**

Run:
```bash
git add games/static/js/filter_bar.js
git commit -m "feat: add click-to-deselect behavior and update checked-radio serialization in JS"
```

---

### Task 5: Add Comprehensive Test Coverage & Verification

**Files:**
- Modify: `tests/test_filter_bars.py`

- [ ] **Step 1: Write explicit tests for boolean radio elements in filter bars**

Add a test case checking that the filter bars output `type="radio"` and contain `value="true"` and `value="false"` for boolean fields:

In `tests/test_filter_bars.py`, add the following test method:

```python
    def test_boolean_fields_render_as_radio_groups(self):
        """Boolean fields must render as radio groups with True/False choices."""
        from common.components import FilterBar, SessionFilterBar, PurchaseFilterBar

        # 1. Games Filter Bar
        games_html = str(FilterBar(filter_json=""))
        self.assertIn('type="radio"', games_html)
        self.assertIn('name="filter-mastered"', games_html)
        self.assertIn('value="true"', games_html)
        self.assertIn('value="false"', games_html)

        # 2. Session Filter Bar
        session_html = str(SessionFilterBar(filter_json=""))
        self.assertIn('type="radio"', session_html)
        self.assertIn('name="filter-emulated"', session_html)
        self.assertIn('value="true"', session_html)
        self.assertIn('value="false"', session_html)

        # 3. Purchase Filter Bar
        purchase_html = str(PurchaseFilterBar(filter_json=""))
        self.assertIn('type="radio"', purchase_html)
        self.assertIn('name="filter-refunded"', purchase_html)
        self.assertIn('value="true"', purchase_html)
        self.assertIn('value="false"', purchase_html)
```

- [ ] **Step 2: Run pytest to verify all tests (including new ones) pass**

Run: `pytest`
Expected output: `356 passed` (including the new test case).

- [ ] **Step 3: Commit final tests**

Run:
```bash
git add tests/test_filter_bars.py
git commit -m "test: add explicit radio group and True/False choice checks for boolean fields"
```
