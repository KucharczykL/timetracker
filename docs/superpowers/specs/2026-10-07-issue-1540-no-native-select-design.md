# No native select can come back (#1540)

## Goal

No page renders a native `<select>`. A suite-wide check keeps it so, and no
application code builds one.

## Decisions

### One check for every HTML answer

`tests/html_answers.py` holds `html_answer_faults(path, response)` and an
autouse, session-scoped fixture `html_answers_checked`, imported by
`tests/conftest.py`. The fixture patches `django.test.Client.request`. Every
client in `tests/` is that class: the pytest-django `client` fixture,
`TestCase.client_class`, and each bare `Client()`. A redirect a test follows
goes through `request` again, so the landing page is checked too.

The check reads every answer whose content type names `html`, at any
status: the bulk confirmation re-renders its Edit form at 400. It also reads
the `html` of a form-dialog answer: a request carrying `X-Form-Dialog`
whose JSON answer is an object of `kind` `page`. A streaming answer
is skipped. It refuses:

- a floating panel without `popover="manual"` (the check that was
  `PanelCheckingClient`, before only on `test_paths_return_200.py`);
- a `<select>` tag (`<select` before a space, `/` or `>`, so a
  `select-…` element passes), except under `/tracker/settings-kit-preview/`, the
  DEBUG-only kit page that shows the native look on purpose.

Reason: a hand-picked URL list misses pages (Library, historical playtime,
Add Platform, the bulk Edit pages). The whole suite already renders them.
A probe run of `make test-fast` with the check on passed: 9898 tests, no
fault.

The two URL-list tests in `tests/test_html_validity.py` and
`PanelCheckingClient` are removed. `e2e/` drives a browser, not this client,
and is out of reach. So is a view a test calls through `RequestFactory`,
and an `AsyncClient` or Ninja `TestClient`, which no test uses today.
`render_pages` builds a `Client` too, so `tests/test_render_pages.py` runs
every read-only page through the check.

### The swap names Django's default choice widget

`_holds_a_plain_select` keeps its rule (a `ChoiceField`, not a model or
multiple choice field, on Django's default choice widget) but names that
widget as `forms.ChoiceField.widget`. The rule does not change; the select
is named once, by Django. A model field left on
its default select is not swapped; the check above fails the page.

### Dead native paths go

- `SettingWidget.MODEL`, `SettingDefinition.model_queryset`,
  `QuerysetFactory` and `_model_label` are removed. No registered setting
  uses them. `empty_display` stays: a SELECT setting reads it.
- `UnsetWidget` no longer joins a `forms.Select`: `_join_of` answers none
  for it, so construction raises `TypeError`. No form wrapped one. Its
  `choices` setter writes a `ChoiceSearchSelectWidget` only, and
  `ts/elements/unset-field.ts` stops looking for a `select`.
- `native_control_class` loses its select branch. `SELECT_CLASS`, which the
  kit page reads, is built from `_SELECT_LOOK` directly. A select or a
  model field left on its default select now gets the input look; the
  check fails its page first.
- The `Select`, `Option` and `Optgroup` node builders leave
  `common/components/elements.py`, `primitives.py` and the exports. The kit
  page builds its one select with `Element`.

After this, `git grep 'forms.Select\b'` over `games/`, `common/` and
`timetracker/` finds nothing. Tests still build a `forms.Select` as the
input the swap acts on.

### Comments and docs

`ts/elements/filter-group.ts` stops calling the operator and quantifier
"plain `<select>`s"; `common/components/filters.py` stops naming native
selects; `docs/database.md` names `default_device` a picker. The #1222 and
#1292 specs name this check, not the removed URL list. CLAUDE.md drops the
MODEL exception and names the check.

## Tests

- `tests/test_html_answers.py`: a page with a `ModelChoiceField` on the
  default widget raises; a `ChoiceField` page passes; the kit path is
  exempt; an unstamped panel is a fault.
- `tests/test_unset_field.py`: `UnsetWidget(forms.Select())` raises; it
  replaces `test_a_native_select_gets_its_choices_and_shape`. The select
  case in `ts/elements/unset-field.test.ts` goes.
- A dialog answer holding a select is a fault; a `<select-x>` tag is not.
- MODEL tests in `tests/test_settings_registry.py` and
  `tests/test_settings_forms.py` are removed with the feature.

## Follow-up issues to file

None.
