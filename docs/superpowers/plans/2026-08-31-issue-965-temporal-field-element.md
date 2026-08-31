# Temporal Field Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn #964's native temporal control into an ordinary date field that expands inline to month, year, decade, range and unknown, and posts exactly what the server already parses.

**Architecture:** The server keeps rendering #964's controls, and adds — hidden — a segmented date per endpoint, five script-only checkboxes, and a live region. `<temporal-field>` upgrades that markup: it hides the number inputs and the shape select, shows the segments, and derives the shape from what a person fills. A partial-date codec drives the shared segment engine through a scratch input, and each commit fans the segment buffers out to #964's named inputs. Remove the script and #964's control stands untouched.

**Tech Stack:** Django 6 components (`common/components/`), custom elements + TypeScript (`ts/elements/`), the segment engine in `ts/elements/date-field-core.ts`, vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-965-temporal-field-element-design.md` (Task 9 corrects three paragraphs of it; read the corrections in that task before trusting those paragraphs).

**One task is temporary.** Task 4 adds a `DEBUG`-gated preview page so the field
can be looked at while the branch is open — nothing hosts one until #969. Task
9 removes it. The branch must not merge with that page still in it.

## Global Constraints

- **Everything through `make`.** Never `uv run`, `pytest`, `pnpm` or `npx` directly. Focused runs: `make test ARGS="tests/test_temporal_form_field.py -x"`, `make test-e2e ARGS="-k temporal"`, `make test-ts` (whole vitest suite, no ARGS).
- **Verification gate:** the full `make check` must be green before the branch is done. `make check-fast` while iterating.
- Python 3.14, Node ≥ 26. A `SyntaxError` in `except A, B:` means the wrong interpreter, not broken code.
- **It enhances; it does not replace.** Every value #964 stores must still round-trip with scripting off. No new posted input name: the element writes only into the thirteen names `timetracker/temporal.py` already defines.
- **Comments are at most seven words** and say why, not what.
- **Complete words in identifiers.** `element` not `el`, `value` not `v`, `removeButton` not `removeBtn`.
- **Build UI with Python components** — `Div()`, `Span()`, `Fieldset()`, htpy form `Builder(attr=…)[children]`. No HTML strings, no inline Alpine.
- **`hidden` is a UA rule with no weight.** A Tailwind `display` utility (`flex`, `block`, `grid`, `inline-flex`) beats it. **Nothing this element toggles with the `hidden` attribute may carry a `display` utility** — put the layout class on an inner wrapper instead. There is no `[hidden]` rule in `games/static/base.css`; do not add one.
- **Refused words** — `make vale` enforces `docs/vocabulary.md` over docs and code comments.
- Commit messages: imperative, no `feat:`/`fix:` prefix, ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Design summary

The collapsed field is one ordinary date box. A year alone, or a month and a
year, needs nothing more: the segments simply stay empty, and #964 derives the
precision from what was filled. Only a decade, a qualifier, or a second
endpoint needs the disclosure.

```
COLLAPSED (default)
  Release date
  ┌────────────────────────┐
  │ DD - MM - YYYY         │
  └────────────────────────┘
  I don't know the exact date

EXPANDED
  Start  ┌──────────────────┐
         │ DD - MM - YYYY   │
         └──────────────────┘
         ☐ Approximate   ☐ Uncertain
         ☐ Whole decade          → snaps the year, the box reads YYYYs
         ☐ No known start        → Until
  ☐ Add an end date              → Range
  End    ┌──────────────────┐
         │ DD - MM - YYYY   │
         └──────────────────┘
         ☐ Approximate   ☐ Uncertain
         ☐ Ongoing, no end date  → Since
```

The shape is never picked from a menu. It is derived:

| Filled | Shape |
|---|---|
| nothing anywhere | `unknown` |
| start only | `date` |
| start and end | `range` |
| start, "Ongoing" checked | `since` |
| end, "No known start" checked | `until` |

The disclosure is a one-way reveal. Nothing collapses back, so no state can
hide behind a closed control; a reload decides the state from what is stored.

## File Structure

| File | Responsibility |
|---|---|
| `ts/elements/temporal-codec.ts` (create) | The partial-date codec and the decade arithmetic. Pure functions, no DOM. |
| `ts/elements/temporal-codec.test.ts` (create) | vitest over the codec. |
| `ts/elements/temporal-field.ts` (create) | The custom element: hide, reveal, bind, fan out, derive, announce. |
| `ts/elements/temporal-field.test.ts` (create) | vitest over the element against hand-built markup. |
| `common/components/temporal_field.py` (modify) | #964's controls plus the hidden enhancement markup. |
| `common/components/custom_elements.py` (modify) | `TemporalFieldProps`, the registration, the builder. |
| `games/forms.py` (modify) | `presentation` on `TemporalWidget` and `TemporalFormField`. |
| `tests/test_temporal_form_field.py` (modify) | The new constructor argument, the media assertion, the enhancement markup. |
| `e2e/test_temporal_field_e2e.py` (create) | A synthetic form page; script on and script off store the same value. |
| `games/views/temporal_field_preview.py` (create, **then remove**) | Task 4's `DEBUG`-gated spot-check page. Task 9 takes it out again. |
| `games/urls.py` (modify, **then revert**) | The `DEBUG`-gated route for that page. |
| `games/views/returns.py` (modify, **then revert**) | That route in `READ_ONLY` and `DEBUG_ONLY`. |
| `docs/superpowers/specs/2026-08-30-issue-965-temporal-field-element-design.md` (modify) | Three corrected paragraphs. |
| `CLAUDE.md` (modify) | The `temporal_field.py` entry now carries a script. |

### The DOM contract

Every hook is a `data-` attribute the server stamps and the element reads.

| Attribute | On | Meaning |
|---|---|---|
| `data-temporal-field` | the inner `role="group"` | the whole control |
| `data-temporal-input="<key>"` | each named control | one of the thirteen posted inputs, keyed by its `TemporalDraftData` key |
| `data-temporal-native` | wrappers around the shape select and the number rows | hidden once the element upgrades |
| `data-temporal-extra` | wrappers around anything only the expanded state shows | hidden while collapsed |
| `data-temporal-segments="<endpoint>"` | the segmented row's wrapper | shown once the element upgrades |
| `data-temporal-scratch="<endpoint>"` | an unnamed hidden input | the codec's value; never posted |
| `data-temporal-part="<part>"` | one segment cell | hidden in decade mode unless it is the year |
| `data-temporal-prefix` | the separator span inside a cell | hidden when its cell leads the row |
| `data-temporal-decade-suffix` | the trailing `s` | shown in decade mode |
| `data-temporal-toggle="<name>"` | the five script-only checkboxes | `whole_decade_start`, `whole_decade_end`, `add_end`, `open_start`, `open_end` |
| `data-temporal-end-group` | the wrapper around the End fieldset | shown when the value has an end |
| `data-temporal-disclosure` | the reveal button | hides itself once used |
| `data-temporal-announcement` | the live region | says the precision when it changes |

---

### Task 1: The partial-date codec

The engine's `dateCodec` encodes `""` for anything short of a whole day. A
temporal field's whole point is the short value, so it needs its own codec:
the longest coarse-first run of filled parts.

**Files:**
- Create: `ts/elements/temporal-codec.ts`
- Test: `ts/elements/temporal-codec.test.ts`

**Interfaces:**
- Consumes: `FieldCodec`, `PartValues` from `./date-field-core.js`.
- Produces:
  - `coarsestPrefix(values: PartValues): string` — `""`, `"1984"`, `"1984-06"` or `"1984-06-22"`.
  - `temporalCodec: FieldCodec`
  - `decadeStart(year: string): string` — `"1982"` → `"1980"`, non-numeric → `""`.

- [ ] **Step 1: Write the failing test**

Create `ts/elements/temporal-codec.test.ts`:

```ts
// @vitest-environment node
import { describe, expect, it } from "vitest";
import { coarsestPrefix, decadeStart, temporalCodec } from "./temporal-codec.js";

describe("coarsestPrefix", () => {
  it("states nothing when no year is filled", () => {
    expect(coarsestPrefix({ year: "", month: "06", day: "22" })).toBe("");
  });

  it("states a year alone", () => {
    expect(coarsestPrefix({ year: "1984", month: "", day: "" })).toBe("1984");
  });

  it("stops at the first part nobody filled", () => {
    expect(coarsestPrefix({ year: "1984", month: "", day: "22" })).toBe("1984");
  });

  it("states a whole day", () => {
    expect(coarsestPrefix({ year: "1984", month: "06", day: "22" })).toBe("1984-06-22");
  });
});

describe("temporalCodec", () => {
  it("encodes a partial date the whole-day codec would drop", () => {
    expect(temporalCodec.encode({ year: "1984", month: "06", day: "" }, false)).toBe(
      "1984-06",
    );
  });

  it("round-trips every precision", () => {
    for (const wire of ["", "1984", "1984-06", "1984-06-22"]) {
      expect(temporalCodec.encode(temporalCodec.decode(wire), false)).toBe(wire);
    }
  });

  it("decodes missing parts as empty", () => {
    expect(temporalCodec.decode("1984")).toEqual({ year: "1984", month: "", day: "" });
  });
});

describe("decadeStart", () => {
  it("snaps a year down to the ten it belongs to", () => {
    expect(decadeStart("1982")).toBe("1980");
    expect(decadeStart("1980")).toBe("1980");
    expect(decadeStart("1989")).toBe("1980");
  });

  it("states nothing for text that is not a year", () => {
    expect(decadeStart("")).toBe("");
    expect(decadeStart("nineteen")).toBe("");
  });
});
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `make test-ts`
Expected: FAIL — cannot resolve `./temporal-codec.js`.

- [ ] **Step 3: Write the codec**

Create `ts/elements/temporal-codec.ts`:

```ts
/**
 * The wire format one temporal endpoint's segments state.
 *
 * `dateCodec` encodes "" for anything short of a whole day, because a date
 * input has one precision. A temporal endpoint has five, so this codec
 * encodes the longest coarse-first run a person filled and ignores the rest.
 * The value it produces is never posted: it lives in an unnamed scratch
 * input and only exists so the shared engine can tell a change from a
 * keystroke that changed nothing.
 */
import type { FieldCodec, PartValues } from "./date-field-core.js";

/** The coarse-first run of filled parts, joined the way EDTF joins them. */
export function coarsestPrefix(values: PartValues): string {
  const year = values.year ?? "";
  const month = values.month ?? "";
  const day = values.day ?? "";
  if (!year) return "";
  if (!month) return year;
  if (!day) return `${year}-${month}`;
  return `${year}-${month}-${day}`;
}

export const temporalCodec: FieldCodec = {
  // `complete` says every segment is full, which no partial date is.
  encode(values) {
    return coarsestPrefix(values);
  },
  decode(value) {
    const pieces = value.split("-");
    return { year: pieces[0] ?? "", month: pieces[1] ?? "", day: pieces[2] ?? "" };
  },
};

/** The year a decade opens on: 1982 belongs to 1980. */
export function decadeStart(year: string): string {
  if (!/^\d+$/.test(year)) return "";
  return String(Math.floor(parseInt(year, 10) / 10) * 10);
}
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/temporal-codec.ts ts/elements/temporal-codec.test.ts
git commit -m "$(cat <<'EOF'
Encode the parts of a date somebody knows

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The enhancement markup

Everything the element needs, rendered by the server and hidden until it
upgrades. Nothing here changes what #964 posts.

**Files:**
- Modify: `common/components/custom_elements.py` (after `DatePickerProps`, around line 239)
- Modify: `common/components/temporal_field.py`
- Modify: `games/forms.py:363` (`TemporalWidget.__init__`), `games/forms.py:411` (`TemporalFormField.__init__`)
- Test: `tests/test_temporal_form_field.py`

**Interfaces:**
- Consumes: `coarsestPrefix` is not used here; this task is server-side only.
- Produces:
  - `TemporalField(*, name, data, label, presentation, input_id="", required=False, invalid=False) -> Node`
  - `TemporalWidget(*, presentation: DateTimePresentation, label: str, attrs=None)`
  - `TemporalFormField(*, presentation: DateTimePresentation, label: str = "Date", **kwargs)`
  - `class TemporalFieldProps(TypedDict): expanded: bool` → `readTemporalFieldProps(el).expanded`
  - The DOM contract table above.

- [ ] **Step 1: Write the failing tests**

In `tests/test_temporal_form_field.py`, add `presentation` to the two helpers
that build a control, then add the new tests. Replace the `markup()` helper and
`test_the_control_carries_no_script`:

```python
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
```

```python
def presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def markup(
    data: TemporalDraftData | None = None,
    *,
    required: bool = False,
    invalid: bool = False,
) -> str:
    node = TemporalField(
        name="release",
        data=data if data is not None else posted(kind="unknown"),
        label="Release date",
        presentation=presentation(),
        input_id="id_release",
        required=required,
        invalid=invalid,
    )
    return str(render(node))


def test_the_script_only_enhances() -> None:
    """Every posted control is here, named, and shown."""
    node = TemporalField(
        name="release",
        data=posted(kind="unknown"),
        label="Release date",
        presentation=presentation(),
        input_id="id_release",
    )
    media = collect_media(node)

    assert media.js == ("dist/elements/temporal-field.js",)
    assert 'name="release-year"' in str(render(node))


def test_the_segments_wait_for_the_script() -> None:
    """Shown before the upgrade, they would be a second date field."""
    html = markup()

    assert '<div data-temporal-segments="start" hidden' in html
    assert '<div data-temporal-segments="end" hidden' in html


def test_a_segment_carries_the_stored_part_zero_padded() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )
    html = markup(data)
    segments = html.split('data-temporal-segments="start"')[1]

    assert 'value="1984" data-date-part="year" data-date-side="start"' in segments
    assert 'value="06" data-date-part="month" data-date-side="start"' in segments
    assert 'value="22" data-date-part="day" data-date-side="start"' in segments


def test_a_stored_decade_renders_its_own_shape() -> None:
    """An upgrade unhides this; it never rebuilds it."""
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("198X")))
    start = markup(data).split('data-temporal-segments="start"')[1]

    assert 'value="1980" data-date-part="year"' in start
    assert '<span data-temporal-part="month" hidden' in start
    assert '<span data-temporal-decade-suffix="">s</span>' in start


def test_each_endpoint_has_an_unnamed_scratch_input() -> None:
    """Named, it would post a fourteenth thing the server cannot read."""
    html = markup()

    assert '<input type="hidden" data-temporal-scratch="start">' in html
    assert "name" not in html.split('data-temporal-scratch="start"')[0].rsplit("<", 1)[1]


def test_every_script_only_toggle_is_rendered_and_nameless() -> None:
    html = markup()

    for toggle in (
        "whole_decade_start",
        "whole_decade_end",
        "add_end",
        "open_start",
        "open_end",
    ):
        assert f'data-temporal-toggle="{toggle}"' in html
    assert html.count('name=""') == 5


def test_the_posted_controls_carry_their_draft_key() -> None:
    """The element addresses them by the key the server reads."""
    html = markup()

    assert 'data-temporal-input="kind"' in html
    assert 'data-temporal-input="start_year"' in html
    assert 'data-temporal-input="end_uncertain"' in html


def test_a_plain_stored_date_needs_no_disclosure() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )

    assert 'expanded="false"' in markup(data)


def test_a_stored_range_opens_expanded() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984/1986")))

    assert 'expanded="true"' in markup(data)


def test_a_stored_qualifier_opens_expanded() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984~")))

    assert 'expanded="true"' in markup(data)


def test_text_a_segment_cannot_hold_keeps_the_native_controls() -> None:
    """Segments take digits. Hiding them would swallow what was typed."""
    html = markup(posted(kind="date", start_year="nineteen"))

    assert "<temporal-field" not in html
    assert 'name="release-year" value="nineteen"' in html


def test_the_control_says_when_its_precision_changes() -> None:
    assert 'data-temporal-announcement="" role="status" aria-live="polite"' in markup()
```

Also update the two direct constructions further down the file:

```python
def test_an_omitted_control_is_reported_as_omitted() -> None:
    widget = TemporalWidget(presentation=presentation(), label="Release date")
```

and every `TemporalFormField(label="Release date", required=False)` becomes
`TemporalFormField(presentation=presentation(), label="Release date", required=False)`,
including the `ReleaseForm` and `RequiredReleaseForm` class bodies and the
`disabled=True` case. Add `from zoneinfo import ZoneInfo` at the top.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `make test ARGS="tests/test_temporal_form_field.py -x"`
Expected: FAIL — `TemporalField() got an unexpected keyword argument 'presentation'`.

- [ ] **Step 3: Register the element**

In `common/components/custom_elements.py`, after the `_DatePicker` line
(around line 239):

```python
class TemporalFieldProps(TypedDict):
    # The stored value needs the precision controls, so open showing them.
    expanded: bool


register_element("temporal-field", "TemporalField", TemporalFieldProps)
_TemporalField = custom_element_builder("temporal-field")
```

- [ ] **Step 4: Rewrite the component**

Replace `common/components/temporal_field.py` with:

```python
"""TemporalField: native controls for a date at any precision.

A person states the parts they know and whether the date is approximate
or uncertain. Nothing here needs a script: the controls are a select,
then four number inputs and two checkboxes per endpoint, and the server
rebuilds the value from what they post.

``ts/elements/temporal-field.ts`` enhances that. It hides the number
inputs and the shape select, shows a segmented date in their place, and
derives the shape from what a person fills. Remove the script and every
control above is still here, still named, and still read the same way.

The precision is never picked from a menu. It is derived from which
parts a person filled, which is why there is no precision control here.

Nothing the element hides carries a Tailwind ``display`` utility: the
``hidden`` attribute is a UA rule and any such class outranks it.
"""

from common.components.core import Node
from common.components.custom_elements import _TemporalField
from common.components.date_range_picker import (
    FIELD_CONTAINER_CLASS,
    date_segment_input,
)
from common.components.elements import (
    Div,
    Fieldset,
    Label,
    Legend,
    Option,
    P,
    Select,
    Span,
)
from common.components.primitives import Checkbox, Input, field_label_id
from common.date_time_presentation import DateTimePresentation
from timetracker.temporal import (
    TEMPORAL_DRAFT_KIND_LABELS,
    TemporalDraftData,
    TemporalDraftKind,
    temporal_input_name,
)

_GROUP_CLASS = "flex flex-col gap-3"
_ENDPOINT_CLASS = "flex flex-col gap-1"
_ROW_CLASS = "flex flex-row flex-wrap items-end gap-3"
_TOGGLE_ROW_CLASS = "flex flex-row flex-wrap items-center gap-3"
_PART_LABEL_CLASS = "flex flex-col gap-1 text-type-label text-heading"
_LEGEND_CLASS = "text-type-label text-body"
_DISCLOSURE_CLASS = (
    "self-start text-type-body text-brand underline underline-offset-2 "
    "cursor-pointer bg-transparent border-0 p-0"
)
_PART_WIDTHS = {"year": 4, "month": 2, "day": 2}


def TemporalField(
    *,
    name: str,
    data: TemporalDraftData,
    label: str,
    presentation: DateTimePresentation,
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """The whole control: a shape, two endpoints, two qualifiers.

    ``input_id`` goes on the kind select, so the form row's
    ``<label for>`` focuses the first control. The container is
    additionally a named ``role="group"``, because the part inputs carry
    their own labels and the row label would otherwise name nothing.

    Text a segment cannot hold keeps the native controls alone: hiding
    them would swallow the characters somebody typed.
    """
    label_id = field_label_id(input_id)
    group = Div(
        role="group",
        aria_labelledby=label_id or None,
        aria_label=None if label_id else label,
        aria_required="true" if required else None,
        aria_invalid="true" if invalid else None,
        data_temporal_field="",
        class_=_GROUP_CLASS,
    )[
        Div(data_temporal_native="")[
            _kind_select(name=name, kind=data["kind"], input_id=input_id)
        ],
        _endpoint_group(
            name=name,
            endpoint="start",
            legend="Start",
            presentation=presentation,
            open_label="No known start",
            open_toggle="open_start",
            year=data["start_year"],
            month=data["start_month"],
            day=data["start_day"],
            decade=data["start_decade"],
            approximate=data["start_approximate"],
            uncertain=data["start_uncertain"],
        ),
        Div(data_temporal_extra="", hidden=True)[
            _script_toggle(toggle="add_end", label="Add an end date")
        ],
        Div(data_temporal_end_group="", hidden=True)[
            _endpoint_group(
                name=name,
                endpoint="end",
                legend="End",
                presentation=presentation,
                open_label="Ongoing, no end date",
                open_toggle="open_end",
                year=data["end_year"],
                month=data["end_month"],
                day=data["end_day"],
                decade=data["end_decade"],
                approximate=data["end_approximate"],
                uncertain=data["end_uncertain"],
            )
        ],
        _disclosure(),
        P(
            data_temporal_announcement="",
            role="status",
            aria_live="polite",
            class_="sr-only",
        ),
    ]
    if not _segments_can_hold(data):
        return group
    return _TemporalField(
        expanded="true" if _needs_precision_controls(data) else "false"
    )[group]


def _needs_precision_controls(data: TemporalDraftData) -> bool:
    """A stored value the one collapsed box cannot state.

    A year, or a month and a year, needs nothing: the finer segments
    simply stay empty and the server derives the precision from that.
    """
    if data["kind"].strip() not in (
        "",
        TemporalDraftKind.DATE.value,
        TemporalDraftKind.UNKNOWN.value,
    ):
        return True
    return any(
        text.strip()
        for text in (
            data["start_decade"],
            data["start_approximate"],
            data["start_uncertain"],
            data["end_year"],
            data["end_month"],
            data["end_day"],
            data["end_decade"],
            data["end_approximate"],
            data["end_uncertain"],
        )
    )


def _segments_can_hold(data: TemporalDraftData) -> bool:
    """Whether every part is digits a segment has room for."""
    parts = (
        (data["start_year"], 4),
        (data["start_month"], 2),
        (data["start_day"], 2),
        (data["start_decade"], 4),
        (data["end_year"], 4),
        (data["end_month"], 2),
        (data["end_day"], 2),
        (data["end_decade"], 4),
    )
    return all(
        not text.strip() or (text.strip().isdigit() and len(text.strip()) <= width)
        for text, width in parts
    )


def _kind_select(*, name: str, kind: str, input_id: str) -> Node:
    # Imported here: games.forms imports this module.
    from games.forms import SELECT_CLASS

    selected = kind.strip() or TemporalDraftKind.UNKNOWN.value
    offered = [draft_kind.value for draft_kind in TEMPORAL_DRAFT_KIND_LABELS]
    options = [
        Option(value=draft_kind.value, selected=draft_kind.value == selected)[text]
        for draft_kind, text in TEMPORAL_DRAFT_KIND_LABELS.items()
    ]
    if selected not in offered:
        # A refused shape echoes back, like a number.
        options.insert(0, Option(value=selected, selected=True)[selected])
    return Select(
        name=temporal_input_name(name, "kind"),
        id_=input_id or None,
        data_temporal_input="kind",
        class_=SELECT_CLASS,
    )[*options]


def _endpoint_group(
    *,
    name: str,
    endpoint: str,
    legend: str,
    presentation: DateTimePresentation,
    open_label: str,
    open_toggle: str,
    year: str,
    month: str,
    day: str,
    decade: str,
    approximate: str,
    uncertain: str,
) -> Node:
    """One end's parts and the two boxes that qualify them.

    The boxes sit inside the endpoint, because the grammar qualifies
    each end on its own. One pair for the whole value could not state
    "1984 to about 1986", and rewrote it on every save.
    """
    return Fieldset(class_=_ENDPOINT_CLASS, data_temporal_endpoint=endpoint)[
        Legend(class_=_LEGEND_CLASS, data_temporal_extra="")[legend],
        Div(data_temporal_native="")[
            Div(class_=_ROW_CLASS)[
                _part_input(
                    name=name,
                    key=f"{endpoint}_year",
                    text=year,
                    label="Year",
                    minimum=1,
                    maximum=9999,
                    step=1,
                ),
                _part_input(
                    name=name,
                    key=f"{endpoint}_month",
                    text=month,
                    label="Month",
                    minimum=1,
                    maximum=12,
                    step=1,
                ),
                _part_input(
                    name=name,
                    key=f"{endpoint}_day",
                    text=day,
                    label="Day",
                    minimum=1,
                    maximum=31,
                    step=1,
                ),
                _part_input(
                    name=name,
                    key=f"{endpoint}_decade",
                    text=decade,
                    label="Decade",
                    minimum=10,
                    maximum=9990,
                    step=10,
                ),
            ]
        ],
        _segment_row(
            endpoint=endpoint,
            presentation=presentation,
            year=year,
            month=month,
            day=day,
            decade=decade,
        ),
        _qualifier_row(
            name=name,
            endpoint=endpoint,
            approximate=approximate,
            uncertain=uncertain,
        ),
        Div(data_temporal_extra="", hidden=True)[
            Div(class_=_TOGGLE_ROW_CLASS)[
                _script_toggle(
                    toggle=f"whole_decade_{endpoint}",
                    label="Whole decade",
                    checked=bool(decade.strip()),
                ),
                _script_toggle(toggle=open_toggle, label=open_label),
            ]
        ],
    ]


def _segment_row(
    *,
    endpoint: str,
    presentation: DateTimePresentation,
    year: str,
    month: str,
    day: str,
    decade: str,
) -> Node:
    """The segmented date the element binds, in its final state.

    A stored decade already shows one year cell and the trailing "s",
    so an upgrade unhides this row rather than rebuilding it.
    """
    whole_decade = bool(decade.strip())
    values = {
        "year": _padded(decade if whole_decade else year, 4),
        "month": "" if whole_decade else _padded(month, 2),
        "day": "" if whole_decade else _padded(day, 2),
    }
    parts = list(presentation.profile.segments_for("date"))
    shown = [part for part in parts if not whole_decade or part.name == "year"]
    cells: list[Node] = []
    for index, part in enumerate(parts):
        prefix = part.segmented.prefix if index > 0 else ""
        children: list[Node] = []
        if prefix:
            children.append(
                Span(data_temporal_prefix="", class_="text-body select-none")[prefix]
            )
        children.append(
            date_segment_input(
                part=part,
                side=endpoint,
                value=values.get(part.name, ""),
                segment_id="",
            )
        )
        # No display utility: the hidden attribute has to win.
        cells.append(
            Span(data_temporal_part=part.name, hidden=part not in shown)[*children]
        )
    return Div(data_temporal_segments=endpoint, hidden=True)[
        Span(class_=FIELD_CONTAINER_CLASS, data_date_field_side=endpoint)[
            Input(type="hidden", data_temporal_scratch=endpoint),
            *cells,
            Span(
                data_temporal_decade_suffix="",
                hidden=not whole_decade,
                class_="text-body select-none",
            )["s"],
        ]
    ]


def _padded(text: str, width: int) -> str:
    """A segment holds digits, right-aligned in its own width."""
    stripped = text.strip()
    return stripped.zfill(width) if stripped.isdigit() else ""


def _part_input(
    *,
    name: str,
    key: str,
    text: str,
    label: str,
    minimum: int,
    maximum: int,
    step: int,
) -> Node:
    """A number input inside its own label. No id needed.

    The browser range is a courtesy, not the rule. The server refuses
    every disagreement itself, so a control the browser lets through is
    answered with a sentence rather than stored.
    """
    from games.forms import INPUT_CLASS

    return Label(class_=_PART_LABEL_CLASS)[
        label,
        Input(
            type="number",
            name=temporal_input_name(name, key),
            value=text,
            min=str(minimum),
            max=str(maximum),
            step=str(step),
            inputmode="numeric",
            data_temporal_input=key,
            class_=INPUT_CLASS,
        ),
    ]


def _qualifier_row(
    *, name: str, endpoint: str, approximate: str, uncertain: str
) -> Node:
    """The two boxes that qualify one end."""
    return Div(data_temporal_extra="", hidden=True)[
        Div(class_=_ROW_CLASS)[
            Checkbox(
                name=temporal_input_name(name, f"{endpoint}_approximate"),
                label="Approximate",
                checked=bool(approximate.strip()),
                value="on",
                data_temporal_input=f"{endpoint}_approximate",
            ),
            Checkbox(
                name=temporal_input_name(name, f"{endpoint}_uncertain"),
                label="Uncertain",
                checked=bool(uncertain.strip()),
                value="on",
                data_temporal_input=f"{endpoint}_uncertain",
            ),
        ]
    ]


def _script_toggle(*, toggle: str, label: str, checked: bool = False) -> Node:
    """A box only the element reads. Nameless, so it never posts."""
    return Checkbox(
        name="",
        label=label,
        checked=checked,
        data_temporal_toggle=toggle,
    )


def _disclosure() -> Node:
    """The one thing the collapsed field offers beyond a date."""
    return Div(hidden=True, data_temporal_disclosure_row="")[
        Element(
            "button",
            [
                ("type", "button"),
                ("data-temporal-disclosure", ""),
                ("aria-expanded", "false"),
                ("class", _DISCLOSURE_CLASS),
            ],
            ["I don't know the exact date"],
        )
    ]
```

Add `Element` to the `common.components.core` import line:

```python
from common.components.core import Element, Node
```

Note `_qualifier_row` is now wrapped in `data-temporal-extra`, which is why the
qualifier boxes are hidden while collapsed but visible with no script.
`_disclosure` is `hidden` server-side: with no script there is nothing to
disclose.

- [ ] **Step 5: Thread the presentation through the widget**

In `games/forms.py`, `TemporalWidget`:

```python
    def __init__(
        self, *, presentation: DateTimePresentation, label: str, attrs=None
    ) -> None:
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label
```

and in its `render()`, pass `presentation=self.presentation` to `TemporalField(...)`.

`TemporalFormField`:

```python
    def __init__(
        self, *, presentation: DateTimePresentation, label: str = "Date", **kwargs
    ) -> None:
        kwargs.setdefault(
            "widget", TemporalWidget(presentation=presentation, label=label)
        )
        kwargs.setdefault("required", False)
        super().__init__(label=label, **kwargs)
```

- [ ] **Step 6: Regenerate the element types and run the tests**

Run: `make gen-element-types && make test ARGS="tests/test_temporal_form_field.py"`
Expected: PASS. `ts/generated/props.ts` gains `TemporalFieldProps` and
`readTemporalFieldProps`; commit that file.

- [ ] **Step 7: Run the fast aggregate**

Run: `make check-fast`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add common/components/temporal_field.py common/components/custom_elements.py \
        games/forms.py tests/test_temporal_form_field.py ts/generated/props.ts
git commit -m "$(cat <<'EOF'
Render the controls a script would show, hidden

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Bind the segments and post what a person types

The collapsed field. No decade, no range, no disclosure yet: type a date, and
the named inputs the server reads say what the segments say.

**Files:**
- Create: `ts/elements/temporal-field.ts`
- Test: `ts/elements/temporal-field.test.ts`

**Interfaces:**
- Consumes: `temporalCodec`, `coarsestPrefix` from `./temporal-codec.js`; `bindSegmentField`, `readSideParts`, `segmentsForSide`, `setSegmentBuffer`, `segmentBuffer` from `./date-field-core.js`; the DOM contract from Task 2.
- Produces: `customElements.define("temporal-field", …)`, and these module-level functions the later tasks extend — `commitEndpoint(host: HTMLElement, endpoint: string): void`, `currentKind(host: HTMLElement): string`, `namedInput(host: HTMLElement, key: string): HTMLInputElement | HTMLSelectElement | null`.

- [ ] **Step 1: Write the failing test**

Create `ts/elements/temporal-field.test.ts`. The fixture mirrors Task 2's
markup in ISO segment order:

```ts
// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import "./temporal-field.js";

const PARTS = ["year", "month", "day"] as const;

function endpointMarkup(endpoint: string, openLabel: string, openToggle: string): string {
  const cells = PARTS.map(
    (part, index) => `
      <span data-temporal-part="${part}">
        ${index > 0 ? '<span data-temporal-prefix="">-</span>' : ""}
        <input data-date-part="${part}" data-date-side="${endpoint}"
               maxlength="${part === "year" ? 4 : 2}" value="">
      </span>`,
  ).join("");
  return `
    <fieldset data-temporal-endpoint="${endpoint}">
      <legend data-temporal-extra="" hidden>${endpoint}</legend>
      <div data-temporal-native="">
        <input data-temporal-input="${endpoint}_year" value="">
        <input data-temporal-input="${endpoint}_month" value="">
        <input data-temporal-input="${endpoint}_day" value="">
        <input data-temporal-input="${endpoint}_decade" value="">
      </div>
      <div data-temporal-segments="${endpoint}" hidden>
        <span data-date-field-side="${endpoint}">
          <input type="hidden" data-temporal-scratch="${endpoint}">
          ${cells}
          <span data-temporal-decade-suffix="" hidden>s</span>
        </span>
      </div>
      <div data-temporal-extra="" hidden>
        <input type="checkbox" data-temporal-input="${endpoint}_approximate">
        <input type="checkbox" data-temporal-input="${endpoint}_uncertain">
        <input type="checkbox" data-temporal-toggle="whole_decade_${endpoint}">
        <input type="checkbox" data-temporal-toggle="${openToggle}" aria-label="${openLabel}">
      </div>
    </fieldset>`;
}

function mount(expanded = "false"): HTMLElement {
  document.body.innerHTML = `
    <temporal-field expanded="${expanded}">
      <div data-temporal-field="">
        <div data-temporal-native="">
          <select data-temporal-input="kind">
            <option value="date">Date</option>
            <option value="range">Range</option>
            <option value="since">Since</option>
            <option value="until">Until</option>
            <option value="unknown" selected>Unknown</option>
          </select>
        </div>
        ${endpointMarkup("start", "No known start", "open_start")}
        <div data-temporal-extra="" hidden>
          <input type="checkbox" data-temporal-toggle="add_end">
        </div>
        <div data-temporal-end-group="" hidden>
          ${endpointMarkup("end", "Ongoing, no end date", "open_end")}
        </div>
        <div hidden data-temporal-disclosure-row="">
          <button type="button" data-temporal-disclosure="" aria-expanded="false">
            I don't know the exact date
          </button>
        </div>
        <p data-temporal-announcement="" role="status" aria-live="polite"></p>
      </div>
    </temporal-field>`;
  return document.querySelector("temporal-field")!;
}

function segment(host: HTMLElement, endpoint: string, part: string): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(
    `input[data-date-part="${part}"][data-date-side="${endpoint}"]`,
  )!;
}

function type(host: HTMLElement, endpoint: string, part: string, digits: string): void {
  const target = segment(host, endpoint, part);
  target.focus();
  for (const digit of digits) {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: digit, bubbles: true }));
  }
}

function named(host: HTMLElement, key: string): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(`[data-temporal-input="${key}"]`)!;
}

describe("temporal-field", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("swaps the number inputs for the segments", () => {
    const host = mount();

    expect(host.querySelector('[data-temporal-segments="start"]')!.hasAttribute("hidden")).toBe(
      false,
    );
    host.querySelectorAll("[data-temporal-native]").forEach((wrapper) => {
      expect(wrapper.hasAttribute("hidden")).toBe(true);
    });
  });

  it("offers the disclosure once it is the only way to say more", () => {
    const host = mount();

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("keeps the extras closed until somebody asks", () => {
    const host = mount();

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(true);
    });
  });

  it("writes a typed year into the input the server reads", () => {
    const host = mount();

    type(host, "start", "year", "1984");

    expect(named(host, "start_year").value).toBe("1984");
    expect(named(host, "kind").value).toBe("date");
  });

  it("writes a whole typed day", () => {
    const host = mount();

    type(host, "start", "year", "1984");
    type(host, "start", "month", "06");
    type(host, "start", "day", "22");

    expect(named(host, "start_month").value).toBe("06");
    expect(named(host, "start_day").value).toBe("22");
  });

  it("clears a part no coarser part can carry", () => {
    const host = mount();

    type(host, "start", "year", "1984");
    type(host, "start", "day", "22");

    expect(segment(host, "start", "day").value).toBe("");
    expect(named(host, "start_day").value).toBe("");
  });

  it("says unknown while nothing is filled", () => {
    const host = mount();

    expect(named(host, "kind").value).toBe("unknown");
  });
});
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `make test-ts`
Expected: FAIL — cannot resolve `./temporal-field.js`.

- [ ] **Step 3: Write the element**

Create `ts/elements/temporal-field.ts`:

```ts
/**
 * TemporalField — the browser half of a date at any precision.
 *
 * The server renders every control (common/components/temporal_field.py):
 * a shape select, four number inputs and two checkboxes per endpoint, and
 * — hidden — a segmented date, five nameless toggles and a live region.
 * This element hides the first set, shows the second, and derives the
 * shape from what a person fills. With no script the first set stands and
 * stores the same value.
 *
 * The segments ride the shared engine (date-field-core.ts) through a
 * partial-date codec. Its value goes to an unnamed scratch input, never to
 * the wire: every commit reads the segment buffers and writes them out to
 * the named inputs the server already parses.
 */
import {
  bindSegmentField,
  readSideParts,
  segmentBuffer,
  segmentsForSide,
  setSegmentBuffer,
} from "./date-field-core.js";
import { coarsestPrefix, temporalCodec } from "./temporal-codec.js";

const ENDPOINTS = ["start", "end"] as const;

export function namedInput(
  host: HTMLElement,
  key: string,
): HTMLInputElement | HTMLSelectElement | null {
  return host.querySelector<HTMLInputElement | HTMLSelectElement>(
    `[data-temporal-input="${key}"]`,
  );
}

function setNamed(host: HTMLElement, key: string, value: string): void {
  const control = namedInput(host, key);
  if (control) control.value = value;
}

function scratchInput(host: HTMLElement, endpoint: string): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>(
    `input[data-temporal-scratch="${endpoint}"]`,
  );
}

/** Clear a part no coarser part can carry. */
function enforceGrowth(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  const stale = !values.year ? ["month", "day"] : !values.month ? ["day"] : [];
  segmentsForSide(host, endpoint).forEach((segment) => {
    const part = segment.dataset.datePart ?? "";
    if (stale.includes(part) && segmentBuffer(segment)) setSegmentBuffer(segment, "");
  });
}

function endpointHasValue(host: HTMLElement, endpoint: string): boolean {
  return coarsestPrefix(readSideParts(host, endpoint).values) !== "";
}

export function currentKind(host: HTMLElement): string {
  const start = endpointHasValue(host, "start");
  const end = endpointHasValue(host, "end");
  if (!start && !end) return "unknown";
  return start ? "date" : "unknown";
}

function writeNamedParts(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  setNamed(host, `${endpoint}_year`, values.year ?? "");
  setNamed(host, `${endpoint}_month`, values.month ?? "");
  setNamed(host, `${endpoint}_day`, values.day ?? "");
}

export function commitEndpoint(host: HTMLElement, endpoint: string): void {
  enforceGrowth(host, endpoint);
  ENDPOINTS.forEach((each) => writeNamedParts(host, each));
  setNamed(host, "kind", currentKind(host));
}

function show(element: Element | null, visible: boolean): void {
  element?.toggleAttribute("hidden", !visible);
}

function setExpanded(host: HTMLElement, expanded: boolean): void {
  host
    .querySelectorAll("[data-temporal-extra]")
    .forEach((extra) => show(extra, expanded));
  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.setAttribute("aria-expanded", String(expanded));
  show(host.querySelector("[data-temporal-disclosure-row]"), !expanded);
}

function initField(host: HTMLElement): void {
  host.querySelectorAll("[data-temporal-native]").forEach((wrapper) => {
    show(wrapper, false);
  });
  ENDPOINTS.forEach((endpoint) => {
    show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), true);
  });

  bindSegmentField({
    picker: host,
    field: host.querySelector<HTMLElement>("[data-temporal-field]")!,
    resolveHidden: (endpoint) => scratchInput(host, endpoint),
    onCommit: (endpoint) => commitEndpoint(host, endpoint),
    codec: temporalCodec,
  });

  // The codec ignores a part the value cannot state, so that keystroke
  // changes no scratch value and onCommit stays silent. This clears it.
  host.addEventListener("keyup", (event) => {
    const segment = (event.target as HTMLElement | null)?.closest<HTMLInputElement>(
      "input[data-date-part]",
    );
    if (segment) commitEndpoint(host, segment.dataset.dateSide ?? "start");
  });

  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.addEventListener("click", () => setExpanded(host, true));

  setExpanded(host, host.getAttribute("expanded") === "true");
}

class TemporalFieldElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    initField(this);
  }
}

customElements.define("temporal-field", TemporalFieldElement);
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/temporal-field.ts ts/elements/temporal-field.test.ts
git commit -m "$(cat <<'EOF'
Type a date into segments and post its parts

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: A page to look at it on

Nothing hosts a temporal field until #969, so there is nowhere to spot-check
one. This task adds a `DEBUG`-gated page carrying two of them — a plain one and
a stored range — and **Task 9 removes it again before the branch merges**. It
lands here, right after the segments start posting, so every task after it can
be looked at as well as tested.

**Files:**
- Create: `games/views/temporal_field_preview.py`
- Modify: `games/urls.py` (the `_settings_kit_preview_urlpatterns()` block at the tail)
- Modify: `games/views/returns.py` (`READ_ONLY` and `DEBUG_ONLY`)
- Test: `tests/test_returns_classification.py` (already written; it must stay green)

**Interfaces:**
- Consumes: `TemporalFormField(presentation=…, label=…)` from Task 2; `date_time_presentation_for_request` from `common/date_time_presentation.py`.
- Produces: the route `games:temporal_field_preview` at `/tracker/temporal-field-preview/`. Nothing later depends on it; Task 9 takes it away.

- [ ] **Step 1: Write the view**

Create `games/views/temporal_field_preview.py`:

```python
"""Developer-only page for spot-checking the #965 temporal field.

Nothing hosts a temporal field until #969, so there is nowhere to look
at one. This page carries two: a plain field and a stored range. It is
routed only when DEBUG was true at import time, and it goes away with
the branch that added it.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse

from common.components import ContentContainer, ControlButton, Div, Form, FormFields
from common.components.primitives import P, PageHeading
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from games.forms import TemporalFormField
from timetracker.temporal import TemporalValue


class TemporalPreviewForm(forms.Form):
    """One collapsed field and one that opens showing its range."""

    def __init__(self, *args, presentation, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["released"] = TemporalFormField(
            presentation=presentation, label="Release date"
        )
        self.fields["supported"] = TemporalFormField(
            presentation=presentation, label="Support window"
        )


@login_required
def temporal_field_preview(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    initial = {"supported": TemporalValue.parse("1984/1986~")}
    form = TemporalPreviewForm(
        request.POST or None, presentation=presentation, initial=initial
    )
    stored: list[str] = []
    if request.method == "POST" and form.is_valid():
        stored = [
            f"{name}: {value!r} renders as {value}" if value else f"{name}: nothing"
            for name, value in form.cleaned_data.items()
        ]

    return render_page(
        request,
        ContentContainer(class_="flex flex-col gap-6")[
            PageHeading("Temporal field preview"),
            Form(method="post")[
                FormFields(form),
                ControlButton(type="submit", color="blue")["Save"],
            ],
            Div(class_="flex flex-col gap-1")[*[P()[line] for line in stored]],
        ],
        title="Temporal field preview",
    )
```

`PageHeading` takes its children positionally and `ContentContainer` takes them
via `[]`; `games/views/settings_kit_preview.py` is the working example of the
same page shape if anything else here does not line up.

- [ ] **Step 2: Route it, only under DEBUG**

In `games/urls.py`, the tail already has a `DEBUG`-gated block for the settings
kit preview. Add a second one beside it:

```python
def _temporal_field_preview_urlpatterns() -> list:
    """Routed only under DEBUG. Removed with the #965 branch."""
    if not settings.DEBUG:
        return []
    from games.views import temporal_field_preview

    return [
        path(
            "temporal-field-preview/",
            temporal_field_preview.temporal_field_preview,
            name="temporal_field_preview",
        ),
    ]


urlpatterns += _temporal_field_preview_urlpatterns()
```

- [ ] **Step 3: Classify the route**

In `games/views/returns.py`, add `"games:temporal_field_preview"` to **both**
`READ_ONLY` (it renders and never redirects) and `DEBUG_ONLY` (it is not routed
when DEBUG is off, and the guard subtracts that set).

- [ ] **Step 4: Run the guard**

Run: `make test ARGS="tests/test_returns_classification.py"`
Expected: PASS. A red run here means the route is in one set and not the other.

- [ ] **Step 5: Look at it**

Run: `make devlogin` once, then `make dev`, and open
`http://localhost:8000/tracker/temporal-field-preview/`.

Expect: "Release date" is one collapsed date box with "I don't know the exact
date" beneath it. "Support window" opens already expanded, with 1984 in the
start, 1986 in the end, and only the **end**'s Approximate box ticked. Type a
date, save, and the page prints what was stored.

Tasks 5 through 8 each add something visible here — the range toggle, the
decade box, the open ends — so reload after each.

- [ ] **Step 6: Commit**

```bash
git add games/views/temporal_field_preview.py games/urls.py games/views/returns.py
git commit -m "$(cat <<'EOF'
Add a debug page for looking at the field

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The disclosure and the second endpoint

Expanding reveals the qualifier boxes and the "Add an end date" toggle;
checking it reveals the End field and makes the shape a range.

**Files:**
- Modify: `ts/elements/temporal-field.ts`
- Test: `ts/elements/temporal-field.test.ts`

**Interfaces:**
- Consumes: `commitEndpoint`, `currentKind`, `setExpanded`, `show`, `toggleBox` from Task 3.
- Produces: `isToggled(host: HTMLElement, toggle: string): boolean`, and `currentKind` now returns `"range"`.

- [ ] **Step 1: Write the failing test**

Append to `ts/elements/temporal-field.test.ts`, inside the `describe`, and add
the helper above it:

```ts
function toggle(host: HTMLElement, name: string): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(`[data-temporal-toggle="${name}"]`)!;
}

function check(host: HTMLElement, name: string, checked = true): void {
  const box = toggle(host, name);
  box.checked = checked;
  box.dispatchEvent(new Event("change", { bubbles: true }));
}
```

```ts
  it("reveals the extras when somebody says they do not know", () => {
    const host = mount();

    host.querySelector<HTMLButtonElement>("[data-temporal-disclosure]")!.click();

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(false);
    });
    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("opens already expanded when the stored value needs it", () => {
    const host = mount("true");

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
    expect(toggle(host, "add_end").closest("[data-temporal-extra]")!.hasAttribute("hidden")).toBe(
      false,
    );
  });

  it("keeps the end field away until somebody adds one", () => {
    const host = mount("true");

    expect(host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden")).toBe(
      true,
    );

    check(host, "add_end");

    expect(host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden")).toBe(
      false,
    );
  });

  it("becomes a range once both ends say something", () => {
    const host = mount("true");
    check(host, "add_end");

    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    expect(named(host, "kind").value).toBe("range");
    expect(named(host, "end_year").value).toBe("1986");
  });

  it("forgets an end nobody wants any more", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "add_end", false);

    expect(named(host, "end_year").value).toBe("");
    expect(named(host, "kind").value).toBe("date");
  });
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `make test-ts`
Expected: FAIL — the end group stays hidden and `kind` reads `date`.

- [ ] **Step 3: Extend the element**

In `ts/elements/temporal-field.ts`, add the toggle reader and clearing helper
above `currentKind`:

```ts
export function isToggled(host: HTMLElement, toggle: string): boolean {
  return (
    host.querySelector<HTMLInputElement>(`[data-temporal-toggle="${toggle}"]`)
      ?.checked ?? false
  );
}

/** Empty one end, so a shape that never reads it posts nothing. */
function clearEndpoint(host: HTMLElement, endpoint: string): void {
  segmentsForSide(host, endpoint).forEach((segment) => setSegmentBuffer(segment, ""));
  const scratch = scratchInput(host, endpoint);
  if (scratch) scratch.value = "";
}
```

Replace `currentKind`:

```ts
export function currentKind(host: HTMLElement): string {
  const start = endpointHasValue(host, "start");
  const end = endpointHasValue(host, "end");
  if (!start && !end) return "unknown";
  if (isToggled(host, "add_end")) return "range";
  return start ? "date" : "unknown";
}
```

Add the toggle wiring inside `initField`, above the disclosure listener:

```ts
  function syncEndGroup(): void {
    const wanted = isToggled(host, "add_end");
    show(host.querySelector("[data-temporal-end-group]"), wanted);
    if (!wanted) clearEndpoint(host, "end");
    commitEndpoint(host, "end");
  }

  toggleBox(host, "add_end")?.addEventListener("change", syncEndGroup);
```

and the accessor beside `scratchInput`:

```ts
function toggleBox(host: HTMLElement, toggle: string): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>(`[data-temporal-toggle="${toggle}"]`);
}
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/temporal-field.ts ts/elements/temporal-field.test.ts
git commit -m "$(cat <<'EOF'
Grow a second endpoint when somebody asks for one

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Whole decade

A decade is ten years: 1980 through 1989. Checking the box snaps the typed year
down to the ten it belongs to, drops the finer cells, and makes the box read
`YYYYs`. Unchecking restores what was typed.

**Files:**
- Modify: `ts/elements/temporal-field.ts`
- Test: `ts/elements/temporal-field.test.ts`

**Interfaces:**
- Consumes: `decadeStart` from `./temporal-codec.js`; `isToggled`, `commitEndpoint` from Tasks 3 and 5.
- Produces: `writeNamedParts` now routes the year to `{endpoint}_decade` in decade mode.

- [ ] **Step 1: Write the failing test**

Append inside the `describe`:

```ts
  it("snaps the typed year down to the ten it belongs to", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    expect(segment(host, "start", "year").value).toBe("1980");
    expect(named(host, "start_decade").value).toBe("1980");
    expect(named(host, "start_year").value).toBe("");
  });

  it("shows one cell and the trailing letter", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    const cell = (part: string) =>
      host.querySelector(
        `[data-temporal-endpoint="start"] [data-temporal-part="${part}"]`,
      )!;
    expect(cell("month").hasAttribute("hidden")).toBe(true);
    expect(cell("day").hasAttribute("hidden")).toBe(true);
    expect(
      host
        .querySelector('[data-temporal-endpoint="start"] [data-temporal-decade-suffix]')!
        .hasAttribute("hidden"),
    ).toBe(false);
  });

  it("hides the separator the leading cell no longer needs", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    const prefixes = host.querySelectorAll(
      '[data-temporal-endpoint="start"] [data-temporal-part"]:not([hidden]) [data-temporal-prefix]',
    );
    prefixes.forEach((prefix) => expect(prefix.hasAttribute("hidden")).toBe(true));
  });

  it("gives back the year somebody actually typed", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");
    check(host, "whole_decade_start");

    check(host, "whole_decade_start", false);

    expect(segment(host, "start", "year").value).toBe("1982");
    expect(named(host, "start_year").value).toBe("1982");
    expect(named(host, "start_decade").value).toBe("");
  });

  it("keeps snapping a year typed while the box is checked", () => {
    const host = mount("true");
    check(host, "whole_decade_start");

    type(host, "start", "year", "1975");

    expect(named(host, "start_decade").value).toBe("1970");
  });
```

Note the third test's selector has a typo to fix while writing it:
`[data-temporal-part]:not([hidden])`.

- [ ] **Step 2: Run the test and watch it fail**

Run: `make test-ts`
Expected: FAIL — `start_decade` stays empty.

- [ ] **Step 3: Extend the element**

Import `decadeStart`:

```ts
import { coarsestPrefix, decadeStart, temporalCodec } from "./temporal-codec.js";
```

Add, above `writeNamedParts`:

```ts
/** What a person typed before the decade box swallowed it. */
const typedYears = new WeakMap<HTMLElement, Record<string, string>>();

function rememberYear(host: HTMLElement, endpoint: string, year: string): void {
  const remembered = typedYears.get(host) ?? {};
  remembered[endpoint] = year;
  typedYears.set(host, remembered);
}

function endpointPart(host: HTMLElement, endpoint: string, part: string): Element | null {
  return host.querySelector(
    `[data-temporal-endpoint="${endpoint}"] [data-temporal-part="${part}"]`,
  );
}

/** One cell, one glyph: the box reads YYYYs and states ten years. */
function paintDecade(host: HTMLElement, endpoint: string, whole: boolean): void {
  ["month", "day"].forEach((part) => show(endpointPart(host, endpoint, part), !whole));
  const cells = Array.from(
    host.querySelectorAll(`[data-temporal-endpoint="${endpoint}"] [data-temporal-part]`),
  ).filter((cell) => !cell.hasAttribute("hidden"));
  cells.forEach((cell, index) => {
    show(cell.querySelector("[data-temporal-prefix]"), index > 0);
  });
  show(
    host.querySelector(
      `[data-temporal-endpoint="${endpoint}"] [data-temporal-decade-suffix]`,
    ),
    whole,
  );
}

function snapYearToDecade(host: HTMLElement, endpoint: string): void {
  const yearSegment = segmentsForSide(host, endpoint).find(
    (segment) => segment.dataset.datePart === "year",
  );
  if (!yearSegment) return;
  const buffer = segmentBuffer(yearSegment);
  if (buffer.length !== 4) return;
  const snapped = decadeStart(buffer);
  if (snapped && snapped !== buffer) setSegmentBuffer(yearSegment, snapped);
}
```

Rewrite `writeNamedParts` and extend `enforceGrowth`:

```ts
function writeNamedParts(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  const whole = isToggled(host, `whole_decade_${endpoint}`);
  setNamed(host, `${endpoint}_year`, whole ? "" : (values.year ?? ""));
  setNamed(host, `${endpoint}_month`, whole ? "" : (values.month ?? ""));
  setNamed(host, `${endpoint}_day`, whole ? "" : (values.day ?? ""));
  setNamed(host, `${endpoint}_decade`, whole ? decadeStart(values.year ?? "") : "");
}
```

```ts
export function commitEndpoint(host: HTMLElement, endpoint: string): void {
  if (isToggled(host, `whole_decade_${endpoint}`)) snapYearToDecade(host, endpoint);
  enforceGrowth(host, endpoint);
  ENDPOINTS.forEach((each) => writeNamedParts(host, each));
  setNamed(host, "kind", currentKind(host));
}
```

Wire the two boxes inside `initField`, beside the `add_end` listener:

```ts
  ENDPOINTS.forEach((endpoint) => {
    toggleBox(host, `whole_decade_${endpoint}`)?.addEventListener("change", () => {
      const whole = isToggled(host, `whole_decade_${endpoint}`);
      const yearSegment = segmentsForSide(host, endpoint).find(
        (segment) => segment.dataset.datePart === "year",
      );
      if (whole) {
        rememberYear(host, endpoint, segmentBuffer(yearSegment!));
      } else if (yearSegment) {
        setSegmentBuffer(yearSegment, typedYears.get(host)?.[endpoint] ?? "");
      }
      paintDecade(host, endpoint, whole);
      commitEndpoint(host, endpoint);
    });
    paintDecade(host, endpoint, isToggled(host, `whole_decade_${endpoint}`));
  });
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/temporal-field.ts ts/elements/temporal-field.test.ts
git commit -m "$(cat <<'EOF'
Say a whole decade in one box

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: The open ends and the announcement

"No known start" and "Ongoing, no end date" are the two open shapes. Each
empties the end it opens, because the server refuses a part the shape never
reads. The live region says what the precision became.

**Files:**
- Modify: `ts/elements/temporal-field.ts`
- Test: `ts/elements/temporal-field.test.ts`

**Interfaces:**
- Consumes: `isToggled`, `clearEndpoint`, `commitEndpoint`, `currentKind`.
- Produces: `precisionSentence(host: HTMLElement): string`; `currentKind` now returns `"since"` and `"until"`.

- [ ] **Step 1: Write the failing test**

Append inside the `describe`:

```ts
  it("opens the end and calls it since", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "open_end");

    expect(named(host, "kind").value).toBe("since");
    expect(named(host, "end_year").value).toBe("");
  });

  it("opens the start and calls it until", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "open_start");

    expect(named(host, "kind").value).toBe("until");
    expect(named(host, "start_year").value).toBe("");
  });

  it("brings the end along when the start opens", () => {
    const host = mount("true");

    check(host, "open_start");

    expect(toggle(host, "add_end").checked).toBe(true);
    expect(host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden")).toBe(
      false,
    );
  });

  it("refuses to open both ends at once", () => {
    const host = mount("true");
    check(host, "add_end");

    check(host, "open_end");
    check(host, "open_start");

    expect(toggle(host, "open_end").checked).toBe(false);
  });

  it("says the precision it arrived at", () => {
    const host = mount("true");
    const region = host.querySelector("[data-temporal-announcement]")!;

    type(host, "start", "year", "1984");
    expect(region.textContent).toBe("Year precision");

    type(host, "start", "month", "06");
    expect(region.textContent).toBe("Month precision");

    check(host, "whole_decade_start");
    expect(region.textContent).toBe("Decade precision");
  });

  it("says nothing while nothing changed", () => {
    const host = mount("true");
    const region = host.querySelector("[data-temporal-announcement]")!;

    expect(region.textContent).toBe("");
  });
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `make test-ts`
Expected: FAIL — `kind` reads `range` and the region stays empty.

- [ ] **Step 3: Extend the element**

Replace `currentKind`:

```ts
export function currentKind(host: HTMLElement): string {
  const start = endpointHasValue(host, "start");
  const end = endpointHasValue(host, "end");
  if (!start && !end) return "unknown";
  if (isToggled(host, "open_start")) return "until";
  if (isToggled(host, "open_end")) return "since";
  if (isToggled(host, "add_end")) return "range";
  return start ? "date" : "unknown";
}
```

Add the sentence builder above `commitEndpoint`:

```ts
function endpointSentence(host: HTMLElement, endpoint: string): string {
  if (isToggled(host, `whole_decade_${endpoint}`)) return "Decade precision";
  const { values } = readSideParts(host, endpoint);
  if (values.day) return "Day precision";
  if (values.month) return "Month precision";
  if (values.year) return "Year precision";
  return "No date";
}

/** What a screen reader hears when the precision moves. */
export function precisionSentence(host: HTMLElement): string {
  const kind = currentKind(host);
  if (kind === "unknown") return "Unknown date";
  if (kind === "until") return `Until ${endpointSentence(host, "end").toLowerCase()}`;
  if (kind === "since") return `Since ${endpointSentence(host, "start").toLowerCase()}`;
  if (kind === "range") {
    return `Range, ${endpointSentence(host, "start").toLowerCase()} to ${endpointSentence(
      host,
      "end",
    ).toLowerCase()}`;
  }
  return endpointSentence(host, "start");
}

function announce(host: HTMLElement): void {
  const region = host.querySelector("[data-temporal-announcement]");
  if (!region) return;
  const sentence = precisionSentence(host);
  // Repeating it on every keystroke would drown the field out.
  if (region.textContent !== sentence) region.textContent = sentence;
}
```

Append `announce(host)` as the last line of `commitEndpoint`. Because the
region starts empty and a fresh field is `Unknown date`, seed it on connect —
in `initField`, after `setExpanded`:

```ts
  const region = host.querySelector("[data-temporal-announcement]");
  if (region) region.textContent = "";
```

Wire the two open toggles inside the `ENDPOINTS.forEach` block in `initField`:

```ts
  const OPEN_TOGGLES: Record<string, string> = {
    open_start: "start",
    open_end: "end",
  };
  Object.entries(OPEN_TOGGLES).forEach(([toggle, endpoint]) => {
    toggleBox(host, toggle)?.addEventListener("change", () => {
      if (!isToggled(host, toggle)) {
        commitEndpoint(host, endpoint);
        return;
      }
      // An open end needs the other end to say something.
      const other = toggle === "open_start" ? "open_end" : "open_start";
      const otherBox = toggleBox(host, other);
      if (otherBox?.checked) {
        otherBox.checked = false;
        otherBox.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const addEnd = toggleBox(host, "add_end");
      if (addEnd && !addEnd.checked) {
        addEnd.checked = true;
        addEnd.dispatchEvent(new Event("change", { bubbles: true }));
      }
      clearEndpoint(host, endpoint);
      show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), false);
      commitEndpoint(host, endpoint);
    });
  });
```

and re-show a closed end's segments when its toggle clears — replace the early
return above with:

```ts
      if (!isToggled(host, toggle)) {
        show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), true);
        commitEndpoint(host, endpoint);
        return;
      }
```

`syncEndGroup` must not wipe the start when `open_start` unchecks `add_end`; it
already only clears `end`, which is correct.

- [ ] **Step 4: Run the test and watch it pass**

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 5: Run the fast aggregate**

Run: `make check-fast`
Expected: green. Fix any `tsc` complaint from `make ts-check` here.

- [ ] **Step 6: Commit**

```bash
git add ts/elements/temporal-field.ts ts/elements/temporal-field.test.ts
git commit -m "$(cat <<'EOF'
Open one end of a range and say so

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: The browser round trip

No production page hosts a temporal field until #969, so the test builds its
own — the `e2e/test_date_picker_e2e.py` pattern. What matters is that the two
paths store the same value.

**Files:**
- Create: `e2e/test_temporal_field_e2e.py`

**Interfaces:**
- Consumes: `TemporalFormField(presentation=…, label=…)`, the DOM contract, `date_time_format_profile`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `e2e/test_temporal_field_e2e.py`:

```python
"""The temporal field in a real browser, with the script and without it.

No page hosts one until #969, so this mounts a synthetic form. The
assertion that matters is the last one: both paths store the same value.
"""

from zoneinfo import ZoneInfo

from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from common.components import ControlButton, Form, FormFields
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.layout import render_page
from django import forms
from games.forms import TemporalFormField


def _presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


class ReleaseForm(forms.Form):
    released = TemporalFormField(presentation=_presentation(), label="Release date")


@csrf_exempt
def temporal_page_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReleaseForm(data=request.POST)
        stored = str(form.cleaned_data["released"]) if form.is_valid() else "refused"
        return HttpResponse(f'<p id="stored">{stored}</p>')
    return render_page(
        request,
        Form(method="post")[
            FormFields(ReleaseForm()),
            ControlButton(type="submit")["Save"],
        ],
        title="Temporal harness",
    )


urlpatterns = [path("test-temporal/", temporal_page_view)]


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_a_typed_day_stores_as_a_day(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("19840622")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984-06-22"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_the_keyboard_alone_reaches_a_decade(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("1982")
    page.click("[data-temporal-disclosure]")
    page.check("[data-temporal-toggle='whole_decade_start']")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "198X"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_a_range_reaches_both_ends(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("1984")
    page.click("[data-temporal-disclosure]")
    page.check("[data-temporal-toggle='add_end']")
    page.click("[data-date-part='year'][data-date-side='end']")
    page.keyboard.type("1986")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984/1986"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_the_same_value_stores_with_no_script(live_server, browser):
    """The script enhances. Without it the native controls stand."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(f"{live_server.url}/test-temporal/")

    assert page.is_visible("[data-temporal-input='start_year']")
    assert page.is_hidden("[data-temporal-segments='start']")

    page.select_option("[data-temporal-input='kind']", "date")
    page.fill("[data-temporal-input='start_year']", "1984")
    page.fill("[data-temporal-input='start_month']", "6")
    page.fill("[data-temporal-input='start_day']", "22")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984-06-22"
    context.close()
```

- [ ] **Step 2: Run the test and watch it fail or pass**

Run: `make ts && make test-e2e ARGS="-k temporal"`
Expected: the four tests run. Anything red is a real gap — fix the element or
the markup, not the test's expectation, unless the expectation is wrong about
the grammar (check `timetracker/temporal.py` for what a shape stores).

- [ ] **Step 3: Commit**

```bash
git add e2e/test_temporal_field_e2e.py
git commit -m "$(cat <<'EOF'
Prove a browser stores what the form says

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: The docs sweep and the page's removal

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-issue-965-temporal-field-element-design.md`
- Modify: `CLAUDE.md`
- Remove: `docs/superpowers/plans/2026-08-31-issue-965-temporal-field-element.md`

- [ ] **Step 1: Correct the spec's three wrong paragraphs**

The spec was written before three things were checked. Rewrite them.

**"How the field grows"** — the spec says the field starts as a bare year box
and grows a segment at a time. It does not. Replace that paragraph with:

> The collapsed field is one ordinary date box. A year alone, or a month and a
> year, needs nothing more: the finer segments stay empty and the server
> derives the precision from that. Clearing a coarser part clears every finer
> part, so no value states a month with no year.
>
> "I don't know the exact date" reveals the rest: the two qualifier boxes per
> endpoint, a "Whole decade" box, "No known start", "Add an end date", and
> behind that an End field with its own qualifiers and "Ongoing, no end date".
> The reveal is one-way, so nothing hides behind a closed control; a reload
> decides the state from what is stored.
>
> The shape is never picked from a menu. Nothing filled is unknown; a start
> alone is a date; both ends is a range; a deliberately open end is since, and
> an open start is until. Each open box empties the end it opens, because the
> server refuses a part the shape never reads.

**The qualifier paragraph** — the spec says a range toggle "copies the
qualifiers" to the second endpoint. That is the exact rewrite #964's review
removed. Replace with:

> Each endpoint keeps its own pair of boxes and nothing is ever copied between
> them. One pair for the whole value could not state "1984 to about 1986", and
> it rewrote a stored `1984/1986~` as `1984~/1986~` on the next save of a
> record nobody edited.

**The codec sentence** — the spec says the codec "writes the parts to the named
inputs of #964". A `FieldCodec` is a `PartValues ↔ string` translator with no
DOM. Replace with:

> The codec encodes the coarse-first run of filled parts into an unnamed
> scratch input, which is never posted and exists only so the shared engine can
> tell a change from a keystroke that changed nothing. Each commit reads the
> segment buffers and writes them out to the named inputs of #964.

Add a line under "Tests": the field also announces its precision through a
polite live region, which the element updates only when the sentence changes.

- [ ] **Step 2: Correct CLAUDE.md**

In the `common/components/` list, the `temporal_field.py` entry says it
"carries **no** `Media` on purpose". That is no longer true. Replace that
sentence with:

> Since #965 it carries the `<temporal-field>` element's `Media`, which only
> enhances: the element hides the number inputs and the shape select, shows a
> segmented date, and derives the shape from what a person fills. Text a
> segment cannot hold keeps the native controls alone. Nothing the element
> toggles with `hidden` carries a Tailwind `display` utility, which would
> outrank the UA rule.

- [ ] **Step 3: Lint the prose**

Run: `make vale`
Expected: no errors. Warnings that are not about the domain sense of a refused
word are fine.

- [ ] **Step 4: Take the preview page back out**

Task 4's page was scaffolding for spot-checking, not a feature. Remove all
three parts of it and leave nothing behind:

```bash
git rm games/views/temporal_field_preview.py
```

- In `games/urls.py`, remove `_temporal_field_preview_urlpatterns()` and the
  `urlpatterns += …` line that calls it. Leave the settings-kit block alone.
- In `games/views/returns.py`, remove `"games:temporal_field_preview"` from
  both `READ_ONLY` and `DEBUG_ONLY`.

Then prove nothing still names it:

```bash
grep -rn "temporal_field_preview" . --exclude-dir=.git
```

Expected: no output. Any hit is a leftover — remove it before continuing.

- [ ] **Step 5: Drop the plan**

```bash
git rm docs/superpowers/plans/2026-08-31-issue-965-temporal-field-element.md
```

- [ ] **Step 6: Run the gate**

Run: `make check`
Expected: green, including `e2e/`. This is the gate; no hand-picked subset.
`tests/test_returns_classification.py` is the one that catches a half-removed
route.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Say what the element does and take the scaffolding down

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| "It enhances; it does not replace" | 2 (markup), 3 (hide/reveal), 8 (script-off e2e) |
| "The segments come from the existing core" | 1 (codec), 3 (`bindSegmentField`, fan-out) |
| Segment order from `DateTimePresentation` | 2 (`presentation.profile.segments_for("date")`) |
| "How the field grows" (as corrected) | 3 (growth rule), 5 (disclosure, range), 6 (decade), 7 (open ends) |
| "No calendar" | Nothing binds a calendar; `date-picker` is untouched. |
| Tests: vitest + a browser round trip | 1, 3, 5–7 (vitest), 8 (e2e) |
| Boundary: no form field, no presenter, no stored shape | Only `presentation` is added to #964's field; `common/temporal_presentation.py` and `timetracker/temporal.py` are untouched. |
| Acceptance: announces the precision change | 7 |
| Acceptance: initializes on parse and inside an htmx swap | `connectedCallback` fires for both; no `onSwap` needed. |
| (Not from the spec) A place to look at it | 4, removed again by 9 |

**Known cost.** The extras and the native controls are rendered visible and the
element hides them on connect. A deferred module script runs before first
paint in practice — this is what `date-picker`'s `inert` removal already relies
on — so no flash is expected, but it is not a guarantee the DOM gives us. The
alternative (hiding them server-side and unhiding under `<noscript>`) is
styling-at-a-distance, which this codebase refuses.

**Type consistency.** `commitEndpoint`, `currentKind`, `isToggled`,
`clearEndpoint`, `precisionSentence`, `namedInput`, `toggleBox`, `show`,
`paintDecade`, `snapYearToDecade` keep one name and one signature across Tasks
3 and 5–7. The five toggle names (`whole_decade_start`, `whole_decade_end`,
`add_end`, `open_start`, `open_end`) match between Task 2's Python, Tasks 3 and
5–7's TypeScript, and Task 8's Playwright selectors. The thirteen
`data-temporal-input` keys are exactly `TemporalDraftData`'s keys, which is what
`temporal_input_name()` already takes.
