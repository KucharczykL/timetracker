"""DateRangePicker: a segmented date-range input with a calendar popup.

``DateRangePicker`` composes two parts:

- ``DateRangeField`` — the visible widget, styled as a single input. Each
  date is split into per-part segments ordered by the active presentation
  profile that the user fills digit by digit,
  plus a calendar icon that opens the popup.
- ``DateRangeCalendar`` — the popup: a preset column (today, yesterday,
  last 7 days, …), a month grid rendered client-side, and a
  Cancel / Clear / Select footer.

The committed value lives in two hidden ISO-date inputs named
``{input_name_prefix}-min`` / ``{input_name_prefix}-max``, which the filter
serializers read into a ``DateCriterion``. All behaviour is wired by
``ts/elements/date-range-picker.ts``.
"""

from common.components.core import Node, Safe
from common.components.custom_elements import _DateRangePicker
from common.components.primitives import (
    Button,
    Div,
    FilterWidgetPath,
    Input,
    Span,
    filter_widget_attributes,
)
from common.date_time_presentation import DatePartSpec, DateTimePresentation

# font-mono: every glyph (placeholder letters and digits alike) is exactly
# 1ch wide, so the exact segment widths below leave no slack and the gaps
# around the dashes stay uniform. Container and segments share text-type-input
# (the 16px input size) so the dashes advance like the segment digits.
_FIELD_CONTAINER_CLASS = (
    "flex items-center gap-0.5 w-full rounded-base border border-default-medium "
    "bg-neutral-secondary-medium font-mono text-type-input text-heading p-1.5 "
    "cursor-text focus-within:ring-1 focus-within:ring-brand "
    "focus-within:border-brand"
)

# The segments must not stand out from the container: transparent background,
# no border, and only a subtle highlight when active (focused).
_SEGMENT_INPUT_CLASS = (
    "bg-transparent border-0 p-0 text-center text-type-input text-heading "
    "placeholder:text-body rounded-xs focus:outline-none focus:ring-0 "
    "focus:bg-brand/30 caret-transparent"
)

_SEGMENT_WIDTH_CLASSES = {2: "w-[2ch]", 4: "w-[4ch]"}

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
    "px-3 py-1.5 text-type-body text-start text-body hover:text-heading "
    "hover:bg-neutral-tertiary-medium rounded-base cursor-pointer whitespace-nowrap"
)

_NAV_BUTTON_CLASS = (
    "p-1.5 text-body hover:text-heading hover:bg-neutral-tertiary-medium "
    "rounded-base cursor-pointer"
)

_FOOTER_BUTTON_CLASS = (
    "px-3 py-1.5 text-type-body font-medium rounded-base cursor-pointer "
    "text-heading bg-neutral-secondary-medium border border-default-medium "
    "hover:bg-neutral-tertiary-medium"
)

_FOOTER_SELECT_BUTTON_CLASS = (
    "px-3 py-1.5 text-type-body font-medium rounded-base cursor-pointer "
    "solid-brand border border-transparent hover:bg-brand-strong"
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


def _segment_input(*, part: DatePartSpec, side: str, label: str, value: str) -> Node:
    side_label = "from" if side == "min" else "to"
    return Input(
        inputmode="numeric",
        autocomplete="off",
        maxlength=str(part.input_length),
        placeholder=part.placeholder,
        value=value,
        data_date_part=part.name,
        data_date_side=side,
        aria_label=f"{label} {side_label} {part.name}",
        class_=(
            f"{_SEGMENT_INPUT_CLASS} "
            f"{_SEGMENT_WIDTH_CLASSES.get(part.input_length, 'w-[4ch]')}"
        ),
    )


def _segment_group(
    *,
    side: str,
    label: str,
    iso_value: str,
    presentation: DateTimePresentation,
) -> Node:
    """One date's worth of segments (``DD - MM - YYYY``) for a range side."""
    parts = list(presentation.profile.date_parts)
    initial_values = _iso_part_values(iso_value, parts)
    children: list[Node] = []
    for index, part in enumerate(parts):
        if index > 0:
            children.append(
                Span(class_="text-body select-none")[
                    presentation.profile.segmented_date_separator
                ]
            )
        children.append(
            _segment_input(
                part=part,
                side=side,
                label=label,
                value=initial_values.get(part.name, ""),
            )
        )
    return Span(class_="flex items-center gap-0.5", data_date_range_side=side)[
        *children
    ]


def DateRangeField(
    *,
    presentation: DateTimePresentation,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    calendar_toggle: bool = True,
) -> Node:
    """The visible half of the DateRangePicker: a single-input-looking
    container holding two segmented dates, a calendar toggle, and the two
    hidden ISO inputs (``{prefix}-min`` / ``{prefix}-max``) that carry the
    committed value to the filter serializers.

    ``calendar_toggle=False`` omits the toggle icon — the panel variant
    (:func:`DateRangePanel`) shows its calendar statically, so there is
    nothing to toggle."""
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    children: list[Node] = [
        Input(
            type="hidden",
            name=min_input_id,
            id_=min_input_id,
            value=min_value,
            data_date_range_hidden="min",
            data_range_min="",
        ),
        Input(
            type="hidden",
            name=max_input_id,
            id_=max_input_id,
            value=max_value,
            data_date_range_hidden="max",
            data_range_max="",
        ),
        _segment_group(
            side="min",
            label=label,
            iso_value=min_value,
            presentation=presentation,
        ),
        Span(class_="text-body select-none px-0.5")["–"],
        _segment_group(
            side="max",
            label=label,
            iso_value=max_value,
            presentation=presentation,
        ),
    ]
    if calendar_toggle:
        children.append(
            Button(
                type="button",
                data_date_range_calendar_toggle="",
                aria_label=f"Open {label} calendar",
                class_=(
                    "ms-auto p-1 text-body hover:text-heading rounded "
                    "cursor-pointer shrink-0"
                ),
            )[Safe(_CALENDAR_ICON_SVG)]
        )
    return Div(class_=_FIELD_CONTAINER_CLASS, data_date_range_field="")[*children]


def _calendar_nav_button(direction: str, arrow: str, label: str) -> Node:
    return Button(
        [("type", "button"), (f"data-date-range-{direction}", "")],
        aria_label=label,
        class_=_NAV_BUTTON_CLASS,
    )[arrow]


def _footer_button(action: str, label: str, button_class: str) -> Node:
    return Button(
        [("type", "button"), (f"data-date-range-{action}", "")],
        class_=button_class,
    )[label]


# The static (panel) calendar surface: no hidden/absolute/shadow — it flows in
# the document below the field, on a dropdown dialog's own surface.
_STATIC_CALENDAR_CLASS = (
    "mt-2 flex rounded-base border border-default-medium bg-neutral-secondary-medium"
)


def DateRangeCalendar(*, input_name_prefix: str, static: bool = False) -> Node:
    """The popup half of the DateRangePicker: preset column, month grid
    (filled client-side into ``[data-date-range-grid]``), and the
    Cancel / Clear / Select footer. Hidden until the calendar toggle opens it.

    ``static=True`` is the panel variant (:func:`DateRangePanel`): the
    calendar flows statically, always visible, and the footer shrinks to
    Clear alone — Cancel/Select only exist to close the popup, and the
    hosting dropdown owns open/close."""
    preset_buttons = [
        Button(
            type="button",
            data_date_range_preset=preset_value,
            class_=_PRESET_BUTTON_CLASS,
        )[preset_label]
        for preset_value, preset_label in _PRESET_OPTIONS
    ]
    footer_buttons: list[Node] = []
    if not static:
        footer_buttons.append(_footer_button("cancel", "Cancel", _FOOTER_BUTTON_CLASS))
    footer_buttons.append(_footer_button("clear", "Clear", _FOOTER_BUTTON_CLASS))
    if not static:
        footer_buttons.append(
            _footer_button("select", "Select", _FOOTER_SELECT_BUTTON_CLASS)
        )
    return Div(
        class_=_STATIC_CALENDAR_CLASS
        if static
        else (
            "hidden absolute z-20 top-full start-0 mt-1 flex "
            "rounded-base border border-default-medium "
            "bg-neutral-secondary-medium shadow-lg"
        ),
        data_date_range_calendar="",
        data_input_name_prefix=input_name_prefix,
    )[
        Div(
            class_="flex flex-col gap-0.5 p-2 border-e border-default-medium",
            data_date_range_presets="",
        )[*preset_buttons],
        Div(class_="p-2")[
            Div(class_="flex items-center justify-between gap-2")[
                _calendar_nav_button("prev", "‹", "Previous month"),
                Span(
                    class_="text-type-body font-medium text-heading",
                    data_date_range_month_label="",
                ),
                _calendar_nav_button("next", "›", "Next month"),
            ],
            Div(
                class_="grid grid-cols-7 gap-y-0.5 mt-1",
                data_date_range_grid="",
            ),
            Div(
                class_=(
                    "flex justify-end gap-2 mt-2 pt-2 border-t border-default-medium"
                ),
            )[*footer_buttons],
        ],
    ]


def DateRangePicker(
    *,
    presentation: DateTimePresentation,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    path: FilterWidgetPath | None = None,
) -> Node:
    """A date-range widget: segmented manual entry plus a calendar popup.

    ``min_value`` / ``max_value`` are ISO ``YYYY-MM-DD`` strings prefilling
    both the segments and the hidden ``{prefix}-min`` / ``{prefix}-max``
    inputs.

    Filter callers pass ``path`` so the root self-describes for the generic
    filter serializer; non-filter callers (e.g. a standalone date picker)
    leave it None and the extra attributes are omitted."""
    widget_attributes = (
        filter_widget_attributes(path, "date") if path is not None else []
    )
    return _DateRangePicker(widget_attributes, class_="relative")[
        DateRangeField(
            presentation=presentation,
            label=label,
            input_name_prefix=input_name_prefix,
            min_value=min_value,
            max_value=max_value,
        ),
        DateRangeCalendar(input_name_prefix=input_name_prefix),
    ]


def DateRangePanel(
    *,
    presentation: DateTimePresentation,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    path: FilterWidgetPath | None = None,
) -> Node:
    """The dropdown-panel variant of :func:`DateRangePicker`: the
    segmented field (no calendar toggle) above a statically flowing,
    always-visible calendar — for hosting inside a ``ComboboxDropdown``
    dialog, whose surface can't host the absolute popup (the panel clips
    overflow and scrolls vertically while open).

    Same custom element and hidden ``{prefix}-min``/``{prefix}-max``
    contract. ``data-static-calendar`` is the client discriminator:
    ``ts/elements/date-range-picker.ts`` renders the grid at init, skips
    toggle/dismiss wiring, and never closes the calendar."""
    widget_attributes = (
        filter_widget_attributes(path, "date") if path is not None else []
    )
    return _DateRangePicker(widget_attributes, class_="block", data_static_calendar="")[
        DateRangeField(
            presentation=presentation,
            label=label,
            input_name_prefix=input_name_prefix,
            min_value=min_value,
            max_value=max_value,
            calendar_toggle=False,
        ),
        DateRangeCalendar(input_name_prefix=input_name_prefix, static=True),
    ]
