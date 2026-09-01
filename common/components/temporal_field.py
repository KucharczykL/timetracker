"""TemporalField: native controls for a date at any precision.

A person states a shape, the parts they know, and whether the date is
approximate or uncertain. Nothing here needs a script: the controls are
a select, then four number inputs and two checkboxes per endpoint, and
the server rebuilds the value from what they post.

``ts/elements/temporal-field.ts`` enhances that. It hides the number
inputs and the shape select, shows a segmented date in their place, and
derives the shape from what a person fills. Remove the script and every
control above is still here, still named, and still read the same way.

The precision is never picked from a menu. It is derived from which
parts a person filled, which is why there is no precision control here.

Only what a script would use is rendered hidden: the segments, the
nameless toggles, the end-shape radios and the disclosure. Every
posted control is shown, so
with no script a person still reaches both endpoints and both
qualifiers. The element hides what a person does not need yet.

Nothing the element hides carries a Tailwind ``display`` utility: the
``hidden`` attribute is a user-agent rule any such class outranks.
"""

from common.components.core import Element, Node
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
from common.components.primitives import Checkbox, Input, Radio, field_label_id
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
_PART_LABEL_CLASS = "flex flex-col gap-1 text-type-label text-heading"
_LEGEND_CLASS = "text-type-label text-body"
_AFFIX_CLASS = "text-body select-none"
_DISCLOSURE_CLASS = (
    "self-start text-type-body text-fg-brand underline underline-offset-2 "
    "cursor-pointer bg-transparent border-0 p-0"
)
_PART_WIDTHS = {"year": 4, "month": 2, "day": 2, "decade": 4}


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
        _end_shape_group(name=name),
        # Shown: no script means no way to reveal an end date.
        Div(data_temporal_end_group="")[
            _endpoint_group(
                name=name,
                endpoint="end",
                legend="End",
                presentation=presentation,
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
    return all(
        _fits(data[f"{endpoint}_{part}"], width)  # type: ignore[literal-required]
        for endpoint in ("start", "end")
        for part, width in _PART_WIDTHS.items()
    )


def _fits(text: str, width: int) -> bool:
    stripped = text.strip()
    return not stripped or (stripped.isdigit() and len(stripped) <= width)


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
    open_label: str = "",
    open_toggle: str = "",
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

    Only the start offers an open toggle. How a value ends is stated
    once, by the radio group beside it, so the end names no toggle.
    """
    return Fieldset(class_=_ENDPOINT_CLASS, data_temporal_endpoint=endpoint)[
        # Marked in place: a legend wrapped in a div names nothing.
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
            Div(class_=_ROW_CLASS)[
                _script_toggle(
                    toggle=f"whole_decade_{endpoint}",
                    label="Whole decade",
                    checked=bool(decade.strip()),
                ),
                *(
                    [_script_toggle(toggle=open_toggle, label=open_label)]
                    if open_toggle
                    else []
                ),
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
    for part in parts:
        children: list[Node] = []
        # The leading visible cell shows no separator before it.
        if part.segmented.prefix:
            children.append(
                Span(
                    data_temporal_prefix="",
                    hidden=part is shown[0],
                    class_=_AFFIX_CLASS,
                )[part.segmented.prefix]
            )
        children.append(
            date_segment_input(
                part=part, side=endpoint, value=values.get(part.name, "")
            )
        )
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
                class_=_AFFIX_CLASS,
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
    return Div(data_temporal_extra="")[
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


def _script_radio(*, name: str, toggle: str, label: str) -> Node:
    """One of a group only the element reads.

    Radios need a shared name to be one group, so these cannot be
    nameless the way the boxes are. Disabled instead: a disabled
    control never posts, and the element enables the group on connect.
    None is checked here. The element picks the one the stored value
    already states.
    """
    return Radio(
        name=f"{name}-end-shape",
        label=label,
        value=toggle,
        disabled=True,
        data_temporal_toggle=toggle,
    )


def _end_shape_group(*, name: str) -> Node:
    """How the value ends: nothing more, a date, or still going.

    One answer, stated once. Two boxes reaching into each other could
    state "ends on a date" and "still going" at the same time, which
    the grammar has no shape for.
    """
    return Fieldset(class_=_ENDPOINT_CLASS, data_temporal_extra="", hidden=True)[
        Legend(class_=_LEGEND_CLASS)["After the start date"],
        Div(class_=_ROW_CLASS)[
            _script_radio(name=name, toggle="end_none", label="Nothing more"),
            _script_radio(name=name, toggle="end_date", label="Ends on a date"),
            _script_radio(name=name, toggle="end_open", label="Still going"),
        ],
    ]


def _disclosure() -> Node:
    """The one thing the collapsed field offers beyond a date.

    It opens and closes. The element swaps the two labels and takes
    the button away while the extras hold something the collapsed
    field could not state, so closing it never strands an answer.
    """
    return Div(hidden=True, data_temporal_disclosure_row="")[
        Element(
            "button",
            [
                ("type", "button"),
                ("data-temporal-disclosure", ""),
                ("aria-expanded", "false"),
                ("class", _DISCLOSURE_CLASS),
            ],
            [
                Span(data_temporal_disclosure_label="collapsed")[
                    "I don't know the exact date"
                ],
                Span(data_temporal_disclosure_label="expanded", hidden=True)[
                    "I know the exact date"
                ],
            ],
        )
    ]
