# Design Spec: Boolean Filters Overhaul (Approach A with Reusable Primitives)

Expose a two-radio-button UI for all boolean filters to allow selecting "True" (Yes), "False" (No), or leaving the filter "Unset" (Not set).

## 1. Architectural Changes

### 1.1 Backend Primitives & Components

We will extract the `_filter_checkbox` rendering logic from `common/components/filters.py` and generalize it into a reusable, filter-agnostic `Checkbox` component in `common/components/primitives.py`. We will also add a corresponding `Radio` component.

#### In `common/components/primitives.py`:
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

#### In `common/components/filters.py`:
We will import `Checkbox` and `Radio` from `common.components.primitives`. We will redefine `_filter_checkbox` as a thin adapter pointing to our new generalized `Checkbox` component (preserving any backward compatibility), and we will create a new helper `_filter_boolean_radio` using `Radio`:

```python
_FILTER_RADIO_CLASS = (
    "rounded-full border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)

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

### 1.2 Parsing Filter JSON (Backend)

We will introduce a robust parsing function in `common/components/filters.py` to distinguish `True`, `False`, and `None` (unset):

```python
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
```

### 1.3 UI Overhauls in Filter Bars

We will update the following filter bars to use `_parse_bool_nullable` and `_filter_boolean_radio`:
1. **GameFilterBar:** `mastered`, `purchase_refunded`, `purchase_infinite`, `session_emulated`.
2. **SessionFilterBar:** `emulated`, `is_active`.
3. **PurchaseFilterBar:** `is_refunded`, `infinite`, `needs_price_update`.

---

## 2. Frontend JS Changes (`games/static/js/filter_bar.js`)

### 2.1 Deselectable Radios Behavior
To support resetting filters back to "Unset" without resetting the whole form, we add click behavior that unchecks an already checked radio button when clicked.

```javascript
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

We will call `setupDeselectableRadios()` during `DOMContentLoaded`.

### 2.2 Serializing Radio States
Update `buildFilterJSON(form)` to collect checked radios from boolean field groups:

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

---

## 3. Testing Strategy

1. **Unit Tests (`tests/test_filter_helpers.py`):**
   - Add test coverage for `_parse_bool_nullable` covering `None`, `True`, `False`, strings, missing keys, etc.
2. **Component Tests (`tests/test_filter_bars.py`):**
   - Update tests where the filters render checkbox elements to assert that radio groups are rendered instead (with "True" and "False" radio buttons).
3. **Integration and End-to-End Tests:**
   - Execute the test suite using `pytest` to ensure that all 355 tests continue to pass and reflect the updated UI structure perfectly.
