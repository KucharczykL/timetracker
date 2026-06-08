"""Search field + dropdown select component (pure Python, domain-agnostic).

Pairs a search box with a dropdown of options. Supports single/multi select;
in multi-select, chosen items render as removable ``Pill``s, each backed by a
hidden ``<input>`` so an existing ``ModelMultipleChoiceField`` keeps validating.

This module imports only from ``common.components`` — it has no Django-forms or
``games`` knowledge. Styling is inline Tailwind utilities; behavioural hooks are
``data-*`` attributes wired up by ``games/static/js/search_select.js``.

Option sourcing follows two axes. *Population*: options are either rendered
inline up front (``options=``, no ``search_url``) or fetched from ``search_url``.
*Completeness*: without a ``search_url`` the inline set is the whole dataset and
filtering is purely client-side; with a ``search_url`` the loaded rows are a
window, so the JS filters the loaded rows instantly on each keystroke while
issuing a debounced server request for the rest. ``prefetch`` (rows to load on
first open, ``0`` = none) seeds that window so the panel is populated before the
user types.
"""

from collections.abc import Callable, Iterable
from typing import TypedDict

from django.utils.safestring import SafeText

from common.components.core import Component, HTMLAttribute
from common.components.primitives import Pill


class SearchSelectOption(TypedDict):
    value: str | int
    label: str
    data: dict[str, str]  # becomes data-* attrs on the row / pill


# The pills and the search box share one flex-wrap row (with padding) so the
# widget reads as a single clickable field; the pills wrapper uses `contents`
# so its pills/hidden inputs flow as direct participants of that row, inline
# with the search input. The options panel is absolute, so it sits outside the
# flex flow. (border omitted intentionally — see if it's needed later.)
_CONTAINER_CLASS = (
    "relative flex flex-wrap items-center gap-1 p-2 "
    "rounded-base bg-neutral-secondary-medium"
)
_PILLS_CLASS = "contents"
_SEARCH_CLASS = (
    "flex-1 min-w-[8rem] border-0 bg-transparent text-sm text-heading "
    "focus:ring-0 focus:outline-hidden placeholder:text-body"
)
# top-full anchors the panel to the container's bottom edge: as an absolutely
# positioned child of the flex field, its static position would otherwise be
# centered by items-center and overlap the search box.
_OPTIONS_CLASS = (
    "absolute z-10 top-full left-0 right-0 mt-1 overflow-y-auto "
    "border border-default-medium rounded-base bg-neutral-secondary-medium shadow-lg"
)
_OPTION_ROW_CLASS = "px-3 py-2 text-sm text-heading cursor-pointer hover:bg-brand/15"
_NO_RESULTS_CLASS = "px-3 py-2 text-sm italic text-body hidden"

# Approximate rendered height of one option row (px-3 py-2 text-sm) in rem,
# used to derive the panel's max-height from items_visible.
_ROW_HEIGHT_REM = 2.25

# ── FilterSelect styling ───────────────────────────────────────────────────
# Inline class strings (ported verbatim from the retired SelectableFilter CSS)
# so the filter combobox is fully self-styled — nothing in input.css. JS-added
# rows/pills are cloned from server-rendered <template>s, so these strings live
# only here — never duplicated in search_select.js.
_FILTER_INCLUDE_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-brand/15 text-heading"
)
_FILTER_EXCLUDE_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-red-500/15 text-red-600 line-through decoration-red-400"
)
_FILTER_MODIFIER_PILL_CLASS = (
    "inline-flex items-center px-2 py-0.5 text-sm rounded "
    "bg-amber-500/15 text-amber-600 cursor-pointer"
)
_FILTER_PILL_REMOVE_CLASS = "ml-1 text-body hover:text-heading font-bold cursor-pointer"
_FILTER_OPTION_ROW_CLASS = (
    "flex items-center justify-between px-2 py-1 rounded text-sm "
    "hover:bg-neutral-secondary-strong cursor-pointer"
)
_FILTER_OPTION_LABEL_CLASS = "truncate text-body"
_FILTER_OPTION_BUTTONS_CLASS = "flex gap-1 ml-2 shrink-0"
# text-body keeps the +/− readable on dark backgrounds; hover:border-brand-strong
# keeps the edge visible against the brand hover fill.
_FILTER_ACTION_BUTTON_CLASS = (
    "w-5 h-5 flex items-center justify-center text-xs font-bold rounded text-body "
    "border border-brand "
    "hover:bg-brand hover:text-white hover:border-brand-strong"
)
_FILTER_MODIFIER_ROW_CLASS = (
    "px-2 py-1 text-sm text-body hover:bg-neutral-secondary-strong cursor-pointer"
)


def _normalize_option(option) -> SearchSelectOption:
    """Coerce a dict option or a ``(value, label)`` tuple into the TypedDict."""
    if isinstance(option, dict):
        return {
            "value": option["value"],
            "label": option["label"],
            "data": option.get("data") or {},
        }
    value, label = option
    return {"value": value, "label": label, "data": {}}


def _data_attributes(data: dict[str, str]) -> list[HTMLAttribute]:
    return [(f"data-{key}", str(value)) for key, value in data.items()]


def _hidden_input(name: str, value) -> SafeText:
    return Component(
        tag_name="input",
        attributes=[("type", "hidden"), ("name", name), ("value", str(value))],
    )


def _label_slot(text: str, *, extra_class: str = "") -> SafeText:
    """A ``<span data-search-select-label>`` holding a row/pill's visible label. JS fills this
    one node when cloning the shape from a ``<template>``, so labels are the only
    thing the JS sets — all classes and structure stay server-side."""
    attributes: list[HTMLAttribute] = [("data-search-select-label", "")]
    if extra_class:
        attributes.append(("class", extra_class))
    return Component(tag_name="span", attributes=attributes, children=[text])


def _template(name: str, node: SafeText) -> SafeText:
    """Wrap a prototype row/pill in an inert ``<template data-search-select-template=name>`` that
    the JS clones. Rendering the prototype with the real component keeps the JS
    free of any markup or class strings."""
    return Component(
        tag_name="template",
        attributes=[("data-search-select-template", name)],
        children=[node],
    )


# A placeholder option for rendering template prototypes (JS overwrites it).
_BLANK_OPTION: SearchSelectOption = {"value": "", "label": "", "data": {}}


def _option_row(option: SearchSelectOption) -> SafeText:
    return Component(
        tag_name="div",
        attributes=[
            ("data-search-select-option", ""),
            ("data-value", str(option["value"])),
            ("data-label", option["label"]),
            ("class", _OPTION_ROW_CLASS),
            *_data_attributes(option["data"]),
        ],
        children=[_label_slot(option["label"])],
    )


def _combobox_shell(
    *,
    container_attributes: list[HTMLAttribute],
    pills: SafeText,
    search_attributes: list[HTMLAttribute],
    options_children: list[SafeText],
    always_visible: bool,
    items_visible: int,
    templates: list[SafeText] | None = None,
) -> SafeText:
    """Assemble the shared, domain-agnostic combobox skeleton.

    Every combobox built on top of this shell has the same three regions in the
    same order: the ``pills`` region, the search box, and the options panel (which
    always carries a trailing no-results node). Callers supply the already-built
    ``pills`` region, the ``search_attributes`` for the text box, the
    ``options_children`` (value rows plus any pinned pseudo-options), the
    ``container_attributes`` that carry the widget's identity and behaviour flags,
    and any ``templates`` (inert ``<template>`` prototypes the JS clones for
    dynamically-added rows/pills). The shell knows nothing about how individual
    rows or pills look.
    """
    search = Component(tag_name="input", attributes=search_attributes)

    no_results = Component(
        tag_name="div",
        attributes=[
            ("data-search-select-no-results", ""),
            ("class", _NO_RESULTS_CLASS),
        ],
        children=["No results"],
    )
    options_class = _OPTIONS_CLASS if always_visible else _OPTIONS_CLASS + " hidden"
    options_panel = Component(
        tag_name="div",
        attributes=[
            ("data-search-select-options", ""),
            ("style", f"max-height: {items_visible * _ROW_HEIGHT_REM:.2f}rem"),
            ("class", options_class),
        ],
        children=[*options_children, no_results],
    )

    return Component(
        tag_name="div",
        attributes=container_attributes,
        children=[pills, search, options_panel, *(templates or [])],
    )


def SearchSelect(
    *,
    name: str,
    selected: list[SearchSelectOption] | None = None,
    options: list[SearchSelectOption] | None = None,
    search_url: str = "",
    multi_select: bool = False,
    always_visible: bool = False,
    items_visible: int = 5,
    items_scroll: int = 10,
    prefetch: int = 0,
    placeholder: str = "Search…",
    id: str = "",
    sync_url: bool = False,
    autofocus: bool = False,
) -> SafeText:
    """Render the search-select widget. See module docstring for the contract."""
    selected = [_normalize_option(option) for option in (selected or [])]
    options = [_normalize_option(option) for option in (options or [])]

    # ── Pills + their hidden inputs (the submitted channel) ──
    # Multi-select renders a removable Pill per value; single-select renders no
    # pill — the committed label shows inside the search box instead, with a
    # lone hidden input carrying the value. Both keep the hidden input(s) inside
    # `[data-search-select-pills]` so the JS reads/writes values uniformly.
    pills_children: list[SafeText] = []
    search_value = ""
    if multi_select:
        for option in selected:
            pills_children.append(
                Pill(
                    option["label"],
                    value=str(option["value"]),
                    removable=True,
                    label_slot=True,
                    attributes=_data_attributes(option["data"]),
                )
            )
            pills_children.append(_hidden_input(name, option["value"]))
    elif selected:
        option = selected[0]
        pills_children.append(_hidden_input(name, option["value"]))
        search_value = option["label"]

    pills = Component(
        tag_name="div",
        attributes=[("data-search-select-pills", ""), ("class", _PILLS_CLASS)],
        children=pills_children,
    )

    # ── Search box (NO name — the query is never submitted) ──
    search_attrs: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("type", "text"),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    if autofocus:
        search_attrs.append(("autofocus", ""))
    if search_value:
        search_attrs.append(("value", search_value))

    # ── Options panel (pre-rendered only when there is no search_url) ──
    option_rows = [_option_row(option) for option in options] if not search_url else []

    # ── Templates the JS clones: a row when results are fetched, a pill when
    #    multi-select adds chosen items. ──
    templates: list[SafeText] = []
    if search_url:
        templates.append(_template("row", _option_row(_BLANK_OPTION)))
    if multi_select:
        templates.append(
            _template("pill", Pill("", value="", removable=True, label_slot=True))
        )

    container_attributes: list[HTMLAttribute] = [
        ("data-search-select", ""),
        ("data-name", name),
        ("data-search-url", search_url),
        ("data-multi", "true" if multi_select else "false"),
        ("data-always-visible", "true" if always_visible else "false"),
        ("data-items-visible", str(items_visible)),
        ("data-items-scroll", str(items_scroll)),
        ("data-prefetch", str(prefetch)),
        ("data-sync-url", "true" if sync_url else "false"),
        ("class", _CONTAINER_CLASS),
    ]
    if id:
        container_attributes.append(("id", id))

    return _combobox_shell(
        container_attributes=container_attributes,
        pills=pills,
        search_attributes=search_attrs,
        options_children=option_rows,
        always_visible=always_visible,
        items_visible=items_visible,
        templates=templates,
    )


def _filter_remove_button() -> SafeText:
    return Component(
        tag_name="button",
        attributes=[
            ("type", "button"),
            ("data-pill-remove", ""),
            ("class", _FILTER_PILL_REMOVE_CLASS),
            ("aria-label", "Remove"),
        ],
        children=["×"],
    )


def _filter_value_pill(option: SearchSelectOption, kind: str) -> SafeText:
    """An include (✓) or exclude (✗) value pill. ``kind`` is "include"/"exclude"."""
    symbol = "✓" if kind == "include" else "✗"
    css = (
        _FILTER_INCLUDE_PILL_CLASS if kind == "include" else _FILTER_EXCLUDE_PILL_CLASS
    )
    return Component(
        tag_name="span",
        attributes=[
            ("class", css),
            ("data-pill", ""),
            ("data-value", str(option["value"])),
            ("data-label", option["label"]),
            ("data-search-select-type", kind),
            *_data_attributes(option["data"]),
        ],
        children=[f"{symbol} ", _label_slot(option["label"]), _filter_remove_button()],
    )


def _filter_modifier_pill(modifier_value: str, label: str) -> SafeText:
    """The lone, sticky modifier pill (e.g. "(Any)"/"(None)")."""
    return Component(
        tag_name="span",
        attributes=[
            ("class", _FILTER_MODIFIER_PILL_CLASS),
            ("data-pill", ""),
            ("data-search-select-modifier", modifier_value),
        ],
        children=[_label_slot(label), _filter_remove_button()],
    )


def _filter_action_button(action: str, symbol: str, title: str) -> SafeText:
    return Component(
        tag_name="button",
        attributes=[
            ("type", "button"),
            ("data-search-select-action", action),
            ("class", _FILTER_ACTION_BUTTON_CLASS),
            ("title", title),
        ],
        children=[symbol],
    )


def _filter_option_row(value: str | int, label: str) -> SafeText:
    """A value row with include (+) and exclude (−) buttons."""
    return Component(
        tag_name="div",
        attributes=[
            ("data-search-select-option", ""),
            ("data-value", str(value)),
            ("data-label", label),
            ("class", _FILTER_OPTION_ROW_CLASS),
        ],
        children=[
            _label_slot(label, extra_class=_FILTER_OPTION_LABEL_CLASS),
            Component(
                tag_name="span",
                attributes=[("class", _FILTER_OPTION_BUTTONS_CLASS)],
                children=[
                    _filter_action_button("include", "+", "Include"),
                    _filter_action_button("exclude", "−", "Exclude"),
                ],
            ),
        ],
    )


def _filter_modifier_row(modifier_value: str, label: str) -> SafeText:
    """A pinned pseudo-option row. It carries no ``data-search-select-option`` so the text
    filter never hides it — modifiers stay visible at the top of the panel."""
    return Component(
        tag_name="div",
        attributes=[
            ("data-search-select-modifier-option", modifier_value),
            ("data-label", label),
            ("class", _FILTER_MODIFIER_ROW_CLASS),
        ],
        children=[label],
    )


def FilterSelect(
    *,
    field_name: str,
    options: list | None = None,
    included: list | None = None,
    excluded: list | None = None,
    modifier: str = "",
    modifier_options: list[tuple[str, str]] | None = None,
    search_url: str = "",
    prefetch: int = 0,
    items_visible: int = 6,
    items_scroll: int = 10,
    placeholder: str = "Search…",
    id: str = "",
) -> SafeText:
    """Include/exclude filter combobox built on the shared ``_combobox_shell``.

    Like ``SearchSelect`` but each value row carries +/− buttons that add an
    *include* (✓) or *exclude* (✗) pill, plus an optional set of pinned
    ``modifier_options`` (e.g. ``[("NOT_NULL", "(Any)"), ("IS_NULL", "(None)")]``)
    rendered above the value rows. A selected modifier is mutually exclusive with
    value pills. State is read from the DOM into the filter JSON by
    ``readSearchSelect`` (filter mode) — nothing is submitted by ``name``.

    ``included``/``excluded`` are resolved options (value + label) so pills show
    labels even when the value rows come from ``search_url``. ``options``
    pre-renders the value rows for the complete-set (no ``search_url``) case.
    """
    options = [_normalize_option(option) for option in (options or [])]
    included = [_normalize_option(option) for option in (included or [])]
    excluded = [_normalize_option(option) for option in (excluded or [])]
    modifier_options = modifier_options or []

    active_modifier_label = ""
    for modifier_value, label in modifier_options:
        if modifier_value == modifier:
            active_modifier_label = label
            break

    # ── Pills: a lone modifier pill, or include/exclude value pills ──
    pills_children: list[SafeText] = []
    if active_modifier_label:
        pills_children.append(_filter_modifier_pill(modifier, active_modifier_label))
    else:
        for option in included:
            pills_children.append(_filter_value_pill(option, "include"))
        for option in excluded:
            pills_children.append(_filter_value_pill(option, "exclude"))

    pills = Component(
        tag_name="div",
        attributes=[("data-search-select-pills", ""), ("class", _PILLS_CLASS)],
        children=pills_children,
    )

    # ── Search box (NO name — the query is never submitted) ──
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("type", "text"),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]

    # ── Options: pinned modifier rows, then value rows (pre-rendered only when
    #    there is no search_url; otherwise the JS fetches them) ──
    modifier_rows = [
        _filter_modifier_row(value, label) for value, label in modifier_options
    ]
    value_rows = (
        [_filter_option_row(option["value"], option["label"]) for option in options]
        if not search_url
        else []
    )

    # ── Templates the JS clones: include/exclude pills (added on click), the
    #    modifier pill (when modifiers exist), and a value row (when fetched). ──
    templates: list[SafeText] = [
        _template("pill-include", _filter_value_pill(_BLANK_OPTION, "include")),
        _template("pill-exclude", _filter_value_pill(_BLANK_OPTION, "exclude")),
    ]
    if modifier_options:
        templates.append(_template("pill-modifier", _filter_modifier_pill("", "")))
    if search_url:
        templates.append(_template("row", _filter_option_row("", "")))

    container_attributes: list[HTMLAttribute] = [
        ("data-search-select", ""),
        ("data-search-select-mode", "filter"),
        ("data-name", field_name),
        ("data-search-url", search_url),
        ("data-multi", "true"),
        ("data-always-visible", "false"),
        ("data-items-visible", str(items_visible)),
        ("data-items-scroll", str(items_scroll)),
        ("data-prefetch", str(prefetch)),
        ("data-sync-url", "false"),
        ("class", _CONTAINER_CLASS),
    ]
    if modifier:
        container_attributes.append(("data-modifier", modifier))
    if id:
        container_attributes.append(("id", id))

    return _combobox_shell(
        container_attributes=container_attributes,
        pills=pills,
        search_attributes=search_attributes,
        options_children=[*modifier_rows, *value_rows],
        always_visible=False,
        items_visible=items_visible,
        templates=templates,
    )


def searchselect_selected(
    values: list,
    resolver: Callable[[list], Iterable[SearchSelectOption]],
) -> list[SearchSelectOption]:
    """Resolve ``values`` into ``SearchSelectOption``s via ``resolver``.

    ``resolver(values)`` should resolve ONLY the given ids (a ``pk__in`` query)
    — never iterating all choices, so it stays cheap.
    """
    if not values:
        return []
    return [_normalize_option(option) for option in resolver(values)]
