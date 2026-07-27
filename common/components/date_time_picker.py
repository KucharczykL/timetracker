"""DateTimePicker: a segmented date **and time** input with a calendar popup.

The date half is the same segmented entry as :mod:`common.components.date_picker`;
the time half is additional segments in the *same* run, so arrows and
auto-advance cross the date/time seam without the field knowing there is one.
Which segments exist, in what order, and what punctuation sits between them all
come from the presentation contract's segment list — including whether there is
a day-period segment at all.

The committed value is an offset-qualified wall clock
(``2026-07-27T14:30:00.000000+02:00``) in one hidden input named after the real
Django field. ``DateTimeField.to_python`` parses that as aware, so
``from_current_timezone`` leaves it alone and the server needs no change. See
``ts/elements/date-time-codec.ts`` for the DST rules that produce it.
"""

import re

from common.components.core import Node, Safe
from common.components.custom_elements import _DateTimeField, _Dropdown
from common.components.date_range_picker import (
    CALENDAR_ICON_SVG,
    FIELD_CONTAINER_CLASS,
    date_calendar_shell,
    footer_button,
    segment_group,
)
from common.components.primitives import Button, Div, Input
from common.date_time_presentation import (
    DateTimePresentation,
    day_periods_for_locale,
)

_SIDE = "value"

# The same shape ts/elements/date-time-codec.ts accepts: a wall clock with
# optional seconds, fraction, and offset. Both the offset-qualified value the
# widget renders and the naive one a rejected submission posts back must parse,
# or a DST rejection would re-render an empty field and eat the user's input.
_WIRE_PATTERN = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"[T ](?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2})(?:\.(?P<fraction>\d{1,6}))?)?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})?$"
)

type SegmentBuffers = dict[str, str]  # e.g. {"year": "2026", "day_period": "01"}


def datetime_part_values(
    wire_value: str, presentation: DateTimePresentation
) -> tuple[SegmentBuffers, SegmentBuffers]:
    """Split a wire value into per-segment buffers and their display text.

    The two differ only for the day period, which steps and encodes as 0/1 but
    shows the locale's own label. Malformed input yields empty segments rather
    than raising — a bound form can carry anything the user typed.
    """

    match = _WIRE_PATTERN.match(wire_value.strip()) if wire_value else None
    if match is None:
        return {}, {}

    hour = int(match["hour"])
    buffers: SegmentBuffers = {
        "year": match["year"],
        "month": match["month"],
        "day": match["day"],
        "hour": match["hour"],
        "minute": match["minute"],
    }
    display: SegmentBuffers = {}
    if presentation.profile.hour_cycle == "h12":
        buffers["hour"] = f"{hour % 12 or 12:02d}"
        period = 0 if hour < 12 else 1
        buffers["day_period"] = f"{period:02d}"
        periods = day_periods_for_locale(presentation.locale)
        display["day_period"] = periods["am" if period == 0 else "pm"]
    return buffers, display


def DateTimeField(
    *,
    presentation: DateTimePresentation,
    label: str,
    name: str,
    value: str = "",
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """The visible half: the hidden input Django binds, one flat run of date
    and time segments, and a calendar toggle.

    Rendered ``inert`` and freed on upgrade, like the date field — the segments
    carry no ``name`` of their own, so typing before the engine binds would be
    silently discarded.
    """

    parts = list(presentation.profile.segments_for("date", "time"))
    buffers, display = datetime_part_values(value, presentation)
    children: list[Node] = [
        Input(
            type="hidden",
            name=name,
            value=value,
            data_date_time_hidden="",
        ),
        segment_group(
            side=_SIDE,
            parts=parts,
            initial_values=buffers,
            display_values=display,
            first_segment_id=input_id,
        ),
        Button(
            type="button",
            data_date_picker_calendar_toggle="",
            aria_label=f"Open {label} calendar",
            class_=(
                "ms-auto p-1 text-body hover:text-heading rounded "
                "cursor-pointer shrink-0"
            ),
        )[Safe(CALENDAR_ICON_SVG)],
    ]
    return Div(
        role="group",
        aria_label=label,
        aria_required="true" if required else None,
        aria_invalid="true" if invalid else None,
        inert=True,
        data_date_picker_field="",
        data_toggle="",
        class_=FIELD_CONTAINER_CLASS,
    )[*children]


def DateTimeCalendar(*, input_name_prefix: str) -> Node:
    """The popup half: a month grid, and a footer of Now / Clear.

    "Now" is a labelled button here rather than an icon on the field: it
    matches the Today/Yesterday preset vocabulary the range calendar already
    uses, and adds no second cramped target beside the segments. Picking a day
    keeps the typed time — only the date segments change.
    """

    return date_calendar_shell(
        input_name_prefix=input_name_prefix,
        presets=None,
        footer_buttons=[
            footer_button("now", "Now"),
            footer_button("clear", "Clear"),
        ],
    )


def DateTimePicker(
    *,
    presentation: DateTimePresentation,
    label: str,
    name: str,
    value: str = "",
    input_id: str = "",
    required: bool = False,
    invalid: bool = False,
) -> Node:
    """A presentation-aware datetime widget: segmented manual entry plus a
    calendar popup, submitting an offset-qualified wall clock under ``name``."""

    field = _DateTimeField(class_="relative")[
        DateTimeField(
            presentation=presentation,
            label=label,
            name=name,
            value=value,
            input_id=input_id,
            required=required,
            invalid=invalid,
        ),
        DateTimeCalendar(input_name_prefix=name),
    ]
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="date-calendar",
    )[field]
