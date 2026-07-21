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
from django.utils.safestring import SafeText

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
from common.criteria import FilterWidgetPath, LeafWidgetKind
from common.sorting import SortString, SortTerm, collapse_sort, cycle_sort

type ButtonColor = Literal["blue", "red", "gray", "green"]  # e.g. "red" (destructive)
type ButtonVariant = Literal[
    "filled",  # standalone default
    "segmented",  # ButtonGroup member
    "outline",  # bordered dropdown-toggle look (colorless)
    "plain",  # borderless navbar nav-link look (colorless)
    "ghost",  # transparent-until-hover dropdown-toggle look (colorless)
]

# Shared disabled appearance for every form control, so all form elements look
# the same when disabled. Put on the control itself (DISABLED_CONTROL_CLASS) or,
# for composite controls whose disabled state lives on an inner element (e.g.
# SearchSelect), on the wrapper via :has() (DISABLED_WITHIN_CLASS).
DISABLED_CONTROL_CLASS = "disabled:opacity-50 disabled:cursor-not-allowed"
DISABLED_WITHIN_CLASS = "has-[:disabled]:opacity-50 has-[:disabled]:cursor-not-allowed"


def filter_widget_attributes(
    path: FilterWidgetPath,
    kind: LeafWidgetKind,
) -> list[HTMLAttribute]:
    """The self-describe attributes every filter widget root carries.

    The generic serializers (``ts/elements/quick-filter-bar.ts`` and the
    builder's leaf readers in ``ts/elements/filter-widgets.ts``) read
    ``data-path`` (the widget's filter-JSON key, as a JSON array) and
    ``data-kind`` off any ``[data-filter-widget]`` root to handle all widgets
    uniformly.
    """
    return [
        ("data-filter-widget", ""),
        ("data-path", json.dumps(path)),
        ("data-kind", kind),
    ]


# The single max-width every content container obeys — navbar, page bodies
# (lists, detail, stats), and popovers. Only a cap: callers add
# `w-full` to fill to it and `mx-auto`/`self-center` to centre. The `w-full`
# matters inside #main-container's flex column, where bare self-center/mx-auto
# turn off flex `stretch` and the box would otherwise shrink to content width.
CONTENT_MAX_WIDTH_CLASS = "max-w-7xl"

# Horizontal page gutter: keeps content off the viewport edges below the
# CONTENT_MAX_WIDTH_CLASS cap (everything is edge-to-edge under 1280px without
# it). Applied at the shell (#main-container) and the navbar row so every page
# inherits it in one place. `sm:px-6` widens the gutter on larger screens.
PAGE_GUTTER_CLASS = "px-4 sm:px-6"

# Narrower cap for form-shaped containers (add/edit forms, confirm pages,
# modals). Forms read better constrained; the wide CONTENT_MAX_WIDTH_CLASS cap
# is for page bodies, lists, and the navbar.
FORM_MAX_WIDTH_CLASS = "max-w-xl"

# The one micro-label spelling — filter facet labels and search-select group
# headers. Weight is `font-medium`; callers add a colour token (`text-body`).
MICRO_LABEL_CLASS = "text-type-micro-caps uppercase"

# The one dialog/confirm-page title spelling. Built on a raw `Element("h1")`
# (not the `H1` builder) so the baked `text-type-title`/`mb-2` scale does not leak in —
# accumulation can't down-scale a baked size.
DIALOG_TITLE_CLASS = "text-type-dialog text-heading text-center"


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


def _html_element(tag_name: str, media: Media | None = None, default_class: str = ""):
    """Build a generic element builder for ``tag_name`` (the whitelist factory).

    If ``media`` is provided, every node created by the builder will carry it
    (used for custom elements whose compiled JS must be loaded automatically).

    ``default_class`` bakes a base class list onto every node; caller ``class_``
    accumulates onto it (node-layer class merge). Note accumulation is not
    override — a caller cannot down-scale a baked size utility (Tailwind sorts
    ``text-*`` alphabetically), so components wanting a different scale build on
    a raw ``Element`` instead of the baked builder.
    """

    def element(
        attrs: "AttrsArg | None" = None,
        **kwargs: object,
    ) -> Element:
        # Merge order is priority order — first contributor wins per the node
        # algebra: baked ``default_class`` first, then positional ``attrs``
        # (dynamic), then htpy ``kwargs`` (static); ``class`` accumulates across
        # all three. Children come via ``[]``.
        merged = _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs)
        if default_class:
            merged = [("class", default_class), *merged]
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
Br = _html_element("br")
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
H1 = _html_element("h1", default_class="text-type-title mb-2")
H2 = _html_element("h2", default_class="text-type-heading mb-2")
H3 = _html_element("h3", default_class="text-type-subheading mb-2")


# The <pop-over> hover/focus tooltip element (behavior: ts/elements/pop-over.ts).
# Registered for codegen in common/components/custom_elements.py (which imports
# from this module, so registration can't live here). Media is auto-attached, so
# Page() emits the compiled JS wherever a Popover appears.
_PopOver = custom_element_builder("pop-over")
_TruncatedText = custom_element_builder("truncated-text")

_TOOLTIP_PANEL_CLASS = (
    f"z-10 inline-block text-type-body text-heading bg-brand-soft border "
    f"border-brand/30 rounded-base shadow-xs {CONTENT_MAX_WIDTH_CLASS}"
)


def _tooltip_panel(
    content: Child,
    *,
    id: str = "",
    aria_hidden: bool = False,
) -> Node:
    """The shared server-rendered panel anatomy for passive tooltips."""
    attributes: list[HTMLAttribute] = [("data-pop-over-panel", "")]
    if aria_hidden:
        attributes.append(("aria-hidden", "true"))
    else:
        attributes.extend([("id", id), ("role", "tooltip")])
    attributes.extend([("hidden", ""), ("class", _TOOLTIP_PANEL_CLASS)])
    return Div(attributes)[
        Div([("data-pop-over-content", "")], class_="px-3 py-2 overflow-y-auto")[
            content
        ],
        Div([("data-pop-over-arrow", "")], class_="absolute w-2 h-2 rotate-45"),
        Safe(  # nosec — intentional HTML comment for Tailwind JIT
            "<!-- for Tailwind CSS to generate decoration-dotted CSS "
            "from Python component -->"
        ),
        Span(class_="hidden decoration-dotted"),
    ]


def _popover_html(
    id: str,
    popover_content: Child,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    slot: "Node | str" = "",
    *,
    tap: bool = True,
    trigger_label: str = "",
    preface: "Node | str" = "",
    selectable_text: bool = False,
) -> Node:
    """Generate popover HTML. Single source of truth for popover structure.

    Renders the ``<pop-over>`` hover/focus tooltip (behavior:
    ``ts/elements/pop-over.ts``). The trigger carries ``aria-describedby``
    pointing at the ``role="tooltip"`` panel; the element owns show/hide and
    viewport-aware ``position: fixed`` placement.

    ``tap`` (default) renders the trigger as a real ``<button>`` so a tap on a
    touch device toggles the panel; ``tap=False`` keeps the hover/focus-only
    ``<span>`` (used where the popover sits inside a caller's interactive
    element, so a ``<button>`` would nest illegally). ``preface`` renders a node
    (e.g. a link) as a sibling *before* the trigger inside the host — the whole
    host still opens on hover, but only the small ``<button>`` trigger is
    tappable, keeping the trigger out of the preface link. ``trigger_label``
    sets the button's ``aria-label`` when its visible content is a bare glyph;
    ``selectable_text`` re-enables text selection + left alignment on button
    triggers whose content is meaningful text (e.g. a price).
    """
    display_content = wrapped_content if wrapped_content else slot
    trigger_children = [display_content] if display_content else []

    if tap:
        button_classes = wrapped_classes
        if selectable_text:
            button_classes = f"{button_classes} select-text text-start".strip()
        trigger_attributes = [
            ("type", "button"),
            ("data-pop-over-trigger", ""),
            ("aria-describedby", id),
            ("class", button_classes),
        ]
        if trigger_label:
            trigger_attributes.append(("aria-label", trigger_label))
        trigger: Node = Button(trigger_attributes)[*trigger_children]
    else:
        trigger = Span(
            [
                ("data-pop-over-trigger", ""),
                ("aria-describedby", id),
                ("class", wrapped_classes),
            ]
        )[*trigger_children]

    # No positioning class — the element sets `position: fixed` + coords on show
    # and clears them on hide; the `hidden` attribute owns the closed state.
    panel = _tooltip_panel(popover_content, id=id)

    # self-start keeps the host at its trigger's content width in a flex parent:
    # a flex column blockifies the inline-block and stretches it to full width,
    # which mis-anchors the fixed panel (the positioner centres on the host, #446).
    # align-self opts out of that cross-axis stretch; it's inert outside flex.
    # With a preface (the host-wraps-link case) the host lays the preface and the
    # glyph trigger side by side; hover on the whole host opens, only the trigger
    # is tappable — keeping the <button> a sibling of the preface link, never a
    # descendant.
    host_class = (
        "inline-flex items-center gap-1 self-start"
        if preface
        else "inline-block self-start"
    )
    host_children = (
        Fragment(preface, trigger, panel, separator="\n")
        if preface
        else Fragment(trigger, panel, separator="\n")
    )
    return _PopOver(tap="true" if tap else "false", class_=host_class)[host_children]


def Popover(
    popover_content: Child,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    children: Children = None,
    attributes: Attributes | None = None,
    id: str = "",
    *,
    tap: bool = True,
    trigger_label: str = "",
    preface: "Node | str" = "",
    selectable_text: bool = False,
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
        tap=tap,
        trigger_label=trigger_label,
        preface=preface,
        selectable_text=selectable_text,
    )


def PopoverIf(
    condition: bool,
    popover_content: Child,
    node: Node | str,
    id: str = "",
    *,
    tap: bool = True,
) -> Node | str:
    """Wrap `node` in a popover showing `popover_content` when `condition` holds.

    Without an explicit `id`, the popover's DOM id is derived from
    `popover_content` alone — pass `id` when two popovers on the same page
    could share the same content. `tap=False` keeps the hover/focus-only span
    (for a popover nested inside a caller's interactive element).
    """
    if condition:
        return Popover(popover_content=popover_content, children=[node], id=id, tap=tap)
    return node


NAME_MAX_WIDTH_CLASS = "max-w-[16rem]"
_TRUNCATED_CLIP_CLASS = (
    "block min-w-0 overflow-hidden whitespace-nowrap "
    "group-data-[overflowing]:"
    "[mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)]"
)
_TRUNCATED_REVEAL_CLASS = (
    "absolute inset-y-0 right-0 my-auto hidden size-6 items-center justify-center "
    "text-subtle hover:text-heading hover:cursor-pointer rounded-base shrink-0 "
)


def TruncatedText(
    text: str,
    *,
    leading: Child | None = None,
    link: str | None = None,
    tap: bool = True,
    reveal: Literal["auto", "always"] = "auto",
    tooltip_content: Child | None = None,
    instance_key: str | None = None,
    reveal_label: str = "Show full text",
    max_width: str = NAME_MAX_WIDTH_CLASS,
) -> Node:
    """Width-clipped text with a fade and a passive full-content tooltip.

    The full ``text`` always remains in the clip span. ``tooltip_content`` is
    only for differing information (multi-game purchase contents or a differing
    game sort name), where ``instance_key`` supplies a stable, page-unique ARIA
    relationship. Informative tooltips use an info reveal icon; visual-only
    overflow recovery uses an ellipsis.
    """
    informative = tooltip_content is not None
    if informative and not instance_key:
        raise ValueError("instance_key is required when tooltip_content is set")
    if not informative and instance_key:
        raise ValueError("instance_key is only valid when tooltip_content is set")

    panel_id = (
        randomid(content=f"truncated-text:{instance_key}:{text}") if informative else ""
    )
    describedby = [("aria-describedby", panel_id)] if informative else []
    # Informative content has an always-visible reveal button on no-hover
    # devices. Reserve that stable 24px before measuring, so a name that only
    # stops fitting because of the info button is correctly faded rather than
    # painted underneath it. Overflow-only ellipses stay out of layout; their
    # touch mask instead becomes fully transparent under the button.
    clip_class = _TRUNCATED_CLIP_CLASS
    if informative and tap:
        clip_class = f"{clip_class} [@media(hover:none)]:pe-6"
    clip_attributes: list[HTMLAttribute] = [
        ("data-truncated-clip", ""),
        ("class", clip_class),
    ]
    if informative and link is None:
        clip_attributes.extend(describedby)
    clip = Span(clip_attributes)[text]

    if link is not None:
        visible: Node = A(
            [
                ("href", link),
                ("class", "inline-flex w-full min-w-0 items-center gap-2"),
                *describedby,
            ]
        )[leading or "", clip]
    else:
        visible = Fragment(leading or "", clip)

    children: list[Child] = [visible]
    if tap:
        visibility = (
            "[@media(hover:none)]:inline-flex"
            if reveal == "always"
            else "[@media(hover:none)]:group-data-[overflowing]:inline-flex"
        )
        reveal_icon = "info" if informative else "ellipsis"
        button_attributes: list[HTMLAttribute] = [
            ("type", "button"),
            ("data-truncated-reveal", reveal_icon),
            ("aria-label", reveal_label),
            ("class", f"{_TRUNCATED_REVEAL_CLASS} {visibility}"),
            *describedby,
        ]
        children.append(
            Button(button_attributes)[
                Icon(reveal_icon, [("class", "shrink-0")], size="size-[1.1em]")
            ]
        )

    panel_content: Child = tooltip_content if tooltip_content is not None else text
    children.append(
        _tooltip_panel(
            panel_content,
            id=panel_id,
            aria_hidden=not informative,
        )
    )
    return _TruncatedText(
        tap="true" if tap else "false",
        reveal=reveal,
        class_=(
            f"group relative inline-flex w-full min-w-0 items-center gap-2 "
            f"font-condensed {max_width}"
        ),
    )[*children]


# The classes both ControlButton variants truly share. Everything else —
# sizing, rounding, focus treatment — belongs to the variant, so the segmented
# look stays what ButtonGroup members rendered before the unification.
# inline-flex keeps every button the same height regardless of content — an
# icon+text button (e.g. "Log this game") would otherwise sit taller than its
# text-only siblings and step a segmented group's bottom edge.
_CONTROL_BASE_CLASS = (
    "font-medium text-type-body hover:cursor-pointer inline-flex items-center justify-center "
    f"{DISABLED_CONTROL_CLASS}"
)

# Shared by EVERY button-shaped variant. Height is the canonical control
# height (min-h-control = 42px, from --height-control), floored not fixed so a
# multi-line control still grows; the inline-flex base centers content in it.
# Only horizontal padding is set here — height no longer depends on font,
# padding, or any `@container` ancestor, so a button is the same 42px in every
# row (the container-query step and its cross-row inconsistency are gone).
CONTROL_SIZE_CLASS = "min-h-control px-3"

_FILLED_VARIANT_CLASS = (
    "gap-2 text-center leading-5 focus:outline-hidden focus:ring-4 rounded-base "
    f"{CONTROL_SIZE_CLASS}"
)

_SEGMENTED_VARIANT_CLASS = f"focus:z-10 {CONTROL_SIZE_CLASS}"

# Status-token notes shared by both tables:
# - danger/success -subtle rings shade-match brand-medium (x-200 light /
#   x-900 dark), giving every filled color the same ring weight; the -medium
#   status tokens sit one shade lighter in light theme.
# - The dark success scale tops out at success-strong (emerald-700) — the
#   AA-passing dark fill — so the darker hover shade has no token and stays
#   raw emerald-800 (the light success-strong value).
# - fg-brand fails AA on the dark hover surface (blue-500 on gray-700), so
#   every hover/focus text accent pairs with dark:*:text-heading.
# - Neutral hovers pair hover:bg-neutral-tertiary-medium with
#   hover:border-default-strong: in dark the tertiary-medium fill equals both
#   the resting border (default-medium, gray-700) and the table row-hover
#   surface, so without the one-step-lighter hover border the control
#   vanishes when hovered inside a hovered row. Light is a no-op (strong ==
#   medium == gray-200).
_FILLED_COLOR_CLASSES: dict[ButtonColor, str] = {
    "blue": "solid-brand box-border border border-transparent hover:bg-brand-strong focus:ring-brand-medium",
    "red": "solid-danger box-border border border-transparent hover:bg-danger-strong focus:ring-danger-subtle",
    "gray": (
        "text-heading bg-neutral-primary-medium border border-default-medium "
        "hover:bg-neutral-tertiary-medium hover:border-default-strong "
        "hover:text-fg-brand dark:hover:text-heading "
        "focus:ring-neutral-tertiary-medium"
    ),
    "green": (
        "text-white bg-success dark:bg-success-strong box-border border "
        "border-transparent hover:bg-success-strong dark:hover:bg-emerald-800 "
        "focus:ring-success-subtle"
    ),
}

# The segmented shell every color shares; the per-color entries add hover
# fill + focus accents.
_SEGMENTED_SHELL_CLASS = (
    "text-heading bg-neutral-primary-medium border border-default-medium "
    "focus:ring-2 focus:ring-fg-brand focus:text-fg-brand "
    "dark:focus:text-heading"
)

_SEGMENTED_COLOR_CLASSES: dict[ButtonColor, str] = {
    # Red/green hover previews the filled action color (danger/success fill),
    # with the border one shade darker than the fill so the segmented buttons
    # share the same "ring" look (only the hue differs). Gray's hover fill
    # matches the resting border shade, so it needs no hover border.
    "blue": (f"{_SEGMENTED_SHELL_CLASS} hover:solid-brand hover:border-brand-strong"),
    "gray": (
        f"{_SEGMENTED_SHELL_CLASS} "
        "hover:bg-neutral-tertiary-medium hover:border-default-strong "
        "hover:text-fg-brand dark:hover:text-heading"
    ),
    "red": (f"{_SEGMENTED_SHELL_CLASS} hover:solid-danger hover:border-danger-strong"),
    "green": (
        f"{_SEGMENTED_SHELL_CLASS} "
        "hover:bg-success dark:hover:bg-success-strong "
        "hover:border-success-strong dark:hover:border-emerald-800 "
        "hover:text-white"
    ),
}


# Dropdown-toggle variants (issue #272): single-look, no color axis. Outline
# is a regular button-shaped control — base + shared sizing + its bordered
# look. Plain is the navbar nav-link: its layout (flex justify-between,
# md:p-0) contradicts the base and the sizing scale, so it alone carries its
# complete look and skips both.
_OUTLINE_VARIANT_CLASS = (
    f"{CONTROL_SIZE_CLASS} text-heading bg-neutral-primary-medium border "
    "border-default-medium hover:bg-neutral-tertiary-medium "
    "hover:border-default-strong focus:outline-hidden focus:ring-2 "
    "focus:ring-fg-brand whitespace-nowrap"
)

# Ghost is the quiet outline sibling: invisible chrome at rest (transparent
# background AND transparent border — the border box is always there, so
# hover adds no layout shift), outline's bordered look on hover. Used by
# compact triggers that would read as clutter in a row of many (the quick
# filter bar's facet dropdowns).
_GHOST_VARIANT_CLASS = (
    f"{CONTROL_SIZE_CLASS} gap-2 rounded-base bg-transparent border "
    "border-transparent text-heading hover:bg-neutral-tertiary-medium "
    "hover:border-default-strong focus:outline-hidden focus:ring-2 "
    "focus:ring-fg-brand whitespace-nowrap"
)

_PLAIN_VARIANT_CLASS = (
    "flex items-center justify-between w-full py-2 px-3 text-gray-900 rounded-base "
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
    selectors — callers add rounding by shape, e.g. ``rounded-e-base``);
    ``variant="ghost"`` is the transparent-until-hover toggle (quick-facet
    dropdown triggers) — outline's look on hover, invisible chrome at rest;
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
        elif variant == "ghost":
            class_attrs = [
                ("class", _CONTROL_BASE_CLASS),
                ("class", _GHOST_VARIANT_CLASS),
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
    # The <button type>: "submit" makes a bare-button member submit its
    # ancestor form (the quick bar's Apply). Only meaningful with
    # button_attributes; defaults to "button".
    type: str


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
                type=member.get("type", "button"),
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
            "inline-flex rounded-base shadow-xs "
            "[&>*:first-child]:rounded-s-base "
            "[&>*:first-child_button]:rounded-s-base "
            "[&>*:last-child]:rounded-e-base "
            "[&>*:last-child_button]:rounded-e-base"
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

    return Label(
        class_="flex items-center gap-2 text-type-body text-heading cursor-pointer"
    )[input_el, label]


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

    return Label(
        class_="flex items-center gap-1 text-type-body text-heading cursor-pointer"
    )[input_el, label]


# Pill's inline utilities. Client-side pills clone this server <template>
# (search-select.ts never names a pill class), so this is the single source of
# pill markup — no byte-for-byte JS contract to keep in sync.
_PILL_CLASS = (
    "font-condensed inline-flex items-center min-h-control gap-1 px-2 py-0.5 text-type-body rounded-base "
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
    "font-condensed inline-flex items-center justify-center font-semibold "
    "leading-none rounded bg-brand-soft text-heading"
)
_BADGE_SIZE_CLASSES = {
    "sm": "text-type-micro px-1.5 py-0.5",
    "base": "text-type-body px-2 py-0.5",
    "lg": "text-type-heading px-2.5 py-0.5",
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


def ModuleScript(filename: str) -> Node:
    """A `<script type="module">` node pointing at a static JS file.

    A node (not a safe string) so it drops straight into a tree — head list or
    `scripts=` — beside the other `Script`/`Link` nodes, no `Safe(str(...))`."""
    return Script(type="module", src=static("js/" + filename))


def ExternalScript(url: str) -> Node:
    """A plain `<script src=...>` node for an external/CDN script."""
    return Script(src=url)


def StaticScript(filename: str) -> Node:
    """A plain (classic, non-module) `<script src=...>` node for a static JS
    file — for vendored UMD bundles, which break inside module scope."""
    return Script(src=static("js/" + filename))


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
        "solid-brand border-transparent hover:bg-brand-strong"
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
                    f"inline-flex items-center rounded-base {CONTROL_SIZE_CLASS} "
                    f"text-type-body font-medium {classes}",
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
_LABEL_CLASS = "mb-2.5 text-type-label text-heading"
_FIELD_ERROR_CLASS = (
    "mt-4 mb-1 pl-3 py-2 solid-danger w-full text-type-body rounded-base"
)
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
    heading_class = "mb-4 text-type-title leading-none text-heading"
    badge_html: Node | str = ""

    if badge:
        heading_class = "flex items-center " + heading_class
        badge_html = Badge(badge, size="lg", extra_class="me-2 ms-2")

    # Raw Element, not the H1 builder: the baked scale would fight this
    # heading's own text-type-title/mb-4 (accumulation, not override).
    return Element("h1", [("class", heading_class)])[
        *as_children(children), *([badge_html] if badge_html else [])
    ]


def DialogTitle(children: Children = None) -> Element:
    """The one dialog/confirm-page title — ``<h1>`` in :data:`DIALOG_TITLE_CLASS`.

    Raw ``Element`` (not the ``H1`` builder) so the baked heading scale does not
    accumulate underneath — see :data:`DIALOG_TITLE_CLASS`.
    """
    return Element("h1", [("class", DIALOG_TITLE_CLASS)])[*as_children(children)]


# The <modal-dialog> overlay element (behavior: ts/elements/modal-dialog.ts).
# Registered for codegen in common/components/custom_elements.py. Media is
# auto-attached, so Page() emits the compiled JS wherever a Modal appears.
_ModalDialog = custom_element_builder("modal-dialog")


class Modal(BaseComponent):
    """Modal overlay with container. Content goes via the htpy ``[]`` slot —
    ``Modal(modal_id)[form, buttons]`` — which the inner panel ``<div>`` wraps.

    The overlay is the ``<modal-dialog>`` custom element (behavior:
    ``ts/elements/modal-dialog.ts``): it wires the dismiss contract — Escape, a
    backdrop click, and any ``[data-modal-dismiss]`` control (via
    ``bindPopupDismiss``) — and carries ``role="dialog"``/``aria-modal``.
    Dismissing removes the overlay from the DOM.

    ``self_dismiss=False`` renders the same markup but keeps the element inert,
    for overlays managed by another element (the session-reset confirm, wrapped
    in ``<session-actions>``); a second dismiss engine would fight that owner.
    """

    def __init__(
        self,
        modal_id: str,
        _children: Children = None,
        *,
        self_dismiss: bool = True,
    ) -> None:
        self.modal_id = modal_id
        self._children = as_children(_children)
        self.self_dismiss = self_dismiss

    def __getitem__(self, children: Children) -> "Modal":
        return Modal(
            self.modal_id, as_children(children), self_dismiss=self.self_dismiss
        )

    def render(self) -> Node:
        return _ModalDialog(
            id_=self.modal_id,
            role="dialog",
            aria_modal="true",
            data_manage="true" if self.self_dismiss else "false",
            # z-40: above in-page positioned UI (popovers z-10, dropdown
            # panels z-20) so the overlay dims and covers them, but below the
            # toast container (z-50). Matters for modals rendered inline in a
            # row (e.g. the session reset confirm) rather than portaled into
            # the body-level #global-modal-container.
            class_=(
                "fixed z-40 inset-0 bg-dark-backdrop/70 overflow-y-auto "
                "h-full w-full flex items-center justify-center"
            ),
        )[
            Div(
                [("data-modal-panel", "")],
                class_=(
                    f"relative mx-auto p-5 border-accent border w-full "
                    f"{FORM_MAX_WIDTH_CLASS} shadow-lg/50 rounded-base "
                    "bg-neutral-primary-soft @container"
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
            DialogTitle(title),
            P(class_="text-heading text-center mt-5")[*as_children(message)],
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
    return Td(class_="px-2 sm:px-3 lg:px-4 py-2")[*as_children(children)]


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
    itself), so set both to "right" together for an Actions column. ``class_``
    supplies column sizing classes to the header and, for the row-header first
    column, its body ``<th>``."""

    label: str
    sort_key: str | None = None
    align: Align = "left"
    class_: str = ""


class TableData(TypedDict):
    """Canonical table shape consumed by :func:`StyledTable` /
    :func:`paginated_table_content`. Every list view builds this."""

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


def TableRow(data: TableRowData, columns: Sequence[Column] | None = None) -> Element:
    """Render a styled ``<tr>`` from a :class:`TableRowData`.

    First cell is a ``<th scope="row">``, the rest ``<td>``. The cosmetic row
    ``class`` is fixed here; ``data["attributes"]`` (``id``, ``hx-*`` …) is
    applied on top. For a differently-styled row use the generic ``Tr`` builder.
    """
    cells = data["cell_data"]

    # Hover lightens the text along with the surface: body-subtle text fails AA
    # on the tertiary hover surface in both themes.
    tr_class = (
        "odd:bg-neutral-primary-soft even:bg-neutral-secondary-medium "
        "border-default-medium hover:bg-neutral-tertiary-medium "
        "hover:text-heading [&_a]:underline [&_a]:underline-offset-4 "
        "[&_a]:decoration-2"
    )
    tr_attrs: list[HTMLAttribute] = [("class", tr_class), *data.get("attributes", [])]

    cell_elements: list[Node] = []
    for i, cell in enumerate(cells):
        if i == 0:
            column_class = columns[0].class_ if columns else ""
            cell_elements.append(
                Th(
                    scope="row",
                    class_=(
                        "px-2 sm:px-3 lg:px-6 py-4 font-medium text-heading "
                        "whitespace-nowrap "
                        f"{column_class}"
                    ).strip(),
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
# need to touch the individual icon snippets. ICON_BASE_CLASS is intentionally
# colourless: monochrome icons use `fill="currentColor"`, so they inherit the
# text colour of their container (button, badge, body). Pinning a colour here
# would defeat that — an icon on a coloured button would keep black while the
# label followed the button's `text-white`. The size is ICON_SIZE_CLASS by
# default, or whatever a caller passes as `size=`. ICON_BUTTON_SIZE_CLASS is the
# override for icons rendered inside buttons (bigger than the small inline
# platform icons). Tune sizes here.
ICON_BASE_CLASS = ""
# em-based so a badge is always ~1.15x its adjacent text at any breakpoint —
# scales with font size, no jump at a viewport width.
ICON_SIZE_CLASS = "size-[1.15em]"
# Flat 1.25rem (20px) to match text-type-body's fixed line-height — buttons
# no longer use container-scaled text, so the icon must also be flat (not
# @md-responsive) to keep icon-only buttons the same height as text ones at
# every breakpoint (#272).
ICON_BUTTON_SIZE_CLASS = "w-5 h-5"


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


def _page_size_control(request, page_size: int, *, class_: str = "") -> Node:
    """The rows-per-page label + picker group, embedded in the pagination nav
    between the summary and the page links."""
    classes = f"flex items-center gap-2 text-type-body text-body-subtle {class_}"
    return Div(class_=classes.strip())[
        Span()["Rows per page"], PageSizeSelect(request, page_size)
    ]


def _pagination_nav(
    page_obj, elided_page_range, request, page_size: int | None = None
) -> Node:
    page_link_class = (
        "flex items-center justify-center px-3 min-h-control leading-tight text-body-subtle "
        "bg-neutral-primary-medium border border-default-medium "
        "hover:bg-neutral-tertiary-medium hover:text-heading"
    )
    # Brand fill: the current page is informational (`aria-current`), so its
    # text must clear AA — the muted-gray treatment didn't.
    current_link_class = (
        "cursor-not-allowed flex items-center justify-center px-3 min-h-control leading-tight "
        "solid-brand border border-brand"
    )
    disabled_link_class = (
        "cursor-not-allowed flex items-center justify-center px-3 min-h-control leading-tight "
        "text-fg-disabled bg-neutral-primary-medium border border-default-medium"
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
            class_=f"{page_link_class} ms-0 rounded-s-base",
        )["Previous"]
    else:
        prev_link = A(
            aria_current="page",
            class_=f"{disabled_link_class} rounded-s-base",
        )["Previous"]

    if page_obj.has_next():
        next_link = A(
            href=_page_url(request, page_obj.next_page_number()),
            class_=f"{page_link_class} rounded-e-base",
        )["Next"]
    else:
        next_link = A(
            aria_current="page",
            class_=f"{disabled_link_class} rounded-e-base",
        )["Next"]

    number_class = "font-semibold text-heading"
    summary = Span(
        class_=(
            "text-type-body text-center font-normal text-body-subtle "
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
    pages = Ul(
        class_="inline-flex -space-x-px rtl:space-x-reverse text-type-body min-h-control"
    )[Li()[prev_link, *page_items, next_link]]
    nav_children: list[Node] = [summary]
    # The rows-per-page picker sits between the "1—3 of 3" summary and the
    # prev/next page links.
    if page_size is not None and request is not None:
        nav_children.append(
            _page_size_control(request, page_size, class_="mb-4 md:mb-0")
        )
    nav_children.append(pages)
    return Nav(
        class_=(
            "flex items-center flex-col md:flex-row md:justify-between px-6 py-4 "
            "bg-neutral-primary-soft"
        ),
        aria_label="Table navigation",
    )[*nav_children]


# <sort-header> wraps a header anchor; its TS intercepts shift-click to navigate
# to the multi-column target (data-shift-href). Registered in custom_elements.py.
_SortHeader = custom_element_builder("sort-header")

_SORT_HEADER_LINK_CLASS = (
    "flex items-center gap-1 select-none no-underline hover:text-heading"
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
    base_class = "px-2 sm:px-3 lg:px-6 py-3" + (
        " text-right" if column.align == "right" else ""
    )
    if column.class_:
        base_class = f"{base_class} {column.class_}"
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


# The per-page sizes offered by the list-view rows-per-page picker.
PAGE_SIZE_PRESETS = (10, 25, 50, 100, 500, 1000)


def PageSizeSelect(request, current: int) -> Node:
    """A rows-per-page menu: a current-value trigger over ``?per_page=`` links.

    Pure navigation — each preset is an ``<a href>`` produced by ``_replace_query``
    (so ``sort``/``filter`` ride along and ``page`` resets), and ``<drop-down>``
    owns open/close. No new JS. The dropdown builders are imported lazily to avoid
    a module-load cycle (``custom_elements`` imports this module)."""
    from common.components.custom_elements import ButtonDropdown, DropdownLinkItem

    items = [
        DropdownLinkItem(
            _replace_query(request, set_params={"per_page": str(size)}, drop=("page",)),
            str(size),
            current=size == current,
        )
        for size in PAGE_SIZE_PRESETS
    ]
    return ButtonDropdown(
        label=str(current),
        items=items,
        id="page-size",
        aria_label="Rows per page",
    )


def StyledTable(
    columns: list[Column] | None = None,
    rows: Sequence[TableRowData] | None = None,
    page_obj=None,
    elided_page_range=None,
    request=None,
    sort_terms: Sequence[SortTerm] | None = None,
    page_size: int | None = None,
    show_header: bool = True,
    footer: Node | None = None,
) -> Node:
    """Styled, paginated table — the opinionated wrapper over the generic
    ``Table`` primitive (shadow, rounded, zebra rows, responsive column-hiding,
    pagination nav). Python equivalent of the old simple_table.html.

    Returns a node tree, so each cell component's declared ``Media`` bubbles up
    automatically via ``TimetrackerDocument()``'s ``collect_media`` — no manual collection.

    ``show_header=False`` suppresses the ``<thead>`` for headerless tables (e.g. the
    key-value stats blocks); ``columns`` is still required for the cell-count guard and
    column alignment.

    ``footer`` is a general slot rendered as the shell's last child, inside the
    rounded clip, after the scroll wrapper — for totals rows, "view all" bars, counts.
    The footer carries its own surface/padding classes. Pagination is one footer
    consumer: passing ``page_obj``/``elided_page_range`` renders the pagination nav in
    this slot, so supplying an explicit ``footer`` alongside pagination args is a
    contradiction and raises ``ValueError``.
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
    # `columns` still drives the count-guard and align rules when the header is
    # hidden (show_header=False) — e.g. the headerless key-value stats tables.
    if show_header:
        header_row = Tr()[
            [_header_cell(column, sort_terms, request) for column in columns]
        ]
        table_children.append(
            Thead(
                class_=(
                    "text-type-micro text-body uppercase bg-neutral-tertiary "
                    "max-md:[&_th:not(:first-child):not(:last-child)]:hidden"
                ),
            )[header_row]
        )
    # Body-cell alignment is a table-level rule (not per-row) so an htmx-swapped
    # <tr> aligns from the live <tbody> it lands in — the fragment row stays
    # dumb. Driven by Column.align; a right column at position i targets its
    # <td> (the first cell is a <th scope="row">, so td:nth-child(i+1) is right).
    # The nth-child literals are safelisted via @source inline in input.css.
    tbody_class = (
        "font-condensed dark:divide-y "
        "max-md:[&_td:not(:first-child):not(:last-child)]:hidden"
    )
    align_rules = " ".join(
        f"[&_td:nth-child({index + 1})]:text-right"
        for index, column in enumerate(columns)
        if column.align == "right"
    )
    if align_rules:
        tbody_class = f"{tbody_class} {align_rules}"
    table_children.append(
        Tbody(class_=tbody_class)[[TableRow(data=row, columns=columns) for row in rows]]
    )

    table = Table(
        class_="w-full text-type-body text-left rtl:text-right text-body-subtle",
    )[*table_children]

    # The scroll wrapper owns horizontal scroll only; the shell owns the radius
    # and clips this wrapper to it (a rounded clip can't coexist with overflow-x
    # scroll on one element, so they stay on separate elements).
    inner_children: list[Node] = [Div(class_="relative overflow-x-auto")[table]]

    paginated = bool(page_obj and elided_page_range)
    if paginated and footer is not None:
        raise ValueError(
            "StyledTable got both an explicit footer and pagination args; the "
            "footer slot holds one region. Pass pagination args OR footer, not both."
        )
    # The rows-per-page picker lives inside the pagination nav; with no nav
    # (per_page=0 → whole list shown) there is nothing to page, so no picker.
    footer_node = (
        _pagination_nav(page_obj, elided_page_range, request, page_size=page_size)
        if paginated
        else footer
    )
    if footer_node is not None:
        inner_children.append(footer_node)

    # The shell owns the intrinsic radius symmetrically; `overflow-hidden` clips
    # the scroll wrapper and footer to it, so top+bottom corners are rounded
    # regardless of which parts are present. The box-shadow follows this radius.
    # Warning: never add `transform`/`filter`/`contain`/`backdrop-filter` here —
    # it would make the shell a containing block for the `position: fixed`
    # dropdown menus and clip them (see e2e/test_dropdown_clipping_e2e.py).
    return Div(class_="shadow-md sm:rounded-base overflow-hidden", hx_boost="false")[
        *inner_children
    ]


def ContentContainer(attrs: "AttrsArg | None" = None, **kwargs: object) -> Element:
    """The page-body content container: fills #main-container's flex column
    (``w-full``), caps at ``CONTENT_MAX_WIDTH_CLASS`` and centres itself
    (``self-center``). Page bodies only — the navbar and popovers apply the
    max-width constant with their own layout classes, and form/confirm pages
    cap narrower via ``FORM_MAX_WIDTH_CLASS``/``AddForm``. Caller ``class``
    accumulates onto the baked classes; children come via ``[]``.
    """
    baked: list[HTMLAttribute] = [
        ("class", f"w-full {CONTENT_MAX_WIDTH_CLASS} self-center")
    ]
    return Div(baked + _coerce_attrs(attrs) + _attrs_from_kwargs(kwargs))


def paginated_table_content(
    data: TableData,
    *,
    page_obj=None,
    elided_page_range=None,
    request=None,
    page_size: int | None = None,
) -> Node:
    """The list-page table: a StyledTable (+ pagination) built from ``data``.

    `data` is the table dict with keys ``columns`` and ``rows`` (the same shape
    every list view already builds). The page-width container is the caller's
    job — list views wrap this, together with their filter tiers, in
    :func:`ContentContainer` (issue #313).

    Pass ``page_size`` (the resolved ``FindFilter.per_page``) to render the
    rows-per-page picker above the table.
    """
    return StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        sort_terms=data.get("sort_terms"),
        page_size=page_size,
    )
