"""Search field + dropdown select component (pure Python, domain-agnostic).

Pairs a search box with a dropdown of options. Supports single/multi select;
in multi-select, chosen items render as removable ``Pill``s, each backed by a
hidden ``<input>`` so an existing ``ModelMultipleChoiceField`` keeps validating.

This module imports only from ``common.components`` — it has no Django-forms or
``games`` knowledge. Styling is inline Tailwind utilities; behavioural hooks are
``data-*`` attributes wired up by ``games/static/js/search_select.js``.
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


# removed border and border-default-medium, see later if it's needed
_CONTAINER_CLASS = "relative rounded-base bg-neutral-secondary-medium"
# The pills and the search box share one flex-wrap row so the widget reads as a
# single field; the pills wrapper uses `contents` so its pills/hidden inputs
# flow as direct participants of that row, inline with the search input.
_FIELD_CLASS = "flex flex-wrap items-center gap-1 p-2"
_PILLS_CLASS = "contents"
_SEARCH_CLASS = (
    "flex-1 min-w-[8rem] border-0 bg-transparent text-sm text-heading "
    "focus:ring-0 focus:outline-hidden placeholder:text-body"
)
_OPTIONS_CLASS = (
    "absolute z-10 left-0 right-0 mt-1 overflow-y-auto border border-default-medium "
    "rounded-base bg-neutral-secondary-medium shadow-lg"
)
_OPTION_ROW_CLASS = "px-3 py-2 text-sm text-heading cursor-pointer hover:bg-brand/15"
_NO_RESULTS_CLASS = "px-3 py-2 text-sm italic text-body hidden"

# Approximate rendered height of one option row (px-3 py-2 text-sm) in rem,
# used to derive the panel's max-height from items_visible.
_ROW_HEIGHT_REM = 2.25


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


def _option_row(option: SearchSelectOption) -> SafeText:
    return Component(
        tag_name="div",
        attributes=[
            ("data-ss-option", ""),
            ("data-value", str(option["value"])),
            ("data-label", option["label"]),
            ("class", _OPTION_ROW_CLASS),
            *_data_attributes(option["data"]),
        ],
        children=[option["label"]],
    )


def _combobox_shell(
    *,
    container_attributes: list[HTMLAttribute],
    pills: SafeText,
    search_attributes: list[HTMLAttribute],
    options_children: list[SafeText],
    always_visible: bool,
    items_visible: int,
) -> SafeText:
    """Assemble the shared, domain-agnostic combobox skeleton.

    Every combobox built on top of this shell has the same three regions in the
    same order: the ``pills`` region, the search box, and the options panel (which
    always carries a trailing no-results node). Callers supply the already-built
    ``pills`` region, the ``search_attributes`` for the text box, the
    ``options_children`` (value rows plus any pinned pseudo-options), and the
    ``container_attributes`` that carry the widget's identity and behaviour flags.
    The shell knows nothing about how individual rows or pills look.
    """
    search = Component(tag_name="input", attributes=search_attributes)

    no_results = Component(
        tag_name="div",
        attributes=[("data-ss-no-results", ""), ("class", _NO_RESULTS_CLASS)],
        children=["No results"],
    )
    options_class = _OPTIONS_CLASS if always_visible else _OPTIONS_CLASS + " hidden"
    options_panel = Component(
        tag_name="div",
        attributes=[
            ("data-ss-options", ""),
            ("style", f"max-height: {items_visible * _ROW_HEIGHT_REM:.2f}rem"),
            ("class", options_class),
        ],
        children=[*options_children, no_results],
    )

    return Component(
        tag_name="div",
        attributes=container_attributes,
        children=[pills, search, options_panel],
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
    placeholder: str = "Search…",
    id: str = "",
    sync_url: bool = False,
    autofocus: bool = False,
) -> SafeText:
    """Render the search-select widget. See module docstring for the contract."""
    selected = [_normalize_option(o) for o in (selected or [])]
    options = [_normalize_option(o) for o in (options or [])]

    # ── Pills + their hidden inputs (the submitted channel) ──
    # Multi-select renders a removable Pill per value; single-select renders no
    # pill — the committed label shows inside the search box instead, with a
    # lone hidden input carrying the value. Both keep the hidden input(s) inside
    # `[data-ss-pills]` so the JS reads/writes values uniformly.
    pills_children: list[SafeText] = []
    search_value = ""
    if multi_select:
        for option in selected:
            pills_children.append(
                Pill(
                    option["label"],
                    value=str(option["value"]),
                    removable=True,
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
        attributes=[("data-ss-pills", ""), ("class", _PILLS_CLASS)],
        children=pills_children,
    )

    # ── Search box (NO name — the query is never submitted) ──
    search_attrs: list[HTMLAttribute] = [
        ("data-ss-search", ""),
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
    option_rows = [_option_row(o) for o in options] if not search_url else []

    container_attributes: list[HTMLAttribute] = [
        ("data-search-select", ""),
        ("data-name", name),
        ("data-search-url", search_url),
        ("data-multi", "true" if multi_select else "false"),
        ("data-always-visible", "true" if always_visible else "false"),
        ("data-items-visible", str(items_visible)),
        ("data-items-scroll", str(items_scroll)),
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
    return [_normalize_option(o) for o in resolver(values)]
