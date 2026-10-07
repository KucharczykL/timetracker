# No native select

No page renders a native `<select>`. A check over the whole suite keeps it
so. No application code builds one.

## The check

`tests/html_answers.py` holds `html_answer_faults(path, response, dialog=…)`
and the autouse fixture `html_answers_checked`. `tests/conftest.py` imports
the fixture. The fixture has session scope and patches
`django.test.Client.request`. Every test client is that class: the
pytest-django `client` fixture, `TestCase.client_class`, each bare
`Client()`, and the client that `render_pages` builds. A followed redirect
goes through `request` again, so the check reads the landing page too.

The check reads these answers, at any status:

- An answer whose content type names `html`.
- The `html` of a form-dialog answer. The request carries `X-Form-Dialog`,
  and the JSON answer is an object of `kind` `page`.

The fixture patches `AsyncClient.request` too.

A streamed HTML answer fails the test. Tag and content-type case do not
matter. The check refuses two things:

- A floating panel without `popover="manual"`. A `<dialog>` is not a
  floating panel.
- A `<select>` tag. The path `/tracker/settings-kit-preview/` is exempt.
  That DEBUG-only page shows the native look on purpose. A custom element
  named `select-…` is not a select.

The check cannot reach a view that a test calls through `RequestFactory`.
It cannot reach `e2e/`, which drives a browser, or a Ninja `TestClient`,
which no test uses.

Reason: a list of URLs misses pages. The suite already renders every page.

## The swap

`apply_primitive_widget_classes` gives a picker to a `ChoiceField` that is
on Django's default choice widget, `forms.ChoiceField.widget`. It does not
swap a model or multiple-choice field. A model field states its own picker.
If a model field stays on its default select, the check fails its page.
django-stubs types `ChoiceField.widget` as `Any`, so mypy does not check
this name.

## No native path

- A setting has two widgets: `TEXT` and `SELECT`. `empty_display` names
  the unset value of a `SELECT` setting; another widget refuses it.
  Without it, the first choice's label names the unset value.
- `UnsetWidget` refuses a `forms.Select` with `TypeError`.
  `ts/elements/unset-field.ts` does not look for a `select`.
- `native_control_class` has no select look. The kit page reads
  `SELECT_CLASS`, which `_SELECT_LOOK` builds.
- The node builders have no `Select`, `Option` or `Optgroup`. The kit page
  keeps two private builders for its select.

`forms.Select` does not occur in `games/`, `common/` or `timetracker/`.
Tests build a `forms.Select` as input to the swap.

## Tests

- `tests/test_html_answers.py`:
  - A page with a `ModelChoiceField` on the default widget fails.
  - A `ChoiceField` page passes.
  - The kit path is exempt.
  - A dialog page with a select is a fault. A JSON list is not a dialog
    page.
  - A `<select-list>` element passes.
  - A refused page is checked.
  - A panel without the stamp is a fault.
- `tests/test_unset_field.py`: `UnsetWidget(forms.Select())` raises.
