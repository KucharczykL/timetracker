"""Stash-style filter bars and the SelectableFilter widget."""

from typing import NamedTuple

from django.db import models
from django.utils.html import escape
from django.utils.safestring import SafeText, mark_safe

from common.components.core import Component
from common.components.primitives import Label, Span
from common.components.search_select import FilterSelect


class FilterChoice(NamedTuple):
    """Parsed state of a SelectableFilter widget from a filter JSON blob."""

    selected: list[str]
    excluded: list[str]
    modifier: str


_FILTER_LABEL_CLASS = "text-xs font-medium text-body uppercase tracking-wide"


_FILTER_INPUT_CLASS = (
    "block w-full rounded-base border border-default-medium "
    "bg-neutral-secondary-medium text-sm text-heading p-2 "
    "focus:ring-brand focus:border-brand"
)


_FILTER_CHECKBOX_CLASS = (
    "rounded border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)


_FILTER_GRID_CLASS = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4"


def _filter_parse(filter_json: str) -> dict:
    if not filter_json:
        return {}
    try:
        import json

        loaded = json.loads(filter_json)
        return loaded if isinstance(loaded, dict) else {}
    except (ValueError, TypeError):
        return {}


def _filter_get_choice(existing: dict, field: str) -> FilterChoice:
    raw = existing.get(field, {})
    if not isinstance(raw, dict):
        return FilterChoice([], [], "")
    value = raw.get("value", [])
    excluded = raw.get("excludes", [])
    modifier = raw.get("modifier", "")
    if isinstance(value, str):
        value = [value]
    if isinstance(excluded, str):
        excluded = [excluded]
    return FilterChoice(
        selected=[str(v) for v in (value or [])],
        excluded=[str(v) for v in (excluded or [])],
        modifier=modifier or "",
    )


def _parse_range(existing: dict, key: str) -> tuple[str, str]:
    """Extract (value, value2) from a filter criterion, defaulting to ("", "")."""
    field = existing.get(key, {})
    if not isinstance(field, dict):
        return "", ""
    return str(field.get("value", "")), str(field.get("value2", ""))


def _parse_bool(existing: dict, key: str) -> bool:
    """Extract a boolean value from a filter criterion."""
    field = existing.get(key, {})
    if not isinstance(field, dict):
        return False
    return bool(field.get("value", False))


def _get_filter_options(model_class, order_by="name") -> list[tuple[str, str]]:
    """Return (value, label) pairs for a SelectableFilter from model rows.

    Uses values_list for efficiency (only fetches needed columns),
    but unpacks each row into readable local variables.
    """
    options: list[tuple[str, str]] = []
    for object_id, object_name in model_class.objects.order_by(order_by).values_list(
        "id", order_by
    ):
        options.append((str(object_id), object_name))
    return options


# ── FilterSelect adapters ────────────────────────────────────────────────────
# Each list filter is a FilterSelect. Enum fields pre-render their small, fixed
# option set; model-backed fields fetch from a search endpoint and only resolve
# the currently-selected ids to labels for their pills.

_FILTER_PREFETCH = 20


def _modifier_options(nullable: bool) -> list[tuple[str, str]]:
    """Pinned (Any)/(None) pseudo-options; (None) only when the field is nullable."""
    options = [("NOT_NULL", "(Any)")]
    if nullable:
        options.append(("IS_NULL", "(None)"))
    return options


def _resolve_game_options(ids):
    if not ids:
        return []
    from games.models import Game

    return [
        {"value": g.id, "label": g.search_label}
        for g in Game.objects.filter(pk__in=ids)
    ]


def _resolve_device_options(ids):
    if not ids:
        return []
    from games.models import Device

    return [{"value": d.id, "label": d.name} for d in Device.objects.filter(pk__in=ids)]


def _resolve_platform_options(ids):
    if not ids:
        return []
    from games.models import Platform

    return [
        {"value": p.id, "label": p.name} for p in Platform.objects.filter(pk__in=ids)
    ]


def _enum_filter(
    field_name: str, options, choice: FilterChoice, *, nullable
) -> SafeText:
    """A FilterSelect over a small, fully pre-rendered option set (enum field)."""
    options_str = [(str(value), label) for value, label in options]
    included = [(value, _find_label(options_str, value)) for value in choice.selected]
    excluded = [(value, _find_label(options_str, value)) for value in choice.excluded]
    return FilterSelect(
        field_name=field_name,
        options=options_str,
        included=included,
        excluded=excluded,
        modifier=choice.modifier,
        modifier_options=_modifier_options(nullable),
    )


def _model_filter(
    field_name: str, choice: FilterChoice, *, search_url, resolver, nullable
) -> SafeText:
    """A FilterSelect backed by a search endpoint; only selected ids are resolved
    to labels (for the pills) — the option rows are fetched on demand."""
    return FilterSelect(
        field_name=field_name,
        included=list(resolver(choice.selected)),
        excluded=list(resolver(choice.excluded)),
        modifier=choice.modifier,
        modifier_options=_modifier_options(nullable),
        search_url=search_url,
        prefetch=_FILTER_PREFETCH,
    )


def _filter_mins_to_hrs(val) -> str:
    if val is None or val == "" or val == 0:
        return ""
    try:
        mins = int(val)
    except (TypeError, ValueError):
        return ""
    if mins == 0:
        return ""
    hrs = mins / 60
    return str(int(hrs)) if hrs == int(hrs) else f"{hrs:.1f}"


def _filter_field(label: str, widget) -> SafeText:
    """A labelled filter field: <div><label>…</label>{widget}</div>."""
    return Component(
        tag_name="div",
        attributes=[("class", "flex flex-col gap-1")],
        children=[
            Label(
                attributes=[("class", _FILTER_LABEL_CLASS)],
                children=[label],
            ),
            widget,
        ],
    )


def _filter_number(label, name, value="", placeholder="") -> SafeText:
    return _filter_field(
        label,
        Component(
            tag_name="input",
            attributes=[
                ("type", "number"),
                ("name", escape(name)),
                ("id", escape(name)),
                ("value", escape(value)),
                ("placeholder", escape(placeholder)),
                ("class", _FILTER_INPUT_CLASS),
            ],
        ),
    )


def _filter_checkbox(name: str, label: str, checked: bool) -> SafeText:
    return Label(
        attributes=[("class", "flex items-center gap-2 text-sm text-heading")],
        children=[
            Component(
                tag_name="input",
                attributes=[
                    ("type", "checkbox"),
                    ("name", name),
                    ("value", "1"),
                    *([("checked", "true")] if checked else []),
                    ("class", _FILTER_CHECKBOX_CLASS),
                ],
            ),
            label,
        ],
    )


# SVG icons for the mode toggle (shared across all RangeSliders)
_RANGE_ICON_SVG = (
    '<svg width="16" height="10" viewBox="0 0 16 10">'
    '<line x1="3" y1="5" x2="13" y2="5" stroke="currentColor" stroke-width="1.5"/>'
    '<circle cx="3" cy="5" r="3" fill="currentColor"/>'
    '<circle cx="13" cy="5" r="3" fill="currentColor"/>'
    "</svg>"
)

_POINT_ICON_SVG = (
    '<svg width="16" height="10" viewBox="0 0 16 10">'
    '<circle cx="8" cy="5" r="3" fill="currentColor"/>'
    "</svg>"
)

_RANGE_SLIDER_INPUT_CLASS = (
    "w-24 rounded-base border border-default-medium bg-neutral-secondary-medium "
    "text-sm text-heading p-1.5 focus:ring-brand focus:border-brand"
)


def RangeSlider(
    *,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    range_min: int,
    range_max: int,
    step: str = "1",
    min_placeholder: str = "",
    max_placeholder: str = "",
) -> SafeText:
    """A labelled range slider with number inputs and range/point mode toggle.

    Renders a label row (label, two number inputs, toggle button) and a slider
    row (track with one or two custom draggable handles). Defaults to range mode
    (two handles). If min_value and max_value are both set and equal, starts in
    point mode (single handle). The toggle switches between modes.
    """
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    point_mode = bool(min_value and max_value and min_value == max_value)
    initial_mode = "point" if point_mode else "range"

    return Component(
        tag_name="div",
        attributes=[("class", "range-slider-block mb-4")],
        children=[
            # ── Label row ──
            Component(
                tag_name="div",
                attributes=[("class", "flex items-center gap-2 mb-1")],
                children=[
                    Label(
                        attributes=[
                            ("class", _FILTER_LABEL_CLASS),
                            ("for", min_input_id),
                        ],
                        children=[label],
                    ),
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "number"),
                            ("name", min_input_id),
                            ("id", min_input_id),
                            ("value", min_value),
                            ("placeholder", min_placeholder),
                            (
                                "class",
                                f"{_RANGE_SLIDER_INPUT_CLASS}"
                                + (" hidden" if point_mode else ""),
                            ),
                        ],
                    ),
                    Span(
                        attributes=[
                            (
                                "class",
                                "range-dash text-body text-sm"
                                + (" hidden" if point_mode else ""),
                            ),
                        ],
                        children=["–"],
                    ),
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "number"),
                            ("name", max_input_id),
                            ("id", max_input_id),
                            ("value", max_value),
                            ("placeholder", max_placeholder),
                            ("class", _RANGE_SLIDER_INPUT_CLASS),
                        ],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            (
                                "class",
                                "range-mode-toggle p-1 text-body hover:text-heading "
                                "rounded cursor-pointer shrink-0",
                            ),
                            (
                                "title",
                                "Toggle between range and single value",
                            ),
                            (
                                "aria-label",
                                "Toggle between range and single value",
                            ),
                        ],
                        children=[
                            Span(
                                attributes=[
                                    (
                                        "class",
                                        "range-mode-icon-range"
                                        + (" hidden" if point_mode else ""),
                                    ),
                                ],
                                children=[mark_safe(_RANGE_ICON_SVG)],
                            ),
                            Span(
                                attributes=[
                                    (
                                        "class",
                                        "range-mode-icon-point"
                                        + ("" if point_mode else " hidden"),
                                    ),
                                ],
                                children=[mark_safe(_POINT_ICON_SVG)],
                            ),
                        ],
                    ),
                ],
            ),
            # ── Slider row ──
            Component(
                tag_name="div",
                attributes=[
                    ("class", "range-slider relative h-10 select-none mt-1"),
                    ("data-mode", initial_mode),
                    ("data-min", str(range_min)),
                    ("data-max", str(range_max)),
                    ("data-step", str(step)),
                ],
                children=[
                    Component(
                        tag_name="div",
                        attributes=[
                            (
                                "class",
                                "absolute top-1/2 -translate-y-1/2 w-full h-2 "
                                "rounded-full bg-neutral-quaternary",
                            ),
                        ],
                    ),
                    Component(
                        tag_name="div",
                        attributes=[
                            (
                                "class",
                                "range-track-fill absolute top-1/2 -translate-y-1/2 "
                                "h-2 bg-brand rounded-full",
                            ),
                            ("style", "left:0;width:100%"),
                        ],
                    ),
                    # Min handle (hidden in point mode via JS)
                    Component(
                        tag_name="div",
                        attributes=[
                            (
                                "class",
                                "range-handle range-handle-min absolute top-1/2 "
                                "-translate-y-1/2 w-5 h-5 bg-brand rounded-full "
                                "border-2 border-white shadow cursor-pointer "
                                "hover:scale-110 transition-transform",
                            ),
                            ("data-target", min_input_id),
                            (
                                "style",
                                "left:0" + (";display:none" if point_mode else ""),
                            ),
                        ],
                    ),
                    # Max handle
                    Component(
                        tag_name="div",
                        attributes=[
                            (
                                "class",
                                "range-handle range-handle-max absolute top-1/2 "
                                "-translate-y-1/2 w-5 h-5 bg-brand rounded-full "
                                "border-2 border-white shadow cursor-pointer "
                                "hover:scale-110 transition-transform",
                            ),
                            ("data-target", max_input_id),
                            ("style", "left:100%"),
                        ],
                    ),
                ],
            ),
        ],
    )


_FILTER_FORM_ID = "filter-bar-form"


_FILTER_INPUT_ID = "filter-json-input"


def _filter_collapse_button() -> SafeText:
    return Component(
        tag_name="button",
        attributes=[
            ("type", "button"),
            (
                "onclick",
                "var b=document.getElementById('filter-bar-body');b.classList.toggle('hidden');if(!b.classList.contains('hidden')&&window.initRangeSliders)window.initRangeSliders()",
            ),
            (
                "class",
                "flex items-center gap-2 text-sm font-medium text-body "
                "hover:text-heading mb-2",
            ),
        ],
        children=[
            mark_safe(
                '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" /></svg>'
            ),
            "Filters",
        ],
    )


def _filter_action_row(preset_list_url: str, preset_save_url: str) -> SafeText:
    return Component(
        tag_name="div",
        attributes=[("class", "flex gap-3 items-center")],
        children=[
            Component(
                tag_name="button",
                attributes=[
                    ("type", "submit"),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-white bg-brand "
                        "rounded-lg hover:bg-brand-strong focus:ring-4 "
                        "focus:ring-brand-medium",
                    ),
                ],
                children=["Apply"],
            ),
            Component(
                tag_name="button",
                attributes=[
                    ("type", "button"),
                    (
                        "onclick",
                        f"clearFilterBar('{_FILTER_FORM_ID}', '{_FILTER_INPUT_ID}')",
                    ),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-gray-900 bg-white "
                        "border border-gray-200 rounded-lg hover:bg-gray-100 "
                        "dark:bg-gray-800 dark:border-gray-600 dark:text-gray-400 "
                        "dark:hover:bg-gray-700 dark:hover:text-white",
                    ),
                ],
                children=["Clear"],
            ),
            Span(
                attributes=[
                    ("class", "flex gap-2 items-center"),
                    ("id", "save-preset-area"),
                ],
                children=[
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("id", "preset-name-input"),
                            ("placeholder", "Preset name..."),
                            (
                                "class",
                                "hidden px-3 py-2 text-sm rounded-lg border "
                                "border-default-medium bg-neutral-secondary-medium "
                                "text-heading focus:ring-brand focus:border-brand",
                            ),
                        ],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("id", "save-preset-btn"),
                            ("onclick", "showPresetNameInput()"),
                            (
                                "class",
                                "px-4 py-2 text-sm font-medium text-gray-900 "
                                "bg-white border border-gray-200 rounded-lg "
                                "hover:bg-gray-100 dark:bg-gray-800 "
                                "dark:border-gray-600 dark:text-gray-400 "
                                "dark:hover:bg-gray-700 dark:hover:text-white",
                            ),
                        ],
                        children=["Save Preset"],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("id", "confirm-save-preset-btn"),
                            (
                                "onclick",
                                f"savePreset('{_FILTER_FORM_ID}', '{_FILTER_INPUT_ID}', '{preset_save_url}')",
                            ),
                            (
                                "class",
                                "hidden px-4 py-2 text-sm font-medium text-white "
                                "bg-green-700 rounded-lg hover:bg-green-800 "
                                "focus:ring-4 focus:ring-green-300",
                            ),
                        ],
                        children=["Save"],
                    ),
                ],
            ),
            Component(
                tag_name="div",
                attributes=[
                    ("id", "preset-dropdown"),
                    ("class", "relative"),
                    ("data-preset-list-url", preset_list_url),
                ],
                children=[
                    Span(
                        attributes=[("class", "text-sm text-body")],
                        children=["Loading presets..."],
                    ),
                ],
            ),
        ],
    )


def _filter_bar(fields, filter_json, preset_list_url, preset_save_url) -> SafeText:
    """Shared collapsible filter-bar chrome. `fields` is the per-entity body
    (grids, sliders, checkboxes); the shell adds the collapse toggle, the form,
    the hidden filter-json input and the Apply/Clear/preset action row."""
    return Component(
        tag_name="div",
        attributes=[("id", "filter-bar"), ("class", "mb-6")],
        children=[
            _filter_collapse_button(),
            Component(
                tag_name="div",
                attributes=[
                    ("id", "filter-bar-body"),
                    (
                        "class",
                        "hidden border border-default-medium rounded-base p-4 "
                        "bg-neutral-secondary-medium/50",
                    ),
                ],
                children=[
                    Component(
                        tag_name="form",
                        attributes=[
                            ("id", _FILTER_FORM_ID),
                            ("onsubmit", "return applyFilterBar(event)"),
                        ],
                        children=[
                            Component(
                                tag_name="input",
                                attributes=[
                                    ("type", "hidden"),
                                    ("id", _FILTER_INPUT_ID),
                                    ("name", "filter"),
                                    # NB: Component escapes attribute values, so the
                                    # raw JSON is passed through (no double-escape).
                                    ("value", filter_json),
                                ],
                            ),
                            *fields,
                            _filter_action_row(preset_list_url, preset_save_url),
                        ],
                    ),
                ],
            ),
        ],
    )


def FilterBar(
    filter_json: str = "",
    status_options: list[tuple[str, str]] | None = None,
    preset_list_url: str = "",
    preset_save_url: str = "",
) -> SafeText:
    """Collapsible filter bar for the Game list."""
    from games.models import Game

    if status_options is None:
        status_options = [(s.value, s.label) for s in Game.Status]

    existing = _filter_parse(filter_json)
    status_choice = _filter_get_choice(existing, "status")
    platform_choice = _filter_get_choice(existing, "platform")

    year_min, year_max = _parse_range(existing, "year_released")
    mastered_value = _parse_bool(existing, "mastered")
    playtime = existing.get("playtime_minutes", {})
    if isinstance(playtime, dict):
        playtime_min = _filter_mins_to_hrs(playtime.get("value", ""))
        playtime_max = _filter_mins_to_hrs(playtime.get("value2", ""))
    else:
        playtime_min = ""
        playtime_max = ""

    try:
        year_aggregate = Game.objects.aggregate(
            year_min=models.Min("year_released"), year_max=models.Max("year_released")
        )
    except Exception:
        year_aggregate = {}
    try:
        playtime_aggregate = Game.objects.aggregate(playtime_max=models.Max("playtime"))
    except Exception:
        playtime_aggregate = {}
    year_range_min = max(int(year_aggregate.get("year_min") or 1970), 1970)
    year_range_max = min(int(year_aggregate.get("year_max") or 2030), 2030)
    playtime_range_max = (
        int((playtime_aggregate.get("playtime_max") or 0).total_seconds() / 3600)
        if playtime_aggregate.get("playtime_max")
        else 200
    )

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Status",
                    _enum_filter(
                        "status",
                        status_options,
                        status_choice,
                        nullable=not Game._meta.get_field("status").has_default(),
                    ),
                ),
                _filter_field(
                    "Platform",
                    _model_filter(
                        "platform",
                        platform_choice,
                        search_url="/api/platforms/search",
                        resolver=_resolve_platform_options,
                        nullable=Game._meta.get_field("platform").null,
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Year",
            input_name_prefix="filter-year",
            min_value=year_min,
            max_value=year_max,
            range_min=year_range_min,
            range_max=year_range_max,
            min_placeholder="e.g. 2020",
            max_placeholder="e.g. 2024",
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex items-end gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-mastered", "Mastered", mastered_value),
            ],
        ),
        RangeSlider(
            label="Playtime",
            input_name_prefix="filter-playtime",
            min_value=playtime_min,
            max_value=playtime_max,
            range_min=0,
            range_max=playtime_range_max,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 100",
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def _selectable_filter_tag(
    value: str, label: str, *, excluded: bool = False
) -> SafeText:
    """A selected (\u2713) or excluded (\u2717) value pill in the SelectableFilter."""
    checkmark = "\u2717" if excluded else "\u2713"
    css = "sf-tag sf-excluded" if excluded else "sf-tag"
    return Span(
        attributes=[
            ("class", css),
            ("data-value", value),
            ("data-type", "exclude" if excluded else "include"),
        ],
        children=[
            Span(
                attributes=[("class", "sf-tag-text")],
                children=[f"{checkmark} {label}"],
            ),
            Component(
                tag_name="button",
                attributes=[
                    ("type", "button"),
                    ("class", "sf-remove"),
                    ("aria-label", "Remove"),
                ],
                children=["\u00d7"],
            ),
        ],
    )


def _selectable_filter_modifier_tag(modifier: str, label: str) -> SafeText:
    """An active modifier pill ((Any) / (None)) in the SelectableFilter."""
    return Span(
        attributes=[
            ("class", "sf-modifier-tag active"),
            ("data-modifier", modifier),
        ],
        children=[label],
    )


def _selectable_filter_modifier_option(modifier: str, label: str) -> SafeText:
    """A modifier choice in the SelectableFilter dropdown list."""
    return Component(
        tag_name="div",
        attributes=[
            ("class", "sf-option sf-modifier-option"),
            ("data-modifier", modifier),
            ("data-label", label),
        ],
        children=[
            Span(
                attributes=[("class", "sf-option-label")],
                children=[label],
            ),
        ],
    )


def _selectable_filter_option(value: str, label: str) -> SafeText:
    """An option row with include (+) and exclude (\u2212) buttons."""
    return Component(
        tag_name="div",
        attributes=[
            ("class", "sf-option"),
            ("data-value", value),
            ("data-label", label),
        ],
        children=[
            Span(
                attributes=[("class", "sf-option-label")],
                children=[label],
            ),
            Span(
                attributes=[("class", "sf-option-buttons")],
                children=[
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("class", "sf-btn-include"),
                            ("data-action", "include"),
                            ("title", "Include"),
                        ],
                        children=["+"],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "button"),
                            ("class", "sf-btn-exclude"),
                            ("data-action", "exclude"),
                            ("title", "Exclude"),
                        ],
                        children=["\u2212"],
                    ),
                ],
            ),
        ],
    )


def SelectableFilter(
    field_name: str,
    options: list[tuple[str, str]],
    selected: list[str] | None = None,
    excluded: list[str] | None = None,
    modifier: str = "",
    nullable: bool = True,
) -> "SafeText":
    """Stash-style selectable filter with search, include/exclude, modifier tags."""
    selected = selected or []
    excluded = excluded or []

    modifier_options = [("NOT_NULL", "(Any)")]
    if nullable:
        modifier_options.append(("IS_NULL", "(None)"))

    active_modifier_tag = ""
    inactive_modifier_options: list[SafeText] = []
    for modifier_value, modifier_label in modifier_options:
        if modifier == modifier_value:
            active_modifier_tag = _selectable_filter_modifier_tag(
                modifier_value, modifier_label
            )
        else:
            inactive_modifier_options.append(
                _selectable_filter_modifier_option(modifier_value, modifier_label)
            )

    selected_tags: list[SafeText] = []
    for value in selected:
        selected_tags.append(
            _selectable_filter_tag(value, _find_label(options, value), excluded=False)
        )
    for value in excluded:
        selected_tags.append(
            _selectable_filter_tag(value, _find_label(options, value), excluded=True)
        )

    option_rows: list[SafeText] = []
    for value, label in options:
        option_rows.append(_selectable_filter_option(value, label))

    selected_area_children: list[SafeText] = []
    if active_modifier_tag:
        selected_area_children.append(active_modifier_tag)
    selected_area_children.extend(selected_tags)

    options_area_children: list[SafeText] = []
    options_area_children.extend(inactive_modifier_options)
    options_area_children.extend(option_rows)

    return Component(
        tag_name="div",
        attributes=[
            ("class", "sf-container"),
            ("data-selectable-filter", field_name),
            *([("data-modifier", modifier)] if modifier else []),
        ],
        children=[
            Component(
                tag_name="div",
                attributes=[("class", "sf-selected")],
                children=selected_area_children,
            ),
            Component(
                tag_name="input",
                attributes=[
                    ("type", "text"),
                    ("class", "sf-search"),
                    ("placeholder", "Search\u2026"),
                ],
            ),
            Component(
                tag_name="div",
                attributes=[("class", "sf-options")],
                children=options_area_children,
            ),
        ],
    )


def _find_label(options: list[tuple[str, str]], value: str) -> str:
    for v, label in options:
        if str(v) == str(value):
            return label
    return value


def SessionFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Session list."""
    from games.models import Game, Session

    existing = _filter_parse(filter_json)
    game_choice = _filter_get_choice(existing, "game")
    device_choice = _filter_get_choice(existing, "device")

    duration_min, duration_max = _parse_range(existing, "duration_minutes")
    duration_min = _filter_mins_to_hrs(duration_min)
    duration_max = _filter_mins_to_hrs(duration_max)
    emulated_value = _parse_bool(existing, "emulated")
    is_active_value = _parse_bool(existing, "is_active")
    try:
        duration_aggregate = Session.objects.aggregate(
            duration_max=models.Max("duration_total")
        )
        duration_range_max = max(
            int((duration_aggregate.get("duration_max") or 0).total_seconds() / 3600)
            if duration_aggregate.get("duration_max")
            else 200,
            1,
        )
    except Exception:
        duration_range_max = 200

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "game",
                        game_choice,
                        search_url="/api/games/search",
                        resolver=_resolve_game_options,
                        nullable=not Game._meta.get_field("name").has_default(),
                    ),
                ),
                _filter_field(
                    "Device",
                    _model_filter(
                        "device",
                        device_choice,
                        search_url="/api/devices/search",
                        resolver=_resolve_device_options,
                        nullable=Session._meta.get_field("device").null,
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Duration",
            input_name_prefix="filter-playtime",
            min_value=duration_min,
            max_value=duration_max,
            range_min=0,
            range_max=duration_range_max,
            min_placeholder="e.g. 0.5",
            max_placeholder="e.g. 10",
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-emulated", "Emulated", emulated_value),
                _filter_checkbox("filter-active", "Active", is_active_value),
            ],
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def PurchaseFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Purchase list."""
    from games.models import Purchase

    type_options = [(value, label) for value, label in Purchase.TYPES]
    ownership_options = [(value, label) for value, label in Purchase.OWNERSHIP_TYPES]
    existing = _filter_parse(filter_json)
    game_choice = _filter_get_choice(existing, "games")
    platform_choice = _filter_get_choice(existing, "platform")
    type_choice = _filter_get_choice(existing, "type")
    ownership_choice = _filter_get_choice(existing, "ownership_type")
    price_min, price_max = _parse_range(existing, "price")
    is_refunded_value = _parse_bool(existing, "is_refunded")
    try:
        price_aggregate = Purchase.objects.aggregate(
            price_min=models.Min("price"), price_max=models.Max("price")
        )
        price_range_min = int(price_aggregate.get("price_min") or 0)
        price_range_max = max(int(price_aggregate.get("price_max") or 100), 1)
    except Exception:
        price_range_min, price_range_max = 0, 100

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "games",
                        game_choice,
                        search_url="/api/games/search",
                        resolver=_resolve_game_options,
                        nullable=False,
                    ),
                ),
                _filter_field(
                    "Platform",
                    _model_filter(
                        "platform",
                        platform_choice,
                        search_url="/api/platforms/search",
                        resolver=_resolve_platform_options,
                        nullable=Purchase._meta.get_field("platform").null,
                    ),
                ),
                _filter_field(
                    "Type",
                    _enum_filter(
                        "type",
                        type_options,
                        type_choice,
                        nullable=not Purchase._meta.get_field("type").has_default(),
                    ),
                ),
                _filter_field(
                    "Ownership",
                    _enum_filter(
                        "ownership_type",
                        ownership_options,
                        ownership_choice,
                        nullable=not Purchase._meta.get_field(
                            "ownership_type"
                        ).has_default(),
                    ),
                ),
            ],
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex items-end gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-refunded", "Refunded", is_refunded_value),
            ],
        ),
        RangeSlider(
            label="Price",
            input_name_prefix="filter-price",
            min_value=price_min,
            max_value=price_max,
            range_min=price_range_min,
            range_max=price_range_max,
            min_placeholder="0.00",
            max_placeholder="100.00",
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)
