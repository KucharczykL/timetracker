# Settings Form Registry Derivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a ninth user-scoped setting cost exactly one registry entry, by deriving both settings forms and both state builders from `SETTINGS_REGISTRY` instead of hand-declaring them twice.

**Architecture:** `timetracker/settings_registry.py` gains the data a control needs (`SettingWidget` enum, `choices`, `model_queryset`, `reload_after_save`, `user_help_text`) plus `__post_init__` invariants, staying free of `django.forms`. A new `games/settings_forms.py` builds fields from the user-scoped definitions and assembles each page's form, states, and presentations in one resolve pass. `games/views/settings.py` shrinks to HTTP handlers.

**Tech Stack:** Django 6, Python 3.14, pytest / pytest-django, mypy, ruff.

Design source: `docs/superpowers/specs/2026-07-26-issue-495-settings-form-registry-derivation-design.md`. One naming change from the spec: the state builder is `settings_page_data()`, not `form_and_states()` — it returns a three-field `SettingsPageData`, so the old name undersold it.

## Global Constraints

- **Every command goes through `make`.** Never `direnv exec .`, never bare `uv run` / `pytest` / `pnpm`. Focused runs use `make test ARGS="..."`.
- **Python 3.14 only.** `except A, B:` (PEP 758, unparenthesized) is valid here; a `SyntaxError` on those lines means the wrong interpreter, not broken code.
- **Verification gate:** the full `make check` (lint + format-check + mypy + ts-check + vitest + the entire pytest suite **including `e2e/`**) must be green before the work is called done. `ARGS` is for iterating, never for the gate.
- **Never write to `GeneratedField`s.** Not touched here, but it stands.
- **Complete-word identifiers** in Python and TypeScript (`definition` not `defn`, `field_name` not `fn`).
- **Comments explain obscure intent only.** No issue or PR numbers in new comments, no history narration.
- **Named compound types.** A tuple/dict crossing a function boundary gets a `TypedDict`/`NamedTuple`/`type` alias. PEP 695 aliases carry a trailing example comment.
- **`config()` for settings**, never bare `os.environ`. Not touched here.
- Registry must stay importable from `settings.py`: **no import-time** `django.forms` or `games.models` reference in `timetracker/settings_registry.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `timetracker/settings_registry.py` (modify) | Declares per-setting data incl. control kind, choices, model source, reload/help policy; validates definition shape at import |
| `games/forms.py` (modify) | Gains module-level `apply_primitive_widget_classes(fields)`; `PrimitiveWidgetsMixin` becomes its caller |
| `games/settings_forms.py` (create) | Registry-derived form base + both page subclasses, `display_label`, `settings_page_data` |
| `games/views/settings.py` (modify) | HTTP handlers + `_infra_fields` only |
| `tests/test_settings_registry.py` (modify) | Adds definition-invariant tests |
| `tests/test_settings_forms.py` (create) | Parity, synthetic-ninth-setting, live-save derivation, `display_label` |
| `tests/test_admin_settings_page.py` (modify) | One import line moves to the new module |

---

### Task 1: Registry declares control data

**Files:**
- Modify: `timetracker/settings_registry.py`
- Test: `tests/test_settings_registry.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `SettingWidget` (StrEnum: `TEXT="text"`, `SELECT="select"`, `MODEL="model"`), `type SettingOption = tuple[Any, str]`, `type QuerysetFactory = Callable[[], QuerySet[Any]]`, `PAGE_SIZE_OPTIONS: Final[tuple[SettingOption, ...]]`, and four new `SettingDefinition` fields: `choices: tuple[SettingOption, ...] | None = None`, `model_queryset: QuerysetFactory | None = None`, `reload_after_save: bool = False`, `user_help_text: str = ""`. `widget` changes type from `str | None` to `SettingWidget | None`.

- [ ] **Step 1: Write the failing invariant tests**

Append to `tests/test_settings_registry.py` (it already imports `pytest`, `settings_registry`, `ApplyTiming`, `SettingScope`, `get_definition` — add `SettingDefinition` and `SettingWidget` to the existing import from `timetracker.settings_registry` if absent):

```python
def test_user_scoped_definition_must_declare_a_widget():
    with pytest.raises(ValueError, match="must declare a widget"):
        SettingDefinition(
            "SYNTHETIC",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Synthetic",
            default_factory=lambda: None,
        )


def test_select_widget_requires_choices():
    with pytest.raises(ValueError, match="SELECT"):
        SettingDefinition(
            "SYNTHETIC",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Synthetic",
            default_factory=lambda: None,
            widget=SettingWidget.SELECT,
        )


def test_model_widget_requires_a_queryset_factory():
    with pytest.raises(ValueError, match="MODEL"):
        SettingDefinition(
            "SYNTHETIC",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Synthetic",
            default_factory=lambda: None,
            widget=SettingWidget.MODEL,
        )


def test_choices_require_a_select_widget():
    with pytest.raises(ValueError, match="SELECT"):
        SettingDefinition(
            "SYNTHETIC",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Synthetic",
            default_factory=lambda: None,
            widget=SettingWidget.TEXT,
            choices=(("a", "A"),),
        )


def test_reload_after_save_requires_live_apply_timing():
    with pytest.raises(ValueError, match="reload_after_save"):
        SettingDefinition(
            "SYNTHETIC",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Synthetic",
            default_factory=lambda: None,
            reload_after_save=True,
        )


def test_registered_user_settings_carry_control_data():
    currency = get_definition("DEFAULT_CURRENCY")
    assert currency.widget is SettingWidget.TEXT
    assert currency.user_help_text.startswith("A personal value affects only")

    device = get_definition("DEFAULT_DEVICE")
    assert device.widget is SettingWidget.MODEL
    assert device.model_queryset is not None

    landing_page = get_definition("DEFAULT_LANDING_PAGE")
    assert landing_page.widget is SettingWidget.SELECT
    assert landing_page.choices == settings_registry.LANDING_PAGE_CHOICES

    page_size = get_definition("DEFAULT_PAGE_SIZE")
    assert page_size.choices == settings_registry.PAGE_SIZE_OPTIONS
    assert page_size.reload_after_save is False

    for key in ("THEME", "DISPLAY_TIME_ZONE", "DATE_FORMAT_LOCALE", "DATETIME_FORMAT"):
        assert get_definition(key).reload_after_save is True, key
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
make test ARGS="tests/test_settings_registry.py -x -q"
```

Expected: FAIL — `TypeError: SettingDefinition.__init__() got an unexpected keyword argument 'choices'` (and `AttributeError` on `settings_registry.PAGE_SIZE_OPTIONS`).

- [ ] **Step 3: Add the type aliases and the widget enum**

In `timetracker/settings_registry.py`, extend the `typing` import to include `Any` and add a `TYPE_CHECKING` guard for `QuerySet`. After the existing `type SettingWriteValidator = ...` alias block (around line 28), add:

```python
type SettingOption = tuple[Any, str]  # e.g. ("cs", "Čeština"), (25, "25")
type QuerysetFactory = Callable[[], "QuerySet[Any]"]  # lazy; imports models when called
```

and at the top of the imports:

```python
from typing import TYPE_CHECKING, Any, Callable, Final, cast

if TYPE_CHECKING:
    from django.db.models import QuerySet
```

Next to `class SettingScope(StrEnum)` add:

```python
class SettingWidget(StrEnum):
    """Control kind a settings page builds for a user-scoped setting.

    StrEnum, not Enum: the registry contract tests compare against the raw
    string values.
    """

    TEXT = "text"
    SELECT = "select"
    MODEL = "model"
```

- [ ] **Step 4: Add `PAGE_SIZE_OPTIONS`**

Directly after the existing `PAGE_SIZE_CHOICES` constant:

```python
PAGE_SIZE_OPTIONS: Final[tuple[SettingOption, ...]] = tuple(
    (size, str(size)) for size in PAGE_SIZE_CHOICES
)
```

`PAGE_SIZE_CHOICES` keeps its `tuple[int, ...]` shape — `_validate_page_size` reads it.

- [ ] **Step 5: Add the lazy device queryset factory**

Beside `_require_existing_device` (which already does the lazy-import dance):

```python
def _device_queryset() -> "QuerySet[Any]":
    """Options for the default-device control. The models import happens on call,
    never at module import, so settings.py can import this module."""
    from games.models import Device

    return Device.objects.order_by("name")
```

- [ ] **Step 6: Extend `SettingDefinition` and its invariants**

Change the `widget` annotation and add the four fields:

```python
    widget: SettingWidget | None = None
    choices: tuple[SettingOption, ...] | None = None
    model_queryset: QuerysetFactory | None = None
    reload_after_save: bool = False
    user_help_text: str = ""
```

Append to `__post_init__`, after the existing INFRA/RESTART check:

```python
        if self.scope is SettingScope.USER and self.widget is None:
            raise ValueError(f"{self.key}: user-scoped settings must declare a widget.")
        if (self.widget is SettingWidget.SELECT) != (self.choices is not None):
            raise ValueError(
                f"{self.key}: a SELECT widget needs choices, and choices need a "
                "SELECT widget."
            )
        if (self.widget is SettingWidget.MODEL) != (self.model_queryset is not None):
            raise ValueError(
                f"{self.key}: a MODEL widget needs model_queryset, and "
                "model_queryset needs a MODEL widget."
            )
        # A restart-only value cannot be fixed by reloading the page.
        if self.reload_after_save and self.apply_timing is not ApplyTiming.LIVE:
            raise ValueError(
                f"{self.key}: reload_after_save requires apply_timing=LIVE."
            )
```

- [ ] **Step 7: Update the eight user-scoped definitions**

In `_build_registry()`, replace each `widget="..."` string with the enum member and add the new data:

```python
        SettingDefinition(
            "DEFAULT_CURRENCY",
            ...
            widget=SettingWidget.TEXT,
            user_help_text=(
                "A personal value affects only your purchase entry; purchases "
                "saved without user context and FX/reporting continue to use the "
                "site value."
            ),
        ),
        SettingDefinition(
            "DEFAULT_DEVICE",
            ...
            widget=SettingWidget.MODEL,
            model_queryset=_device_queryset,
            write_validator=_require_existing_device,
        ),
        SettingDefinition(
            "DEFAULT_LANDING_PAGE",
            ...
            widget=SettingWidget.SELECT,
            choices=LANDING_PAGE_CHOICES,
        ),
        SettingDefinition(
            "DEFAULT_PAGE_SIZE",
            ...
            widget=SettingWidget.SELECT,
            choices=PAGE_SIZE_OPTIONS,
        ),
```

and for `THEME`, `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, `DATETIME_FORMAT`:

```python
            widget=SettingWidget.SELECT,
            choices=THEME_CHOICES,          # DISPLAY_TIME_ZONE_CHOICES /
            reload_after_save=True,         # FORMAT_LOCALE_CHOICES /
                                            # DATETIME_FORMAT_CHOICES respectively
```

`DEFAULT_LANDING_PAGE` moving from `"text"` to `SELECT` is the drift fix — it has rendered as a `ChoiceField` on both pages all along.

- [ ] **Step 8: Run the registry tests**

```bash
make test ARGS="tests/test_settings_registry.py -q"
```

Expected: PASS, including the pre-existing `test_datetime_format_registry_contract`, whose `definition.widget == "select"` assertion holds because `SettingWidget` is a `StrEnum`.

- [ ] **Step 9: Confirm nothing else regressed and types are clean**

```bash
make typecheck
```

Expected: `Success: no issues found`. If mypy rejects `choices=` on a Django field later, note that `SettingOption` is deliberately `tuple[Any, str]` to match django-stubs' `_Choice`.

```bash
make test ARGS="tests/test_settings_commands.py tests/test_admin_settings_page.py tests/test_settings_page.py -q"
```

Expected: PASS — this step changes no behavior.

- [ ] **Step 10: Commit**

```bash
git add timetracker/settings_registry.py tests/test_settings_registry.py && git commit -m "feat(settings): let the registry describe each setting's control"
```

---

### Task 2: Extract the widget-class stamping function

**Files:**
- Modify: `games/forms.py:93-115`
- Test: `tests/test_settings_forms.py` (created here, one test)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `apply_primitive_widget_classes(fields: Mapping[str, forms.Field]) -> None` in `games/forms.py`. Task 3 calls it.

Why: `RegistrySettingsForm` builds its fields *after* `super().__init__()` (assigning `self.base_fields` before `super()` works at runtime but fails mypy — django-stubs declares it a `ClassVar`). Fields built that late are out of `PrimitiveWidgetsMixin`'s reach, so the stamping has to be callable directly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_forms.py`:

```python
from django import forms

from games.forms import INPUT_CLASS, SELECT_CLASS, apply_primitive_widget_classes


def test_stamping_applies_the_shared_control_classes_by_widget_type():
    fields: dict[str, forms.Field] = {
        "choice": forms.ChoiceField(choices=(("a", "A"),)),
        "text": forms.CharField(),
    }

    apply_primitive_widget_classes(fields)

    assert fields["choice"].widget.attrs["class"] == SELECT_CLASS
    assert fields["text"].widget.attrs["class"] == INPUT_CLASS
```

- [ ] **Step 2: Run it to verify it fails**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: FAIL — `ImportError: cannot import name 'apply_primitive_widget_classes' from 'games.forms'`.

- [ ] **Step 3: Extract the function**

Replace `games/forms.py:93-115` with:

```python
def apply_primitive_widget_classes(fields: Mapping[str, forms.Field]) -> None:
    """Stamp the shared native-control classes over a form's fields.

    Callable on its own so a form that builds fields after ``super().__init__()``
    can opt in; :class:`PrimitiveWidgetsMixin` is the declarative path.
    """
    for field in fields.values():
        if isinstance(field, forms.BooleanField):
            field.widget = PrimitiveCheckboxWidget()
            # Maintain the field's explicit required status (usually False for booleans)
            continue
        widget = field.widget
        # SearchSelect is a self-styled composite component; never stamp the
        # native-control classes onto it.
        if isinstance(widget, SearchSelectWidget):
            continue
        if isinstance(widget, forms.Select):
            control_class = SELECT_CLASS
        elif isinstance(widget, forms.Textarea):
            control_class = TEXTAREA_CLASS
        else:
            control_class = INPUT_CLASS
        existing = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{existing} {control_class}".strip()


class PrimitiveWidgetsMixin:
    """Automatically applies primitive custom widgets to native Django form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_primitive_widget_classes(self.fields)
```

Add `from collections.abc import Mapping` to the imports at the top of `games/forms.py`.

- [ ] **Step 4: Run the test and the forms-touching suites**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: PASS.

```bash
make test ARGS="tests/test_components.py tests/test_rendered_pages.py tests/test_search_select.py tests/test_settings_page.py tests/test_admin_settings_page.py -q"
```

Expected: PASS — every existing form still routes through the mixin.

- [ ] **Step 5: Commit**

```bash
git add games/forms.py tests/test_settings_forms.py && git commit -m "refactor(forms): make primitive widget stamping callable on its own"
```

---

### Task 3: Registry-derived form classes

**Files:**
- Create: `games/settings_forms.py`
- Test: `tests/test_settings_forms.py`

**Interfaces:**
- Consumes: Task 1's `SettingWidget`, `SettingOption`, `SettingDefinition.choices/model_queryset/user_help_text`; Task 2's `apply_primitive_widget_classes`.
- Produces: `RegistrySettingsForm`, `UserSettingsForm`, `SiteSettingsForm`, `display_label(definition, value) -> str`, `user_setting_definitions() -> list[SettingDefinition]`, `field_name_for(definition) -> str`, `TextFieldOverride`. Task 4 consumes all of them.

- [ ] **Step 1: Write the failing form tests**

Append to `tests/test_settings_forms.py`:

```python
import pytest

from games.models import Device
from games.settings_forms import SiteSettingsForm, UserSettingsForm, display_label
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    LANDING_PAGE_CHOICES,
    PAGE_SIZE_OPTIONS,
    SettingScope,
    get_definition,
)


def _user_field_names() -> list[str]:
    return [
        key.lower()
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.scope is SettingScope.USER
    ]


@pytest.mark.django_db
def test_both_forms_expose_every_user_scoped_key_in_registry_order():
    assert list(UserSettingsForm().fields) == _user_field_names()
    assert list(SiteSettingsForm().fields) == _user_field_names()


@pytest.mark.django_db
def test_field_classes_match_pairwise_across_the_two_pages():
    site_fields = SiteSettingsForm().fields
    for field_name, field in UserSettingsForm().fields.items():
        assert type(field) is type(site_fields[field_name]), field_name


@pytest.mark.django_db
def test_page_size_is_typed_on_both_pages():
    assert isinstance(
        UserSettingsForm().fields["default_page_size"], forms.TypedChoiceField
    )
    assert isinstance(
        SiteSettingsForm().fields["default_page_size"], forms.TypedChoiceField
    )


@pytest.mark.django_db
def test_currency_keeps_its_mask_and_length_while_a_plain_text_setting_would_not():
    currency = UserSettingsForm().fields["default_currency"]

    assert currency.max_length == 3
    assert currency.widget.attrs["x-mask"] == "aaa"
    assert "uppercase" in currency.widget.attrs["class"]


@pytest.mark.django_db
def test_the_site_page_uses_the_static_empty_label():
    fields = SiteSettingsForm().fields

    assert list(fields["default_landing_page"].choices) == [
        ("", "Use configured default"),
        *LANDING_PAGE_CHOICES,
    ]
    assert list(fields["default_page_size"].choices) == [
        ("", "Use configured default"),
        *PAGE_SIZE_OPTIONS,
    ]


@pytest.mark.django_db
def test_the_user_page_names_the_inherited_site_value():
    fields = UserSettingsForm().fields

    assert fields["default_landing_page"].choices[0] == ("", "Use site default (Sessions)")
    assert fields["default_page_size"].choices[0] == ("", "Use site default (25)")
    assert fields["default_device"].empty_label == "Use site default (No device)"
    assert (
        fields["default_currency"].widget.attrs["placeholder"]
        == "Use site default (USD)"
    )


@pytest.mark.django_db
def test_display_label_falls_back_to_the_first_choice_only_for_none():
    landing_page = get_definition("DEFAULT_LANDING_PAGE")
    assert display_label(landing_page, None) == "Sessions"
    assert display_label(landing_page, "games:list_games") == "Games"

    # A timezone outside the frozen choices tuple must print itself, not the
    # alphabetically first zone.
    time_zone = get_definition("DISPLAY_TIME_ZONE")
    assert display_label(time_zone, "Europe/Prague") == "Europe/Prague"
    assert display_label(time_zone, "Factory/Unknown") == "Factory/Unknown"


@pytest.mark.django_db
def test_display_label_names_the_device_or_reports_none():
    device = Device.objects.create(name="Desktop", type="pc")
    definition = get_definition("DEFAULT_DEVICE")

    assert display_label(definition, device.pk) == str(device)
    assert display_label(definition, None) == "No device"
    assert display_label(definition, device.pk + 1000) == "No device"
```

The site-page currency assertion is deliberately absent: that field now gains
`placeholder="Use configured default"`, an accepted change (invisible in normal
use, accurate when an admin clears the box).

- [ ] **Step 2: Run to verify failure**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'games.settings_forms'`.

- [ ] **Step 3: Create `games/settings_forms.py` with the field builder**

```python
"""Settings controls derived from the registry.

Both settings pages render the same eight user-scoped settings; they differ only
in how an inherited value is named and in how each value is resolved. The field
set, its widgets, and its labels come from ``SETTINGS_REGISTRY``, so a new
user-scoped setting needs no edit here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from django import forms

from games.forms import apply_primitive_widget_classes
from timetracker.config import SettingSource
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    SettingDefinition,
    SettingKey,
    SettingScope,
    SettingWidget,
)
from timetracker.settings_resolver import (
    ResolvedSetting,
    resolve_for_user_with_origin,
    resolve_with_origin,
)

# DEFAULT_DEVICE is the only MODEL setting; this is the label its unset state
# reads as in "Use site default (…)".
_EMPTY_MODEL_LABEL: Final = "No device"


@dataclass(frozen=True, slots=True)
class TextFieldOverride:
    """Per-setting extras for a TEXT control.

    Currency is masked to three uppercase letters; a plain text setting must not
    inherit that, so the specifics live here rather than in the TEXT branch.
    """

    max_length: int | None = None
    widget_attrs: Mapping[str, str] = field(default_factory=dict)


_TEXT_FIELD_OVERRIDES: Final[dict[SettingKey, TextFieldOverride]] = {
    "DEFAULT_CURRENCY": TextFieldOverride(
        max_length=3,
        widget_attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"},
    ),
}


def user_setting_definitions() -> list[SettingDefinition]:
    """The user-scoped definitions, in registry order."""
    return [
        definition
        for definition in SETTINGS_REGISTRY.values()
        if definition.scope is SettingScope.USER
    ]


def field_name_for(definition: SettingDefinition) -> str:
    """The Django form field name for a registry key."""
    return definition.key.lower()


def _model_label(definition: SettingDefinition, value: object) -> str:
    # bool is an int subclass; a stray True must not look up pk=1.
    if isinstance(value, int) and not isinstance(value, bool):
        queryset_factory = definition.model_queryset
        if queryset_factory is not None:
            instance = queryset_factory().filter(pk=value).first()
            if instance is not None:
                return str(instance)
    return _EMPTY_MODEL_LABEL


def display_label(definition: SettingDefinition, value: object) -> str:
    """The human label for a resolved value, as used in "Use site default (…)"."""
    if definition.widget is SettingWidget.MODEL:
        return _model_label(definition, value)
    if definition.widget is SettingWidget.SELECT:
        choices = definition.choices or ()
        for choice_value, label in choices:
            if choice_value == value:
                return label
        # Only an unset value means "the first option"; anything else prints
        # itself, so an out-of-choices timezone is not relabeled as another zone.
        if value is None and choices:
            return choices[0][1]
    return str(value)
```

- [ ] **Step 4: Add the form base and the two page subclasses**

Append to `games/settings_forms.py`:

```python
class RegistrySettingsForm(forms.Form):
    """Controls for every user-scoped setting, built from the registry.

    Fields are built after ``super().__init__()`` and assigned to ``self.fields``:
    ``base_fields`` is a ClassVar in django-stubs, so a per-instance assignment
    fails mypy. That also puts the fields outside ``PrimitiveWidgetsMixin``'s
    reach, hence the direct stamping call. Merging ``self.fields`` last keeps a
    field a subclass declares the ordinary way.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields = {**self._build_fields(), **self.fields}
        apply_primitive_widget_classes(self.fields)

    def empty_label(self, definition: SettingDefinition) -> str:
        """Text of the option/placeholder meaning "inherit"."""
        raise NotImplementedError

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        """Resolve one setting the way this page reads it."""
        raise NotImplementedError

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        """Whether a resolved value is prefilled into the control."""
        raise NotImplementedError

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> "SettingFieldState":
        """Per-field settings metadata for this page."""
        raise NotImplementedError

    def _build_fields(self) -> dict[str, forms.Field]:
        fields: dict[str, forms.Field] = {}
        for definition in user_setting_definitions():
            built = self._build_field(definition)
            built.label = definition.label
            fields[field_name_for(definition)] = built
        return fields

    def _build_field(self, definition: SettingDefinition) -> forms.Field:
        empty_label = self.empty_label(definition)
        if definition.widget is SettingWidget.MODEL:
            queryset_factory = definition.model_queryset
            if queryset_factory is None:
                raise ValueError(f"{definition.key}: MODEL widget without a queryset.")
            return forms.ModelChoiceField(
                queryset=queryset_factory(),
                required=False,
                empty_label=empty_label,
            )
        if definition.widget is SettingWidget.SELECT:
            choices = (("", empty_label), *(definition.choices or ()))
            if definition.cast is not None:
                return forms.TypedChoiceField(
                    required=False,
                    choices=choices,
                    coerce=definition.cast,
                    empty_value=None,
                )
            return forms.ChoiceField(required=False, choices=choices)
        override = _TEXT_FIELD_OVERRIDES.get(definition.key, TextFieldOverride())
        return forms.CharField(
            required=False,
            max_length=override.max_length,
            widget=forms.TextInput(
                attrs={**override.widget_attrs, "placeholder": empty_label}
            ),
        )


class SiteSettingsForm(RegistrySettingsForm):
    """Site defaults. Every control shows the resolved value, so the empty option
    names the configured fallback rather than a value."""

    def empty_label(self, definition: SettingDefinition) -> str:
        return "Use configured default"

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        return resolve_with_origin(definition.key)

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        return True

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> "SettingFieldState":
        return SettingFieldState(
            definition.key,
            str(resolved.source),
            locked=resolved.locked,
            help_text=definition.help_text,
            live_save=live_save,
        )


class UserSettingsForm(RegistrySettingsForm):
    """Personal preferences. An empty control inherits, and says which site value
    it inherits."""

    def empty_label(self, definition: SettingDefinition) -> str:
        site_value = resolve_with_origin(definition.key).value
        return f"Use site default ({display_label(definition, site_value)})"

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        return resolve_for_user_with_origin(user, definition.key)

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        return resolved.source is SettingSource.USER

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> "SettingFieldState":
        return SettingFieldState(
            definition.key,
            str(resolved.source),
            help_text=definition.user_help_text or definition.help_text,
            live_save=live_save,
            # Each control already names the site value it inherits, so an origin
            # badge here would only repeat it.
            show_source=False,
        )
```

Add `SettingFieldState` to the imports (`from common.components import SettingFieldState`) and drop the forward-reference quotes once it is imported.

- [ ] **Step 5: Run the form tests**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: PASS, all of them.

- [ ] **Step 6: Type-check**

```bash
make typecheck
```

Expected: `Success: no issues found`. In particular the `self.fields = {...}` assignment must be accepted; if `base_fields` appears anywhere in this module, it is the rejected approach and must be removed.

- [ ] **Step 7: Commit**

```bash
git add games/settings_forms.py tests/test_settings_forms.py && git commit -m "feat(settings): build both settings forms from the registry"
```

---

### Task 4: One state builder, and views reduced to handlers

**Files:**
- Modify: `games/settings_forms.py` (append)
- Modify: `games/views/settings.py:1-309` (delete forms/helpers/builders), `:312-340` and `:366-429` (rewire)
- Modify: `tests/test_admin_settings_page.py:279`
- Test: `tests/test_settings_forms.py`

**Interfaces:**
- Consumes: Task 3's form classes.
- Produces: `SettingsPageData(form, states, presentations)` NamedTuple and `settings_page_data(form_class, *, user=None, presentations=None) -> SettingsPageData`.

- [ ] **Step 1: Write the failing state-builder tests**

Append to `tests/test_settings_forms.py`:

```python
from common.components import FormFieldPresentation, Span
from games.settings_forms import settings_page_data
from timetracker.settings_registry import (
    ApplyTiming,
    SettingDefinition,
    SettingWidget,
)
from timetracker.settings_resolver import clear_cache

_SYNTHETIC_CHOICES = (("alpha", "Alpha"), ("beta", "Beta"))


@pytest.fixture
def synthetic_setting(monkeypatch):
    """A ninth user-scoped setting added to the registry and nowhere else."""
    definition = SettingDefinition(
        "SYNTHETIC_NINTH",
        scope=SettingScope.USER,
        apply_timing=ApplyTiming.LIVE,
        label="Synthetic ninth",
        help_text="Added by a test.",
        default_factory=lambda: "alpha",
        widget=SettingWidget.SELECT,
        choices=_SYNTHETIC_CHOICES,
    )
    monkeypatch.setitem(SETTINGS_REGISTRY, definition.key, definition)
    clear_cache()
    yield definition
    clear_cache()


@pytest.mark.django_db
def test_a_new_registry_entry_reaches_both_forms_with_no_form_edit(synthetic_setting):
    user_field = UserSettingsForm().fields["synthetic_ninth"]
    site_field = SiteSettingsForm().fields["synthetic_ninth"]

    assert isinstance(user_field, forms.ChoiceField)
    assert user_field.label == "Synthetic ninth"
    assert list(user_field.choices) == [
        ("", "Use site default (Alpha)"),
        *_SYNTHETIC_CHOICES,
    ]
    assert list(site_field.choices) == [
        ("", "Use configured default"),
        *_SYNTHETIC_CHOICES,
    ]


@pytest.mark.django_db
def test_a_new_registry_entry_reaches_both_state_builders(synthetic_setting):
    user_page = settings_page_data(UserSettingsForm, user=None)
    site_page = settings_page_data(SiteSettingsForm)

    assert user_page.states["synthetic_ninth"].key == "SYNTHETIC_NINTH"
    assert user_page.states["synthetic_ninth"].source == "default"
    assert user_page.states["synthetic_ninth"].show_source is False
    assert site_page.states["synthetic_ninth"].help_text == "Added by a test."
    assert site_page.form.initial["synthetic_ninth"] == "alpha"


@pytest.mark.django_db
def test_the_personal_page_prefills_only_its_own_overrides(django_user_model):
    user = django_user_model.objects.create_user(username="tester", password="pw")
    page = settings_page_data(UserSettingsForm, user=user)

    assert page.form.initial == {}
    assert page.states["default_page_size"].source == "default"


@pytest.mark.django_db
def test_a_control_decorator_takes_over_saving_and_its_reload_stamp():
    page = settings_page_data(
        UserSettingsForm,
        user=None,
        presentations={
            "theme": FormFieldPresentation(decorate_control=lambda node: node)
        },
    )

    assert page.states["theme"].live_save is False
    assert "data-reload-after-save" not in page.form.fields["theme"].widget.attrs
    assert "data-reload-after-save" in page.form.fields["datetime_format"].widget.attrs


@pytest.mark.django_db
def test_a_cosmetic_presentation_keeps_the_field_live_saving():
    page = settings_page_data(
        UserSettingsForm,
        user=None,
        presentations={"theme": FormFieldPresentation(after_control=Span()["hint"])},
    )

    assert page.states["theme"].live_save is True
    assert "data-reload-after-save" in page.form.fields["theme"].widget.attrs


@pytest.mark.django_db
def test_the_site_page_stamps_every_display_setting_for_reload():
    page = settings_page_data(SiteSettingsForm)

    for field_name in ("theme", "display_time_zone", "date_format_locale", "datetime_format"):
        assert "data-reload-after-save" in page.form.fields[field_name].widget.attrs
    for field_name in ("default_currency", "default_device", "default_page_size"):
        assert "data-reload-after-save" not in page.form.fields[field_name].widget.attrs
```

- [ ] **Step 2: Run to verify failure**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: FAIL — `ImportError: cannot import name 'settings_page_data' from 'games.settings_forms'`.

- [ ] **Step 3: Add `SettingsPageData` and `settings_page_data`**

Append to `games/settings_forms.py` (and add `NamedTuple` to the `typing` import, `FormFieldPresentation` to the `common.components` import):

```python
class SettingsPageData(NamedTuple):
    """One settings page's form, per-field state, and the presentations that the
    state policy and the renderer must both see."""

    form: RegistrySettingsForm
    states: dict[str, SettingFieldState]
    presentations: dict[str, FormFieldPresentation]


def settings_page_data(
    form_class: type[RegistrySettingsForm],
    *,
    user: object = None,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
) -> SettingsPageData:
    """Resolve every user-scoped setting once, then build the page's form and state.

    A presentation that replaces the control (``decorate_control``) declares that
    something other than the generic live-save element owns it; a purely cosmetic
    presentation does not. A control someone else owns also skips the reload
    stamp, since the generic element is what would act on it.
    """
    supplied = dict(presentations or {})
    initial: dict[str, object] = {}
    states: dict[str, SettingFieldState] = {}
    reload_field_names: list[str] = []
    for definition in user_setting_definitions():
        field_name = field_name_for(definition)
        resolved = form_class.resolve(definition, user)
        if form_class.keeps_initial(resolved):
            initial[field_name] = resolved.value
        presentation = supplied.get(field_name)
        live_save = presentation is None or presentation.decorate_control is None
        states[field_name] = form_class.field_state(
            definition, resolved, live_save=live_save
        )
        if definition.reload_after_save and live_save:
            reload_field_names.append(field_name)
    form = form_class(initial=initial)
    for field_name in reload_field_names:
        form.fields[field_name].widget.attrs["data-reload-after-save"] = ""
    return SettingsPageData(form, states, supplied)
```

- [ ] **Step 4: Run the state-builder tests**

```bash
make test ARGS="tests/test_settings_forms.py -q"
```

Expected: PASS.

- [ ] **Step 5: Reduce `games/views/settings.py` to handlers**

Delete lines 47–309 wholesale — `_FIELD_KEYS`, `_PERSONAL_CURRENCY_HELP`, `UserSettingsForm`, `SiteSettingsForm`, `_device_label`, `_landing_page_label`, `_format_locale_label`, `_datetime_format_label`, `_form_and_states`, `_site_form_and_states`. Then replace the two handler bodies' first lines and the `__all__` block:

```python
@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    page = settings_page_data(
        UserSettingsForm,
        user=request.user,
        presentations={"theme": FormFieldPresentation(decorate_control=ThemeSetting)},
    )
    patch_url = reverse(
        "api-1.0.0:update_user_setting",
        kwargs={"key": "__key__"},
    )
    sections = [
        SettingsSection(
            "preferences",
            "Preferences",
            LiveSettingFields(
                page.form,
                states=page.states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                namespace=SettingNamespace.USER,
                presentations=page.presentations,
            ),
            "Defaults used when creating records and opening Timetracker.",
        )
    ]
```

and in `admin_settings`, replacing `form, states = _site_form_and_states()`:

```python
    page = settings_page_data(SiteSettingsForm)
```

with the section's `LiveSettingFields(page.form, states=page.states, …, presentations=page.presentations)`.

Fix the imports: drop `forms`, `cast`, `Device`, `PrimitiveWidgetsMixin`, the choice constants, `get_definition`, `resolve_for_user_with_origin`, and `SettingFieldState`; add

```python
from games.settings_forms import SiteSettingsForm, UserSettingsForm, settings_page_data
```

Keep `SETTINGS_REGISTRY`, `SettingScope`, `resolve_with_origin`, and `SettingSource` only if `_infra_fields` still needs them (it needs the first three). Trim `__all__` to:

```python
__all__ = [
    "admin_settings",
    "export_admin_settings_ini",
    "user_settings",
]
```

No compatibility re-export: the form classes now live in `games/settings_forms.py` and their one external importer moves in the next step.

- [ ] **Step 6: Move the one external import**

In `tests/test_admin_settings_page.py:279`, change

```python
    from games.views.settings import SiteSettingsForm
```

to

```python
    from games.settings_forms import SiteSettingsForm
```

- [ ] **Step 7: Run every settings suite**

```bash
make test ARGS="tests/test_settings_forms.py tests/test_settings_page.py tests/test_admin_settings_page.py tests/test_settings_registry.py tests/test_settings_commands.py tests/test_settings_ui_kit.py -q"
```

Expected: PASS. The page tests are the real gate here — `tests/test_settings_page.py` pins the exact `"Use site default (No device)"` / `(Sessions)` / `(25)` / `(System)` / `(ISO 8601)` options, the currency placeholder, and the datetime reload stamp; `tests/test_admin_settings_page.py` pins the field classes, the seven empty options, and both stamps.

- [ ] **Step 8: Lint, format, type-check**

```bash
make lint-fix && make format && make typecheck
```

Expected: no lint findings, formatting stable, `Success: no issues found`.

- [ ] **Step 9: Commit**

```bash
git add games/settings_forms.py games/views/settings.py tests/test_settings_forms.py tests/test_admin_settings_page.py && git commit -m "refactor(settings): assemble both settings pages from one resolve pass"
```

---

### Task 5: Full verification gate

**Files:** none modified unless the gate finds something.

- [ ] **Step 1: Run the full check**

```bash
make check
```

Expected: green — lint, format-check, mypy, ts-check, icon drift, vitest, and the entire pytest suite **including `e2e/`**. The e2e settings specs (`e2e/test_settings_page_e2e.py`, `e2e/test_settings_ui_kit_e2e.py`) exercise the live-save PATCH round-trip and the reload behavior in a real browser; they are the only check that the derived `data-reload-after-save` / `data-live-setting-control` stamps still drive the TypeScript element.

- [ ] **Step 2: Confirm the goal empirically**

```bash
git diff --stat main...HEAD -- timetracker/settings_registry.py games/settings_forms.py games/views/settings.py
```

Expected: `games/views/settings.py` down by roughly 250 lines. Sanity-check the claim by reading the synthetic-ninth-setting test: it adds a setting to the registry alone and asserts it appears on both pages.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin claude/github-issue-495-plan-cee3d5
```

```bash
gh pr create --title "Derive the settings forms from the registry" --body "Closes #495"
```

---

## Notes for the implementer

- **`self.base_fields` is a trap.** Assigning it per instance before `super().__init__()` renders correctly but fails mypy (`Cannot assign to class variable "base_fields" via instance`), so `make check` goes red. The plan's post-`super()` `self.fields` assignment is the verified alternative.
- **`SettingWidget` must stay a `StrEnum`.** `tests/test_settings_registry.py` compares `definition.widget == "select"`; a plain `Enum` breaks it.
- **`UserSettingsForm` now needs a database** at construction — it resolves site values for its empty labels. Every test constructing it needs `@pytest.mark.django_db`.
- **The reload stamp lives on the widget**, not just in `SettingFieldState`; `tests/test_admin_settings_page.py` asserts it inside the opening control tag.
- **Test imports go at the top of the file.** The plan shows each task's new
  imports beside the tests that need them for readability; collect them into the
  existing import block, or ruff will flag the module-level ordering.
- **Commit count differs from the spec.** The spec sketched three commits; this
  plan makes four, because TDD puts each task's tests in the commit that
  introduces the behavior rather than in a trailing test commit. The layering is
  unchanged.
- If a step's assertion disagrees with reality, stop and check the spec section it came from rather than loosening the assertion.
