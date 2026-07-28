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
2. `SettingDefinition.widget` (`"text"`/`"device"`/`"select"`) has no production
   reader — only `tests/test_settings_registry.py:139` asserts
   `definition.widget == "select"` — and has already drifted:
   `DEFAULT_LANDING_PAGE` declares `widget="text"` while both forms render it as
   a `ChoiceField`.
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
type SettingOption = tuple[object, str]  # e.g. ("cs", "Čeština"), (25, "25")
type QuerysetFactory = Callable[[], "QuerySet"]  # lazy; imports models when called
```

and on `SettingDefinition`:

| Field | Type | Purpose |
|---|---|---|
| `widget` | `SettingWidget \| None` | was `str \| None`; now a `StrEnum` and load-bearing |
| `choices` | `tuple[SettingOption, ...] \| None` | options for `SELECT`; `None` otherwise |
| `model_queryset` | `QuerysetFactory \| None` | options for `MODEL`; called at form-build time |
| `reload_after_save` | `bool = False` | the page shows stale server-rendered output until reloaded |
| `user_help_text` | `str = ""` | help text the personal page shows instead of `help_text` |

`SettingWidget` is a **`StrEnum`** with values `"text"`, `"select"`, `"model"`.
That is load-bearing: `tests/test_settings_registry.py:139` asserts
`definition.widget == "select"`, which stays green because a `StrEnum` member
compares equal to its string value. A plain `Enum` would break it.

`QuerySet` is imported under `if TYPE_CHECKING:` so the module keeps its "safe to
import from `settings.py`" property. The `MODEL` factory does its `games.models`
import inside the callable, matching `_require_existing_device`.

`__post_init__` gains invariants, so a malformed definition fails at import
rather than 500-ing the settings page on first render:

- a `SettingScope.USER` definition must declare a `widget`;
- `SELECT` requires `choices`, `MODEL` requires `model_queryset`, and neither
  may carry the other's companion;
- `reload_after_save=True` requires `ApplyTiming.LIVE` (a RESTART setting cannot
  be fixed by reloading a page, and INFRA is already forced to RESTART).

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

### 2. `games/settings_forms.py`

New module owning the form layer.

**Field construction happens after `super().__init__()`, into `self.fields`.**

```python
class RegistrySettingsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields = {**self._build_fields(), **self.fields}
        apply_primitive_widget_classes(self.fields)
```

This point is load-bearing and was settled empirically:

- Assigning `self.base_fields` *before* `super().__init__()` works at runtime but
  **fails `mypy`** — django-stubs declares `base_fields` as a `ClassVar`, so the
  assignment is `error: Cannot assign to class variable "base_fields" via
  instance [misc]`. Verified against this repo's pinned mypy. It would redden
  `make check`, so it is rejected.
- Assigning `self.fields` after `super()` type-checks clean and renders
  correctly — verified: `initial={"a": 25}` still marks `<option value="25"
  selected>`, the builder-prepended empty option renders, and the control classes
  land.

Because the fields no longer exist when `PrimitiveWidgetsMixin.__init__` would
run, the mixin's stamping loop is extracted into a module-level
`apply_primitive_widget_classes(fields)` in `games/forms.py`; the mixin becomes a
one-line caller of it and every existing form is unaffected.
`RegistrySettingsForm` calls the function directly and does not use the mixin.
The merge order `{**built, **self.fields}` keeps registry order first while
leaving any field a future subclass declares intact rather than silently
dropping it.

`_build_fields()` walks `SETTINGS_REGISTRY` in order, skips anything that is not
`SettingScope.USER`, uses `definition.key.lower()` as the field name, and sets
`field.label = definition.label` (the job the deleted `_FIELD_KEYS` loop did).
Field class by kind:

| `widget` | Field |
|---|---|
| `TEXT` | `forms.CharField(required=False)` |
| `SELECT`, `cast is not None` | `forms.TypedChoiceField(coerce=definition.cast, empty_value=None)` |
| `SELECT` otherwise | `forms.ChoiceField(required=False)` |
| `MODEL` | `forms.ModelChoiceField(queryset=definition.model_queryset())` |

The typed/untyped split keys on `cast is not None`, not `cast is int`: a future
`SELECT` setting with a `float` or custom cast would otherwise silently fall back
to a plain `ChoiceField` — the exact class divergence this table exists to
prevent. `default_page_size` becomes a `TypedChoiceField` on **both** pages from
one registry fact, so the existing admin-page assertion keeps passing and the
divergence cannot return.

`DEFAULT_CURRENCY`'s `max_length=3` and
`{"x-mask": "aaa", "x-data": "", "class": "uppercase"}` are **not** generic TEXT
facts — after `DEFAULT_LANDING_PAGE` moves to `SELECT`, currency is the only TEXT
setting, and those attributes are currency-shaped. A ninth TEXT setting built
from the generic branch would silently render as a three-character,
letters-only-masked, uppercased box. So the TEXT branch produces a plain
`CharField`, and the currency specifics live in an explicit keyed override in
this module:

```python
_TEXT_FIELD_OVERRIDES: Final[dict[SettingKey, TextFieldOverride]] = {...}
```

A new TEXT setting needs no entry; it gets a correct plain input.

The empty option is **not** part of `definition.choices`. The builder prepends it
using the single overridable hook:

```python
def empty_label(self, definition: SettingDefinition) -> str: ...
```

`SELECT` fields get `("", empty_label(definition))` prepended, `MODEL` fields get
it as `empty_label=`, and `TEXT` fields get it as a `placeholder` (an empty box
means inherit; clearing PATCHes `value: null`).

Subclasses, both constructed with no arguments:

- `UserSettingsForm` — `empty_label` resolves the **site** value for the key
  (`resolve_with_origin`, no user needed) and returns
  `f"Use site default ({display_label(definition, value)})"`.
- `SiteSettingsForm` — returns `"Use configured default"`.

The user identity belongs to `form_and_states` (§3), not to the form: the form
needs only site values for its labels. Neither subclass takes a `user=`
parameter.

Accepted rendering change: the site page's `default_currency` input gains
`placeholder="Use configured default"`, which it does not have today. It is
invisible in normal use (that page always seeds the resolved value) and accurate
when an admin clears the box.

`display_label(definition, value) -> str` replaces `_device_label`,
`_landing_page_label`, `_format_locale_label`, and `_datetime_format_label`:

- `SELECT` — look the value up in `definition.choices`. On a miss, return the
  **first choice's label** if the value is `None`, otherwise `str(value)`.
- `MODEL` — `str(device)` for the row named by the pk, else `"No device"` (value
  is `None`, a `bool`, or a dangling id). One explicit branch replacing
  `_device_label`.
- `TEXT` — `str(value)`, matching today's `str(site_currency)`.

The `None`-vs-`str(value)` split is what makes this byte-exact rather than
approximately right. `DEFAULT_LANDING_PAGE` has `default_factory=lambda: None`,
so its unset case must produce `"Sessions"` (the first choice) — and it does.
`DISPLAY_TIME_ZONE` and `DEFAULT_PAGE_SIZE` are rendered with a bare `str(value)`
today, not a choices lookup; a blanket first-choice fallback would have turned an
out-of-choices timezone into a confident `"Africa/Abidjan"`, so they keep
`str(value)`. One unreachable delta remains: an invalid `DATE_FORMAT_LOCALE`
would print raw instead of `"English (United States)"`. Every resolve layer runs
the validator, so that value cannot exist.

Deleted by this module: `_FIELD_KEYS`, the eight `default_*_label` kwargs on
`UserSettingsForm.__init__`, the four `_*_label` helpers, `_PERSONAL_CURRENCY_HELP`
(moves into the registry as `user_help_text`), and both per-form
`data-reload-after-save` tuples.

### 3. One state builder returning one bundle

```python
class SettingsPageData(NamedTuple):
    form: RegistrySettingsForm
    states: dict[str, SettingFieldState]
    presentations: dict[str, FormFieldPresentation]
```

`form_and_states(form_class, *, user=None, presentations=None) -> SettingsPageData`
replaces `_form_and_states` and `_site_form_and_states`. It makes a **single**
pass over the USER-scope definitions — today each page loops the key set twice,
once in the form `__init__` for labels and once in the state builder for initial
plus states.

Returning the presentations in the bundle matters: the view hands the same object
to `LiveSettingFields`, so the mapping that decides `live_save` and the mapping
that renders cannot disagree. Threading it to two consumers separately would
recreate, in miniature, the two-sites-must-agree disease this issue exists to
kill.

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

`live_save` is derived for both, from the presentation's **`decorate_control`**:

```python
live_save = (presentation is None) or (presentation.decorate_control is None)
```

Keying on mere presence of a presentation would be wrong. `FormFieldPresentation`
is a general row decorator — `prepare_setting_fields` merges `label_extra` and
`after_control` onto fields that keep `live_save=True`
(`tests/test_settings_ui_kit.py:97-120`). Only `decorate_control` replaces the
control itself, which is what "something else owns the save" actually means. Under
the presence rule, a page that later added a cosmetic hint to a field would
silently stop saving it. The behaviour today is unchanged: the user view passes
`decorate_control=ThemeSetting` for `theme` and nothing else, so the existing
`field_name != "theme"` check is reproduced exactly.

`data-reload-after-save` is stamped where `definition.reload_after_save and
live_save`, as a **widget attribute on the control** (matching how
`data-live-setting-control` is stamped in `common/components/settings_kit.py`),
because `tests/test_admin_settings_page.py` asserts it on the opening control
tag. This reproduces today's split exactly — the site page stamps all four
display settings, the user page stamps three because its `theme` is not
live-save-owned — from one registry fact instead of two hand-maintained tuples.

### 4. Views

`games/views/settings.py` keeps `user_settings`, `admin_settings`,
`export_admin_settings_ini`, and `_infra_fields`, dropping from 452 to roughly
200 lines. `_infra_fields` is untouched — it already loops `SETTINGS_REGISTRY`.

No compatibility re-export. `UserSettingsForm` and `SiteSettingsForm` move to
`games/settings_forms.py` and the one external importer —
`tests/test_admin_settings_page.py:279` — is updated. A shim for a single test
import is churn avoidance, which this project deliberately rejects.

## Testing

New `tests/test_settings_forms.py`:

1. **Synthetic ninth setting.** `monkeypatch.setitem(SETTINGS_REGISTRY, …)` adds a
   `SettingScope.USER` definition, then `clear_cache()`. Assert both forms grow
   the field with the right class, choices, label, and empty-option text, and
   that both pages produce a `SettingFieldState` for it — with zero form edits.
   Verified viable: the resolver's caches are DB snapshots keyed by setting, not
   definition memos, and an unmapped key falls through
   `USER_PREFERENCE_FIELD_BY_KEY` into the `extra_preferences` JSON bag, so no
   model column or migration is involved.
2. **Pairwise parity.** Form field names equal the derived USER-scope keys in
   registry order, and user/site field classes match pairwise, so the page-size
   divergence cannot come back.
3. **Malformed definitions are rejected at construction** — a USER definition
   with no `widget`, a `SELECT` with no `choices`, a `MODEL` with no
   `model_queryset`, and `reload_after_save=True` on a `RESTART` setting each
   raise from `__post_init__`.

Both form tests need the `db` fixture. `UserSettingsForm` now resolves site
values (and a `Device` row) during `__init__` for its empty labels, so unlike
today's `SiteSettingsForm()` it cannot be constructed without database access.

Existing coverage stays green unmodified except for the one moved import:
`tests/test_admin_settings_page.py` (field classes, registry choices, the
`data-live-setting-control` / `data-reload-after-save` stamps, the 7-empty-option
count), `tests/test_settings_page.py` (the user page's datetime reload stamp, the
exact `"Use site default (…)"` labels, the currency placeholder),
`tests/test_settings_registry.py` (`widget == "select"`),
`tests/test_settings_commands.py`, `tests/test_settings_ui_kit.py`,
`e2e/test_settings_page_e2e.py`, `e2e/test_settings_ui_kit_e2e.py`.

Gate: full `make check`, including `e2e/`.

## Commits

One PR, three commits, each compiling on its own:

1. **registry** — `SettingWidget` enum, `choices`, `model_queryset`,
   `reload_after_save`, `user_help_text`, `PAGE_SIZE_OPTIONS`, the
   `__post_init__` invariants, landing-page widget drift fix. No behaviour
   change.
2. **forms** — `apply_primitive_widget_classes` extracted in `games/forms.py`;
   `games/settings_forms.py` with the base form, both subclasses,
   `display_label`, and `form_and_states`; `games/views/settings.py` reduced to
   handlers; the one test import updated.
3. **tests** — synthetic-ninth-setting, parity, and registry-invariant tests.

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
  forms ever gain POST handling. Note it protects a future, not a present —
  the coercion is dead code either way.
- **Keeping the `data-reload-after-save` tuples per form.** They encode one fact
  twice and are exactly what drifts silently.
- **`user_help_text` as a keyed override in `UserSettingsForm` instead of a
  registry field.** Argued in review: it will be `""` on seven of eight entries,
  and it encodes the current two-page information architecture into the config
  layer. Rejected because the string states a *scope semantic* — a personal
  currency affects only your purchase entry, while FX and reporting keep using
  the site value — which is a fact about the setting, not page copy. A keyed
  override would also reintroduce the hardcoded-key check this design removes.

## Follow-ups

None. The one natural candidate — deriving the read-only infrastructure fields
from the registry — is already done.
