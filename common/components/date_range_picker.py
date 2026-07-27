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
from common.components.custom_elements import (
    OVERLAY_SURFACE_CLASS,
    _DateRangePicker,
    _Dropdown,
)
from common.components.primitives import (
    Button,
    ButtonColor,
    ControlButton,
    Div,
    FilterWidgetPath,
    Input,
    Span,
    Template,
    control_button_class,
    filter_widget_attributes,
)
from common.date_time_presentation import DateTimePresentation, DateTimeSegmentSpec

# font-mono: every glyph (placeholder letters and digits alike) is exactly
# 1ch wide, so the exact segment widths below leave no slack and the gaps
# around the dashes stay uniform. Container and segments share text-type-input
# (the 16px input size) so the dashes advance like the segment digits.
# px-3/min-h-control/shadow-xs (not p-1.5) match INPUT_CLASS's box model
# (games/forms.py) so this composite control sits flush with plain text
# inputs in the same form row instead of looking visibly shorter/tighter.
FIELD_CONTAINER_CLASS = (
    "flex items-center gap-0.5 w-full rounded-base border border-default-medium "
    "bg-neutral-secondary-medium font-mono text-type-input text-heading px-3 "
    "min-h-control shadow-xs cursor-text focus-within:ring-1 focus-within:ring-brand "
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

CALENDAR_ICON_SVG = (
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

# Every calendar control is a ControlButton — no hand-rolled class tables here
# (that is how the day cells drifted into square corners and a 16px hit area).
# Only the GRID GEOMETRY below is the calendar's own: a fixed cell width, so the
# seven columns line up whether the label is "1" or "31". ControlButton owns the
# height (min-h-control) and every colour/hover/focus treatment.
#
# w-11 (44px) rather than a narrower cell: ControlButton bakes px-3 (12px a
# side), so a 2-digit label needs ~40px before the box starts clipping.
_DAY_CELL_GEOMETRY_CLASS = "w-11 shrink-0"
_NAV_BUTTON_GEOMETRY_CLASS = "w-11 shrink-0"

# The day-cell variants, composed from ControlButton so the calendar cannot
# disagree with the rest of the app's buttons. Published to TypeScript by
# `manage.py gen_element_types` (ts/generated/calendar-classes.ts) because the
# 42 cells are cloned client-side — see date_calendar_shell's day template.
#
# Rounding is applied to EVERY variant, not just the unselected one: rounding,
# fill and dimming are orthogonal, and folding them into one if/else chain is
# exactly what left selected and adjacent-month cells square.
type CalendarDayVariant = str  # e.g. "selected"
CALENDAR_DAY_CLASSES: dict[CalendarDayVariant, str] = {
    # Unselected, in-month: transparent chrome until hover.
    "default": f"{control_button_class(variant='ghost')} {_DAY_CELL_GEOMETRY_CLASS}",
    # Picked date (both pickers) — the filled brand button.
    "selected": (
        f"{control_button_class(color='blue', variant='filled')} "
        f"{_DAY_CELL_GEOMETRY_CLASS}"
    ),
    # Leading/trailing days from the adjacent month: the default look, dimmed.
    "adjacent": (
        f"{control_button_class(variant='ghost')} {_DAY_CELL_GEOMETRY_CLASS} opacity-40"
    ),
    # Range-picker only: the fixed endpoint while the other end is being picked.
    "anchor": (
        f"{control_button_class(color='blue', variant='filled')} "
        f"{_DAY_CELL_GEOMETRY_CLASS} ring-2 ring-inset ring-brand-strong"
    ),
}

# Range-picker only: the days BETWEEN the two endpoints. Layered on top of a
# day variant, and deliberately not rounded — a continuous track reads as one
# bar. Outlined while picking the second date, filled once both are set, muted
# when showing an already-committed range read-only.
#
# The background carries Tailwind's `!` important suffix because it has to beat
# the day variant's own `bg-transparent` (ControlButton's ghost look). Two
# background utilities on one element are resolved by STYLESHEET order, not
# class order, so without this the track silently lost and the connective
# highlight between the two endpoints disappeared. The border colour needs no
# such treatment — the variant sets `border-transparent`, a different property
# value, and `border-y` only re-widens the edges this rule colours.
type CalendarTrackVariant = str  # e.g. "filled"
CALENDAR_TRACK_CLASSES: dict[CalendarTrackVariant, str] = {
    "outlined": "border-y border-brand/70! bg-brand/10!",
    "filled": "bg-brand/30!",
    "muted": "bg-brand/15!",
}

# The weekday header row (Mo/Tu/…): a label, not a control, so it is not a
# ControlButton — only matched to the day-cell width so the columns align.
CALENDAR_WEEKDAY_CLASS = (
    f"{_DAY_CELL_GEOMETRY_CLASS} h-6 flex items-center justify-center "
    "text-type-micro text-body select-none"
)


def iso_part_values(iso_value: str, parts: list[DateTimeSegmentSpec]) -> dict[str, str]:
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


def date_segment_input(
    *,
    part: DateTimeSegmentSpec,
    side: str,
    label: str,
    value: str,
    side_label: str = "",
    segment_id: str = "",
) -> Node:
    """One typed digit-entry segment (e.g. the ``YYYY`` part). ``side_label``
    ("from"/"to" for a range side) is folded into the segment's aria-label;
    empty for a single-date field. ``segment_id`` stamps a DOM id on this one
    segment — used to put the field's real id on the first segment so a
    ``<label for=>`` focuses it (single-date fields only; range sides have no
    associated ``<label>`` today)."""
    aria_label = (
        f"{label} {side_label} {part.name}" if side_label else f"{label} {part.name}"
    )
    return Input(
        inputmode="numeric",
        autocomplete="off",
        maxlength=str(part.input_length),
        placeholder=part.placeholder,
        value=value,
        id_=segment_id or None,
        data_date_part=part.name,
        data_date_side=side,
        aria_label=aria_label,
        class_=(
            f"{_SEGMENT_INPUT_CLASS} "
            f"{_SEGMENT_WIDTH_CLASSES.get(part.input_length, 'w-[4ch]')}"
        ),
    )


def date_segment_group(
    *,
    side: str,
    label: str,
    iso_value: str,
    presentation: DateTimePresentation,
    side_label: str = "",
    first_segment_id: str = "",
) -> Node:
    """One date's worth of segments (``DD - MM - YYYY``), ordered by the
    active presentation profile, for one side (a range's "min"/"max", or a
    single-date field's own side id)."""
    parts = list(presentation.profile.segments_for("date"))
    initial_values = iso_part_values(iso_value, parts)
    children: list[Node] = []
    for index, part in enumerate(parts):
        if index > 0 and part.segmented.prefix:
            children.append(Span(class_="text-body select-none")[part.segmented.prefix])
        children.append(
            date_segment_input(
                part=part,
                side=side,
                label=label,
                value=initial_values.get(part.name, ""),
                side_label=side_label,
                segment_id=first_segment_id if index == 0 else "",
            )
        )
    return Span(class_="flex items-center gap-0.5", data_date_field_side=side)[
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
    nothing to toggle. ``calendar_toggle=True`` also stamps ``data-toggle``:
    this field is the ``<drop-down>`` positioning anchor for the popup
    calendar (issue #485 follow-up) — the panel variant sits inside its own
    outer ``<drop-down>`` already (the quick-facet "Label ▾" host) and needs
    no anchor of its own."""
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    field_attrs = [("data-toggle", "")] if calendar_toggle else []
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
        date_segment_group(
            side="min",
            label=label,
            iso_value=min_value,
            presentation=presentation,
            side_label="from",
        ),
        Span(class_="text-body select-none px-0.5")["–"],
        date_segment_group(
            side="max",
            label=label,
            iso_value=max_value,
            presentation=presentation,
            side_label="to",
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
            )[Safe(CALENDAR_ICON_SVG)]
        )
    return Div(field_attrs, class_=FIELD_CONTAINER_CLASS, data_date_range_field="")[
        *children
    ]


def _calendar_nav_button(direction: str, arrow: str, label: str) -> Node:
    # Ghost: transparent chrome at rest, which is what the ‹/› glyphs had
    # before — but now with ControlButton's 42px height and a matched cell
    # width, so the hit area clears the 24x24 WCAG 2.5.8 floor by a wide
    # margin (it used to be 16px wide, see e2e/test_touch_targets_e2e.py).
    return ControlButton(
        [(f"data-date-range-{direction}", "")],
        variant="ghost",
        aria_label=label,
        class_=_NAV_BUTTON_GEOMETRY_CLASS,
    )[arrow]


def footer_button(action: str, label: str, *, color: ButtonColor = "gray") -> Node:
    """One calendar footer action. Cancel/Clear are secondary (gray); Select is
    the primary commit (blue)."""
    return ControlButton(
        [(f"data-date-range-{action}", "")],
        color=color,
    )[label]


def _preset_button(preset_value: str, preset_label: str) -> Node:
    # A preset is a choice in a list, so it is left-aligned (align="start") —
    # centered labels read as ragged against each other in the column.
    return ControlButton(
        [("data-date-range-preset", preset_value)],
        variant="ghost",
        align="start",
        class_="w-full whitespace-nowrap",
    )[preset_label]


# The static (panel) calendar surface: no hidden/absolute/positioning offset —
# it flows in the document below the field, inside a dropdown dialog that is
# ALSO OVERLAY_SURFACE_CLASS (frosted). The calendar still carries its own
# frosted surface (not a flat control color) so it looks the same everywhere
# the calendar appears, popup or panel — the double-frost-in-dark-mode
# tradeoff is intentional (issue #485 follow-up option 1). `relative` anchors
# the frost's `before:inset-0` pseudo-element to this box, not the ancestor
# dialog (which would otherwise blur the whole dialog, not just the calendar).
_STATIC_CALENDAR_CLASS = f"mt-2 flex rounded-base border border-default-medium relative {OVERLAY_SURFACE_CLASS}"


def date_calendar_shell(
    *,
    input_name_prefix: str,
    presets: list[tuple[str, str]] | None,
    footer_buttons: list[Node],
    static: bool = False,
) -> Node:
    """The calendar popup shell shared by :func:`DateRangeCalendar` and
    ``DatePickerCalendar``: an optional preset column, the month grid (filled
    client-side into ``[data-date-range-grid]``), nav, and a caller-supplied
    footer. ``presets=None`` omits the preset column entirely (a single-date
    field has nothing to preset). ``static=True`` flows the calendar inline
    instead of as a popup (the quick-facet host already owns visibility).

    The non-static popup is the ``<drop-down>``'s ``[data-menu]`` (issue #485
    follow-up): attachMenu owns visibility via the ``hidden`` attribute and
    viewport-aware fixed positioning, so it carries no positioning classes of
    its own (no ``absolute``/``top-full``/``mt-1``) — only its surface look."""
    children: list[Node] = []
    if presets is not None:
        preset_buttons = [
            _preset_button(preset_value, preset_label)
            for preset_value, preset_label in presets
        ]
        children.append(
            Div(
                class_="flex flex-col gap-0.5 p-2 border-e border-default-medium",
                data_date_range_presets="",
            )[*preset_buttons]
        )
    children.append(
        Div(class_="p-2")[
            Div(class_="flex items-center justify-between gap-2")[
                _calendar_nav_button("prev", "‹", "Previous month"),
                Span(
                    class_="text-type-body font-medium text-heading",
                    data_date_range_month_label="",
                ),
                _calendar_nav_button("next", "›", "Next month"),
            ],
            # w-77 (7 * the w-11 day-cell width) is explicit, not
            # relied-on-shrink-to-fit: Firefox's shrink-to-fit algorithm for
            # an ancestor with width:auto can size a `minmax(0, 1fr)` grid
            # down to its near-zero min-content instead of its max-content,
            # so the fixed-width day cells then overflow their squeezed
            # tracks and visually overlap. An explicit width removes the
            # ambiguity outright, in every browser.
            Div(
                class_="grid grid-cols-7 gap-y-0.5 mt-1 w-77",
                data_date_range_grid="",
            ),
            # The day cell the client clones 42x per month, rendered HERE so
            # its markup and classes come from ControlButton rather than a
            # hand-written string in TypeScript (the same server-template
            # pattern SearchSelect uses for its option rows). The client
            # swaps the class per state from the generated
            # CALENDAR_DAY_CLASSES table and fills in date/label.
            Template(data_date_range_template="day")[
                ControlButton(variant="ghost", class_=_DAY_CELL_GEOMETRY_CLASS)
            ],
            Div(
                class_=(
                    "flex justify-end gap-2 mt-2 pt-2 border-t border-default-medium"
                ),
            )[*footer_buttons],
        ]
    )
    return Div(
        [] if static else [("data-menu", ""), ("hidden", "")],
        class_=_STATIC_CALENDAR_CLASS
        if static
        else f"z-20 flex rounded-base border border-default-medium {OVERLAY_SURFACE_CLASS}",
        data_date_range_calendar="",
        data_input_name_prefix=input_name_prefix,
    )[*children]


def DateRangeCalendar(*, input_name_prefix: str, static: bool = False) -> Node:
    """The popup half of the DateRangePicker: preset column, month grid
    (filled client-side into ``[data-date-range-grid]``), and the
    Cancel / Clear / Select footer. Hidden until the calendar toggle opens it.

    ``static=True`` is the panel variant (:func:`DateRangePanel`): the
    calendar flows statically, always visible, and the footer shrinks to
    Clear alone — Cancel/Select only exist to close the popup, and the
    hosting dropdown owns open/close."""
    footer_buttons: list[Node] = []
    if not static:
        footer_buttons.append(footer_button("cancel", "Cancel"))
    footer_buttons.append(footer_button("clear", "Clear"))
    if not static:
        footer_buttons.append(footer_button("select", "Select", color="blue"))
    return date_calendar_shell(
        input_name_prefix=input_name_prefix,
        presets=_PRESET_OPTIONS,
        footer_buttons=footer_buttons,
        static=static,
    )


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
    leave it None and the extra attributes are omitted.

    Hosted in ``<drop-down behavior="date-calendar">`` (issue #485
    follow-up): the popup's visibility, viewport-aware positioning, and
    outside-click/Escape dismiss all come from the shared attachMenu engine
    instead of a bespoke absolute-positioned Div — this is what fixed the
    calendar overlapping the field on narrow viewports. ``block`` (not the
    generic inline-flex ``Dropdown()`` wrapper) so the field keeps its full
    form-column width, matching ``SearchSelect(host_dropdown=True)``."""
    widget_attributes = (
        filter_widget_attributes(path, "date") if path is not None else []
    )
    picker = _DateRangePicker(widget_attributes, class_="relative")[
        DateRangeField(
            presentation=presentation,
            label=label,
            input_name_prefix=input_name_prefix,
            min_value=min_value,
            max_value=max_value,
        ),
        DateRangeCalendar(input_name_prefix=input_name_prefix),
    ]
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="date-calendar",
    )[picker]


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
