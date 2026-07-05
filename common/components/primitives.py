"""Generic HTML primitives (no domain knowledge).

Generic leaf elements (``Div``, ``Span``, ``Td`` …) are *not* hand-written one
per tag: they are generated from a whitelist via :func:`_html_element`, each a
thin builder over the single :class:`Element` node class. Only elements that add
classes or behaviour (``ControlButton``, ``Pill``, ``Checkbox`` …) are written out.
Everything returns a :class:`Node`; string-built widgets return :class:`Safe`.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Literal, NamedTuple, NotRequired, TypedDict

from django.conf import settings
from django.http import QueryDict
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.utils.safestring import SafeText, mark_safe

from common.components.core import (
    Attributes,
    AttrsArg,
    BaseComponent,
    Child,
    Children,
    Element,
    Fragment,
    HTMLAttribute,
    Media,
    Node,
    Safe,
    as_attributes,
    as_children,
    randomid,
)
from common.components.icons_generated import ICON_NODES
from common.criteria import FilterWidgetKind, FilterWidgetPath, RelationChild
from common.sorting import SortString, SortTerm, collapse_sort, cycle_sort
from common.utils import truncate_info

type ButtonColor = Literal["blue", "red", "gray", "green"]  # e.g. "red" (destructive)
type ButtonVariant = Literal[
    "filled",  # standalone default
    "segmented",  # ButtonGroup member
    "outline",  # bordered dropdown-toggle look (colorless)
    "plain",  # borderless navbar nav-link look (colorless)
]

# Shared disabled appearance for every form control, so all form elements look
# the same when disabled. Put on the control itself (DISABLED_CONTROL_CLASS) or,
# for composite controls whose disabled state lives on an inner element (e.g.
# SearchSelect), on the wrapper via :has() (DISABLED_WITHIN_CLASS).
DISABLED_CONTROL_CLASS = "disabled:opacity-50 disabled:cursor-not-allowed"
DISABLED_WITHIN_CLASS = "has-[:disabled]:opacity-50 has-[:disabled]:cursor-not-allowed"


def filter_widget_attributes(
    path: FilterWidgetPath,
    kind: FilterWidgetKind,
    *,
    relation_child: RelationChild | None = None,
) -> list[HTMLAttribute]:
    """The self-describe attributes every filter-bar widget root carries.

    The generic serializer in ``ts/elements/filter-bar.ts`` reads ``data-path``
    (the widget's filter-JSON key, as a JSON array) and ``data-kind`` off any
    ``[data-filter-widget]`` root to handle all widgets uniformly. See issue #123
    Phase 2.

    Cross-entity widgets are recognised by the serializer from their ``data-path``
    alone: a multi-segment path is a relation chain, so instead of writing the
    leaf at ``data-path`` top-level the serializer folds ``data-path`` into a
    nested object and appends it as its own element of the parent's n-ary ``AND``
    list — several widgets targeting the same relation compose as *independent*
    EXISTS rather than merging into one shared relation node (issue #123 Phase 2d;
    issue #138 removed the redundant ``data-compose`` marker).

    ``relation_child`` (with ``kind="relation-bool"``) supplies the fixed child
    criterion of a relation toggled by a boolean radio: ``data-path`` is the
    relation chain *without* a leaf and ``data-relation-child`` is the child
    keyed by field, e.g. ``{"emulated": {"value": True, "modifier": "EQUALS"}}``.
    A ``True`` radio matches ANY, ``False`` sets ``match: "NONE"``.
    """
    attributes: list[HTMLAttribute] = [
        ("data-filter-widget", ""),
        ("data-path", json.dumps(path)),
        ("data-kind", kind),
    ]
    if relation_child is not None:
        attributes.append(("data-relation-child", json.dumps(relation_child)))
    return attributes


# The single max-width every content container obeys — navbar, page bodies
# (lists, detail, stats), and popovers. Only a cap: callers add
# `w-full` to fill to it and `mx-auto`/`self-center` to centre. The `w-full`
# matters inside #main-container's flex column, where bare self-center/mx-auto
# turn off flex `stretch` and the box would otherwise shrink to content width.
CONTENT_MAX_WIDTH_CLASS = "max-w-7xl"

# Narrower cap for form-shaped containers (add/edit forms, confirm pages,
# modals). Forms read better constrained; the wide CONTENT_MAX_WIDTH_CLASS cap
# is for page bodies, lists, and the navbar.
FORM_MAX_WIDTH_CLASS = "max-w-xl"


# ── Generic leaf elements ────────────────────────────────────────────────────
# A whitelist of plain tags, each turned into a builder over `Element`. The
# tag name is data, not a separate class/function body. Add a tag = one line.


# Builder param names that must never arrive as htpy attribute kwargs. After the
# legacy ``attributes=`` / ``children=`` params are removed, a stray one would be
# silently swallowed by ``**kwargs`` and rendered as a bogus ``attributes="…"``
# HTML attribute — so we reject them with a pointer to the htpy form instead.
_RESERVED_ATTR_KWARGS = frozenset({"attributes", "children"})


def _attrs_from_kwargs(attrs: dict[str, object]) -> list[HTMLAttribute]:
    """Translate htpy-style attribute kwargs to (name, value) pairs.

    ``class_`` -> ``class`` (trailing underscore stripped); ``hx_get`` ->
    ``hx-get`` (inner underscores to hyphens); ``True`` -> ``name="name"``
    (boolean-attribute form); ``False`` / ``None`` -> omitted."""
    for reserved in _RESERVED_ATTR_KWARGS:
        if reserved in attrs:
            raise TypeError(
                f"{reserved!r} is not an htpy attribute kwarg. Pass dynamic "
                "attributes positionally — Builder(attrs) — and children via "
                "Builder(...)[...]."
            )
    result: list[HTMLAttribute] = []
    for key, value in attrs.items():
        if value is None or value is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        result.append((name, name if value is True else value))  # type: ignore[arg-type]
    return result


def _coerce_attrs(attrs: "AttrsArg | None") -> list[HTMLAttribute]:
    """Normalise a dynamic-attributes argument to ``list[HTMLAttribute]``.

    Accepts an ``Attributes`` sequence of ``(name, value)`` pairs **or** a
    ``Mapping`` (``{"data-x": "y"}``), so callers can build dynamic attributes
    as whichever is convenient and pass them through the single positional
    ``attrs`` slot. ``None`` -> empty list.
    """
    if attrs is None:
        return []
    if isinstance(attrs, Mapping):
        return list(attrs.items())
    return list(attrs)


def custom_element_builder(tag_name: str):
    """Create a tag builder for a custom element with auto-attached Media.

    The module path follows the convention ``ts/elements/<tag>.ts`` →
    ``dist/elements/<tag>.js``.
    """
    return _html_element(tag_name, Media(js=(f"dist/elements/{tag_name}.js",)))


def _html_element(tag_name: str, media: Media | None = None):
    """Build a generic element builder for ``tag_name`` (the whitelist factory).

    If ``media`` is provided, every node created by the builder will carry it
    (used for custom elements whose compiled JS must be loaded automatically).
    """

    def element(
        attrs: "AttrsArg | None" = None,
        **kwargs: object,
    ) -> Element:
        # Merge order is priority order — first contributor wins per the node
        # algebra: positional ``attrs`` (dynamic) then htpy ``kwargs`` (static);
        # ``class`` accumulates across both. Children come via ``[]``.
        merged = _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)
        node = Element(tag_name, merged)
        return node.with_media(media) if media else node

    element.__name__ = element.__qualname__ = tag_name[:1].upper() + tag_name[1:]
    element.__doc__ = f"Builder for the <{tag_name}> element."
    return element


A = _html_element("a")
Button = _html_element("button")
Div = _html_element("div")
P = _html_element("p")
Ul = _html_element("ul")
Li = _html_element("li")
Strong = _html_element("strong")
Span = _html_element("span")
Label = _html_element("label")
Template = _html_element("template")
Td = _html_element("td")
Tr = _html_element("tr")
Th = _html_element("th")
Table = _html_element("table")
Thead = _html_element("thead")
Tbody = _html_element("tbody")
Caption = _html_element("caption")
Nav = _html_element("nav")
Img = _html_element("img")
Html = _html_element("html")
Form = _html_element("form")
Head = _html_element("head")
Body = _html_element("body")
Meta = _html_element("meta")
Title = _html_element("title")
Script = _html_element("script")
Link = _html_element("link")
Select = _html_element("select")
Option = _html_element("option")
Optgroup = _html_element("optgroup")
H1 = _html_element("h1")
H2 = _html_element("h2")
H3 = _html_element("h3")


def _popover_html(
    id: str,
    popover_content: Child,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    slot: "Node | str" = "",
) -> Node:
    """Generate popover HTML. Single source of truth for popover structure."""
    display_content = wrapped_content if wrapped_content else slot

    span = Span(
        [
            ("data-popover-target", id),
            ("class", wrapped_classes),
        ]
    )[*([display_content] if display_content else [])]

    popover_tooltip_class = (
        # `[&.invisible]:hidden`: while Flowbite keeps the popover hidden it
        # carries the `invisible` class (visibility:hidden), which still
        # occupies layout — an absolutely-positioned, Popper-transformed
        # popover then expands its scroll container, producing a phantom
        # scrollbar (issue #53 / #40). Removing it from layout while hidden
        # fixes that; Flowbite drops `invisible` on show, restoring display.
        # Shares the one content max-width as a cap only (no `w-full`): the
        # tooltip stays inline-block and small, the cap just bounds huge content.
        f"absolute z-10 invisible [&.invisible]:hidden inline-block text-sm "
        f"text-heading transition-opacity duration-300 bg-brand-soft border "
        f"border-brand/30 rounded-lg shadow-xs opacity-0 {CONTENT_MAX_WIDTH_CLASS}"
    )

    div = Div(
        [
            ("data-popover", ""),
            ("id", id),
            ("role", "tooltip"),
            ("class", popover_tooltip_class),
        ]
    )[
        Div(class_="px-3 py-2")[popover_content],
        Div(data_popper_arrow=""),
        Safe(  # nosec — intentional HTML comment for Tailwind JIT
            "<!-- for Tailwind CSS to generate decoration-dotted CSS "
            "from Python component -->"
        ),
        Span(class_="hidden decoration-dotted"),
    ]

    return Fragment(span, div, separator="\n")


def Popover(
    popover_content: Child,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    children: Children = None,
    attributes: Attributes | None = None,
    id: str = "",
) -> Node:
    children = as_children(children)
    if not wrapped_content and not children:
        raise ValueError("One of wrapped_content or children is required.")
    if not id:
        id = randomid(content=f"{wrapped_content}:{popover_content}:{wrapped_classes}")

    slot = Fragment(*children, separator="\n") if children else ""
    return _popover_html(
        id=id,
        popover_content=popover_content,
        wrapped_content=wrapped_content,
        wrapped_classes=wrapped_classes,
        slot=slot,
    )


def PopoverIf(
    condition: bool, popover_content: Child, node: Node | str, id: str = ""
) -> Node | str:
    """Wrap `node` in a popover showing `popover_content` when `condition` holds.

    Without an explicit `id`, the popover's DOM id is derived from
    `popover_content` alone — pass `id` when two popovers on the same page
    could share the same content.
    """
    if condition:
        return Popover(popover_content=popover_content, children=[node], id=id)
    return node


def PopoverTruncated(
    input_string: str,
    popover_content: Child = "",
    popover_if_not_truncated: bool = False,
    length: int = 30,
    ellipsis: str = "…",
    endpart: str = "",
) -> Node | str:
    """
    Returns `input_string` truncated after `length` of characters
    and displays the untruncated text in a popover HTML element.
    The truncated text ends in `ellipsis`, and optionally
    an always-visible `endpart` can be specified.
    `popover_content` can be specified if:
    1. It needs to be always displayed regardless if text is truncated.
    2. It needs to differ from `input_string`.
    """
    truncation = truncate_info(input_string, length, ellipsis, endpart)
    if truncation.display != input_string:
        return Popover(
            wrapped_content=truncation.display,
            popover_content=popover_content if popover_content else input_string,
        )
    if popover_content and popover_if_not_truncated:
        return Popover(
            wrapped_content=input_string,
            popover_content=popover_content,
        )
    return input_string


# The classes both ControlButton variants truly share. Everything else —
# sizing, rounding, focus treatment — belongs to the variant, so the segmented
# look stays what ButtonGroup members rendered before the unification.
# inline-flex keeps every button the same height regardless of content — an
# icon+text button (e.g. "Log this game") would otherwise sit taller than its
# text-only siblings and step a segmented group's bottom edge.
_CONTROL_BASE_CLASS = (
    "font-medium hover:cursor-pointer inline-flex items-center justify-center "
    f"{DISABLED_CONTROL_CLASS}"
)

# Container-query sizing, shared by EVERY button-shaped variant: compact by
# default (a container-query variant never matches without an `@container`
# ancestor, so "no wrapper" = compact by construction); form-shaped containers
# ≥ 28rem (`@md`) upsize to the old default look. There is deliberately no
# size parameter — the container decides. Note this means segmented groups and
# outline toggles in tables are compact at every viewport width: a
# shrink-to-fit inline-flex group cannot be its own inline-size container
# (containment would collapse it to zero width) and table cells can't be
# containers either — but every button on such a page is compact together.
_CONTROL_SIZE_CLASS = "px-3 py-2 text-xs @md:px-5 @md:py-2.5 @md:text-sm"

_FILLED_VARIANT_CLASS = (
    "gap-2 text-center leading-5 focus:outline-hidden focus:ring-4 rounded-base "
    f"{_CONTROL_SIZE_CLASS}"
)

_SEGMENTED_VARIANT_CLASS = f"focus:z-10 {_CONTROL_SIZE_CLASS}"

_FILLED_COLOR_CLASSES: dict[ButtonColor, str] = {
    "blue": "text-white bg-brand box-border border border-transparent hover:bg-brand-strong focus:ring-brand-medium",
    "red": "bg-red-700 dark:bg-red-600 dark:focus:ring-red-900 dark:hover:bg-red-700 focus:ring-red-300 hover:bg-red-800 text-white",
    "gray": "bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-600 dark:focus:ring-gray-700 dark:hover:bg-gray-700 dark:hover:text-white dark:text-gray-400 focus:ring-gray-100 hover:bg-gray-100 hover:text-blue-700 text-gray-900 border",
    "green": "bg-green-700 dark:bg-green-600 dark:focus:ring-green-800 dark:hover:bg-green-700 focus:ring-green-300 hover:bg-green-800 text-white",
}

_SEGMENTED_COLOR_CLASSES: dict[ButtonColor, str] = {
    # Every color uses a hover border one shade darker than its hover fill, so
    # the segmented buttons share the same "ring" look (only the hue differs).
    "blue": (
        "text-gray-900 bg-white border "
        "border-gray-200 hover:bg-brand hover:border-brand-strong "
        "hover:text-white focus:ring-2 focus:ring-blue-700 focus:text-blue-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-white "
        "dark:hover:text-white dark:hover:border-brand-strong "
        "dark:hover:bg-brand dark:focus:ring-blue-500 dark:focus:text-white"
    ),
    "gray": (
        "text-gray-900 bg-white border "
        "border-gray-200 hover:bg-gray-100 hover:text-blue-700 "
        "focus:ring-2 focus:ring-blue-700 focus:text-blue-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-white "
        "dark:hover:text-white dark:hover:border-gray-800 dark:hover:bg-gray-700 "
        "dark:focus:ring-blue-500 dark:focus:text-white"
    ),
    "red": (
        "text-gray-900 bg-white border "
        "border-gray-200 hover:bg-red-500 hover:border-red-600 hover:text-white "
        "focus:ring-2 focus:ring-blue-700 focus:text-blue-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-white "
        "dark:hover:text-white dark:hover:border-red-800 "
        "dark:hover:bg-red-700 dark:focus:ring-blue-500 dark:focus:text-white"
    ),
    "green": (
        "text-gray-900 bg-white border "
        "border-gray-200 hover:bg-green-500 hover:border-green-600 "
        "hover:text-white focus:ring-2 focus:ring-green-700 "
        "focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:text-white dark:hover:text-white dark:hover:border-green-700 "
        "dark:hover:bg-green-600 dark:focus:ring-green-500 "
        "dark:focus:text-white"
    ),
}


# Dropdown-toggle variants (issue #272): single-look, no color axis. Outline
# is a regular button-shaped control — base + shared sizing + its bordered
# look. Plain is the navbar nav-link: its layout (flex justify-between,
# md:p-0) contradicts the base and the sizing scale, so it alone carries its
# complete look and skips both.
_OUTLINE_VARIANT_CLASS = (
    f"{_CONTROL_SIZE_CLASS} bg-white border border-gray-200 "
    "hover:bg-gray-100 dark:bg-gray-800 dark:border-gray-700 dark:text-white "
    "dark:hover:bg-gray-700 whitespace-nowrap"
)

_PLAIN_VARIANT_CLASS = (
    "flex items-center justify-between w-full py-2 px-3 text-gray-900 rounded-sm "
    "hover:bg-gray-100 md:hover:bg-transparent md:border-0 md:hover:text-blue-700 "
    "md:p-0 md:w-auto dark:text-white md:dark:hover:text-blue-500 "
    "dark:focus:text-white dark:border-gray-700 dark:hover:bg-gray-700 "
    "md:dark:hover:bg-transparent hover:cursor-pointer"
)


class ControlButton(BaseComponent):
    """The one polymorphic button/link builder — single home for button styling
    and the ``<a>``-vs-``<button>`` choice (issue #235).

    Renders, by mode:

    - ``href=`` → a single ``<a href>`` carrying the full button classes (a
      navigation styled as a button — no nested interactive elements);
    - ``method="post"`` → a ``<form method="post">`` wrapping an optional CSRF
      input and a ``type="submit"`` button — a state-changing action that needs
      no JavaScript. Classes and caller attributes land on the inner button;
      ``action`` defaults to ``href``;
    - otherwise → a ``<button>`` with ``type`` (default ``"button"``).

    Sizing contract: compact by default; upsizes inside an ``@container``
    ancestor at least 28rem wide (``@md``). There is no size parameter — the
    container decides, and every button-shaped variant follows the same scale.
    ``variant="segmented"`` is the ButtonGroup-member look (white background,
    hover hue).

    The dropdown-toggle variants are single-look and ignore ``color``:
    ``variant="outline"`` is the bordered toggle (split-button carets, value
    selectors — callers add rounding by shape, e.g. ``rounded-e-lg``);
    ``variant="plain"`` is the borderless navbar nav-link trigger, the one
    variant outside the sizing contract (its navbar layout is its own).

    Children go via the htpy ``[]`` slot — ``ControlButton(color="red")[label]``
    — which routes into the inner button in post mode. Extra attributes take the
    usual forms: dynamic pairs through the positional slot, static ones as
    kwargs (``hx_get=…``, ``data_x=""``, ``title=…``, ``onclick=…``, ``name=…``).
    """

    def __init__(
        self,
        attrs: "AttrsArg | None" = None,
        *,
        color: ButtonColor = "blue",
        variant: ButtonVariant = "filled",
        href: str = "",
        method: str = "",
        action: str = "",
        csrf_token: str = "",
        type: str = "button",
        _children: Children = None,
        **kwargs: object,
    ) -> None:
        if variant == "outline":
            class_attrs: list[HTMLAttribute] = [
                ("class", _CONTROL_BASE_CLASS),
                ("class", _OUTLINE_VARIANT_CLASS),
            ]
        elif variant == "plain":
            class_attrs = [("class", _PLAIN_VARIANT_CLASS)]
        else:
            variant_class = (
                _FILLED_VARIANT_CLASS
                if variant == "filled"
                else _SEGMENTED_VARIANT_CLASS
            )
            color_table = (
                _FILLED_COLOR_CLASSES
                if variant == "filled"
                else _SEGMENTED_COLOR_CLASSES
            )
            class_attrs = [
                ("class", _CONTROL_BASE_CLASS),
                ("class", variant_class),
                ("class", color_table[color]),
            ]
        self._merged_attributes: list[HTMLAttribute] = [
            *class_attrs,
            *_coerce_attrs(attrs),
            *_attrs_from_kwargs(kwargs),
        ]
        self._href = href
        self._method = method
        self._action = action
        self._csrf_token = csrf_token
        self._type = type
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> "ControlButton":
        # A new instance, never a mutation: `_tree()` memoizes the rendered
        # subtree, so mutating self after a render would serve a stale tree.
        clone = ControlButton.__new__(ControlButton)
        clone.__dict__.update(self.__dict__)
        clone.__dict__.pop("_tree_cache", None)
        clone._children = as_children(children)
        return clone

    def as_element(self) -> Element:
        """The rendered node as an :class:`Element` — for machinery typed on
        ``Element`` (e.g. the dropdown trigger stamping), which reads
        ``tag_name``/``attributes`` off the node directly."""
        node = self._tree()
        assert isinstance(node, Element)
        return node

    def render(self) -> Node:
        if self._method.lower() == "post":
            # Forced ("type", "submit") comes first so it wins first-wins over
            # any caller-supplied type; the form is chrome (inline-flex keeps
            # its height and alignment right in flex rows and segmented groups).
            submit = Button([("type", "submit"), *self._merged_attributes])[
                *self._children
            ]
            form_children: list[Node] = []
            if self._csrf_token:
                form_children.append(
                    Safe(
                        '<input type="hidden" name="csrfmiddlewaretoken" '
                        f'value="{self._csrf_token}">'
                    )
                )
            form_children.append(submit)
            return Form(
                method="post",
                action=self._action or self._href,
                class_="inline-flex",
            )[*form_children]
        if self._href:
            return A([("href", self._href), *self._merged_attributes])[*self._children]
        return Button([("type", self._type), *self._merged_attributes])[*self._children]


class ButtonGroupMember(TypedDict, total=False):
    slot: Child
    href: str
    color: ButtonColor
    title: str
    hx_get: str
    hx_target: str
    hx_swap: str
    method: str
    action: str
    csrf_token: str
    button_attributes: list[HTMLAttribute]


def ButtonGroup(buttons: list[ButtonGroupMember] | None = None) -> Element:
    """Generate a button group div of segmented :class:`ControlButton` members.

    Each member dict accepts: slot (required), href, color, title, hx_get,
    hx_target, hx_swap, and — for a state-changing member — method ("post"),
    action (URL), csrf_token. A ``method="post"`` member renders as a no-JS
    ``<form>`` submit button instead of a link; a member with
    ``button_attributes`` renders as a bare ``<button type="button">`` carrying
    those attributes (a JS-driven action with no navigation).
    Empty dicts (no slot) are silently skipped — matching the template behavior
    for conditional buttons (e.g., end-session only when session is active).
    Every button uses one responsive size (small on mobile, larger from ``lg``).
    """
    buttons = buttons or []
    children: list[Node] = []
    for member in buttons:
        slot = member.get("slot", "")
        if not member or not slot:
            continue
        # Attributes are added only when non-empty: an empty ``hx-get=""``
        # would still register with htmx and hijack the link's click into an
        # AJAX GET of the current URL.
        member_attributes: list[HTMLAttribute] = []
        if title := member.get("title", ""):
            member_attributes.append(("title", title))
        for attribute_name, value in (
            ("hx-get", member.get("hx_get", "")),
            ("hx-target", member.get("hx_target", "")),
            ("hx-swap", member.get("hx_swap", "")),
        ):
            if value:
                member_attributes.append((attribute_name, value))
        button_attributes = member.get("button_attributes")
        is_plain_button = button_attributes is not None
        if button_attributes:
            member_attributes.extend(button_attributes)
        children.append(
            ControlButton(
                member_attributes,
                variant="segmented",
                color=member.get("color", "gray"),
                href="" if is_plain_button else member.get("href", "#"),
                method="" if is_plain_button else member.get("method", ""),
                action=member.get("action", ""),
                csrf_token=member.get("csrf_token", ""),
            )[slot]
        )

    # Alignment-agnostic: the group sits where its container puts it. In a table
    # Actions cell the <td> is right-aligned (table-level Column.align rule), so
    # this inline-flex group is pushed right; in the game header it sits left.
    # End-rounding lives here (keyed on child position, not member tag — the one
    # documented styling-at-a-distance exception, because a member cannot know
    # its own position) so a group can freely mix <a> links, <form> submit
    # buttons, and bare buttons: the direct-child selectors round <a>/<button>
    # members, the descendant `_button` ones round a <form> member's inner
    # button.
    return Div(
        class_=(
            "inline-flex rounded-md shadow-xs "
            "[&>*:first-child]:rounded-s-lg "
            "[&>*:first-child_button]:rounded-s-lg "
            "[&>*:last-child]:rounded-e-lg "
            "[&>*:last-child_button]:rounded-e-lg"
        ),
        role="group",
    )[children]


def Input(
    attrs: "AttrsArg | None" = None,
    *,
    type: str = "text",
    **kwargs: object,
) -> Element:
    merged = _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)
    # ``type`` is a default: an explicit ``type`` already in the merged attrs
    # wins (first-wins), so append the default only when no caller supplied one.
    if not any(name == "type" for name, _ in merged):
        merged = merged + [("type", type)]
    return Element("input", merged)


def Checkbox(
    attrs: "AttrsArg | None" = None,
    *,
    name: str,
    label: str | None = None,
    checked: bool = False,
    value: str = "1",
    **kwargs: object,
) -> Node:
    """A filter-agnostic Checkbox component."""
    baked: list[HTMLAttribute] = [
        ("name", name),
        ("value", value),
        (
            "class",
            "rounded border-default-medium bg-neutral-secondary-medium "
            f"text-brand focus:ring-brand {DISABLED_CONTROL_CLASS}",
        ),
    ]
    if checked:
        baked.append(("checked", "true"))
    input_attrs = baked + _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)

    input_el = Input(input_attrs, type="checkbox")
    if label is None:
        return input_el

    return Label(class_="flex items-center gap-2 text-sm text-heading cursor-pointer")[
        input_el, label
    ]


def Radio(
    attrs: "AttrsArg | None" = None,
    *,
    name: str,
    label: str | None = None,
    checked: bool = False,
    value: str = "",
    **kwargs: object,
) -> Node:
    """A filter-agnostic Radio component."""
    baked: list[HTMLAttribute] = [
        ("name", name),
        ("value", value),
        (
            "class",
            "rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand",
        ),
    ]
    if checked:
        baked.append(("checked", "true"))
    input_attrs = baked + _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)

    input_el = Input(input_attrs, type="radio")
    if label is None:
        return input_el

    return Label(class_="flex items-center gap-1 text-sm text-heading cursor-pointer")[
        input_el, label
    ]


# Inline Tailwind utilities for Pill (mirrors the .sf-tag / .sf-remove rules in
# input.css, written inline so styling stays encapsulated in the component). The
# JS that builds pills client-side (search_select.js) MUST emit these exact class
# strings byte-for-byte so Tailwind generates them and server/JS pills match.
_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-brand-soft text-heading"
)
_PILL_REMOVE_CLASS = "ml-1 text-body hover:text-heading font-bold cursor-pointer"


def Pill(
    attrs: "AttrsArg | None" = None,
    *,
    label: str = "",
    value: str = "",
    removable: bool = False,
    extra_class: str = "",
    label_slot: bool = False,
    **kwargs: object,
) -> Node:
    """A small label pill, optionally removable (× button).

    Styling is inline Tailwind utilities; ``data-pill`` / ``data-pill-remove``
    are JS hooks only (no CSS attached). ``value`` (when set) becomes
    ``data-value``; ``extra_class`` and any caller ``class`` accumulate onto the
    pill's base class; extra dynamic ``attrs`` / kwargs land on the outer span.

    ``label_slot=True`` wraps the label in a ``<span data-search-select-label>`` so JS can
    fill it when cloning the pill from a server-rendered ``<template>`` (keeps the
    markup single-sourced — see ``search_select.py``).
    """
    baked: list[HTMLAttribute] = [
        ("class", _PILL_CLASS),
        ("class", extra_class),
        ("data-pill", ""),
    ]
    if value != "":
        baked.append(("data-value", str(value)))
    pill_attrs = baked + _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)

    label_child: "Node | str" = (
        Span(data_search_select_label="")[label] if label_slot else label
    )
    children: list["Node | str"] = [label_child]
    if removable:
        children.append(
            Button(
                type="button",
                data_pill_remove="",
                class_=_PILL_REMOVE_CLASS,
                aria_label="Remove",
            )["×"]
        )

    return Span(pill_attrs)[*children]


# A small count/label badge (the brand-soft pill historically inlined in H1).
# Distinct from `Pill`: that is a removable filter tag carrying JS hooks
# (`data-pill`, search-select label slot); this is a static, hook-free badge for
# counts/indicators. Shape + palette are fixed; only text size + padding vary so
# it reads well from a heading count down to a one-character sort position.
_BADGE_BASE_CLASS = (
    "inline-flex items-center justify-center font-semibold leading-none "
    "rounded-sm bg-brand-soft text-heading"
)
_BADGE_SIZE_CLASSES = {
    "sm": "text-[0.7rem] px-1.5 py-0.5",
    "base": "text-sm px-2 py-0.5",
    "lg": "text-2xl px-2.5 py-0.5",
}


def Badge(
    content: Child,
    *,
    size: str = "base",
    extra_class: str = "",
    attributes: Attributes | None = None,
) -> Node:
    """A static brand-soft badge for counts and indicators.

    ``size`` picks the text/padding scale (``sm`` / ``base`` / ``lg``);
    ``extra_class`` appends positioning utilities (e.g. ``ms-2`` next to a
    heading). For a removable filter tag use :func:`Pill` instead.
    """
    attributes = as_attributes(attributes)
    size_class = _BADGE_SIZE_CLASSES.get(size, _BADGE_SIZE_CLASSES["base"])
    classes = " ".join(
        part for part in (_BADGE_BASE_CLASS, size_class, extra_class) if part
    )
    return Span([("class", classes), *attributes])[content]


def CsrfInput(request) -> Node:
    """Hidden CSRF input, equivalent to the `{% csrf_token %}` template tag.

    Returns a ``Safe`` node (not a safe string): it is always used as a tree
    child, and only nodes render unescaped now."""
    return Safe(
        f'<input type="hidden" name="csrfmiddlewaretoken" value="{get_token(request)}">'
    )


def ModuleScript(filename: str) -> SafeText:
    """A `<script type="module">` tag pointing at a static JS file."""
    return mark_safe(
        f'<script type="module" src="{static("js/" + filename)}"></script>'
    )


def ExternalScript(url: str) -> SafeText:
    """A plain `<script src=...>` tag for an external/CDN script."""
    return mark_safe(f'<script src="{url}"></script>')


def StaticScript(filename: str) -> SafeText:
    """A plain (classic, non-module) `<script src=...>` tag for a static JS
    file — for vendored UMD bundles, which break inside module scope."""
    return mark_safe(f'<script src="{static("js/" + filename)}"></script>')


# The <year-picker> custom element wraps the Flowbite-datepicker year grid.
# The builder auto-attaches dist/elements/year-picker.js; the vendored UMD
# bundle (classic script, runs during parse) is merged in via with_media so
# Datepicker is defined by the time the deferred element module executes.
_YearPicker = custom_element_builder("year-picker")
_DATEPICKER_MEDIA = Media(js_external=("datepicker.umd.js",))

# The down-chevron rendered inside the YearPicker button. Trusted static SVG.
_YEAR_PICKER_CHEVRON = Safe(
    '<svg class="w-4 h-4 ms-2 rtl:rotate-180" aria-hidden="true" '
    'xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 10">'
    '<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" '
    'stroke-width="2" d="M1 5h12m0 0L9 1m4 4L9 9"/></svg>'
)


def YearPicker(
    year: int | None = None,
    available_years: tuple[int, ...] = (),
    url_template: str = "",
) -> Node:
    """A Flowbite-datepicker year picker.

    `year` is the selected year, or ``None`` for the all-time view (the empty
    state). `available_years` are the years to enable in the popup grid.
    `url_template` is a navigation URL containing the literal ``__year__``
    placeholder, substituted with the chosen year in JS (keeps this component
    decoupled from the project's URL names).

    Behavior lives in ``ts/elements/year-picker.ts``; this renders the light
    DOM (toggle button + hidden datepicker input). The element module and the
    Flowbite UMD bundle are declared as ``media`` on the node, so ``TimetrackerDocument()``
    loads both automatically.
    """
    label = str(year) if year is not None else "Choose a year"
    selected = str(year) if year is not None else ""
    classes = (
        "bg-brand text-white border-transparent hover:bg-brand-strong"
        if year is not None
        else "bg-neutral-secondary-medium text-heading border border-default-medium "
        "hover:bg-neutral-tertiary-medium focus:ring-4 focus:ring-brand-medium"
    )
    years_csv = ",".join(str(y) for y in available_years)
    return _YearPicker(
        [
            ("selected-year", selected),
            ("available-years", years_csv),
            ("url-template", url_template),
            ("class", "relative inline-block"),
        ]
    )[
        Button(
            [
                ("type", "button"),
                ("data-year-picker-toggle", ""),
                (
                    "class",
                    "inline-flex items-center rounded-base px-4 py-2 "
                    f"text-sm font-medium {classes}",
                ),
            ]
        )[label, _YEAR_PICKER_CHEVRON],
        Input(
            id_="year-picker-input",
            class_="absolute opacity-0 pointer-events-none",
            style=(
                "width: 1px; height: 1px; padding: 0; margin: -1px; "
                "overflow: hidden; clip: rect(0,0,0,0); border: 0;"
            ),
        ),
    ].with_media(_DATEPICKER_MEDIA)


# Form-field rendering. The element classes (label/error/checkbox-row + the
# controls, which carry their own classes via PrimitiveWidgetsMixin) live here,
# not in input.css — no selector reaches across the DOM to style a form.
_LABEL_CLASS = "mb-2.5 text-sm font-medium text-heading"
_FIELD_ERROR_CLASS = "mt-4 mb-1 pl-3 py-2 bg-red-600 text-slate-200 w-[300px]"
# Checkbox + its label share a row (unlike block fields), justified apart.
_CHECKBOX_ROW_CLASS = "flex flex-row justify-between mt-3"


def _field_errors(errors) -> Node | None:
    """Render a form/field ErrorList as a styled <ul>, or None if empty."""
    items = [Li()[str(error)] for error in errors]
    if not items:
        return None
    return Ul(class_=_FIELD_ERROR_CLASS)[*items]


def FormFields(form, *, extras: dict[str, Node] | None = None) -> Node:
    """Render a Django form's fields as self-styled component rows.

    Replaces ``form.as_div()`` so labels, errors, row layout, and the checkbox
    row carry their own classes (no form styling in input.css). Native controls
    get their classes from ``PrimitiveWidgetsMixin``; composite widgets
    (SearchSelect) self-style. ``extras`` maps a field name to a node appended
    inside that field's row (e.g. the session timestamp helper buttons).
    """
    extras = extras or {}
    rows: list[Node] = []

    non_field = _field_errors(form.non_field_errors())
    if non_field:
        rows.append(non_field)

    for field in form:
        if field.is_hidden:
            rows.append(Safe(str(field)))
            continue

        is_checkbox = getattr(field.field.widget, "input_type", None) == "checkbox"
        label = Label(for_=field.id_for_label, class_=_LABEL_CLASS)[str(field.label)]
        control = Safe(str(field))
        errors = _field_errors(field.errors)
        extra = extras.get(field.name)

        if is_checkbox:
            children: list[Node] = [label, control]
            if errors:
                children.append(errors)
            if extra:
                children.append(extra)
            rows.append(Div(class_=_CHECKBOX_ROW_CLASS)[*children])
        else:
            children = []
            if errors:
                children.append(errors)
            children.extend([label, control])
            if extra:
                children.append(extra)
            rows.append(Div()[*children])

    return Fragment(*rows, separator="\n")


def AddForm(
    form,
    *,
    request,
    fields: Node | SafeText | str | None = None,
    additional_row: Node | SafeText | str = "",
    submit_class: str = "mt-3",
) -> Node:
    """Page body for the generic add/edit form (Python equivalent of add.html).

    `fields` overrides the default ``FormFields(form)`` field markup (used by the
    session form, which lays out its fields manually). `additional_row` holds
    extra submit buttons rendered below the main Submit button. `submit_class`
    is applied to the main Submit button (the session form passes "" to match
    its original markup).
    """
    field_markup = fields if fields is not None else FormFields(form)
    submit_attrs = [("class", submit_class)] if submit_class else []

    inner_form = Form(
        method="post",
        enctype="multipart/form-data",
        # Form owns its row layout (was the #add-form form{} rule in input.css).
        class_="flex flex-col gap-3",
    )[
        CsrfInput(request),
        field_markup,
        Div()[ControlButton(submit_attrs, type="submit")["Submit"]],
        Div(class_="flex flex-wrap gap-2")[
            *([additional_row] if additional_row else [])
        ],
    ]

    return Div(id_="add-form", class_="max-width-container")[
        Div(
            id_="add-form",
            class_=f"form-container w-full {FORM_MAX_WIDTH_CLASS} mx-auto @container",
        )[inner_form]
    ]


def PageHeading(
    children: Children = None,
    badge: str = "",
) -> Element:
    """Page heading (``<h1>``) with optional badge count."""
    children = children or []
    heading_class = "mb-4 text-3xl font-extrabold leading-none tracking-tight text-gray-900 dark:text-white"
    badge_html: Node | str = ""

    if badge:
        heading_class = "flex items-center " + heading_class
        badge_html = Badge(badge, size="lg", extra_class="me-2 ms-2")

    return H1(class_=heading_class)[
        *as_children(children), *([badge_html] if badge_html else [])
    ]


class Modal(BaseComponent):
    """Modal overlay with container. Content goes via the htpy ``[]`` slot —
    ``Modal(modal_id)[form, buttons]`` — which the inner panel ``<div>`` wraps."""

    def __init__(self, modal_id: str, _children: Children = None) -> None:
        self.modal_id = modal_id
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> "Modal":
        return Modal(self.modal_id, as_children(children))

    def render(self) -> Node:
        return Div(
            id_=self.modal_id,
            # z-40: above in-page positioned UI (popovers z-10, dropdown
            # panels z-20) so the overlay dims and covers them, but below the
            # toast container (z-50). Matters for modals rendered inline in a
            # row (e.g. the session reset confirm) rather than portaled into
            # the body-level #global-modal-container.
            class_=(
                "fixed z-40 inset-0 bg-black/70 dark:bg-gray-600/50 overflow-y-auto "
                "h-full w-full flex items-center justify-center"
            ),
        )[
            Div(
                class_=(
                    f"relative mx-auto p-5 border-accent border w-full "
                    f"{FORM_MAX_WIDTH_CLASS} shadow-lg/50 rounded-md bg-white "
                    "dark:bg-gray-900 @container"
                ),
            )[*self._children]
        ]


def ConfirmPage(
    *,
    title: str,
    message: Children,
    action_url: str,
    csrf_token: str,
    cancel_url: str,
    confirm_label: str = "Confirm",
    confirm_color: ButtonColor = "red",
) -> Node:
    """Full-page confirmation: a prompt, a POST ``<form>`` (the confirm action)
    and a cancel link back to the origin. The no-JS replacement for the htmx
    confirmation modals — reusable across delete/refund/split/reset flows.
    """
    return Div(
        class_=f"mx-auto w-full {FORM_MAX_WIDTH_CLASS} p-5 @container",
    )[
        Form(method="post", action=action_url)[
            Safe(
                f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            ),
            P(
                class_="text-2xl leading-6 font-medium dark:text-white text-center",
            )[title],
            P(class_="dark:text-white text-center mt-5")[*as_children(message)],
            Div(class_="flex flex-col gap-2 mt-6")[
                ControlButton(
                    color=confirm_color,
                    type="submit",
                )[confirm_label],
                ControlButton(href=cancel_url, color="gray")["Cancel"],
            ],
        ]
    ]


def TableTd(
    children: Children = None,
) -> Element:
    """Styled table cell."""
    children = children or []
    return Td(class_="px-4 py-2")[*as_children(children)]


type Cell = Child  # one table cell, e.g. NameWithIcon(game=game) or "2024"


class TableRowData(TypedDict):
    """Canonical row shape: positional cells plus optional ``<tr>`` attributes.

    Build with :func:`make_row`; rendered by :func:`TableRow`. The first cell
    becomes a ``<th scope="row">``, the rest ``<td>``. ``attributes`` carries
    htpy-style ``<tr>`` attributes (``id``, ``hx-*`` …) already translated to
    ``(name, value)`` pairs.
    """

    cell_data: list[Cell]
    attributes: NotRequired[list[HTMLAttribute]]


type Align = Literal["left", "right"]  # column text alignment, e.g. "right"


class Column(NamedTuple):
    """One table column header. ``sort_key`` (a public key in the view's
    ``*_SORTS`` map) makes the header clickable-to-sort; ``None`` → a static
    header (e.g. an "Actions" column). ``align`` aligns *the header*; the body
    cell owns its own alignment (e.g. an Actions ``ButtonGroup`` right-aligns
    itself), so set both to "right" together for an Actions column."""

    label: str
    sort_key: str | None = None
    align: Align = "left"


class TableData(TypedDict):
    """Canonical table shape consumed by :func:`StyledTable` /
    :func:`paginated_table_content`. Every list view builds this."""

    header_action: Child | None
    columns: list[Column]
    rows: Sequence[TableRowData]
    # The resolved active sort (from `apply_sort`'s SortResult.terms). Present on
    # the sortable list views; omitted by views with no sortable columns.
    sort_terms: NotRequired[Sequence[SortTerm]]


def make_row(*cells: Cell, **attributes: object) -> TableRowData:
    """Build a :class:`TableRowData` from positional cells and htpy-style
    attribute kwargs (``id=...``, ``hx_select=...`` → ``hx-select`` …).

    Mirrors the generic element builders: ``class_`` → ``class``, ``True`` →
    bare attribute, ``False``/``None`` omitted. Passing a ``class`` is rejected —
    :func:`TableRow` owns the styled row class; drop to the generic ``Tr`` builder
    for a custom-classed row.
    """
    if "class_" in attributes or "class" in attributes:
        raise ValueError(
            "make_row() does not accept a class attribute — TableRow owns the "
            "styled row class. Use the generic Tr builder for a custom-classed row."
        )
    data: TableRowData = {"cell_data": list(cells)}
    attrs = _attrs_from_kwargs(attributes)
    if attrs:
        data["attributes"] = attrs
    return data


def TableRow(data: TableRowData) -> Element:
    """Render a styled ``<tr>`` from a :class:`TableRowData`.

    First cell is a ``<th scope="row">``, the rest ``<td>``. The cosmetic row
    ``class`` is fixed here; ``data["attributes"]`` (``id``, ``hx-*`` …) is
    applied on top. For a differently-styled row use the generic ``Tr`` builder.
    """
    cells = data["cell_data"]

    tr_class = (
        "odd:bg-white dark:odd:bg-gray-900 even:bg-gray-50 "
        "dark:even:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 "
        "dark:hover:bg-gray-600 [&_a]:underline [&_a]:underline-offset-4 "
        "[&_a]:decoration-2"
    )
    tr_attrs: list[HTMLAttribute] = [("class", tr_class), *data.get("attributes", [])]

    cell_elements: list[Node] = []
    for i, cell in enumerate(cells):
        if i == 0:
            cell_elements.append(
                Th(
                    scope="row",
                    class_=(
                        "px-6 py-4 font-medium text-gray-900 "
                        "whitespace-nowrap dark:text-white"
                    ),
                )[cell]
            )
        else:
            cell_elements.append(TableTd()[cell])

    return Tr(tr_attrs)[*cell_elements]


def get_icon_node(name: str) -> Element:
    """Return the pre-built node tree for an icon. Falls back to 'unspecified'.

    The returned node is shared (module-level) and must be treated as read-only.
    """
    return ICON_NODES.get(name) or ICON_NODES["unspecified"]


# Classes applied to every icon, overriding whatever each snippet baked in — no
# need to touch the individual icon snippets. ICON_BASE_CLASS (colour) is always
# applied; the size is ICON_SIZE_CLASS by default, or whatever a caller passes as
# `size=`. ICON_BUTTON_SIZE_CLASS is the override for icons rendered inside
# buttons (bigger than the small inline platform icons). Tune sizes here.
ICON_BASE_CLASS = "text-black dark:text-white"
ICON_SIZE_CLASS = "w-2 h-2 lg:w-4 lg:h-4"
# Tracks _CONTROL_SIZE_CLASS's text line-height (text-xs → 1rem, @md:text-sm
# → 1.25rem) so icon-only buttons stay exactly as tall as text ones.
ICON_BUTTON_SIZE_CLASS = "w-4 h-4 @md:w-5 @md:h-5"


def _with_title(children: Sequence[Child], title: str) -> list[Child]:
    """Return a new child list with the svg's direct-child ``<title>`` set.

    Replaces an existing direct-child ``<title>`` element's text if present,
    else prepends one. Titles baked deeper in the tree (e.g. inside a ``<path>``)
    are left untouched; this sets the icon's accessible name / native tooltip.
    """
    title_node = Title()[title]
    result = list(children)
    for index, child in enumerate(result):
        if isinstance(child, Element) and child.tag_name == "title":
            result[index] = title_node
            return result
    return [title_node, *result]


def Icon(
    name: str,
    attributes: Attributes | None = None,
    size: str | None = None,
) -> Node:
    """Render an icon, overriding its snippet's baked ``class`` with the central
    icon classes (:data:`ICON_BASE_CLASS` colour + size). Every other svg
    attribute (``viewBox``, ``xmlns`` …) is kept — dropping ``viewBox`` would clip
    the paths to a sliver. ``size=`` replaces the default :data:`ICON_SIZE_CLASS`
    wholesale (e.g. ``ICON_BUTTON_SIZE_CLASS`` for button icons). ``title=`` sets
    the accessible ``<title>`` child; a passed ``class=`` appends as an override.
    """
    root = get_icon_node(name)
    extra_attributes: list[HTMLAttribute] = []
    title: str | None = None
    caller_class = ""
    for key, value in attributes or []:
        if key == "title":
            title = str(value)
        elif key == "class":
            caller_class = str(value)
        else:
            extra_attributes.append((key, value))
    children = _with_title(root.children, title) if title is not None else root.children
    class_value = " ".join(
        part
        for part in (ICON_BASE_CLASS, size or ICON_SIZE_CLASS, caller_class)
        if part
    )
    preserved = [(key, value) for key, value in root.attributes if key != "class"]
    return Element(
        root.tag_name,
        [("class", class_value), *preserved, *extra_attributes],
        children,
    )


def TableHeader(
    children: Children = None,
) -> Element:
    """Table caption."""
    children = children or []
    return Caption(
        class_=(
            "p-2 text-lg font-semibold rtl:text-left text-right "
            "text-gray-900 bg-white dark:text-white dark:bg-gray-900"
        ),
    )[*as_children(children)]


def _replace_query(
    request, *, set_params: Mapping[str, str] | None = None, drop: Sequence[str] = ()
) -> str:
    """The current querystring with `set_params` applied and `drop` keys removed.

    The single home for list-view querystring surgery (pagination + sort links).
    Preserves every other param (filter, search, …) untouched.
    """
    params: QueryDict = (
        request.GET.copy() if request is not None else QueryDict(mutable=True)
    )
    for key in drop:
        params.pop(key, None)
    for key, value in (set_params or {}).items():
        params[key] = value
    encoded = params.urlencode()
    return "?" + encoded if encoded else "?"


def _page_url(request, page) -> str:
    """Current querystring with `page` replaced (mirrors {% param_replace %})."""
    return _replace_query(request, set_params={"page": str(page)})


def _sort_href(request, sort_string: SortString) -> str:
    """Sort link target: set (or clear) `sort` and reset to page 1.

    An empty `sort_string` drops the param entirely so the view's default sort
    applies. `page` is always dropped — a sort change invalidates the old page.
    """
    if sort_string:
        return _replace_query(request, set_params={"sort": sort_string}, drop=("page",))
    return _replace_query(request, drop=("sort", "page"))


def _pagination_nav(page_obj, elided_page_range, request) -> Node:
    page_link_class = (
        "flex items-center justify-center px-3 h-8 leading-tight text-gray-500 "
        "bg-white border border-gray-300 hover:bg-gray-100 hover:text-gray-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
        "dark:hover:text-white"
    )
    current_link_class = (
        "cursor-not-allowed flex items-center justify-center px-3 h-8 leading-tight "
        "text-white border bg-gray-400 border-gray-300 dark:bg-gray-900 dark:border-gray-700 "
        "dark:text-gray-200"
    )
    page_items: list[Node] = []
    for page in elided_page_range:
        if page != page_obj.number:
            link = A(href=_page_url(request, page), class_=page_link_class)[str(page)]
        else:
            link = A(aria_current="page", class_=current_link_class)[str(page)]
        page_items.append(Li()[link])

    if page_obj.has_previous():
        prev_link = A(
            href=_page_url(request, page_obj.previous_page_number()),
            class_=(
                "flex items-center justify-center px-3 h-8 ms-0 leading-tight "
                "text-gray-500 bg-white border border-gray-300 rounded-s-lg "
                "hover:bg-gray-100 hover:text-gray-700 dark:bg-gray-800 "
                "dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
                "dark:hover:text-white"
            ),
        )["Previous"]
    else:
        prev_link = A(
            aria_current="page",
            class_=(
                "cursor-not-allowed flex items-center justify-center px-3 h-8 "
                "leading-tight text-gray-300 bg-white border border-gray-300 "
                "rounded-s-lg dark:bg-gray-800 dark:border-gray-700 dark:text-gray-600"
            ),
        )["Previous"]

    if page_obj.has_next():
        next_link = A(
            href=_page_url(request, page_obj.next_page_number()),
            class_=(
                "flex items-center justify-center px-3 h-8 leading-tight "
                "text-gray-500 bg-white border border-gray-300 rounded-e-lg "
                "hover:bg-gray-100 hover:text-gray-700 dark:bg-gray-800 "
                "dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
                "dark:hover:text-white"
            ),
        )["Next"]
    else:
        next_link = A(
            aria_current="page",
            class_=(
                "cursor-not-allowed flex items-center justify-center px-3 h-8 "
                "leading-tight text-gray-300 bg-white border border-gray-300 "
                "rounded-e-lg dark:bg-gray-800 dark:border-gray-700 dark:text-gray-600"
            ),
        )["Next"]

    number_class = "font-semibold text-gray-900 dark:text-white"
    summary = Span(
        class_=(
            "text-sm text-center font-normal text-gray-500 dark:text-gray-400 "
            "mb-4 md:mb-0 block w-full md:inline md:w-auto"
        ),
    )[
        # Element joins children with "", so the em-dash and " of " hug the
        # number spans inline — "1—10 of 50", not "1 — 10 of 50".
        Span(class_=number_class)[str(page_obj.start_index())],
        "—",
        Span(class_=number_class)[str(page_obj.end_index())],
        " of ",
        Span(class_=number_class)[str(page_obj.paginator.count)],
    ]
    pages = Ul(class_="inline-flex -space-x-px rtl:space-x-reverse text-sm h-8")[
        Li()[prev_link, *page_items, next_link]
    ]
    return Nav(
        class_=(
            "flex items-center flex-col md:flex-row md:justify-between px-6 py-4 "
            "dark:bg-gray-900 sm:rounded-b-lg"
        ),
        aria_label="Table navigation",
    )[summary, pages]


# <sort-header> wraps a header anchor; its TS intercepts shift-click to navigate
# to the multi-column target (data-shift-href). Registered in custom_elements.py.
_SortHeader = custom_element_builder("sort-header")

_SORT_HEADER_LINK_CLASS = (
    "flex items-center gap-1 select-none no-underline "
    "hover:text-gray-900 dark:hover:text-white"
)


def _sort_indicator(position: int, descending: bool, total: int) -> Node:
    """Active-column affordance: an arrow (down=desc, rotated up=asc) plus a
    1-based position badge when more than one column is active."""
    # `arrowdownlong` points down (descending); rotate 180° → up (ascending).
    # The snippet already carries `w-3 h-3`; Icon merges these extras onto it.
    arrow_class = "inline-block" + ("" if descending else " rotate-180")
    children: list[Child] = [Icon("arrowdownlong", [("class", arrow_class)])]
    if total > 1:
        children.append(Badge(str(position + 1), size="sm"))
    return Fragment(*children)


def _header_cell(column: "Column", sort_terms: Sequence[SortTerm], request) -> Node:
    """One ``<th>``: a static header for a non-sortable column, else a clickable
    sort link wrapped in ``<sort-header>`` with both navigation targets baked in."""
    base_class = "px-6 py-3" + (" text-right" if column.align == "right" else "")
    if column.sort_key is None:
        return Th(scope="col", class_=base_class)[column.label]

    active = next(
        (
            (index, term)
            for index, term in enumerate(sort_terms)
            if term.key == column.sort_key
        ),
        None,
    )
    aria_sort = "none"
    indicator: Child = ""
    if active is not None:
        index, term = active
        aria_sort = "descending" if term.descending else "ascending"
        indicator = _sort_indicator(index, term.descending, len(sort_terms))

    link = A(
        href=_sort_href(request, collapse_sort(sort_terms, column.sort_key)),
        data_shift_href=_sort_href(request, cycle_sort(sort_terms, column.sort_key)),
        class_=_SORT_HEADER_LINK_CLASS,
    )[column.label, indicator]
    return Th(scope="col", class_=base_class, aria_sort=aria_sort)[_SortHeader()[link]]


def StyledTable(
    columns: list[Column] | None = None,
    rows: Sequence[TableRowData] | None = None,
    header_action: Child | None = None,
    page_obj=None,
    elided_page_range=None,
    request=None,
    sort_terms: Sequence[SortTerm] | None = None,
) -> Node:
    """Styled, paginated table — the opinionated wrapper over the generic
    ``Table`` primitive (shadow, rounded, zebra rows, responsive column-hiding,
    pagination nav). Python equivalent of the old simple_table.html.

    Returns a node tree, so each cell component's declared ``Media`` bubbles up
    automatically via ``TimetrackerDocument()``'s ``collect_media`` — no manual collection.
    """
    columns = columns or []
    rows = rows or []
    sort_terms = sort_terms or []

    # Dev-only guard: a row must have one cell per column, else cells render
    # misaligned under the headers and the position-based mobile column-hiding
    # CSS corrupts. The type system can't express this count rule, so catch a
    # mismatch loudly in DEBUG; prod degrades to a ragged table over a 500.
    if settings.DEBUG:
        for row in rows:
            cell_count = len(row["cell_data"])
            if cell_count != len(columns):
                raise ValueError(
                    f"StyledTable row has {cell_count} cells but {len(columns)} "
                    f"columns were given: {row['cell_data']!r}"
                )

    table_children: list[Node] = []
    if header_action:
        table_children.append(TableHeader()[header_action])

    header_row = Tr()[[_header_cell(column, sort_terms, request) for column in columns]]
    table_children.append(
        Thead(
            class_=(
                "text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 "
                "dark:text-gray-400 "
                "max-sm:[&_th:not(:first-child):not(:last-child)]:hidden"
            ),
        )[header_row]
    )
    # Body-cell alignment is a table-level rule (not per-row) so an htmx-swapped
    # <tr> aligns from the live <tbody> it lands in — the fragment row stays
    # dumb. Driven by Column.align; a right column at position i targets its
    # <td> (the first cell is a <th scope="row">, so td:nth-child(i+1) is right).
    # The nth-child literals are safelisted via @source inline in input.css.
    tbody_class = (
        "dark:divide-y max-sm:[&_td:not(:first-child):not(:last-child)]:hidden"
    )
    align_rules = " ".join(
        f"[&_td:nth-child({index + 1})]:text-right"
        for index, column in enumerate(columns)
        if column.align == "right"
    )
    if align_rules:
        tbody_class = f"{tbody_class} {align_rules}"
    table_children.append(
        Tbody(class_=tbody_class)[[TableRow(data=row) for row in rows]]
    )

    table = Table(
        class_=(
            "w-full text-sm text-left rtl:text-right text-gray-500 dark:text-gray-400"
        ),
    )[*table_children]

    inner_children: list[Node] = [
        Div(class_="relative overflow-x-auto sm:rounded-t-lg")[table]
    ]
    if page_obj and elided_page_range:
        inner_children.append(_pagination_nav(page_obj, elided_page_range, request))

    return Div(class_="shadow-md", hx_boost="false")[*inner_children]


def paginated_table_content(
    data: TableData,
    *,
    page_obj=None,
    elided_page_range=None,
    request=None,
) -> Node:
    """Standard list-page body: a max-width Div wrapping a StyledTable.

    `data` is the table dict with keys ``columns``, ``rows`` and
    ``header_action`` (the same shape every list view already builds).
    """
    return Div(class_=f"w-full {CONTENT_MAX_WIDTH_CLASS} self-center")[
        StyledTable(
            columns=data["columns"],
            rows=data["rows"],
            header_action=data["header_action"],
            page_obj=page_obj,
            elided_page_range=elided_page_range,
            request=request,
            sort_terms=data.get("sort_terms"),
        )
    ]
