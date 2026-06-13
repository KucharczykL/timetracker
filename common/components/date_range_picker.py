"""DateRangePicker: a segmented date-range input with a calendar popup.

``DateRangePicker`` composes two parts:

- ``DateRangeField`` — the visible widget, styled as a single input. Each
  date is split into per-part segments (``DD``/``MM``/``YYYY``, ordered by
  ``common.time.dateformat_hyphenated``) that the user fills digit by digit,
  plus a calendar icon that opens the popup.
- ``DateRangeCalendar`` — the popup: a preset column (today, yesterday,
  last 7 days, …), a month grid rendered client-side, and a
  Cancel / Clear / Select footer.

The committed value lives in two hidden ISO-date inputs named
``{input_name_prefix}-min`` / ``{input_name_prefix}-max`` — the same contract
as the older ``DateRangeFilter``, so ``filter_bar.js`` serializes either
widget into a ``DateCriterion`` unchanged. All behaviour is wired by
``games/static/js/date_range_picker.js``.
"""

from django.utils.safestring import SafeText, mark_safe

from common.components.core import Element, HTMLAttribute, Media, Node
from common.components.primitives import Div, Input, Span
from common.time import DatePartSpec, date_parts

# Wired by date_range_picker.js.
_DATE_RANGE_MEDIA = Media(js=("date_range_picker.js",))

_FIELD_CONTAINER_CLASS = (
    "flex items-center gap-0.5 w-full rounded-base border border-default-medium "
    "bg-neutral-secondary-medium text-sm text-heading p-1.5 cursor-text "
    "focus-within:ring-1 focus-within:ring-brand focus-within:border-brand"
)

# The segments must not stand out from the container: transparent background,
# no border, and only a subtle highlight when active (focused).
_SEGMENT_INPUT_CLASS = (
    "bg-transparent border-0 p-0 text-center text-sm text-heading "
    "placeholder:text-body rounded-xs focus:outline-none focus:ring-0 "
    "focus:bg-brand/30 caret-transparent"
)

_SEGMENT_WIDTH_CLASSES = {2: "w-[2.5ch]", 4: "w-[4.5ch]"}

_CALENDAR_ICON_SVG = (
    '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" '
    'stroke="currentColor" aria-hidden="true">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5'
    "A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5"
    "A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5"
    'A2.25 2.25 0 0 1 21 11.25v7.5"/>'
    "</svg>"
)

_PRESET_OPTIONS: list[tuple[str, str]] = [
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("last_7_days", "Last 7 days"),
    ("last_30_days", "Last 30 days"),
    ("this_month", "This month"),
    ("last_month", "Last month"),
    ("this_year", "This year"),
]

_PRESET_BUTTON_CLASS = (
    "px-3 py-1.5 text-sm text-start text-body hover:text-heading "
    "hover:bg-neutral-tertiary-medium rounded-base cursor-pointer whitespace-nowrap"
)

_NAV_BUTTON_CLASS = (
    "p-1.5 text-body hover:text-heading hover:bg-neutral-tertiary-medium "
    "rounded-base cursor-pointer"
)

_FOOTER_BUTTON_CLASS = (
    "px-3 py-1.5 text-sm font-medium rounded-base cursor-pointer "
    "text-heading bg-neutral-secondary-medium border border-default-medium "
    "hover:bg-neutral-tertiary-medium"
)

_FOOTER_SELECT_BUTTON_CLASS = (
    "px-3 py-1.5 text-sm font-medium rounded-base cursor-pointer "
    "text-white bg-brand border border-transparent hover:bg-brand-strong"
)


def _iso_part_values(iso_value: str, parts: list[DatePartSpec]) -> dict[str, str]:
    """Split an ISO ``YYYY-MM-DD`` string into per-part initial values.

    Returns an empty mapping for empty/malformed input so a bad stored filter
    renders as empty segments instead of crashing."""
    if not iso_value:
        return {}
    pieces = iso_value.split("-")
    if len(pieces) != 3:
        return {}
    year, month, day = pieces
    values = {"year": year, "month": month, "day": day}
    if any(not values[part.name].isdigit() for part in parts):
        return {}
    return values


def _segment_input(
    *, part: DatePartSpec, side: str, label: str, value: str
) -> SafeText:
    side_label = "from" if side == "min" else "to"
    return Input(
        attributes=[
            ("inputmode", "numeric"),
            ("autocomplete", "off"),
            ("maxlength", str(part.length)),
            ("placeholder", part.placeholder),
            ("value", value),
            ("data-date-part", part.name),
            ("data-date-side", side),
            ("aria-label", f"{label} {side_label} {part.name}"),
            (
                "class",
                f"{_SEGMENT_INPUT_CLASS} "
                f"{_SEGMENT_WIDTH_CLASSES.get(part.length, 'w-[4.5ch]')}",
            ),
        ],
    )


def _segment_group(*, side: str, label: str, iso_value: str) -> SafeText:
    """One date's worth of segments (``DD - MM - YYYY``) for a range side."""
    parts = date_parts()
    initial_values = _iso_part_values(iso_value, parts)
    children: list[SafeText] = []
    for index, part in enumerate(parts):
        if index > 0:
            children.append(
                Span(
                    attributes=[("class", "text-body select-none")],
                    children=["-"],
                )
            )
        children.append(
            _segment_input(
                part=part,
                side=side,
                label=label,
                value=initial_values.get(part.name, ""),
            )
        )
    return Span(
        attributes=[
            ("class", "flex items-center gap-0.5"),
            ("data-date-range-side", side),
        ],
        children=children,
    )


def DateRangeField(
    *,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
) -> SafeText:
    """The visible half of the DateRangePicker: a single-input-looking
    container holding two segmented dates, a calendar toggle, and the two
    hidden ISO inputs (``{prefix}-min`` / ``{prefix}-max``) that carry the
    committed value to ``filter_bar.js``."""
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    return Div(
        attributes=[
            ("class", _FIELD_CONTAINER_CLASS),
            ("data-date-range-field", ""),
        ],
        children=[
            Input(
                type="hidden",
                attributes=[
                    ("name", min_input_id),
                    ("id", min_input_id),
                    ("value", min_value),
                    ("data-date-range-hidden", "min"),
                ],
            ),
            Input(
                type="hidden",
                attributes=[
                    ("name", max_input_id),
                    ("id", max_input_id),
                    ("value", max_value),
                    ("data-date-range-hidden", "max"),
                ],
            ),
            _segment_group(side="min", label=label, iso_value=min_value),
            Span(
                attributes=[("class", "text-body select-none px-0.5")],
                children=["–"],
            ),
            _segment_group(side="max", label=label, iso_value=max_value),
            Element(
                "button",
                attributes=[
                    ("type", "button"),
                    ("data-date-range-calendar-toggle", ""),
                    ("aria-label", f"Open {label} calendar"),
                    (
                        "class",
                        "ms-auto p-1 text-body hover:text-heading rounded "
                        "cursor-pointer shrink-0",
                    ),
                ],
                children=[mark_safe(_CALENDAR_ICON_SVG)],
            ),
        ],
    )


def _calendar_nav_button(direction: str, arrow: str, label: str) -> SafeText:
    return Element(
        "button",
        attributes=[
            ("type", "button"),
            (f"data-date-range-{direction}", ""),
            ("aria-label", label),
            ("class", _NAV_BUTTON_CLASS),
        ],
        children=[arrow],
    )


def _footer_button(action: str, label: str, button_class: str) -> SafeText:
    return Element(
        "button",
        attributes=[
            ("type", "button"),
            (f"data-date-range-{action}", ""),
            ("class", button_class),
        ],
        children=[label],
    )


def DateRangeCalendar(*, input_name_prefix: str) -> SafeText:
    """The popup half of the DateRangePicker: preset column, month grid
    (filled client-side into ``[data-date-range-grid]``), and the
    Cancel / Clear / Select footer. Hidden until the calendar toggle opens it."""
    preset_buttons = [
        Element(
            "button",
            attributes=[
                ("type", "button"),
                ("data-date-range-preset", preset_value),
                ("class", _PRESET_BUTTON_CLASS),
            ],
            children=[preset_label],
        )
        for preset_value, preset_label in _PRESET_OPTIONS
    ]
    return Div(
        attributes=[
            (
                "class",
                "hidden absolute z-20 top-full start-0 mt-1 flex "
                "rounded-base border border-default-medium "
                "bg-neutral-secondary-medium shadow-lg",
            ),
            ("data-date-range-calendar", ""),
            ("data-input-name-prefix", input_name_prefix),
        ],
        children=[
            Div(
                attributes=[
                    (
                        "class",
                        "flex flex-col gap-0.5 p-2 border-e border-default-medium",
                    ),
                    ("data-date-range-presets", ""),
                ],
                children=preset_buttons,
            ),
            Div(
                attributes=[("class", "p-2")],
                children=[
                    Div(
                        attributes=[
                            ("class", "flex items-center justify-between gap-2"),
                        ],
                        children=[
                            _calendar_nav_button("prev", "‹", "Previous month"),
                            Span(
                                attributes=[
                                    ("class", "text-sm font-medium text-heading"),
                                    ("data-date-range-month-label", ""),
                                ],
                            ),
                            _calendar_nav_button("next", "›", "Next month"),
                        ],
                    ),
                    Div(
                        attributes=[
                            ("class", "grid grid-cols-7 gap-y-0.5 mt-1"),
                            ("data-date-range-grid", ""),
                        ],
                    ),
                    Div(
                        attributes=[
                            (
                                "class",
                                "flex justify-end gap-2 mt-2 pt-2 border-t "
                                "border-default-medium",
                            ),
                        ],
                        children=[
                            _footer_button("cancel", "Cancel", _FOOTER_BUTTON_CLASS),
                            _footer_button("clear", "Clear", _FOOTER_BUTTON_CLASS),
                            _footer_button(
                                "select", "Select", _FOOTER_SELECT_BUTTON_CLASS
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def DateRangePicker(
    *,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
) -> Node:
    """A date-range widget: segmented manual entry plus a calendar popup.

    Drop-in replacement for ``DateRangeFilter`` — exposes the same hidden
    ``{prefix}-min`` / ``{prefix}-max`` ISO inputs, so the filter-bar
    serializer needs no changes. ``min_value`` / ``max_value`` are ISO
    ``YYYY-MM-DD`` strings used to prefill both the segments and the hidden
    inputs."""
    attributes: list[HTMLAttribute] = [
        ("class", "date-range-picker relative"),
        ("data-date-range-picker", ""),
        ("data-input-name-prefix", input_name_prefix),
    ]
    return Div(
        attributes=attributes,
        children=[
            DateRangeField(
                label=label,
                input_name_prefix=input_name_prefix,
                min_value=min_value,
                max_value=max_value,
            ),
            DateRangeCalendar(input_name_prefix=input_name_prefix),
        ],
    ).with_media(_DATE_RANGE_MEDIA)
