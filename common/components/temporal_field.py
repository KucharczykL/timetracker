"""TemporalField: native controls for a date at any precision.

A person states a shape, the parts they know, and whether the date is
approximate or uncertain. Nothing here needs a script: the controls are
a select, four number inputs per endpoint, and two checkboxes, and the
server rebuilds the value from what they post. That is the contract
issue #965's custom element enhances, and removing the script leaves
this working.

The precision is never picked from a menu. It is derived from which
parts a person filled, which is why there is no precision control here.
"""

from common.components.core import Node
from common.components.elements import Div, Label, Option, Select
from common.components.primitives import Checkbox, Input, field_label_id
from timetracker.temporal import (
    TEMPORAL_DRAFT_KIND_LABELS,
    TemporalDraftData,
    TemporalDraftKind,
    temporal_input_name,
)

_GROUP_CLASS = "flex flex-col gap-3"
_ROW_CLASS = "flex flex-row flex-wrap items-end gap-3"
_PART_LABEL_CLASS = "flex flex-col gap-1 text-type-label text-heading"
_LEGEND_CLASS = "text-type-label text-body"


def TemporalField(
    *,
    name: str,
    data: TemporalDraftData,
    label: str,
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """The whole control: a shape, two endpoints, two qualifiers.

    ``input_id`` goes on the kind select, so the form row's
    ``<label for>`` focuses the first control. The container is
    additionally a named ``role="group"``, because the part inputs carry
    their own labels and the row label would otherwise name nothing.
    """
    label_id = field_label_id(input_id)
    return Div(
        role="group",
        aria_labelledby=label_id or None,
        aria_label=None if label_id else label,
        aria_required="true" if required else None,
        aria_invalid="true" if invalid else None,
        data_temporal_field="",
        class_=_GROUP_CLASS,
    )[
        _kind_select(name=name, kind=data["kind"], input_id=input_id),
        _endpoint_row(
            name=name,
            endpoint="start",
            legend="Start",
            year=data["start_year"],
            month=data["start_month"],
            day=data["start_day"],
            decade=data["start_decade"],
        ),
        _endpoint_row(
            name=name,
            endpoint="end",
            legend="End",
            year=data["end_year"],
            month=data["end_month"],
            day=data["end_day"],
            decade=data["end_decade"],
        ),
        _qualifier_row(
            name=name,
            approximate=data["approximate"],
            uncertain=data["uncertain"],
        ),
    ]


def _kind_select(*, name: str, kind: str, input_id: str) -> Node:
    # Imported here: games.forms imports this module.
    from games.forms import SELECT_CLASS

    selected = kind.strip() or TemporalDraftKind.UNKNOWN.value
    options = [
        Option(value=draft_kind.value, selected=draft_kind.value == selected)[text]
        for draft_kind, text in TEMPORAL_DRAFT_KIND_LABELS.items()
    ]
    return Select(
        name=temporal_input_name(name, "kind"),
        id_=input_id or None,
        class_=SELECT_CLASS,
    )[*options]


def _endpoint_row(
    *,
    name: str,
    endpoint: str,
    legend: str,
    year: str,
    month: str,
    day: str,
    decade: str,
) -> Node:
    return Div(class_=_ROW_CLASS, data_temporal_endpoint=endpoint)[
        Div(class_=_LEGEND_CLASS)[legend],
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
            class_=INPUT_CLASS,
        ),
    ]


def _qualifier_row(*, name: str, approximate: str, uncertain: str) -> Node:
    """One pair of boxes for the whole value."""
    return Div(class_=_ROW_CLASS)[
        Checkbox(
            name=temporal_input_name(name, "approximate"),
            label="Approximate",
            checked=bool(approximate.strip()),
            value="on",
        ),
        Checkbox(
            name=temporal_input_name(name, "uncertain"),
            label="Uncertain",
            checked=bool(uncertain.strip()),
            value="on",
        ),
    ]
