# Issue #495 — Derive the settings forms from the registry

## Problem

`games/views/settings.py` carries two parallel per-setting stacks:

- `UserSettingsForm` and `SiteSettingsForm` declare the same eight fields with the
  same widgets, the same `Device.objects.order_by("name")` init, the same
  `_FIELD_KEYS` label loop, and their own `data-reload-after-save` tuple. They
  differ in empty-option text (live-resolved `"Use site default (…)"` vs static
  `"Use configured default"`) and in `default_page_size` being a
  `TypedChoiceField(coerce=int)` on one side and a plain `ChoiceField` on the
  other.
- `_form_and_states` and `_site_form_and_states` repeat the iterate-keys /
  `get_definition` / resolve / build-`SettingFieldState` skeleton with a
  different resolver and different kwargs.

Adding a ninth setting today touches roughly five sites: the registry,
`_FIELD_KEYS`, both form bodies, and the user form's empty-label kwarg
threading.

Three facts found while reading the code shape the design:

1. `_FIELD_KEYS` is already derivable. Its eight entries are exactly the
   `SettingScope.USER` definitions in registry order, and every field name is
   its key lowercased.
2. `SettingDefinition.widget` (`"text"`/`"device"`/`"select"`) is dead — nothing
   reads it — and has already drifted: `DEFAULT_LANDING_PAGE` declares
   `widget="text"` while both forms render it as a `ChoiceField`.
3. Neither form is ever bound or cleaned. Views only render them and set
   `initial`; saves go through the PATCH API (`update_user_setting` /
   `update_site_setting`), which casts and validates through the registry. So
   the site form's `coerce=int` never runs — the page-size divergence is dead
   code, not just drift.

One difference is real and must survive: `data-reload-after-save` covers three
fields on the user page and four on the site page. The user page's `theme`
control is owned by `ThemeSetting` (`live_save=False`) and applies client-side,
so it needs no reload.

## Goal

A ninth user setting is one registry entry and nothing else. No form edit, no
key list edit, no label-kwarg threading.

## Design

### 1. Registry declares data; `games/` builds widgets

`timetracker/settings_registry.py` stays free of `django.forms` and of any
import-time reference to `games.models`. It gains:

```python
type SettingOption = tuple[object, str]      # e.g. ("cs", "Čeština"), (25, "25")
type QuerysetFactory = Callable[[], "QuerySet"]  # lazy; imports models when called
```

and on `SettingDefinition`:

| Field | Type | Purpose |
|---|---|---|
| `widget` | `SettingWidget \| None` | was `str \| None`; now a `StrEnum` (`TEXT`, `SELECT`, `MODEL`) and load-bearing |
| `choices` | `tuple[SettingOption, ...] \| None` | options for `SELECT`; `None` otherwise |
| `model_queryset` | `QuerysetFactory \| None` | options for `MODEL`; called at form-build time |
| `reload_after_save` | `bool = False` | the page must reload for this value to take effect |
| `user_help_text` | `str = ""` | help text the personal page shows instead of `help_text` |

`QuerySet` is imported under `if TYPE_CHECKING:` so the module keeps its "safe to
import from `settings.py`" property. The `MODEL` factory does its `games.models`
import inside the callable, matching `_require_existing_device`.

Registry changes to existing definitions:

- `DEFAULT_CURRENCY` — `widget=SettingWidget.TEXT`;
  `user_help_text=` the string currently living in `_PERSONAL_CURRENCY_HELP`.
- `DEFAULT_DEVICE` — `widget=SettingWidget.MODEL`,
  `model_queryset=_device_queryset`.
- `DEFAULT_LANDING_PAGE` — `widget=SettingWidget.SELECT`,
  `choices=LANDING_PAGE_CHOICES` (fixes the drift by making the attribute
  load-bearing).
- `DEFAULT_PAGE_SIZE` — `choices=PAGE_SIZE_OPTIONS`.
- `THEME`, `DISPLAY_TIME_ZONE`, `DATE_FORMAT_LOCALE`, `DATETIME_FORMAT` —
  `choices=` their existing constant; `reload_after_save=True` on all four.

Choice constants stay module-level `Final` tuples; definitions hold references to
them. The validators already derive their frozensets from the same tuples
(`_THEME_VALUES`, `_FORMAT_LOCALE_VALUES`, …), so no new duplication appears. One
constant is added:

```python
PAGE_SIZE_OPTIONS: Final[tuple[SettingOption, ...]] = tuple(
    (size, str(size)) for size in PAGE_SIZE_CHOICES
)
```

`PAGE_SIZE_CHOICES` keeps its `tuple[int, ...]` shape for `_validate_page_size`.

### 2. `games/settings_form.py`

New module owning the form layer.

```python
class RegistrySettingsForm(PrimitiveWidgetsMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        self.base_fields = self._build_fields()
        super().__init__(*args, **kwargs)
```

Assigning `base_fields` as an **instance** attribute before `super().__init__()`
is load-bearing and verified: `BaseForm.__init__` deep-copies `self.base_fields`
into `self.fields`, and `PrimitiveWidgetsMixin.__init__` then stamps
`SELECT_CLASS`/`INPUT_CLASS` over the resulting fields. Building fields *after*
`super()` would silently skip that stamping. The class-level `base_fields` stays
`{}`, so nothing leaks between instances or subclasses.

`_build_fields()` walks `SETTINGS_REGISTRY` in order, skips anything that is not
`SettingScope.USER`, and for each definition uses `definition.key.lower()` as the
field name:

| `widget` | Field |
|---|---|
| `TEXT` | `forms.CharField(required=False, …)` |
| `SELECT` and `cast is int` | `forms.TypedChoiceField(coerce=definition.cast, empty_value=None, …)` |
| `SELECT` otherwise | `forms.ChoiceField(required=False, …)` |
| `MODEL` | `forms.ModelChoiceField(queryset=definition.model_queryset(), …)` |

The typed/untyped split is derived from `definition.cast`, so `default_page_size`
becomes a `TypedChoiceField` on **both** pages from one registry fact — the
existing admin-page assertion keeps passing, and the divergence cannot return.
`DEFAULT_CURRENCY` keeps its `max_length=3` and its
`{"x-mask": "aaa", "x-data": "", "class": "uppercase"}` widget attrs; those are
widget-kind-specific details of the TEXT branch, not per-setting data, so they
stay in the builder rather than moving into the registry.

The empty option is **not** part of `definition.choices`. The builder prepends it
using the single overridable hook:

```python
def empty_label(self, definition: SettingDefinition) -> str: ...
```

`SELECT` fields get `("", empty_label(definition))` prepended, `MODEL` fields get
it as `empty_label=`, and `TEXT` fields get it as a `placeholder` (an empty box
means inherit; clearing PATCHes `value: null` — unchanged behaviour).

Subclasses:

- `UserSettingsForm(user=…)` — `empty_label` resolves the site value for the key
  and returns `f"Use site default ({display_label(definition, value)})"`.
- `SiteSettingsForm()` — returns `"Use configured default"`. No-arg construction
  is preserved for `tests/test_admin_settings_page.py`.

`display_label(definition, value) -> str` replaces `_device_label`,
`_landing_page_label`, `_format_locale_label`, and `_datetime_format_label`.
Two branches:

- `SELECT` — look the value up in `definition.choices`; fall back to the **first
  choice's label** when it is missing or the wrong type. That reproduces every
  current fallback exactly, because each hand-written default is its setting's
  first choice: `"Sessions"`, `"English (United States)"`, `"ISO 8601"`,
  `"System"`.
- `MODEL` — return `str(device)` for the row named by the pk, else `"No device"`
  (value is `None`, a `bool`, or a dangling id). One explicit branch replacing
  `_device_label`.

`TEXT` returns `str(value)`, matching today's `str(site_currency)`.

Deleted by this module: `_FIELD_KEYS`, the eight `default_*_label` kwargs on
`UserSettingsForm.__init__`, the four `_*_label` helpers, `_PERSONAL_CURRENCY_HELP`
(moves into the registry as `user_help_text`), and both per-form
`data-reload-after-save` tuples.

### 3. One state builder

`form_and_states(form_class, *, user=None, presentations=None)` replaces
`_form_and_states` and `_site_form_and_states`. It makes a **single** pass over
the USER-scope definitions — today each page loops the key set twice, once in the
form `__init__` for labels and once in the state builder for initial + states.

Per definition it resolves once and produces the initial value and the
`SettingFieldState`. The resolver and the state policy are classmethods on the
form class, so a page's identity lives in one class instead of a class plus a
function that must agree with it:

| Policy | `UserSettingsForm` | `SiteSettingsForm` |
|---|---|---|
| resolve | `resolve_for_user_with_origin(user, key)` | `resolve_with_origin(key)` |
| initial | only when `source is SettingSource.USER` | always |
| `locked` | `False` | `resolved.locked` |
| `show_source` | `False` (the control names its own inheritance, #381) | default |
| help text | `definition.user_help_text or definition.help_text` | `definition.help_text` |

`live_save` is derived for both: `field_name not in presentations`. A supplied
`FormFieldPresentation` *is* the declaration that something else owns the control,
so the user page's `field_name != "theme"` check disappears while the behaviour
stays identical (that view passes `presentations={"theme": …}`).

`data-reload-after-save` is stamped where `definition.reload_after_save and
live_save`. This reproduces today's split exactly — the site page stamps all four
display settings, the user page stamps three because its `theme` is not
live-save-owned — from one registry fact instead of two hand-maintained tuples.

### 4. Views

`games/views/settings.py` keeps `user_settings`, `admin_settings`,
`export_admin_settings_ini`, and `_infra_fields`, dropping from 452 to roughly 200
lines. It re-exports `UserSettingsForm` and `SiteSettingsForm` so `__all__` and
the existing `from games.views.settings import SiteSettingsForm` import keep
working.

`_infra_fields` is untouched — it already loops `SETTINGS_REGISTRY` and is
registry-driven.

## Testing

New `tests/test_settings_form.py`:

1. **Synthetic ninth setting.** `monkeypatch.setitem(SETTINGS_REGISTRY, …)` adds a
   `SettingScope.USER` definition, then `clear_cache()`. Assert both forms grow
   the field with the right class, choices, label, and empty-option text, and
   that both pages produce a `SettingFieldState` for it — with zero form edits.
   Verified viable: the resolver's caches are DB snapshots keyed by setting, not
   definition memos, so a patched key resolves to `DEFAULT` origin correctly.
2. **Pairwise parity.** Form field names equal the derived USER-scope keys in
   registry order, and user/site field classes match pairwise, so the page-size
   divergence cannot come back.

Existing coverage stays green unmodified:
`tests/test_admin_settings_page.py` (field classes, registry choices, the
`data-live-setting-control` / `data-reload-after-save` stamps),
`tests/test_settings_registry.py`, `tests/test_settings_commands.py`,
`e2e/test_settings_ui_kit_e2e.py`.

Gate: full `make check`, including `e2e/`.

## Commits

One PR, three commits, each compiling on its own:

1. **registry** — `SettingWidget` enum, `choices`, `model_queryset`,
   `reload_after_save`, `user_help_text`, `PAGE_SIZE_OPTIONS`, landing-page
   widget drift fix. No behaviour change.
2. **forms** — `games/settings_form.py` with the base form, both subclasses,
   `display_label`, and `form_and_states`; `games/views/settings.py` reduced to
   handlers plus re-exports.
3. **tests** — synthetic-ninth-setting and parity tests.

## Rejected alternatives

- **Shared base class with the eight fields still declared by hand.** Dedups the
  bodies but keeps `_FIELD_KEYS` hand-maintained and leaves the ninth-setting tax
  in place.
- **A `field_factory` callable on `SettingDefinition`.** Maximum flexibility, but
  drags `django.forms` and `games.models.Device` into a module that must stay
  importable from `settings.py`.
- **A separate `SettingsPagePolicy` object beside each form.** Cleaner layering
  in the abstract (a `Form` does not resolve settings), but it recreates the
  exact shape the issue complains about: two objects per page that must agree.
- **Dropping `TypedChoiceField` entirely**, since nothing cleans these forms.
  Honest about today, but deletes a real assertion and re-opens the hole if these
  forms ever gain POST handling.
- **Keeping the `data-reload-after-save` tuples per form.** They encode one fact
  twice and are exactly what drifts silently.

## Follow-ups

None. The one natural candidate — deriving the read-only infrastructure fields
from the registry — is already done.
