# Unify Form Checkboxes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify all Django form checkboxes across the codebase by routing them through our new Python `Checkbox` primitive.
**Architecture:** 
1. Modify `Checkbox` and `Radio` primitives in `common/components/primitives.py` to support headless (label-less) rendering when `label` is `None`, so they can be injected into Django's native `form.as_div()` rendering without duplicating labels.
2. Create a `PrimitiveCheckboxWidget` in `games/forms.py` that extends `forms.CheckboxInput` but renders using our `Checkbox` Python component.
3. Create a `PrimitiveWidgetsMixin` in `games/forms.py` that automatically applies the `PrimitiveCheckboxWidget` to all `forms.BooleanField` instances in a form. Add this mixin to all ModelForms.

**Tech Stack:** Python, Django Forms, HTML.

---

### Task 1: Update Primitives for Headless Rendering

**Files:**
- Modify: `common/components/primitives.py`
- Modify: `tests/test_components.py`

- [ ] **Step 1: Write a failing test for headless rendering**
In `tests/test_components.py`, add a test to `ComponentPrimitivesTest`:
```python
    def test_checkbox_headless(self):
        html = Checkbox(name="test-headless", label=None, checked=True)
        self.assertNotIn('<label', html)
        self.assertIn('<input', html)
        self.assertIn('type="checkbox"', html)
        self.assertIn('name="test-headless"', html)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_components.py -k test_checkbox_headless`
Expected: Fail because `Checkbox` currently requires `label` as a `str` and always renders a `Label` wrapper.

- [ ] **Step 3: Update `Checkbox` and `Radio` in `common/components/primitives.py`**
Update the function signatures to accept `label: str | None = None` and selectively return only the `Input` if `label` is missing.
```python
def Checkbox(
    name: str,
    label: str | None = None,
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
    
    input_el = Input(type="checkbox", attributes=input_attrs)
    if label is None:
        return input_el
        
    return Label(
        attributes=[("class", "flex items-center gap-2 text-sm text-heading cursor-pointer")],
        children=[input_el, label],
    )

def Radio(
    name: str,
    label: str | None = None,
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
        
    input_el = Input(type="radio", attributes=input_attrs)
    if label is None:
        return input_el

    return Label(
        attributes=[("class", "flex items-center gap-1.5 text-sm text-heading cursor-pointer")],
        children=[input_el, label],
    )
```

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_components.py -k ComponentPrimitivesTest`
Expected: PASS

- [ ] **Step 5: Commit**
Run:
```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "refactor: allow Checkbox and Radio primitives to render headlessly without labels"
```

---

### Task 2: Create Django Widget Adapter and Mixin

**Files:**
- Modify: `games/forms.py`

- [ ] **Step 1: Write the Widget and Mixin implementations**
At the top of `games/forms.py`, import `Checkbox` and implement `PrimitiveCheckboxWidget` and `PrimitiveWidgetsMixin`.
```python
from common.components.primitives import Checkbox

class PrimitiveCheckboxWidget(forms.CheckboxInput):
    """Adapts Django's CheckboxInput to use our Checkbox component."""
    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        checked = self.check_test(value)
        attributes = [(k, str(v)) for k, v in final_attrs.items() if k not in ("type", "name", "value", "checked")]
        
        # Django uses boolean values differently for checkboxes, we omit value if empty
        return str(Checkbox(
            name=name,
            label=None,
            checked=checked,
            value=str(value) if value else "1",
            attributes=attributes
        ))

class PrimitiveWidgetsMixin:
    """Automatically applies primitive custom widgets to native Django form fields."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                field.widget = PrimitiveCheckboxWidget()
                # Maintain the field's explicit required status (usually False for booleans)
```

- [ ] **Step 2: Apply the Mixin to all Forms**
In `games/forms.py`, update all the ModelForm classes to inherit from `PrimitiveWidgetsMixin` as the **first** base class (before `forms.ModelForm`).
Example:
```python
class SessionForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class PurchaseForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class GameForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class PlatformForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class DeviceForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class PlayEventForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...

class GameStatusChangeForm(PrimitiveWidgetsMixin, forms.ModelForm):
    # ...
```

- [ ] **Step 3: Test Django Form Rendering**
Run the full test suite to ensure forms still validate properly and render without error.
Run: `pytest`
Expected: PASS

- [ ] **Step 4: Commit**
Run:
```bash
git add games/forms.py
git commit -m "feat: replace all form BooleanFields with PrimitiveCheckboxWidget via mixin"
```