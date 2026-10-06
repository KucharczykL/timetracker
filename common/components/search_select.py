"""Search field + dropdown select component (pure Python, domain-agnostic).

Pairs a search box with a dropdown of options. Supports single/multi select;
in multi-select, chosen items render as removable ``Pill``s, each backed by a
hidden ``<input>`` so an existing ``ModelMultipleChoiceField`` keeps validating.

This module imports only from ``common.components`` — it has no Django-forms or
``games`` knowledge. Styling is inline Tailwind utilities; behavioural hooks are
``data-*`` attributes wired up by ``ts/elements/search-select.ts`` (compiled to
``games/static/js/dist/elements/search-select.js``).

**Field id / label association**: when ``SearchSelect`` is used as a Django form
widget, the field ``id`` (e.g. ``id_related_game``) is placed on the inner
search ``<input>`` (``[data-search-select-search]``), making it a real labelable
control. ``<label for="id_X">`` therefore focuses the search box, and
``document.querySelector('#id_X').disabled`` behaves as for a native input.

**Disabling**: set ``disabled`` directly on the field id (or on the inner
``[data-search-select-search]`` input). The field box greys itself via
``DISABLED_WITHIN_CLASS`` in ``_BOX_CLASS``. Callers toggle only the control's
``disabled`` — never styles.

**ARIA combobox semantics** (issue #154): the search input is a
``role="combobox"`` with ``aria-expanded``/``aria-autocomplete``; the options
panel is a ``role="listbox"`` (``aria-multiselectable`` when multi); option and
modifier rows are ``role="option"`` with ``aria-selected``. What
``aria-selected`` means depends on the mode: in single-select the JS mirrors
the keyboard highlight into it (the APG list-autocomplete convention); in
multi/filter mode — where the listbox is ``aria-multiselectable`` and the
attribute conveys set membership — it is true for rows whose value has a pill
(or the active modifier row), the server pre-renders that state, and the
keyboard highlight is conveyed by ``aria-activedescendant`` alone. The
id-based wiring (``aria-controls`` on the input, stable ``id``s on the panel
and rows, and ``aria-activedescendant`` tracking the highlight) is assigned by
the JS at init — never server-side, because the nested filter builder clones
whole ``<search-select>`` prototypes and server-rendered ids would be
duplicated across clones.

Option sourcing follows two axes. *Population*: options are either rendered
inline up front (``options=``, no ``search_url``) or fetched from ``search_url``.
*Completeness*: without a ``search_url`` the inline set is the whole dataset and
filtering is purely client-side; with a ``search_url`` the loaded rows are a
window, so the JS filters the loaded rows instantly on each keystroke while
issuing a debounced server request for the rest. ``prefetch`` (rows to load on
first open, ``0`` = none) seeds that window so the panel is populated before the
user types.
"""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal, NamedTuple, NotRequired, TypedDict
from urllib.parse import urlencode

from django.utils.functional import Promise

from common.components.core import (
    Attributes,
    Child,
    Element,
    Fragment,
    HTMLAttribute,
    Node,
)
from common.components.custom_elements import (
    DROPDOWN_GROUP_HEADER_CLASS,
    DROPDOWN_ITEM_SHAPE,
    Dropdown,
    DropdownPanel,
    FilterMode,
    SearchSelectCreate,
    _as_dialog_trigger,
    _Dropdown,
    _PresetPanelElement,
    _SearchSelect,
)
from common.components.form_dialog import CreatedOption, form_dialog_link
from common.components.modal import ElementId
from common.components.primitives import (
    CLOSED_POPOVER,
    AppliedDot,
    ButtonColor,
    ButtonGroupMember,
    ButtonShape,
    ControlButton,
    Div,
    FilterWidgetPath,
    Icon,
    Input,
    Pill,
    Span,
    Template,
    field_box_class,
    filter_widget_attributes,
)


class LiteralParam(TypedDict):
    """A value the server states at render time."""

    value: str


class FieldParam(TypedDict):
    """The name of a sibling form field, read when used."""

    field: str


#: One mapping, read by the search query and by the create POST.
#: A field source is a dependency: a change to it searches again.
type ParamSources = dict[str, LiteralParam | FieldParam]


class SearchSelectOption(CreatedOption):
    """One picker row; ``data`` becomes its ``data-*``."""

    #: Muted after the label; never searched.
    hint: NotRequired[str]


# A lightweight (value, label) pair used wherever only those two fields are
# needed — e.g. filter pill lists and modifier pseudo-options. The richer
# SearchSelectOption adds a ``data`` dict for extra row attributes.
LabeledOption = tuple[str, str]

# FilterSelect's two visual personalities: "field" is the bordered form-field
# look (the nested builder's leaf rows); "panel" is the GitHub-label-picker look for widgets
# hosted inside a ComboboxDropdown dialog (pills row above the field box,
# always-visible statically-flowing options).
type FilterSelectLayout = Literal["field", "panel"]


class OptionGroup(NamedTuple):
    """A labelled run of options for a grouped single-select panel.

    Passed as ``SearchSelect(option_groups=[...])`` (mutually exclusive with
    ``options=``); the widget renders a non-selectable header row before each
    group's option rows. Used by the filter builder's add-criterion field picker
    (#191), which groups fields by criterion kind.
    """

    label: str
    options: list[SearchSelectOption]


_BOX_CLASS = field_box_class("full")
_CONTAINER_CLASS = "block"
_PILLS_CLASS = "contents"
# Under 16px text, iOS zooms on focus.
_SEARCH_CLASS = (
    "flex-1 min-w-[8rem] border-0 p-0 bg-transparent text-type-input text-heading "
    "focus:ring-0 focus:outline-hidden placeholder:text-body "
    "disabled:cursor-not-allowed"
)
# The #450 draft cue, at rest only.
_UNCOMMITTED_BOX_CLASS = "not-focus-within:[[data-uncommitted]_&]:border-dashed"
# The loose text reads like a placeholder — muted (the audited placeholder
# token) + italic.
_UNCOMMITTED_SEARCH_CLASS = (
    "[[data-uncommitted]:not(:focus-within)_&]:text-body "
    "[[data-uncommitted]:not(:focus-within)_&]:italic"
)
# The pencil glyph: hidden except when its container is uncommitted at rest.
# Icon() drops the snippet's baked color classes, so text-body must ride here
# (sizing stays Icon()'s default ICON_SIZE_CLASS).
_MARKER_ICON_CLASS = "hidden text-body [[data-uncommitted]:not(:focus-within)_&]:block"
#: Ends the row; box shows mouse focus.
_BOX_BUTTON_CLASS = (
    "ml-auto -mr-1 peer-disabled:hidden focus:ring-0 focus-visible:ring-2"
)
#: A shown × takes the ml-auto instead.
#: Literal, so Tailwind sees it.
_DIALOG_CREATE_CLASS = (
    f"{_BOX_BUTTON_CLASS} [[data-search-select-clear]:not([hidden])~&]:ml-0"
)
#: Shown only between a shown × and the +.
_DIVIDER_CLASS = (
    "mx-1 hidden h-5 shrink-0 border-l border-default-medium "
    "[[data-search-select-clear]:not([hidden])+&]:peer-enabled:block"
)
#: The dialog is this listbox's panel.
_DIALOG_LISTBOX_CLASS = "mt-2 overflow-y-auto scroll-py-2"
#: Picker rows wear the menu item look.
#: Literal, so Tailwind sees it.
_ROW_CLASS = (
    f"{DROPDOWN_ITEM_SHAPE} text-type-body "
    "data-[search-select-highlighted]:bg-neutral-tertiary-medium "
    "data-[search-select-highlighted]:text-heading"
)
_ROW_WITH_ACTIONS_CLASS = f"{_ROW_CLASS} flex items-center justify-between"
_ROW_ACTIONS_CLASS = "flex gap-1 ml-2 shrink-0"
_HINT_CLASS = "ms-2 text-type-micro text-body-subtle"
#: Keeps a 26px button in a 36px row.
_ROW_ACTION_PLACEMENT_CLASS = "-my-0.75"
_NO_RESULTS_CLASS = "px-4 py-2 text-type-body italic text-body hidden"
# Approximate rendered height of one option row (px-3 py-2 text-type-body) in rem,
# used to derive the panel's max-height from items_visible.
_ROW_HEIGHT_REM = 2.25

# Default number of rows to fetch on first focus when a search_url is set.
# Shared by filter and form widgets so the dropdown is populated for keyboard
# navigation as soon as the user opens it.
DEFAULT_PREFETCH = 20


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
    return [(f"data-{key}", value) for key, value in data.items()]


def _option_role_attributes(selected: bool = False) -> list[HTMLAttribute]:
    """The ARIA attributes every listbox row carries (issue #154): value rows
    and modifier rows alike are ``role="option"`` with an ``aria-selected``
    state, so the listbox exposes only option/presentation children."""
    return [("role", "option"), ("aria-selected", "true" if selected else "false")]


def _hidden_input(name: str, value) -> Node:
    return Input(type="hidden", name=name, value=str(value))


def _label_slot(text: str, *, extra_class: str = "") -> Node:
    """A ``<span data-search-select-label>`` holding a row/pill's visible label. JS fills this
    one node when cloning the shape from a ``<template>``, so labels are the only
    thing the JS sets — all classes and structure stay server-side."""
    return Span(data_search_select_label="", class_=extra_class or None)[text]


# A placeholder option for rendering template prototypes (JS overwrites it).
_BLANK_OPTION: SearchSelectOption = {"value": "", "label": "", "data": {}}


type NoneLabel = str  # e.g. "No device"


@dataclass(frozen=True)
class PostCreate:
    """The create row posts to ``url`` and holds the answer."""

    url: str
    verb: str = "Create"

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("A posting create row names its endpoint.")


@dataclass(frozen=True)
class SelectTyped:
    """The create row holds the typed text."""

    verb: str = "Use"


@dataclass(frozen=True)
class EmitCreate:
    """The create row emits ``search-select:create``."""

    verb: str = "Create"
    #: Offered for a name a row holds exactly.
    replace_verb: str = ""


#: How a create row commits.
type CreateRow = PostCreate | SelectTyped | EmitCreate


type ControlLabel = str  # e.g. "New game"


@dataclass(frozen=True, slots=True)
class DialogCreate:
    """A + opening ``url`` in a form dialog.

    The view at ``url`` answers with a ``CreatedRedirect``,
    or the + only reloads the page.
    """

    url: str | Promise
    label: ControlLabel
    #: Literals join the href; fields follow typing.
    params: ParamSources | None = None

    def literal_query(self) -> dict[str, str]:
        literal: dict[str, str] = {}
        for key, source in (self.params or {}).items():
            match source:
                case {"value": str(value)}:
                    literal[key] = value
        return literal

    def field_sources(self) -> ParamSources:
        return {
            key: source
            for key, source in (self.params or {}).items()
            if "field" in source
        }


@dataclass(frozen=True, slots=True)
class ClearControl:
    """The trailing × a box offers."""

    #: A value is held at render.
    shown: bool
    #: The ×'s ``aria-describedby`` target.
    described_by: ElementId | None = None


def _clear_button(clear: ClearControl) -> Node:
    return ControlButton(
        variant="ghost",
        size="compact",
        data_search_select_clear="",
        aria_label="Clear",
        title="Clear",
        aria_describedby=clear.described_by,
        hidden=not clear.shown,
        class_=_BOX_BUTTON_CLASS,
    )[Icon("x-mark", [("aria-hidden", "true"), ("class", "size-4")])]


def _dialog_create_link(create: DialogCreate) -> Node:
    """The divider and the +."""
    href = str(create.url)
    if literal := create.literal_query():
        href = f"{href}?{urlencode(literal)}"
    return Fragment(
        Span(aria_hidden="true", class_=_DIVIDER_CLASS),
        ControlButton(
            form_dialog_link(),
            href=href,
            data_search_select_dialog_create="",
            variant="ghost",
            size="compact",
            aria_label=create.label,
            title=create.label,
            class_=_DIALOG_CREATE_CLASS,
        )[Icon("plus", [("aria-hidden", "true"), ("class", "size-4")])],
    )


class _CreateProps(TypedDict, total=False):
    create: SearchSelectCreate
    create_url: str
    create_verb: str
    replace_verb: str


def _create_props(create: CreateRow | None) -> _CreateProps:
    """The element props one ``CreateRow`` states."""
    match create:
        case PostCreate(url=url, verb=verb):
            return _CreateProps(create="post", create_url=url, create_verb=verb)
        case SelectTyped(verb=verb):
            return _CreateProps(create="select", create_verb=verb)
        case EmitCreate(verb=verb, replace_verb=""):
            return _CreateProps(create="event", create_verb=verb)
        case EmitCreate(verb=verb, replace_verb=replace_verb):
            return _CreateProps(
                create="event", create_verb=verb, replace_verb=replace_verb
            )
        case None:
            return _CreateProps()


class RowKind(Enum):
    """The hook the element reads."""

    OPTION = "option"
    #: Pinned; the text filter never hides it.
    MODIFIER = "modifier"
    #: Hidden until no label equals the query.
    CREATE = "create"
    #: Pinned; picking it holds none.
    NONE = "none"


def _option_row(
    option: SearchSelectOption,
    kind: RowKind = RowKind.OPTION,
    *,
    selected: bool = False,
    actions: Sequence[Node] = (),
) -> Node:
    """Every picker row, in one look.

    A create row carries its own hook, not an option's:
    each answer empties the option rows, and it would
    vanish mid-keystroke.
    """
    label: Node
    if kind is RowKind.CREATE:
        attributes: list[HTMLAttribute] = [
            ("data-search-select-create", ""),
            ("role", "option"),
            ("aria-selected", "false"),
            ("hidden", ""),
        ]
        label = Span(data_label="")
    elif kind is RowKind.NONE:
        attributes = [
            *_option_role_attributes(),
            ("data-search-select-none-option", ""),
            ("data-label", option["label"]),
        ]
        label = Span()[option["label"]]
    elif kind is RowKind.MODIFIER:
        attributes = [
            *_option_role_attributes(selected),
            ("data-search-select-modifier-option", str(option["value"])),
            ("data-label", option["label"]),
        ]
        label = Span()[option["label"]]
    else:
        hint = option.get("hint")
        attributes = [
            *_data_attributes(option["data"]),
            *_option_role_attributes(selected),
            ("data-search-select-option", ""),
            ("data-value", str(option["value"])),
            ("data-label", option["label"]),
        ]
        if hint:
            attributes.append(("data-hint", hint))
        #: Always present, so template clones carry it.
        label = Fragment(
            _label_slot(
                option["label"], extra_class="truncate min-w-0" if actions else ""
            ),
            Span(data_search_select_hint="", hidden=not hint, class_=_HINT_CLASS)[
                hint or ""
            ],
        )
    if not actions:
        return Div(attributes, class_=_ROW_CLASS)[label]
    return Div(attributes, class_=_ROW_WITH_ACTIONS_CLASS)[
        label, Span(class_=_ROW_ACTIONS_CLASS)[*actions]
    ]


def _group_header(label: str) -> Node:
    """A non-selectable header over grouped rows.

    role="presentation" keeps it out of the combobox's option semantics;
    carrying no data-search-select-option excludes it from keyboard nav,
    client-side filtering, and selection. The JS hides a header whose whole
    run of following option rows is filtered out.
    """
    return Div(
        data_search_select_group_header="",
        role="presentation",
        class_=DROPDOWN_GROUP_HEADER_CLASS,
    )[label]


def _grouped_option_rows(groups: list[OptionGroup]) -> list[Node]:
    """Flatten groups into header + option-row nodes for the options panel."""
    rows: list[Node] = []
    for group in groups:
        rows.append(_group_header(group.label))
        rows.extend(_option_row(_normalize_option(option)) for option in group.options)
    return rows


#: Where a combobox's list lives.
type ComboboxHome = Literal["drop_down", "dialog"]


def _combobox_children(
    *,
    pill_nodes: list[Node],
    search_attributes: Attributes,
    options_children: list[Node],
    items_visible: int,
    multi_select: bool = False,
    home: ComboboxHome,
    templates: list[Node] | None = None,
    no_results_text: str = "No results",
    create_row: Node | None = None,
    marker: list[Node] | None = None,
    clear: ClearControl | None = None,
    dialog_create: DialogCreate | None = None,
    box_class: str = _BOX_CLASS,
) -> list[Node]:
    """Build and return the shared combobox interior nodes.

    Returns the field box, the options panel and any templates.

    The shell owns the ARIA combobox pattern (issue #154): the search input is
    the combobox, the options panel the listbox. ``aria-controls`` /
    ``aria-activedescendant`` and the ids they reference are wired by the JS at
    init (see module docstring); the JS also keeps ``aria-expanded`` in sync
    with the panel's visibility.

    ``home`` places the list; a dialog's list is always visible.
    Pills always sit in the box.
    ``box_class`` styles the field box.
    ``clear``, ``dialog_create`` and ``marker`` follow the input inside it;
    either control makes the input their ``peer``.
    """
    aria_attributes: list[HTMLAttribute] = [
        ("role", "combobox"),
        ("aria-expanded", "true" if home == "dialog" else "false"),
        ("aria-autocomplete", "list"),
    ]
    peer: Attributes = [("class", "peer")] if clear or dialog_create else []
    search = Input([*search_attributes, *aria_attributes, *peer])

    # role="presentation" keeps the message node from being exposed as a
    # (non-option) child of the listbox.
    no_results = Div(
        data_search_select_no_results="",
        role="presentation",
        class_=_NO_RESULTS_CLASS,
    )[no_results_text]
    panel_children = [*options_children, no_results]
    if create_row:
        panel_children.append(create_row)
    listbox_attributes: list[HTMLAttribute] = [
        ("data-search-select-options", ""),
        ("role", "listbox"),
        # Else Chrome makes the scroller tabbable.
        ("tabindex", "-1"),
        ("style", f"max-height: {items_visible * _ROW_HEIGHT_REM:.2f}rem"),
    ]
    if multi_select:
        listbox_attributes.append(("aria-multiselectable", "true"))
    options_panel: Node
    if home == "dialog":
        options_panel = Div(listbox_attributes, class_=_DIALOG_LISTBOX_CLASS)[
            *panel_children
        ]
    else:
        options_panel = DropdownPanel(
            [("data-search-select-panel", ""), ("data-menu", ""), *CLOSED_POPOVER],
            width="w-full",
            content_attributes=listbox_attributes,
            content_class="scroll-py-2",
        )[panel_children]
    pills = Div(data_search_select_pills="", class_=_PILLS_CLASS)[*pill_nodes]
    box = Div(data_search_select_box="", class_=box_class)[
        pills,
        search,
        *([_clear_button(clear)] if clear else []),
        *([_dialog_create_link(dialog_create)] if dialog_create else []),
        *(marker or []),
    ]
    return [box, options_panel, *(templates or [])]


type HostData = Mapping[str, str]  # data-* attributes for the host

#: Data attributes the element writes itself.
RESERVED_HOST_DATA: Final = frozenset(
    {"data-toggle", "data-values", "data-included", "data-excluded", "data-modifier"}
)


def SearchSelect(
    *,
    name: str,
    selected: list[SearchSelectOption] | None = None,
    options: list[SearchSelectOption] | None = None,
    option_groups: list[OptionGroup] | None = None,
    search_url: str = "",
    params: ParamSources | None = None,
    create: CreateRow | None = None,
    max_length: int | None = None,
    csrf: str = "",
    commit_sole_option: bool = False,
    multi_select: bool = False,
    items_visible: int = 5,
    items_scroll: int = 10,
    prefetch: int = 0,
    placeholder: str = "Search…",
    id: str = "",
    sync_url: bool = False,
    autofocus: bool = False,
    dynamic_options: bool = False,
    committed_marker: bool = True,
    panel: bool = False,
    clearable: bool = True,
    clear_description_id: str | None = None,
    none_label: NoneLabel | None = None,
    shape: ButtonShape = "full",
    dialog_create: DialogCreate | None = None,
    host_data: HostData | None = None,
    disabled: bool = False,
    described_by: str | None = None,
    invalid: bool = False,
    revert_on_leave: bool = False,
) -> Node:
    """Render the search-select widget. See module docstring for the contract.

    ``panel=True`` is the panel-hosted personality: an always-visible widget
    using the module's static panel classes, for content placed inside a
    :func:`ComboboxDropdown` dialog (which owns open/close/dismiss). The same
    composition :func:`PresetSelect` and a panel-layout :func:`FilterSelect`
    build by hand — the hosting dialog, not the widget, is the disclosure.

    Otherwise the widget sits in ``<drop-down behavior="inline-combobox">``,
    so its panel opens and positions through attachMenu; the
    widget's own search input is the trigger.

    Pass ``option_groups`` instead of ``options`` to render a grouped panel
    (non-selectable header rows before each group's options); the two are mutually
    exclusive and grouping is only meaningful for the inline (no ``search_url``)
    complete-set case.

    ``dynamic_options`` ships the row ``<template>`` even without a ``search_url``,
    so the client can swap the inline option set via the element's ``setOptions``
    (the field-comparison right operand recomputes its list per left column +
    operator, #282). Ignored when a ``search_url`` already ships the template.

    ``committed_marker`` (issue #450, single-select only, default on): renders
    the uncommitted-state cue nodes — a pencil glyph plus a permanently sr-only
    ``role="status"`` span the JS wires via ``aria-describedby`` and fills when
    the box holds text with no committed value. The span's presence is the JS's
    opt-in signal for toggling ``data-uncommitted`` (the visual cue); pass
    ``False`` to opt a widget out. Every single-select flavor built through
    this function gets the cue (form widgets, the filter builder's field
    picker, the comparison column pickers); ``PresetSelect`` and
    ``FilterSelect`` build their own markup and are structurally unaffected —
    correctly so for the preset picker, whose pick is a command and whose box
    clears by design.

    ``clearable``: a trailing × empties query and value; with
    ``none_label`` it holds none.
    ``clear_description_id``: the ×'s ``aria-describedby`` target.
    ``none_label``: a pinned row holding none.
    ``shape``: the corners the box rounds.
    ``create``: how a create row commits; none offers no row.
    ``max_length``: the most characters the box takes.
    ``dialog_create``: a + creating the row in a dialog.
    ``host_data``: ``data-*`` attributes on the element.
    ``disabled``, ``described_by``, ``invalid``: the search box's state.
    ``revert_on_leave``: leaving mid-edit restores the held value.
    """
    host_attributes = list((host_data or {}).items())
    host_keys = {key for key, _ in host_attributes}
    if any(not key.startswith("data-") for key in host_keys):
        raise ValueError(f"host_data takes data-* only: {host_data!r}")
    reserved = RESERVED_HOST_DATA & host_keys
    if reserved:
        raise ValueError(f"host_data names the element's own {sorted(reserved)}")
    if dialog_create and panel:
        raise ValueError("dialog_create is field-hosted only")
    if none_label and (multi_select or panel):
        raise ValueError("none_label is single-select and field-hosted only")
    if revert_on_leave and (multi_select or panel):
        raise ValueError("revert_on_leave is single-select and field-hosted only")
    if options and option_groups:
        raise ValueError("SearchSelect takes options or option_groups, not both")
    selected = [_normalize_option(option) for option in (selected or [])]
    options = [_normalize_option(option) for option in (options or [])]

    # ── Pills + their hidden inputs (the submitted channel) ──
    # Multi-select renders a removable Pill per value; single-select renders no
    # pill — the committed label shows inside the search box instead, with a
    # lone hidden input carrying the value. Both keep the hidden input(s) inside
    # `[data-search-select-pills]` so the JS reads/writes values uniformly.
    pills_children: list[Node] = []
    search_value = ""
    if multi_select:
        for option in selected:
            pills_children.append(
                Pill(
                    _data_attributes(option["data"]),
                    label=option["label"],
                    value=str(option["value"]),
                    removable=True,
                    label_slot=True,
                )
            )
            pills_children.append(_hidden_input(name, option["value"]))
    elif selected:
        option = selected[0]
        pills_children.append(_hidden_input(name, option["value"]))
        search_value = option["label"]
    elif none_label:
        pills_children.append(
            Input(type="hidden", name=name, value="", data_search_select_none="")
        )
        search_value = none_label

    # ── Search box (NO name — the query is never submitted) ──
    search_attrs: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    if id:
        search_attrs.append(("id", id))
    if autofocus:
        search_attrs.append(("autofocus", ""))
    if search_value:
        search_attrs.append(("value", search_value))
    if max_length is not None:
        search_attrs.append(("maxlength", str(max_length)))
    if disabled:
        search_attrs.append(("disabled", ""))
    if described_by:
        search_attrs.append(("aria-describedby", described_by))
    if invalid:
        search_attrs.append(("aria-invalid", "true"))

    home: ComboboxHome = "dialog" if panel else "drop_down"

    # ── Options panel (pre-rendered only when there is no search_url) ──
    if search_url:
        option_rows: list[Node] = []
    elif option_groups:
        option_rows = _grouped_option_rows(option_groups)
    else:
        # In the multi (aria-multiselectable) listbox aria-selected conveys
        # membership, so pre-render it for already-selected values. Single-select
        # keeps the highlight-driven aria-selected, owned by the JS.
        selected_values = (
            {str(option["value"]) for option in selected} if multi_select else set()
        )
        option_rows = [
            _option_row(option, selected=str(option["value"]) in selected_values)
            for option in options
        ]

    if none_label:
        option_rows.insert(
            0,
            _option_row({"value": "", "label": none_label, "data": {}}, RowKind.NONE),
        )

    # ── Templates the JS clones: a row when results are fetched (or when the
    #    client swaps the inline option set via ``setOptions``), a pill when
    #    multi-select adds chosen items. ──
    templates: list[Node] = []
    if search_url or dynamic_options:
        templates.append(
            Template(data_search_select_template="row")[_option_row(_BLANK_OPTION)]
        )
    if multi_select:
        templates.append(
            Template(data_search_select_template="pill")[
                Pill(label="", value="", removable=True, label_slot=True)
            ]
        )

    # ── Committed-marker cue nodes (#450, single-select only): the pencil
    #    "draft" glyph (visual, CSS-toggled off data-uncommitted) and the empty
    #    sr-only status span the JS fills ("No option selected") and points
    #    aria-describedby at. The id is JS-assigned, never rendered here —
    #    the filter builder clones whole <search-select> prototypes (#154). ──
    marker: list[Node] | None = None
    show_marker = committed_marker and not multi_select
    if show_marker:
        # The cue's state utilities ride the search box only on opted-in
        # widgets, so every other flavor's markup stays byte-identical.
        search_attrs.append(("class", _UNCOMMITTED_SEARCH_CLASS))
        marker = [
            Icon(
                "edit",
                [
                    ("data-search-select-marker", ""),
                    ("aria-hidden", "true"),
                    ("class", _MARKER_ICON_CLASS),
                ],
            ),
            Span(data_search_select_status="", role="status", class_="sr-only"),
        ]

    clear = (
        ClearControl(shown=bool(selected), described_by=clear_description_id)
        if clearable
        else None
    )
    children = _combobox_children(
        create_row=_option_row(_BLANK_OPTION, RowKind.CREATE) if create else None,
        pill_nodes=pills_children,
        search_attributes=search_attrs,
        options_children=option_rows,
        items_visible=items_visible,
        multi_select=multi_select,
        templates=templates,
        home=home,
        marker=marker,
        clear=clear,
        dialog_create=dialog_create,
        box_class=f"{field_box_class(shape)} {_UNCOMMITTED_BOX_CLASS}"
        if show_marker
        else field_box_class(shape),
    )
    widget = _SearchSelect(
        # The <search-select> element itself is the drop-down's [data-toggle]: it
        # is the positioning anchor (its field box) and the focus/typing trigger.
        # No id/aria-controls/aria-expanded stamp — the widget owns those at init.
        [*([("data-toggle", "")] if home == "drop_down" else []), *host_attributes],
        name=name,
        search_url=search_url,
        params=json.dumps(params) if params else "",
        dialog_create_params=json.dumps(field_sources)
        if dialog_create and (field_sources := dialog_create.field_sources())
        else "",
        **_create_props(create),
        csrf=csrf,
        commit_sole_option="true" if commit_sole_option else "false",
        multi="true" if multi_select else "false",
        filter_mode="false",
        free_text="false",
        always_visible="true" if panel else "false",
        prefetch=prefetch,
        sync_url="true" if sync_url else "false",
        none_label=none_label,
        revert_on_leave="true" if revert_on_leave else None,
        class_=_CONTAINER_CLASSES[home],
    )[*children]
    return _inline_combobox_host(widget) if home == "drop_down" else widget


def _inline_combobox_host(widget: Node) -> Node:
    """The drop-down a hosted combobox lives in."""
    # block keeps the field's full column width.
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="inline-combobox",
    )[widget]


def _filter_value_pill(
    option: SearchSelectOption, kind: Literal["include", "exclude"]
) -> Node:
    """An include (✓) or exclude (✗) value pill."""
    return Pill(
        _data_attributes(option["data"]),
        label=option["label"],
        removable=True,
        label_slot=True,
        kind=kind,
        data_value=str(option["value"]),
        data_label=option["label"],
        data_search_select_type=kind,
    )


def _filter_modifier_pill(modifier_value: str, label: str) -> Node:
    """The lone, sticky modifier pill (e.g. "(Any)"/"(None)")."""
    return Pill(
        label=label,
        removable=True,
        label_slot=True,
        kind="modifier",
        data_search_select_modifier=modifier_value,
    )


def _row_action(
    action: str, symbol: Child, title: str, *, color: ButtonColor = "gray"
) -> Node:
    """A trailing row button, never tabbable."""
    return ControlButton(
        variant="ghost",
        size="row",
        color=color,
        tabindex="-1",
        data_search_select_action=action,
        class_=_ROW_ACTION_PLACEMENT_CLASS,
        title=title,
        aria_label=title,
    )[symbol]


def _filter_option_row(value: str | int, label: str, *, selected: bool = False) -> Node:
    """A value row; ``selected``: a pill names it."""
    return _option_row(
        {"value": str(value), "label": label, "data": {}},
        selected=selected,
        actions=[
            _row_action("include", "+", "Include"),
            _row_action("exclude", "−", "Exclude"),
        ],
    )


def _filter_modifier_row(
    modifier_value: str, label: str, *, selected: bool = False
) -> Node:
    """A pinned pseudo-option row, e.g. "(Any)"."""
    return _option_row(
        {"value": modifier_value, "label": label, "data": {}},
        RowKind.MODIFIER,
        selected=selected,
    )


def FilterSelect(
    *,
    field_name: str,
    options: Sequence[LabeledOption | SearchSelectOption] | None = None,
    included: Sequence[LabeledOption | SearchSelectOption] | None = None,
    excluded: Sequence[LabeledOption | SearchSelectOption] | None = None,
    modifier: str = "",
    modifier_options: list[LabeledOption] | None = None,
    search_url: str = "",
    prefetch: int = 0,
    items_visible: int = 6,
    items_scroll: int = 10,
    placeholder: str = "Search…",
    id: str = "",
    free_text: bool = False,
    path: FilterWidgetPath | None = None,
    layout: FilterSelectLayout = "field",
    search_aria_label: str = "",
) -> Node:
    """Include/exclude filter combobox built on the shared ``_combobox_shell``.

    Like ``SearchSelect`` but each value row carries +/− buttons that add an
    *include* (✓) or *exclude* (✗) pill, plus an optional set of pinned
    ``modifier_options`` (e.g. ``[("NOT_NULL", "(Any)"), ("IS_NULL", "(None)")]``)
    rendered above the value rows. Presence modifiers (NOT_NULL / IS_NULL) are
    mutually exclusive with value pills. Non-presence modifiers (INCLUDES_ALL /
    INCLUDES_ONLY) coexist with value pills — they govern how the include set
    matches and are only surfaced for many-to-many fields. State is read from
    the DOM into the filter JSON by ``readSearchSelect`` (filter mode) — nothing
    is submitted by ``name``.

    ``included``/``excluded`` are resolved options (value + label) so pills show
    labels even when the value rows come from ``search_url``. ``options``
    pre-renders the value rows for the complete-set (no ``search_url``) case.

    ``free_text`` turns the widget into a typed-pill input: there is no backing
    option list, the JS builds an ephemeral option row from whatever the user
    types so the +/− buttons (and Enter) commit the typed string itself as an
    include / exclude pill.

    The default ``layout="field"`` hosts itself in
    ``<drop-down behavior="inline-combobox">`` so its panel opens/closes/positions/
    dismisses through attachMenu and the surface stack (the search input is the
    trigger — focus opens), mirroring the hosted :func:`SearchSelect`.

    ``layout="panel"`` renders the same widget in the panel personality (see
    :data:`FilterSelectLayout`): pills in their own wrap row above the
    field box, options always visible and flowing statically —
    for hosting inside a :func:`ComboboxDropdown` dialog (which supplies the
    drop-down at that level, so the panel layout stays bare here). State logic,
    templates, every ``data-search-select-*`` hook and the serializer DOM
    contract are identical to the field layout.

    ``search_aria_label`` names the search input (``aria-label``) — required
    by panel callers, whose visible facet label lives on the dropdown trigger
    rather than a ``<label>`` next to the widget.
    """
    panel_layout = layout == "panel"
    normalized_options = [_normalize_option(option) for option in (options or [])]
    normalized_included = [_normalize_option(option) for option in (included or [])]
    normalized_excluded = [_normalize_option(option) for option in (excluded or [])]
    modifier_options = modifier_options or []

    active_modifier_label = ""
    for modifier_value, label in modifier_options:
        if modifier_value == modifier:
            active_modifier_label = label
            break

    # ── Pills: modifier pill (if active), then include/exclude value pills ──
    # Presence modifiers (NOT_NULL / IS_NULL) are mutually exclusive with value
    # pills — but the stored state guarantees they never coexist, so we render
    # both channels unconditionally.  Non-presence modifiers (INCLUDES_ALL /
    # INCLUDES_ONLY) coexist with value pills and render side by side.
    pills_children: list[Node] = []
    if active_modifier_label:
        pills_children.append(_filter_modifier_pill(modifier, active_modifier_label))
    for option in normalized_included:
        pills_children.append(_filter_value_pill(option, "include"))
    for option in normalized_excluded:
        pills_children.append(_filter_value_pill(option, "exclude"))

    home: ComboboxHome = "dialog" if panel_layout else "drop_down"

    # ── Search box (NO name — the query is never submitted) ──
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    if search_aria_label:
        search_attributes.append(("aria-label", search_aria_label))

    # ── Options: pinned modifier rows, then value rows (pre-rendered only when
    #    there is no search_url; otherwise the JS fetches them) ──
    modifier_rows = [
        _filter_modifier_row(value, label, selected=value == modifier)
        for value, label in modifier_options
    ]
    # aria-selected means membership here (the listbox is aria-multiselectable):
    # a row is selected when an include or exclude pill exists for its value.
    pilled_values = {
        str(option["value"]) for option in [*normalized_included, *normalized_excluded]
    }
    value_rows = (
        [
            _filter_option_row(
                option["value"],
                option["label"],
                selected=str(option["value"]) in pilled_values,
            )
            for option in normalized_options
        ]
        if not search_url
        else []
    )

    # ── Templates the JS clones: include/exclude pills (added on click), the
    #    modifier pill (when modifiers exist), and a value row (when fetched). ──
    templates: list[Node] = [
        Template(data_search_select_template="pill-include")[
            _filter_value_pill(_BLANK_OPTION, "include")
        ],
        Template(data_search_select_template="pill-exclude")[
            _filter_value_pill(_BLANK_OPTION, "exclude")
        ],
    ]
    if modifier_options:
        templates.append(
            Template(data_search_select_template="pill-modifier")[
                _filter_modifier_pill("", "")
            ]
        )
    if search_url or free_text:
        templates.append(
            Template(data_search_select_template="row")[_filter_option_row("", "")]
        )

    children = _combobox_children(
        pill_nodes=pills_children,
        search_attributes=search_attributes,
        options_children=[*modifier_rows, *value_rows],
        items_visible=items_visible,
        # FilterSelect is always multi (include/exclude pill sets).
        multi_select=True,
        templates=templates,
        home=home,
    )
    # The self-describe root attributes for the generic filter serializer. Only
    # Filter-layer callers pass ``path``; synthetic/test callers leave it None and
    # get no extra attributes (kind is always "set" for a FilterSelect).
    widget_attributes = (
        filter_widget_attributes(path, "set") if path is not None else []
    )
    if home == "drop_down":
        # The <search-select> element itself is the drop-down's [data-toggle]: its
        # field box is the positioning anchor and its search input is the trigger.
        widget_attributes = [("data-toggle", ""), *widget_attributes]
    widget = _SearchSelect(
        widget_attributes,
        name=field_name,
        search_url=search_url,
        multi="true",
        filter_mode="true",
        free_text="true" if free_text else "false",
        always_visible="true" if panel_layout else "false",
        prefetch=prefetch,
        sync_url="false",
        class_=_CONTAINER_CLASSES[home],
        id_=id or None,
        data_modifier=modifier or None,
    )[*children]
    return _inline_combobox_host(widget) if home == "drop_down" else widget


# ── Panel personality styling ───────────────────────────
# Dialog-hosted comboboxes: field box above a list.
_PANEL_CONTAINER_CLASS = "block text-type-body"

#: The widget's class in each home.
_CONTAINER_CLASSES: dict[ComboboxHome, str] = {
    "drop_down": _CONTAINER_CLASS,
    "dialog": _PANEL_CONTAINER_CLASS,
}

# Fetch-on-open window. A preset collection is per-user and small; one fetch
# returns it all, and the type-to-filter narrows client-side.
_PRESET_PREFETCH = 100


def _preset_option_row(option: SearchSelectOption) -> Node:
    """A preset row with a remove action."""
    return _option_row(
        option,
        actions=[
            _row_action(
                "delete",
                Icon("x-mark", [("aria-hidden", "true"), ("class", "size-4")]),
                "Remove preset",
                color="red",
            )
        ],
    )


def PresetSelect(*, api_url: str, mode: str, items_visible: int = 8) -> Node:
    """The preset list, and the name a save states.

    One box filters the saved presets and names the preset to save: its
    create row reads ``Save “…”``, or ``Overwrite “…”`` for a name a
    preset holds, and emits ``search-select:create``. Options are fetched
    on every open, so the list is fresh after saves and removals.
    ``<preset-panel>`` clears a pick and re-emits it as
    ``preset-panel:load``.
    """
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", PRESET_SEARCH_PLACEHOLDER),
        ("aria-label", PRESET_SEARCH_PLACEHOLDER),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    templates: list[Node] = [
        Template(data_search_select_template="row")[_preset_option_row(_BLANK_OPTION)]
    ]
    children = _combobox_children(
        pill_nodes=[],
        search_attributes=search_attributes,
        options_children=[],
        items_visible=items_visible,
        templates=templates,
        home="dialog",
        no_results_text="No saved presets",
        create_row=_option_row(_BLANK_OPTION, RowKind.CREATE),
    )
    return _SearchSelect(
        name="preset",
        search_url=f"{api_url}?mode={mode}",
        multi="false",
        filter_mode="false",
        free_text="false",
        always_visible="true",
        prefetch=_PRESET_PREFETCH,
        sync_url="false",
        **_create_props(
            EmitCreate(verb=SAVE_PRESET_VERB, replace_verb=OVERWRITE_PRESET_VERB)
        ),
        class_=_PANEL_CONTAINER_CLASS,
    )[*children]


def ComboboxDropdown(
    *,
    label: str,
    content: Node,
    id: str,
    ghost: bool = False,
    config: dict[str, str] | None = None,
    panel_width: str = "w-72",
    applied: bool = False,
) -> Node:
    """A "Label ▾" trigger + combobox dialog, composed from the two shared
    primitives: ``<drop-down>`` owns the trigger,
    open/close, outside press, Escape and the panel surface; the panel hosts
    ``content`` (a combobox-shell widget such as :func:`PresetSelect` or a
    panel-layout :func:`FilterSelect`). The ``combobox`` client behavior opts
    out of the menu's item navigation, focuses the search box on open, and
    refetches its options on every show.

    ``ghost=True`` renders the trigger with the transparent-until-hover
    ``ControlButton`` variant (the quick filter bar's compact facet look);
    the default is the filled gray button. The dialog's accessible name is
    always ``label`` — the trigger text names the panel it opens.
    ``panel_width`` sets the dialog width class: the default ``w-72`` suits
    list-shaped content; content with an intrinsic width (a calendar) passes
    ``w-auto``.

    ``applied`` puts a dot in the trigger's corner and "(applied)" in
    its accessible name.
    """
    mark: list[Node] = []
    if applied:
        mark = [Span(class_="sr-only")[" (applied)"], AppliedDot()]
    trigger = ControlButton(
        color="gray",
        variant="ghost" if ghost else "filled",
        aria_haspopup="dialog",
        class_="relative" if applied else None,
    )[
        label,
        *mark,
        Icon("arrowdown", size="h-3 w-3"),
    ].as_element()
    # A dialog; the widget brings listbox semantics.
    panel = DropdownPanel(role="dialog", aria_label=label, width=panel_width)[content]
    return Dropdown(
        trigger_element=trigger,
        target_element=panel,
        id=id,
        behavior="combobox",
        config=config,
    )


#: The Presets segment's and panel's name.
PRESETS_LABEL = "Presets"

#: The preset box's placeholder and name.
PRESET_SEARCH_PLACEHOLDER = "Find or name a preset"
#: The create row's verbs.
SAVE_PRESET_VERB = "Save"
OVERWRITE_PRESET_VERB = "Overwrite"


def PresetPanel(*, api_url: str, mode: FilterMode) -> Node:
    """The preset list; ``data-preset-picker`` is the removal hook."""
    return _PresetPanelElement(
        preset_api_url=api_url, mode=mode, data_preset_picker=""
    )[PresetSelect(api_url=api_url, mode=mode)]


def presets_member(*, api_url: str, mode: FilterMode, id: str) -> ButtonGroupMember:
    """The Presets segment, opening the panel."""

    def opens(trigger: Element) -> Node:
        panel = DropdownPanel(role="dialog", aria_label=PRESETS_LABEL, width="w-80")[
            PresetPanel(api_url=api_url, mode=mode)
        ]
        return Dropdown(
            trigger_element=_as_dialog_trigger(trigger),
            target_element=panel,
            id=id,
            placement="bottom-end",
            behavior="combobox",
        )

    return {
        "slot": Fragment(Icon("bookmark"), Icon("arrowdown", size="h-3 w-3")),
        "aria_label": PRESETS_LABEL,
        "title": PRESETS_LABEL,
        "opens": opens,
    }


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
