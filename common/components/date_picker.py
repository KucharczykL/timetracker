"""DatePicker: a segmented single-date input with a calendar popup.

Presentation-aware replacement for native ``<input type="date">`` on add/edit
forms (issue #485). Shares its segment-entry engine and calendar popup with
DateRangePicker (``common/components/date_range_picker.py``) — DatePicker
just drives a single side ("value") instead of two, and a single-select
calendar (pick commits and closes; no presets, no anchor) instead of an
anchor-style range.

The committed value lives in one hidden ISO-date input named after the real
Django field, so ``DateField`` binding is unchanged. The field is
rendered ``inert`` and freed on upgrade, so before the script lands
it shows the stored date but cannot be typed into — its segments carry no
``name``, so anything typed there would be discarded. All behaviour is wired
by ``ts/elements/date-picker.ts``.
"""

from common.components.core import Node
from common.components.custom_elements import (
    SheetSpec,
    _DatePicker,
    _Dropdown,
    dropdown_sheet,
)
from common.components.date_range_picker import (
    FIELD_CONTAINER_CLASS,
    date_calendar_shell,
    date_segment_group,
    footer_button,
    sheet_close_button,
)
from common.components.primitives import (
    ControlButton,
    Div,
    Icon,
    Input,
    field_label_id,
)
from common.date_time_presentation import DateTimePresentation

# The single side id DatePicker's segment/hidden-input hooks use — DateRangePicker's
# shared hooks are keyed by side ("min"/"max"); a single-date field has exactly one.
_SIDE = "value"


def DatePickerField(
    *,
    presentation: DateTimePresentation,
    label: str,
    name: str,
    value: str = "",
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """The visible half of DatePicker: a single-input-looking container
    holding the hidden ISO input Django binds, one segmented date, and a
    calendar toggle. Rendered ``inert``; ``bindSegmentField`` frees it once
    the element upgrades.

    Carries ``data-toggle``: this field is the ``<drop-down>`` positioning
    anchor for the popup calendar (issue #485 follow-up)."""
    children: list[Node] = [
        Input(
            type="hidden",
            name=name,
            value=value,
            data_date_picker_hidden="",
        ),
        date_segment_group(
            side=_SIDE,
            iso_value=value,
            presentation=presentation,
            first_segment_id=input_id,
        ),
        ControlButton(
            variant="ghost",
            size="compact",
            data_date_picker_calendar_toggle="",
            aria_label=f"Open {label} calendar",
            class_="ms-auto",
        )[Icon("calendar", decorative=True)],
    ]
    # aria-labelledby when the form row rendered a <label> for this field: that
    # label names itself at nobody (its `for` target is the first segment, which
    # names itself "year"), so without this it is announced as a standalone
    # object and the group repeats the same string right after it.
    label_id = field_label_id(input_id)
    return Div(
        role="group",
        aria_labelledby=label_id or None,
        aria_label=None if label_id else label,
        aria_required="true" if required else None,
        aria_invalid="true" if invalid else None,
        inert=True,
        data_date_picker_field="",
        data_toggle="",
        class_=FIELD_CONTAINER_CLASS,
    )[*children]


def DatePickerCalendar(*, input_name_prefix: str) -> Node:
    """The popup half of DatePicker: month grid, no preset column, Clear-only
    footer. Picking a day commits the value and closes the popup immediately
    — a native date input's one-click UX, unlike the range picker's
    Cancel/Clear/Select confirmation step."""
    return date_calendar_shell(
        input_name_prefix=input_name_prefix,
        presets=None,
        footer_buttons=[footer_button("clear", "Clear"), sheet_close_button()],
    )


def DatePicker(
    *,
    presentation: DateTimePresentation,
    label: str,
    name: str,
    value: str = "",
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """A presentation-aware single-date widget: segmented manual entry plus
    a calendar popup, submitting canonical ISO ``YYYY-MM-DD`` under ``name``.

    ``input_id`` goes on the first segment so a ``<label for=>`` focuses it;
    the container is additionally a labeled ``role="group"`` (the other
    segments have no individual ``<label>`` of their own).

    Its ``<drop-down>`` host opens, positions and dismisses it."""
    picker = _DatePicker(class_="relative")[
        DatePickerField(
            presentation=presentation,
            label=label,
            name=name,
            value=value,
            input_id=input_id,
            required=required,
            invalid=invalid,
        ),
        DatePickerCalendar(input_name_prefix=name),
    ]
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="date-calendar",
    )[picker, dropdown_sheet(SheetSpec(label))]
