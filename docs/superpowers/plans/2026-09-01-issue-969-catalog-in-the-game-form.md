# The Game form owns the catalog graph — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit Game states a Game's whole Edition and Release graph in one form
and one transaction, and the six standalone catalog routes go away.

**Architecture:** A coordinator object (`CatalogGraphForm`) binds one
`EditionRowForm` per Edition and one `ReleaseRowForm` per Release, using
Django's own form prefix for row naming. It validates the set, then calls the
six verbs in `games/catalog_writes.py` in one `write_and_mirror`, promoting the
marked row before anything is demoted or removed. Rows are drawn as a radio
group of choice cards, and a `<catalog-editor>` custom element clones
server-rendered `<template>` rows to add more.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, the in-house Python
component system, TypeScript custom elements, pytest + pytest-playwright,
vitest.

**Spec:** `docs/superpowers/specs/2026-09-01-issue-969-catalog-in-the-game-form-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a bare
  `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="…"`.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` only while iterating.
- **Never `Edition.objects.create()` or `Release.objects.create()`.** Every
  write goes through a verb in `games/catalog_writes.py`. Test fixtures that
  build stored rows directly are the existing exception and stay as they are.
- **Nothing destroys a record.** `remove()` / `restore()` from
  `games/removal.py`; a confirmation is one `confirm_and_remove()` call.
- **Never write a `GeneratedField`**: `release_date_lower`,
  `release_date_upper`, `release_date_kind`, `release_date_precision`.
- **Build UI with Python components**, htpy form only: static attributes as
  kwargs, children via `[]`. No HTML f-strings, no new inline Alpine.
- **Full words in identifiers**, Python and TypeScript: `element` not `el`,
  `removeButton` not `removeBtn`, `option`/`value` not single letters.
- **Refused words** are enforced by `make vale` over docs *and code comments*:
  a projector **replays**; the row it writes is the **projection**. See
  `docs/vocabulary.md`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest,
  so a view that dispatches a command carries no `@transaction.atomic`.
- **Nothing opens a server-side cursor** — no `QuerySet.iterator()`.
- **Mutating links carry their origin** via `action_url(..., origin=…)`, and a
  new or removed route must be reclassified in `games/views/returns.py`.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `common/components/choice_card.py` | `ChoiceCard` / `ChoiceCardGroup` — a radio group whose options are whole rows |
| `games/catalog_form.py` | `EditionRowForm`, `ReleaseRowForm`, `CatalogGraphForm` — bind, validate, write |
| `games/views/catalog_section.py` | Renders the Editions area and its `<template>` rows |
| `ts/elements/catalog-editor.ts` | Clones a template row, renumbers it, marks a row removed |
| `ts/elements/catalog-editor.test.ts` | vitest over the renumbering and the removal mark |
| `tests/test_choice_card.py` | The component's markup and its scoped `:checked` hook |
| `tests/test_catalog_graph_form.py` | Binding, validation, write order, refusal routing |
| `e2e/test_game_form_catalog_e2e.py` | Add, mark and remove a row in a real browser |

**Modified**

| Path | Change |
|---|---|
| `common/components/temporal_field.py:58` | `text-brand` → `text-fg-brand` |
| `common/components/elements.py` | nothing — `Fieldset`, `Legend`, `Template` already exist |
| `common/components/__init__.py` | Export `ChoiceCard`, `ChoiceCardGroup` |
| `common/components/custom_elements.py` | Register `catalog-editor` |
| `common/components/primitives.py` | `AddForm` grows a `width_class` parameter |
| `games/forms.py` | Delete `EditionForm` and `ReleaseForm`; `UNNAMED_SIBLING_EDITION` moves |
| `games/views/game.py` | `edit_game` hosts the graph; `_releases_section` becomes a read-only table |
| `games/urls.py`, `games/views/returns.py` | Six routes go |
| `games/views/catalog.py` | Removed whole |
| `tests/test_catalog_forms.py`, `tests/test_catalog_write_views.py` | Retargeted / removed |

---

## Task 1: The disclosure reads as a link

**Files:**
- Modify: `common/components/temporal_field.py:58`
- Test: `tests/test_temporal_field_component.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing. This is a leaf fix that unblocks the contrast floor for
  every page hosting a `TemporalField`, including the one this plan builds.

`--color-brand` is blue-600 in dark and `--color-fg-brand` is blue-500
(`node_modules/flowbite/src/themes/default.css:144,178`). The disclosure is the
only *text* use of `text-brand` in the app; the other two are checkbox and
radio accents, where it is not text contrast.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_temporal_field_component.py`:

```python
def test_the_disclosure_uses_the_foreground_brand_token():
    """`text-brand` is a surface; in dark it fails the contrast floor."""
    rendered = str(
        TemporalField(
            name="released",
            data=EMPTY_TEMPORAL_DRAFT_DATA,
            label="Released",
            presentation=PRESENTATION,
        )
    )

    assert "text-fg-brand" in rendered
    assert "text-brand" not in rendered
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_temporal_field_component.py -k foreground_brand"`
Expected: FAIL — `assert 'text-fg-brand' in rendered`.

If the imports in that file differ, mirror whatever the neighbouring tests
already import; do not add a second `PRESENTATION`.

- [ ] **Step 3: Make the change**

In `common/components/temporal_field.py`, line 58:

```python
_DISCLOSURE_CLASS = (
    "self-start text-type-body text-fg-brand underline underline-offset-2 "
    "cursor-pointer bg-transparent border-0 p-0"
)
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_temporal_field_component.py"`
Expected: PASS, and no other test in that file regresses.

- [ ] **Step 5: Commit**

```bash
git add common/components/temporal_field.py tests/test_temporal_field_component.py
git commit -m "Let the temporal disclosure read as a link in the dark"
```

---

## Task 2: A row is a radio option

**Files:**
- Create: `common/components/choice_card.py`
- Modify: `common/components/__init__.py`
- Test: `tests/test_choice_card.py`

**Interfaces:**
- Consumes: `Fieldset`, `Legend`, `Label`, `Radio`, `Div`, `Span` from
  `common.components`
- Produces:
  ```python
  CHOICE_CARD_MARK_ATTRIBUTE: Final[str] = "data-choice-card"


  def ChoiceCardGroup(
      *, name: str, legend: str, columns: str = "", class_: str = ""
  ) -> Element: ...  # single content slot: ChoiceCardGroup(...)[cards]


  def ChoiceCard(
      *,
      name: str,
      value: str,
      label: str,
      checked: bool = False,
      columns: str = "",
      class_: str = "",
  ) -> Element: ...  # single content slot: ChoiceCard(...)[controls]
  ```

`columns` is the container-query track list both the group's header and each
card declare, so the two grids size identically. The caller supplies it because
the tracks are the caller's columns, not the component's.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_choice_card.py`:

```python
"""A whole row is one radio option."""

from common.components import ChoiceCard, ChoiceCardGroup

COLUMNS = "@2xl/edition:grid-cols-[5.5rem_minmax(0,1fr)_auto]"


def test_the_group_is_a_fieldset_naming_itself():
    rendered = str(ChoiceCardGroup(name="in_library", legend="Releases")["x"])

    assert "<fieldset" in rendered
    assert "<legend" in rendered
    assert "sr-only" in rendered
    assert "Releases" in rendered


def test_a_card_puts_its_mark_first():
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Show the Wii release")[
            "controls"
        ]
    )

    assert rendered.index("<input") < rendered.index("controls")


def test_a_card_names_its_mark_for_a_screen_reader():
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Show the Wii release")[""]
    )

    assert 'aria-label="Show the Wii release"' in rendered


def test_the_checked_hook_is_scoped_to_the_card_s_own_mark():
    """A hosted TemporalField holds checked radios of its own."""
    rendered = str(ChoiceCard(name="in_library", value="row-0", label="Wii")[""])

    assert "data-choice-card" in rendered
    assert "has-[[data-choice-card]:checked]:border-brand" in rendered
    assert "has-[:checked]:" not in rendered


def test_a_marked_card_carries_the_checked_attribute():
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Wii", checked=True)[""]
    )

    assert "checked" in rendered


def test_the_group_and_its_card_declare_the_same_tracks():
    """Two grids that must line up cannot size themselves apart."""
    group = str(ChoiceCardGroup(name="m", legend="L", columns=COLUMNS)[""])
    card = str(ChoiceCard(name="m", value="v", label="L", columns=COLUMNS)[""])

    assert COLUMNS in group
    assert COLUMNS in card
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_choice_card.py"`
Expected: FAIL at import — `cannot import name 'ChoiceCard'`.

- [ ] **Step 3: Write the component**

Create `common/components/choice_card.py`:

```python
"""A radio group whose options are whole rows.

The mark is the first thing in a card and the first thing in the DOM,
so a card reads as the option it is rather than as a row with a
control at the end.
"""

from typing import Final

from common.components.core import Children, Element
from common.components.elements import Fieldset, Legend
from common.components.primitives import Div, Label, Radio, Span

#: The card's own mark, told apart from any it hosts.
CHOICE_CARD_MARK_ATTRIBUTE: Final[str] = "data-choice-card"

_CARD_CLASS: Final[str] = (
    "grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 rounded-base border p-3 "
    "border-default-soft bg-neutral-primary items-start "
    # Scoped to the card's own mark. A hosted control may hold checked
    # radios of its own, and a bare :has(:checked) lights every card.
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:border-brand "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:ring-1 "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:ring-brand "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:bg-neutral-secondary-soft"
)

#: A bare radio is 16px wide. The column holds the target instead.
_MARK_CLASS: Final[str] = (
    "col-start-1 row-start-1 flex min-h-control cursor-pointer items-center "
    "gap-2 text-type-label text-heading @2xl/edition:min-w-11"
)


def ChoiceCardGroup(
    *, name: str, legend: str, columns: str = "", class_: str = ""
) -> Element:
    """One group of choice cards, named for whoever cannot see it."""
    return Fieldset(
        class_=f"@container/edition flex flex-col gap-3 {columns} {class_}".strip(),
        data_choice_card_group=name,
    )[Legend(class_="sr-only")[legend], _Slot()]


def ChoiceCard(
    *,
    name: str,
    value: str,
    label: str,
    checked: bool = False,
    columns: str = "",
    class_: str = "",
) -> Element:
    """One option: its mark, then whatever the caller puts in it."""
    mark = Label(class_=_MARK_CLASS)[
        Radio(
            name=name,
            value=value,
            checked=checked,
            aria_label=label,
            **{CHOICE_CARD_MARK_ATTRIBUTE.replace("-", "_"): ""},
        ),
        Span(class_="@2xl/edition:sr-only")[label],
    ]
    return Div(class_=f"{_CARD_CLASS} {columns} {class_}".strip())[mark, _Slot()]
```

`_Slot()` is a placeholder: the two builders take their children through the
single content slot, so write them the way the neighbouring single-slot
builders in `primitives.py` are written (`Modal(id)[content]`). Read
`Modal` before writing these two and copy its slot mechanics exactly; do not
invent a `_Slot` type.

- [ ] **Step 4: Export the two builders**

In `common/components/__init__.py`, add to the imports and to `__all__`:

```python
from common.components.choice_card import (
    CHOICE_CARD_MARK_ATTRIBUTE,
    ChoiceCard,
    ChoiceCardGroup,
)
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_choice_card.py"`
Expected: PASS, all six.

- [ ] **Step 6: Commit**

```bash
git add common/components/choice_card.py common/components/__init__.py tests/test_choice_card.py
git commit -m "Let a whole row be the radio option it stands for"
```

---

## Task 3: The form does not depend on a backfill

**Status: no migration needed. Verified, not assumed.**

**Files:** none.

**Interfaces:**
- Consumes: nothing
- Produces: the guarantee Task 5 binds against — but from the write path,
  not from a migration.

The plan first said "852 of 858 Games hold no Edition" and called for a
backfill. That reading came from the **dev** database, which `make loadsample`
seeds from `games/fixtures/sample.yaml.gz` — a fixture holding 858 Games and
**zero** Editions, generated before the hierarchy existed. It says nothing
about production.

Two facts settle it:

1. **Migration `0020_catalog_hierarchy_backfill` already did this**, for every
   Game, idempotently, and it raises `RuntimeError` on any reconciliation
   mismatch — so a deployment that had not applied it could not have
   succeeded quietly.
2. **`save_private_game` uses `get_or_create`** for both the default Edition
   and its default Release, and `save_legacy_game_form` calls it on every
   Game-form save. Its docstring already states the contract: "the save
   guarantees the graph without touching it." No app path can leave a Game
   without one.

So the only graph-less Games are the ones a stale fixture loads, and writing
a second migration to repair a fixture would be the wrong tool.

**What is real, and where it goes instead:** on a GET of Edit Game for a
graph-less Game, `game_hierarchy` returns nothing and the Editions area would
render empty. Task 5 makes the coordinator synthesize one blank Edition block
holding one blank Release row when storage returns none. That is strictly
better than a migration: it removes the form's dependency on any backfill
having run, and it covers the stale fixture for free.

**What is left undone, and why:** `sample.yaml.gz` should be regenerated so
`make loadsample` seeds a graph. That needs `make anonymize-sample` against a
restored production database, which needs `PROD_SSH_HOST`/`PROD_DB_CONTAINER`.
Recorded here rather than silently skipped.

---

## Task 4: One row, one form

**Files:**
- Create: `games/catalog_form.py`
- Test: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `PrimitiveWidgetsMixin`, `TemporalFormField` from `games/forms.py`;
  `UNNAMED_SIBLING_EDITION` moves here from `games/forms.py:1086`
- Produces:
  ```python
  MARK_FIELD: Final[str] = "in_library"
  EDITION_COUNT_FIELD: Final[str] = "editions-count"


  # edition_prefix(0)          -> "edition-0"
  # release_prefix(0, 1)       -> "edition-0-release-1"
  # release_count_field(0)     -> "edition-0-releases-count"
  def edition_prefix(index: int) -> str: ...
  def release_prefix(edition: int, release: int) -> str: ...
  def release_count_field(edition_index: int) -> str: ...


  class EditionRowForm(PrimitiveWidgetsMixin, forms.Form):
      edition_id: forms.UUIDField  # blank on a new row
      name: forms.CharField
      removed: forms.BooleanField  # hidden; "on" means take it out
      instance: Edition | None  # set by CatalogGraphForm


  class ReleaseRowForm(PrimitiveWidgetsMixin, forms.Form):
      release_id: forms.UUIDField
      platform: forms.ModelChoiceField
      release_date: TemporalFormField
      removed: forms.BooleanField
      instance: Release | None
  ```

**Row naming is Django's own prefix.** `BoundField.html_name` is
`f"{prefix}-{name}"`, and Django hands the widget that prefixed name, so
`TemporalWidget` builds `edition-0-release-1-release_date-year` without a line
changing in `timetracker/temporal.py`. Do not invent a naming scheme.

**Platform is a plain `<select>`, not `SearchSelectWidget`.** A composite widget
carries its `id` on a wrapper `<div>`, and a cloned row would have to rewrite
that id and re-run the element's wiring. `PrimitiveWidgetsMixin` stamps
`SELECT_CLASS` on a native select, which is exactly what the approved mockup
draws. `InitialReleaseForm` keeps its `SearchSelectWidget`; it is not a
repeating row.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_graph_form.py`:

```python
"""What one row of the Game form states, and what it refuses."""

from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_form import (
    EditionRowForm,
    ReleaseRowForm,
    edition_prefix,
    release_prefix,
)
from games.models import Game, Platform
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def test_a_row_names_its_inputs_by_its_index():
    form = EditionRowForm(prefix=edition_prefix(2))

    assert form["name"].html_name == "edition-2-name"


def test_a_release_row_carries_its_index_into_the_temporal_control():
    """The whole point of using Django's prefix rather than our own."""
    form = ReleaseRowForm(prefix=release_prefix(0, 1), presentation=PRESENTATION)

    assert form["release_date"].html_name == "edition-0-release-1-release_date"
    assert (
        temporal_input_name(form["release_date"].html_name, "start_year")
        == "edition-0-release-1-release_date-year"
    )


def test_a_release_row_reads_a_stored_temporal_value_back(owned_library):
    posted = {
        temporal_input_name("edition-0-release-0-release_date", "start_year"): "2020",
        temporal_input_name("edition-0-release-0-release_date", "start_month"): "05",
        temporal_input_name("edition-0-release-0-release_date", "start_day"): "29",
        temporal_input_name("edition-0-release-0-release_date", "kind"): "date",
    }
    form = ReleaseRowForm(
        posted, prefix=release_prefix(0, 0), presentation=PRESENTATION
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["release_date"] == TemporalValue.from_day(2020, 5, 29)


def test_a_row_marked_removed_says_so():
    form = EditionRowForm({"edition-0-removed": "on"}, prefix=edition_prefix(0))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["removed"] is True
```

`TemporalValue.from_day` may not be the real constructor — read
`timetracker/temporal.py:137` and use whatever `TemporalValue` actually offers
for a full day, matching how `tests/test_catalog_forms.py` builds one.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: FAIL at import — no module `games.catalog_form`.

- [ ] **Step 3: Write the two row forms**

Create `games/catalog_form.py` with the module docstring, the four naming
helpers, and the two forms. `ReleaseRowForm.__init__` takes
`presentation: DateTimePresentation` keyword-only and builds its
`TemporalFormField(presentation=presentation, label="Released")` the way
`InitialReleaseForm.__init__` does at `games/forms.py:1063`. Order the fields
so `release_date` sits between `platform` and `removed`
(`self.order_fields(...)`), because a field added in `__init__` otherwise sinks
to the bottom.

`platform` is:

```python
platform = forms.ModelChoiceField(
    queryset=Platform.objects.none(),
    required=False,
    empty_label="Unspecified",
)
```

with the real queryset set in `__init__` from the library:
`Platform.objects.visible_to(library).order_by("name")`.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: PASS, all four.

- [ ] **Step 5: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Bind one edition and one release row by their own index"
```

---

## Task 5: The whole graph binds and validates

**Files:**
- Modify: `games/catalog_form.py`
- Test: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `EditionRowForm`, `ReleaseRowForm` and the naming helpers from
  Task 4; `game_hierarchy` from `games/reads/catalog_hierarchy.py`
- Produces:
  ```python
  NO_MARK: Final[str]
  MARK_ON_A_REMOVED_ROW: Final[str]
  LAST_RELEASE: Final[str]
  LAST_EDITION_IN_FORM: Final[str]
  DUPLICATE_NAME_IN_FORM: Final[str]


  @dataclass(slots=True)
  class EditionBlock:
      form: EditionRowForm
      rows: list[ReleaseRowForm]
      edition: Edition | None  # the stored row, or None for a new one

      @property
      def removed(self) -> bool: ...
      @property
      def surviving(self) -> list[ReleaseRowForm]: ...


  class CatalogGraphForm:
      def __init__(self, data, *, game, library, presentation) -> None: ...

      blocks: list[EditionBlock]
      mark: str  # a release row prefix, or ""
      form_errors: list[str]

      def is_valid(self) -> bool: ...
      def marked(self) -> tuple[EditionBlock, ReleaseRowForm] | None: ...
  ```

**Unbound, the form binds the stored graph.** With `data` of `None`, build one
block per `EditionEntry` from `game_hierarchy(game, library)`, in that order,
each row's `initial` taken from its instance, and `mark` set to the prefix of
the row that is the default Release of the default Edition.

**Storage returning nothing yields one blank block, not zero.** A Game with no
Edition cannot come from the app — `save_private_game` `get_or_create`s the
default graph on every Game-form save — but a stale fixture loads plenty, and
a form that renders an empty Editions area for one is a worse answer than a
form that offers the row it would have. This is what replaces Task 3's
migration; see that task for why.

**Bound, the form binds what was posted.** Read `editions-count` and each
`edition-{i}-releases-count` from `data`; those are the hidden inputs the
element keeps. A count that is missing or not an integer binds zero rows, which
then fails validation with `LAST_EDITION_IN_FORM` rather than raising.

**A posted id is checked against the stored graph.** A row naming an Edition or
Release that `game_hierarchy` did not return is treated as a new row with no
instance — never as a write to somebody else's row. Two-library isolation is
already the verbs' job, and this is the belt.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog_graph_form.py`. Cases:

1. **Unbound, one plain Game** — one block, one row, `mark` is
   `"edition-0-release-0"`.
2. **Unbound, two Editions** — the default Edition's block is first and its
   default Release carries the mark.
3. **Bound with no mark** — invalid, `NO_MARK` in `form_errors`.
4. **Bound with the mark on a row marked removed** — invalid,
   `MARK_ON_A_REMOVED_ROW`.
5. **Bound with every Release row of a surviving Edition removed** — invalid,
   `LAST_RELEASE` on that Edition's form.
5b. **Unbound against a Game holding no Edition** — one block, one row, both
   blank, `mark` on that row.
6. **Bound with every Edition removed** — invalid, `LAST_EDITION_IN_FORM`.
7. **Bound with two surviving unnamed Editions** — invalid,
   `UNNAMED_SIBLING_EDITION` on the second one's `name`.
8. **Bound with two surviving Editions sharing a name** — invalid,
   `DUPLICATE_NAME_IN_FORM` on the second one's `name`, and no verb is called.
9. **Bound naming a Release id from another library's Game** — that row binds
   with `instance is None`.

Write a `posted()` helper in the test module that assembles the flat dict for a
whole graph, so each case reads as a small edit of a valid payload rather than
thirty literal keys:

```python
def posted(*blocks, mark="edition-0-release-0"):
    """The flat POST body a graph of `blocks` submits."""
    ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py -k graph"`
Expected: FAIL — `cannot import name 'CatalogGraphForm'`.

- [ ] **Step 3: Write the binding**

`__init__` builds `self.blocks`. Keep the two paths (`data is None` versus
bound) in two private methods, `_blocks_from_storage()` and
`_blocks_from_post(data)`, so neither has to test `data` inline.

- [ ] **Step 4: Write the validation**

```python
def is_valid(self) -> bool:
    """Every row, and then the things only the set can say."""
    valid = all(block.form.is_valid() for block in self.blocks)
    valid = all(row.is_valid() for block in self.blocks for row in block.rows) and valid
    return self._validate_set() and valid
```

Both `all(...)` calls run to completion before the `and`, deliberately: a
person gets every row's errors at once, not the first one's.

`_validate_set()` checks, in this order: at least one surviving block; each
surviving block has a surviving row; names are unique among surviving blocks
and at most one is unnamed; the mark names a surviving row of a surviving
block. Each failure calls `add_error` on the row form it belongs to, or appends
to `self.form_errors` where it belongs to no single row.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: PASS, all nine plus Task 4's four.

- [ ] **Step 6: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Read a whole posted graph, and say what the set refuses"
```

---

## Task 6: One transaction, promotions first

**Files:**
- Modify: `games/catalog_form.py`
- Test: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `CatalogGraphForm` from Task 5; the six verbs and
  `write_and_mirror`
- Produces: `CatalogGraphForm.save() -> bool`

**The order is not a detail; it is the whole task.** `update_edition` raises
`DEMOTED_EDITION` the moment it sees `stored.is_default and not is_default`, and
`update_release` raises `DEMOTED_RELEASE` the same way. So nothing is ever
explicitly demoted. Instead:

1. **Write the marked block's Edition first**, with `is_default=True`.
   `add_edition` and `update_edition` both call `_clear_default_edition`
   internally, so the old default steps down as a side effect of the promotion.
2. **Write the remaining surviving Editions**, with `is_default=False`. By now
   `_writable_edition` re-reads the row and sees `is_default` already false, so
   the demotion guard does not fire.
3. **Per surviving Edition, write its Releases, winner first.** The winner is
   the marked row if the mark is in this Edition; otherwise the surviving row
   whose instance already holds `is_default`; otherwise the first surviving row.
   Write it with `is_default=True`, then every sibling with `is_default=False`.
   Order matters twice here: `add_release` auto-defaults when the Edition holds
   no default, so writing the winner first stops a later add from taking the
   mark.
4. **Remove the Releases marked removed**, in surviving Editions only.
   `remove_release` refuses a default holding live siblings, and by now the
   only default is the winner, which validation guarantees is not removed.
5. **Remove the Editions marked removed**, last. `remove_edition` refuses the
   default, and step 1 already moved the mark off it.

All five steps run inside one `write_and_mirror(self.game, self._write)`, so
`mirror_legacy_columns` runs once at the end.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog_graph_form.py`, each `@pytest.mark.django_db`:

1. **Moving the mark to a sibling Release** moves `Game.platform` and
   `Game.year_released`, and leaves the old default live and not default.
2. **Moving the mark to a Release under a second Edition** makes that Edition
   the default Edition, that Release its Edition's default, and leaves the
   first Edition still holding its own default Release.
3. **Adding a Release does not move the mark** — `Game.platform` is unchanged.
4. **Removing the Edition that currently holds the default**, with the mark
   moved to another Edition's Release in the same submit, succeeds.
5. **A stored `2024-06-14` survives a save that touches only the Edition name.**
6. **Renaming two Editions past each other** (A→B, B→A) — assert the actual
   behaviour you observe and write the test to it; if the intermediate state
   trips `DUPLICATE_EDITION_NAME`, that refusal is correct and the test asserts
   the refusal, not a success.
7. **Nothing is written twice**: saving an unchanged bound form leaves every
   `pk` and every `is_default` exactly as it was.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py -k save"`
Expected: FAIL — `CatalogGraphForm has no attribute 'save'`.

- [ ] **Step 3: Write `_write` and `save`**

```python
def save(self) -> bool:
    """One transaction over the finished graph."""
    self._blamed = None
    try:
        write_and_mirror(self.game, self._write)
    except ValidationError as refusal:
        self._answer(refusal)
        return False
    return True
```

`_answer` is Task 7; for now let it re-raise, so this task's tests exercise the
happy paths and the ordering only.

Write `_write` as five named private methods, one per step above, called in
order from `_write`. A method per step is what makes the ordering readable and
what lets a failing test point at one of them.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: PASS.

- [ ] **Step 5: Prove the transaction with a deliberate refusal**

Add one more test: a graph whose third Release row duplicates the second's
Platform and date. Assert `save()` raises (Task 7 turns this into `False`), and
that after it the Game, its Editions and the first two Releases are exactly as
they were — no partial write, and `Game.platform` unmoved.

Run: `make test ARGS="tests/test_catalog_graph_form.py -k rollback"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Write the whole graph once, and promote before anything steps down"
```

---

## Task 7: A refusal lands on the row that caused it

**Files:**
- Modify: `games/catalog_form.py`
- Test: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `CatalogGraphForm.save` from Task 6
- Produces: `save()` returns `False` and the sentence is on a row form's
  non-field errors, or in `form_errors` when it belongs to no row.

Every verb raises `ValidationError` carrying one sentence. The transaction must
still roll back, so the blame is recorded on the way out and the exception is
re-raised; `save()` reads the record after `write_and_mirror` has unwound.

- [ ] **Step 1: Write the failing tests**

1. `DUPLICATE_RELEASE` from a colliding third row lands on **that row's**
   `non_field_errors()`, and no other row carries an error.
2. `DEFAULT_RELEASE_HELD` — construct a submit the ordering cannot rescue and
   assert the sentence is on the Release row. If Task 6's ordering makes this
   unreachable, say so in the task report and drop the case rather than
   contriving one.
3. `LEGACY_IDENTITY_TAKEN` from `mirror_legacy_columns` belongs to no row and
   lands in `form_errors`.
4. `FOREIGN_PLATFORM` — a posted Platform id from another library. Note the
   `ModelChoiceField` queryset already refuses it at validation, so this
   asserts the *field* error, not the verb's; write whichever the code actually
   produces.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py -k refus"`
Expected: FAIL — the exception escapes `save()`.

- [ ] **Step 3: Write the blame**

```python
@contextmanager
def _blame(self, form: forms.Form) -> Iterator[None]:
    """A refusal names the row that caused it, then keeps rising.

    The raise has to reach `write_and_mirror` for the transaction to
    unwind, so this records rather than answers.
    """
    try:
        yield
    except ValidationError as refusal:
        self._blamed = (form, refusal.messages[0])
        raise
```

Wrap every verb call in Task 6's five step methods with
`with self._blame(row_or_block_form):`.

```python
def _answer(self, refusal: ValidationError) -> None:
    """Put the sentence where the person who typed it will read it."""
    if self._blamed is None:
        self.form_errors.append(refusal.messages[0])
        return
    form, sentence = self._blamed
    form.add_error(None, sentence)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: PASS, including Task 6's rollback test now asserting
`save() is False` rather than a raise. Update that assertion.

- [ ] **Step 5: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Put a refused write's sentence on the row that stated it"
```

---

## Task 8: Edit Game draws the graph

**Files:**
- Create: `games/views/catalog_section.py`
- Modify: `games/views/game.py:377-410`, `common/components/primitives.py`
  (`AddForm`)
- Test: `tests/test_rendered_pages.py`, `tests/test_game_form_page.py` (create
  if absent)

**Interfaces:**
- Consumes: `ChoiceCard`/`ChoiceCardGroup` (Task 2), `CatalogGraphForm`
  (Tasks 5–7)
- Produces:
  ```python
  EDITION_COLUMNS: Final[str] = (
      "@2xl/edition:grid-cols-[5.5rem_minmax(0,13rem)_minmax(0,1fr)_auto]"
  )


  def editions_area(graph: CatalogGraphForm) -> Node: ...
  ```

`AddForm` currently hardcodes `FORM_MAX_WIDTH_CLASS` (`max-w-xl`). Give it
`width_class: str = FORM_MAX_WIDTH_CLASS` and pass
`"max-w-xl md:max-w-4xl"` from `edit_game`. Every other caller keeps the
default, so no other page moves.

- [ ] **Step 1: Write the failing tests**

```python
def test_edit_game_draws_a_block_per_edition(client, owned_user, ...):
    """A plain Game shows one Edition block and one Release row."""

def test_the_marked_row_is_the_default_release(client, ...):
    """The radio that is checked is the one the games list draws."""

def test_a_narrow_row_labels_every_control(client, ...):
    """Above the breakpoint the labels go sr-only, so they must exist."""
    assert 'class="' in ...  # sr-only, never hidden
    assert "@2xl/edition:sr-only" in body
    assert "@2xl/edition:hidden" not in body

def test_the_page_threads_the_temporal_element(client, ...):
    """A widget renders to text, so its Media never bubbles."""
    assert "dist/elements/temporal-field.js" in body
    assert "dist/elements/catalog-editor.js" in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_game_form_page.py"`
Expected: FAIL — the Editions area is not rendered.

- [ ] **Step 3: Write `editions_area`**

One `ChoiceCardGroup` per Edition block, `columns=EDITION_COLUMNS`, holding:
the Edition name field and its bin, an `aria-hidden` header row, one
`ChoiceCard` per Release row, and the ghost "Add release" button. Below the
blocks, the ghost "Add edition" button. Each control's label uses

```python
NARROW_LABEL_CLASS = f"{_LABEL_CLASS} @2xl/edition:sr-only"
```

with `for_=` pointing at the control's `auto_id`. Read
`/tmp/mockup4.py` if it still exists for the exact class strings; otherwise the
spec's § "The Release row is a choice card" states every rule it must satisfy.

Render each row's controls with `FormFields`-style rows where they fit; where
they do not, place them explicitly with the `@2xl/edition:col-start-N` classes
the mockup uses.

- [ ] **Step 4: Host it in `edit_game`**

```python
graph = CatalogGraphForm(
    request.POST or None, game=game, library=library, presentation=presentation
)
if (
    form.is_valid()
    and graph.is_valid()
    and _saved_game_or_form_error(form) is not None
    and graph.save()
    and record_facts_for_request(...)
):
    return redirect(return_url(request, fallback="games:list_games"))
```

Note the short-circuit: `graph.save()` runs only after the Game itself saved,
because `save_legacy_game_form` guarantees the default graph exists before the
coordinator diffs against it.

Then pass the area in:

```python
AddForm(
    form,
    request=request,
    fields=Fragment(FormFields(form), editions_area(graph)),
    width_class="max-w-xl md:max-w-4xl",
)
```

and add `ModuleScript("dist/elements/catalog-editor.js")` to the `scripts=`
Fragment.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_game_form_page.py tests/test_rendered_pages.py"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/views/catalog_section.py games/views/game.py common/components/primitives.py tests/
git commit -m "Draw a game's editions and releases inside the form that states it"
```

---

## Task 9: A row is added by cloning

**Files:**
- Create: `ts/elements/catalog-editor.ts`, `ts/elements/catalog-editor.test.ts`
- Modify: `common/components/custom_elements.py`,
  `games/views/catalog_section.py`
- Test: vitest, plus one pytest asserting the templates render

**Interfaces:**
- Consumes: the markup from Task 8
- Produces: the element `<catalog-editor>`; two `<template>`s
  (`data-catalog-template="edition"` and `="release"`); the placeholders
  `__edition__` and `__release__`; the hidden count inputs from Task 4.

```python
class CatalogEditorProps(TypedDict):
    pass


register_element("catalog-editor", "CatalogEditor", CatalogEditorProps)
```

An empty props TypedDict is the existing pattern — `DateRangePickerProps` is
one. Nothing crosses the boundary as an attribute here: the element reads the
hidden count inputs, which are the posted truth.

**Removal never renumbers.** The bin sets the row's hidden `removed` input to
`"on"` and hides the row. Renumbering on removal would have to rewrite every
later row's names, ids, `for`s and the mark's value, and one miss silently
writes the wrong row. A re-render numbers afresh; the browser only ever
appends.

- [ ] **Step 1: Write the failing vitest**

Create `ts/elements/catalog-editor.test.ts`. Export the pure functions from the
module and test them directly rather than driving the DOM where you can:

```ts
import { describe, expect, it } from "vitest";
import { renumbered } from "./catalog-editor.js";

describe("renumbered", () => {
  it("rewrites the edition index in every posted name", () => {
    const markup = '<input name="edition-__edition__-name">';
    expect(renumbered(markup, { edition: 3 })).toContain('name="edition-3-name"');
  });

  it("rewrites the release index a temporal control carries", () => {
    const markup =
      '<input name="edition-__edition__-release-__release__-release_date-year">';
    expect(renumbered(markup, { edition: 0, release: 2 })).toContain(
      'name="edition-0-release-2-release_date-year"',
    );
  });

  it("rewrites the id and the label that points at it", () => {
    const markup =
      '<label for="id_edition-__edition__-name"></label>' +
      '<input id="id_edition-__edition__-name">';
    const result = renumbered(markup, { edition: 1 });
    expect(result).toContain('for="id_edition-1-name"');
    expect(result).toContain('id="id_edition-1-name"');
  });

  it("rewrites the mark's value so the new row can be chosen", () => {
    const markup =
      '<input type="radio" name="in_library" ' +
      'value="edition-__edition__-release-__release__">';
    expect(renumbered(markup, { edition: 2, release: 0 })).toContain(
      'value="edition-2-release-0"',
    );
  });

  it("leaves a row that names no placeholder alone", () => {
    const markup = '<input name="editions-count" value="2">';
    expect(renumbered(markup, { edition: 9 })).toBe(markup);
  });
});
```

Then two DOM tests over `connectedCallback`: clicking
`[data-catalog-add="release"]` appends a row and bumps that Edition's count
input; clicking `[data-catalog-remove]` sets `removed` to `"on"` and hides the
row without detaching it.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test-ts`
Expected: FAIL — no module `./catalog-editor.js`.

- [ ] **Step 3: Write the element**

`renumbered(markup, indices)` is a plain string replace of `__edition__` and
`__release__`, exported so the tests above reach it. The class:

```ts
class CatalogEditor extends HTMLElement {
  connectedCallback(): void { ... }
}
customElements.define("catalog-editor", CatalogEditor);
```

`connectedCallback` binds one delegated `click` listener on the element itself,
so a cloned row needs no wiring of its own. Guard against a second
`connectedCallback` (htmx can move a node) with a private field, not a DOM
attribute.

- [ ] **Step 4: Render the templates**

In `games/views/catalog_section.py`, emit both `<template>`s inside the
`<catalog-editor>`: a blank Release row at `__edition__`/`__release__`, and a
blank Edition block holding exactly one blank Release row. Build them with the
same functions that build the live rows, passing the placeholder strings as the
indices, so the two can never drift.

Add a pytest asserting both templates are in the rendered page and that each
contains its placeholder.

- [ ] **Step 5: Run everything JS and watch it pass**

Run: `make ts && make test-ts`
Expected: PASS. `make ts` must run so the compiled module exists for the e2e
task and for local serving.

Run: `make ts-check`
Expected: clean — the codegen'd `props.ts` now knows `CatalogEditor`.

- [ ] **Step 6: Commit**

```bash
git add ts/elements/catalog-editor.ts ts/elements/catalog-editor.test.ts common/components/custom_elements.py games/views/catalog_section.py tests/
git commit -m "Clone a blank row rather than asking the server for one"
```

---

## Task 10: Game detail reads the graph

**Files:**
- Modify: `games/views/game.py:804-845` (`_releases_section`) and the helpers
  at `653-700` it no longer needs
- Test: `tests/test_rendered_pages.py`

**Interfaces:**
- Consumes: `game_hierarchy` (unchanged)
- Produces: nothing new; `_releases_section` keeps its signature so
  `view_game` at line 1107 does not move.

One read-only table in place of the per-Edition blocks:

```text
Editions  3

Name                 Platforms                             Actions
Definitive Edition   Nintendo Switch (2025), Steam (2024)   [Edit]
```

The Platforms cell is a comma list **in one cell**, not a spanning cell:
`StyledTable` guards one cell per column
(`common/components/primitives.py:2540`) because the responsive column-hiding
is position-based. `Actions` is the house column —
`Column("Actions", align="right", priority=3)` — holding one link to Edit Game.

`_reads_plainly()` still gates the whole section. The under-construction notice
gains one sentence: a Platform beyond the first does not reach the games list
yet.

- [ ] **Step 1: Write the failing tests**

1. A Game with two Editions renders one row per Edition, and the Platforms cell
   lists both of one Edition's Releases.
2. The section carries no add, remove, or per-row edit control — only the one
   Edit link per row.
3. A plain Game (one unnamed Edition, one Release) renders no section at all.
4. The notice says a second Platform does not reach the list.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_rendered_pages.py -k edition"`
Expected: FAIL — the old blocks still render.

- [ ] **Step 3: Rewrite the section**

Replace `_releases_section`'s body with the table. Then remove
`_release_actions`, `_edition_controls`, `_add_edition_button` and
`_edition_block` — nothing else calls them. Let the linter tell you; do not
guess.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_rendered_pages.py e2e/ -k game"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/
git commit -m "Let game detail read its editions and send edits to the form"
```

---

## Task 11: The six routes go

**Files:**
- Remove: `games/views/catalog.py`, `tests/test_catalog_write_views.py`
- Modify: `games/urls.py:59-86`, `games/views/returns.py`, `games/forms.py`
  (delete `EditionForm`, `ReleaseForm`), `tests/test_catalog_forms.py`

**Interfaces:**
- Consumes: everything above
- Produces: one write path to the catalog graph.

`games/catalog_writes.py` stays whole — the six verbs are the service, they are
tested by `tests/test_catalog_writes.py`, and #782's importer writes through
them.

- [ ] **Step 1: Run the guard and watch it fail**

Remove the six `path(...)` entries from `games/urls.py` and the six names from
`ORIGIN_AWARE`/`CONFIRMATION` in `games/views/returns.py`.

Run: `make test ARGS="tests/test_returns_classification.py"`
Expected: PASS — the guard fails on a routed name with no bucket, and on a
bucketed name with no route. Removing both halves together keeps it green. If
it goes red, you removed one half.

- [ ] **Step 2: Remove the module and its tests**

```bash
git rm games/views/catalog.py tests/test_catalog_write_views.py
```

- [ ] **Step 3: Move what `tests/test_catalog_forms.py` still covers**

That file tests `EditionForm` and `ReleaseForm`. `UNNAMED_SIBLING_EDITION` and
the duplicate-name rules now live in `games/catalog_form.py`, and Task 5
already covers them. Read the file case by case: move anything Task 5 does not
cover into `tests/test_catalog_graph_form.py`, then `git rm` the file. Do not
delete a case without a replacement.

- [ ] **Step 4: Delete the two page forms**

Remove `EditionForm` (`games/forms.py:1091`) and `ReleaseForm`
(`games/forms.py:1156`). `InitialReleaseForm` **stays** — Add Game still uses
it. Move `UNNAMED_SIBLING_EDITION` (`games/forms.py:1086`) to
`games/catalog_form.py` and fix every import.

- [ ] **Step 5: Sweep for dead references**

Run: `make lint && make typecheck`
Expected: clean. Then grep for the six URL names across the whole tree —
templates and TypeScript included — and fix anything that still builds one:

```bash
grep -rn "add_edition\|edit_edition\|remove_edition\|add_release\|edit_release\|remove_release" --include="*.py" --include="*.ts" --include="*.html" .
```

The verbs in `games/catalog_writes.py` share four of those names. Keep those;
remove only the URL-name strings and the view references.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Take the six standalone catalog routes out of the app"
```

---

## Task 12: The browser agrees

**Files:**
- Create: `e2e/test_game_form_catalog_e2e.py`

**Interfaces:**
- Consumes: everything

**A UI assertion is not a database assertion.** The choice card marks itself on
click before anything is posted. Before reading the ORM, wait on something
server-rendered — the page that loads after the redirect.

- [ ] **Step 1: Write the tests**

1. **Add a Release**: open Edit Game, click Add release, fill the Platform and
   a year in the new row, submit, and assert a second live Release exists under
   that Edition and `Game.platform` has not moved.
2. **Move the mark**: click the second row's radio, submit, assert
   `Game.platform` is now the second row's.
3. **Remove a Release**: click the second row's bin, submit, assert its
   `removed_at` is set and the first row is still default.
4. **Add an Edition**: click Add edition, name it, fill its blank Release row,
   submit, assert two live Editions and that the default did not move.
5. **The refusal shows on the row**: make the second row duplicate the first's
   Platform and date, submit, assert the sentence appears inside that row's
   card and nothing was written.
6. **Narrow and wide**: at 390px every control shows its own label; at 1200px
   the header row shows. Assert on the accessible name in both, via
   `page.get_by_label(...)`, so a label that went `hidden` instead of `sr-only`
   fails here.

- [ ] **Step 2: Run them**

Run: `make test-e2e ARGS="-k catalog"`
Expected: PASS. Run `make ts` first if you have not since Task 9 — e2e serves
the compiled output.

- [ ] **Step 3: Run the gate**

Run: `make check`
Expected: green, the whole thing — lint, format, mypy, vale, ts-check, vitest,
and the entire pytest suite including `e2e/`. Never a hand-picked subset.

- [ ] **Step 4: Commit**

```bash
git add e2e/test_game_form_catalog_e2e.py
git commit -m "Drive the whole graph through a real browser"
```

---

## Self-review notes

Three things a reader should know were checked, and one that was not.

**Spec coverage.** Every section of the spec maps to a task: the mark's
game-wide grammar to Tasks 5–6, the choice card and its scoped `:checked` to
Task 2, the container-query layout and the `sr-only` rule to Task 8, the token
fix to Task 1, `<template>` cloning to Task 9, the read-only detail table to
Task 10, the six routes to Task 11, the backfill to Task 3. The spec's own test
list is distributed across Tasks 5, 6, 7, 10 and 12.

**Task 6 is the risk.** The write ordering is derived from reading
`games/catalog_writes.py`, not from running it. `update_edition` at line 177 and
`update_release` at line 283 refuse a demotion outright, which is why nothing is
demoted and everything is promoted; `_writable_edition` re-reads the row, which
is why a later `is_default=False` is safe. If that reasoning is wrong, it is
wrong in Task 6 and its tests will say so.

**Task 6, case 6 is deliberately open.** Two Editions swapping names may or may
not trip `DUPLICATE_EDITION_NAME` in the intermediate state. The plan says to
assert what the code does rather than to prescribe an answer, because the right
answer depends on whether a rename pass before the promotion pass is worth its
complexity. Decide it there, with the failing test in front of you.

**Not checked: how many Platforms a real library holds.** Task 4 chooses a
plain `<select>` over `SearchSelectWidget` because a composite widget's id has
to survive cloning. If a library holds hundreds of Platforms, that select is
unpleasant and the choice should be revisited — but reverting it later is a
widget swap in one form, not a rework.
