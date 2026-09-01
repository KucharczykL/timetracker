"""Generic HTML primitives (no domain knowledge).

Generic leaf elements (``Div``, ``Span``, ``Td`` …) are *not* hand-written one
per tag: they are generated from a whitelist in :mod:`common.components.elements`
via :func:`~common.components.elements.element_builder`, each a thin builder over
the single :class:`Element` node class, and re-exported here. Only elements that
add classes or behaviour (``ControlButton``, ``Pill``, ``Checkbox`` …) are
written out in this module. Everything returns a :class:`Node`; string-built
widgets return :class:`Safe`.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
from common.components.elements import (
    H1,
    H2,
    H3,
    A,
    Body,
    Br,
    Button,
    Caption,
    Circle,
    Dd,
    Dialog,
    Div,
    Dl,
    Dt,
    Fieldset,
    Form,
    G,
    Head,
    Html,
    Img,
    Label,
    Legend,
    Li,
    Meta,
    Nav,
    Noscript,
    Optgroup,
    Option,
    P,
    Path,
    PlainH1,
    PlainH2,
    PlainH4,
    Rect,
    Script,
    Section,
    Select,
    Span,
    Strong,
    Svg,
    Table,
    Tbody,
    Td,
    Template,
    Th,
    Thead,
    Title,
    Tr,
    Ul,
    _attrs_from_kwargs,
    _coerce_attrs,
    element_builder,
)
from common.components.icons_generated import ICON_NODES
from common.criteria import FilterWidgetPath, LeafWidgetKind
from common.sorting import SortString, SortTerm, collapse_sort, cycle_sort
from timetracker.settings_registry import PAGE_SIZE_CHOICES

# Not every builder above is called from this module's own function bodies —
# most exist here purely to be re-exported to callers that import them from
# `common.components.primitives` (or `common.components`). Listing them marks
# that re-export as deliberate, so ruff's unused-import check doesn't flag them.
__all__ = [
    "H1",
    "H2",
    "H3",
    "A",
    "Body",
    "Br",
    "Button",
    "Caption",
    "Circle",
    "Dd",
    "Dialog",
    "Div",
    "Dl",
    "Dt",
    "Fieldset",
    "Form",
    "G",
    "Head",
    "Html",
    "Img",
    "Label",
    "Legend",
    "Li",
    "Link",
    "Meta",
    "Nav",
    "Noscript",
    "Optgroup",
    "Option",
    "P",
    "Path",
    "PlainH1",
    "PlainH2",
    "PlainH4",
    "Rect",
    "Script",
    "Section",
    "Select",
    "Span",
    "Strong",
    "Svg",
    "Table",
    "Tbody",
    "Td",
    "Template",
    "Th",
    "Thead",
    "Title",
    "Tr",
    "Ul",
]

type ButtonColor = Literal["blue", "red", "gray", "green"]  # e.g. "red" (destructive)
type ButtonVariant = Literal[
    "filled",  # standalone default
    "segmented",  # ButtonGroup member
    "outline",  # bordered dropdown-toggle look (colorless)
    "plain",  # borderless navbar nav-link look (colorless)
    "ghost",  # transparent-until-hover dropdown-toggle look (colorless)
]
# How a button's content sits on its main axis. Centered is the button default;
# "start" is for buttons rendered as a LIST of choices (the date picker's preset
# column), where a centered label reads as ragged against its neighbours. This
# is a real parameter rather than a caller `class_` because justify/text
# utilities collide: Tailwind resolves same-specificity conflicts by stylesheet
# order, not class-attribute order, so `class_="justify-start"` on a button
# whose baked class already says `justify-center` wins only by luck.
type ButtonAlign = Literal["center", "start"]
type BadgeSize = Literal["sm", "base", "lg"]
type BadgeTone = Literal["brand", "neutral", "success", "warning", "danger"]

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

# The one dialog/confirm-page title spelling. Built on `PlainH1` (not the
# styled `H1` builder) so the baked `text-type-title`/`mb-2` scale does not
# leak in — accumulation can't down-scale a baked size.
DIALOG_TITLE_CLASS = "text-type-dialog text-heading text-center"


class TooltipDefinition(NamedTuple):
    """One term/value pair in a shared tooltip definition list."""

    term: str
    description: Child
    attributes: AttrsArg | None = None


# ── Generic leaf elements ────────────────────────────────────────────────────
# Plain HTML/SVG builders (`Div`, `Span`, `H1`, …) and the `element_builder`
# factory they're generated from live in `elements.py` (core-adjacent, so the
# icon codegen can import SVG builders without a cycle through this module).
# This module re-exports them (see the import block above) alongside the
# styled/behavioural builders it defines itself below.


# Every anchor in the app goes through one of four builders, so "is this a text
# link?" is answered by the call rather than by remembering a class string.
# `tests/test_anchor_builders.py` fails the build on a bare `A()` outside them.
#
# The underline is the whole signal for "this navigates", which is why the
# colour is a token of its own rather than `brand` — see input.css. Callers add
# their own classes freely; the node layer accumulates `class`.
# Thickness is em-based, not a fixed `decoration-2`: 2px against the navbar's
# 12px micro text reads visibly heavier than the same 2px against 14px body
# text. Expressed as a fraction of the font size it stays proportional wherever
# a link lands.
LINK_CLASS = (
    "text-fg-link hover:text-fg-link-hover font-medium underline underline-offset-4 "
    "[text-decoration-thickness:0.11em]"
)

# Icon-only links carry no underline: there is no text for it to sit under, and
# the icon plus its hover shift already reads as interactive.
ICON_LINK_CLASS = "inline-flex items-center text-body hover:text-heading"

# A reveal glyph beside a link takes the link's colour: the two are one visual
# unit, and a grey circle next to purple underlined text reads as unrelated
# furniture. Beside plain text it stays subtle — the glyph is a button, not a
# link, so it must not claim the link colour where nothing navigates.
_REVEAL_LINKED_COLOR_CLASS = "text-fg-link hover:text-fg-link-hover"
_REVEAL_PLAIN_COLOR_CLASS = "text-subtle hover:text-heading"

#: An inline text link inside page content.
Link = element_builder("a", default_class=LINK_CLASS)

#: A link whose entire content is an icon.
IconLink = element_builder("a", default_class=ICON_LINK_CLASS)

#: Chrome that owns its own appearance — navbar items, pagination, sort
#: headers, the settings rail, dropdown menu items. Adds nothing at all; it
#: exists so "deliberately not a text link" is declared and greppable instead
#: of inferred from the absence of a class.
ControlLink = element_builder("a")


def custom_element_builder(tag_name: str):
    """Create a tag builder for a custom element with auto-attached Media.

    The module path follows the convention ``ts/elements/<tag>.ts`` →
    ``dist/elements/<tag>.js``.
    """
    return element_builder(tag_name, Media(js=(f"dist/elements/{tag_name}.js",)))


# The <pop-over> hover/focus tooltip element (behavior: ts/elements/pop-over.ts).
# Registered for codegen in common/components/custom_elements.py (which imports
# from this module, so registration can't live here). Media is auto-attached, so
# Page() emits the compiled JS wherever a Popover appears.
_PopOver = custom_element_builder("pop-over")
_TruncatedText = custom_element_builder("truncated-text")

# font-sans is deliberate, not redundant: the panel is a DOM descendant of
# whatever it annotates, so a tooltip mounted inside a data table or a
# TruncatedText host inherits font-condensed and renders in a different
# typeface from every other tooltip on the site. Stating the family here keeps
# a tooltip looking like a tooltip wherever it is mounted.
_TOOLTIP_PANEL_CLASS = (
    f"z-10 inline-block font-sans text-type-body text-heading bg-brand-soft "
    f"border border-brand/30 rounded-base shadow-xs {CONTENT_MAX_WIDTH_CLASS}"
)


def TooltipDefinitionList(
    definitions: Sequence[TooltipDefinition],
    *,
    class_: str = "",
) -> Node:
    """Render the canonical term/value treatment for informative tooltips."""
    list_class = f"flex flex-col gap-2 {class_}".strip()
    items = [
        Div(definition.attributes)[
            # font-medium on the term as well as the value: the term set no
            # weight, so it inherited one from wherever the tooltip was
            # mounted — 500 on an ordinary page but 400 inside a data table,
            # which made the same tooltip look different per surface. Term and
            # value are separated by size and color, not weight.
            Dt(class_="text-type-micro text-body font-medium")[definition.term],
            Dd(class_="font-medium")[definition.description],
        ]
        for definition in definitions
    ]
    return Dl(
        [
            ("data-tooltip-definition-list", ""),
            ("class", list_class),
        ],
    )[*items]


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


# The reveal glyph beside a popover's content. Swapping the leading
# `inline-flex` for `hidden [@media(hover:none)]:inline-flex` makes every
# reveal touch-only again — the single dial for how loudly popovers announce
# themselves.
_POPOVER_REVEAL_CLASS = (
    "inline-flex items-center shrink-0 rounded-base hover:cursor-pointer"
)
_POPOVER_REVEAL_LABEL = "More information"


def _popover_reveal(
    *,
    id: str,
    describedby: bool,
    trigger_label: str,
    linked: bool,
) -> Node:
    """The tap target for a popover whose content is not itself a control."""
    color = _REVEAL_LINKED_COLOR_CLASS if linked else _REVEAL_PLAIN_COLOR_CLASS
    attributes: list[HTMLAttribute] = [
        ("type", "button"),
        ("data-pop-over-control", ""),
        ("data-pop-over-reveal", ""),
        ("aria-label", trigger_label or _POPOVER_REVEAL_LABEL),
        ("class", f"{_POPOVER_REVEAL_CLASS} {color}"),
    ]
    if describedby:
        attributes.append(("aria-describedby", id))
    attributes.append(("data-pop-over-trigger", ""))
    return Button(attributes)[Icon("info", size="size-[1.1em]")]


def _popover_html(
    id: str,
    popover_content: Child,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    slot: Node | str = "",
    *,
    tap: bool = True,
    trigger_label: str = "",
    trigger_disabled: bool = False,
    preface: Node | str = "",
    symbol_trigger: bool = False,
    describedby: bool = True,
) -> Node:
    """Generate popover HTML. Single source of truth for popover structure.

    Renders the ``<pop-over>`` hover/focus tooltip (behavior:
    ``ts/elements/pop-over.ts``). The trigger carries ``aria-describedby``
    pointing at the ``role="tooltip"`` panel; the element owns show/hide and
    viewport-aware ``position: fixed`` placement.

    By default the visible content stays plain text and a small ⓘ button
    beside it is the tap target, so a popover announces itself on a device that
    cannot hover. Three shapes opt out, each for a structural reason:
    ``tap=False`` keeps the hover/focus-only ``<span>`` (the popover sits
    inside a caller's interactive element, so any ``<button>`` would nest
    illegally); ``symbol_trigger`` marks content that is already a bare symbol
    (an icon, a one-character badge), where a second glyph says nothing; and a
    disabled control keeps its native disabled button under a focusable
    wrapper, preserving pointer and keyboard access to the explanation. Those
    three render the older anatomy, where the content itself is the trigger.

    ``preface`` renders a node (e.g. a link) as the visible content, for values
    that must navigate — a ``<button>`` may not nest inside an ``<a>``, so the
    reveal has to be its sibling. ``trigger_label`` names the tap target for
    screen readers.
    """
    display_content = wrapped_content if wrapped_content else slot
    trigger_children = [display_content] if display_content else []
    # The content carries no control of its own only when the reveal glyph is
    # there to be one.
    content_is_trigger = symbol_trigger or trigger_disabled or not tap

    if tap and not content_is_trigger:
        visible: Node | str = (
            preface
            if preface
            else Span(class_=wrapped_classes)[*trigger_children]
            if trigger_children
            else ""
        )
        reveal = _popover_reveal(
            id=id,
            describedby=describedby,
            trigger_label=trigger_label,
            # `preface` is how a value that navigates reaches the popover, so
            # its presence is what makes this a link's glyph.
            linked=bool(preface),
        )
        return _PopOver(tap="true", class_="inline-flex items-center gap-1 self-start")[
            Fragment(
                visible,
                reveal,
                _tooltip_panel(popover_content, id=id),
                separator="\n",
            )
        ]

    if tap:
        control_attributes = [
            ("type", "button"),
            ("data-pop-over-control", ""),
            ("class", wrapped_classes),
        ]
        if trigger_disabled:
            # The wrapper span is the interaction and accessibility surface for
            # the whole disabled control. Browsers never dispatch `click` on a
            # disabled button, which would kill the tap-to-open path, so
            # `pointer-events-none` makes taps hit the wrapper instead; the
            # button is also aria-hidden (its label/description live on the
            # wrapper, and a role-less span may not carry an accessible name,
            # hence role="button" + aria-disabled).
            control_attributes.append(("disabled", "disabled"))
            control_attributes.append(("aria-hidden", "true"))
            control_attributes.append(("class", "pointer-events-none"))
            wrapper_attributes: list[HTMLAttribute] = [
                ("data-pop-over-trigger", ""),
                ("role", "button"),
                ("aria-disabled", "true"),
                ("tabindex", "0"),
                ("aria-describedby", id),
                (
                    "class",
                    (
                        "inline-flex rounded-base cursor-not-allowed "
                        "focus:outline-hidden focus:ring-4 "
                        "focus:ring-neutral-tertiary-medium"
                    ),
                ),
            ]
            if trigger_label:
                wrapper_attributes.append(("aria-label", trigger_label))
            trigger = Span(wrapper_attributes)[
                Button(control_attributes)[*trigger_children]
            ]
        else:
            if describedby:
                control_attributes.append(("aria-describedby", id))
            if trigger_label:
                control_attributes.append(("aria-label", trigger_label))
            control_attributes.append(("data-pop-over-trigger", ""))
            trigger = Button(control_attributes)[*trigger_children]
    else:
        span_attributes: list[HTMLAttribute] = [("data-pop-over-trigger", "")]
        if describedby:
            span_attributes.append(("aria-describedby", id))
        span_attributes.append(("class", wrapped_classes))
        trigger = Span(span_attributes)[*trigger_children]

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
    trigger_disabled: bool = False,
    preface: Node | str = "",
    symbol_trigger: bool = False,
    describedby: bool = True,
) -> Node:
    children = as_children(children)
    if not wrapped_content and not children and not preface:
        raise ValueError("One of wrapped_content, children or preface is required.")
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
        trigger_disabled=trigger_disabled,
        preface=preface,
        symbol_trigger=symbol_trigger,
        describedby=describedby,
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


# Below md the name cell must be able to shrink under its content so the
# actions column survives on a phone; max-w-0 is the only way to tell the
# auto-table algorithm that, and w-full then hands it the leftover. Above md
# the same pair makes the column eat every spare pixel, so it stops there and
# ordinary auto layout takes over.
SHRINKABLE_COLUMN_CLASS = "max-md:w-full max-md:max-w-0"

# The pinned first column of a data table. `start-0`, not `left-0`: the table
# flips to rtl:text-right, where the scroll start edge is the right one.
# `bg-inherit` picks up the row's zebra and hover surface — a sticky cell is
# transparent by default and would let the scrolled content show through it.
# The cell outranks its sibling pinned cells only while it holds an open panel:
# a panel nested inside a sticky cell is scoped to that cell's stacking context,
# so a later row's cell would paint over it. 3 clears the siblings at 2 and
# stays under the popover (10) and menu (20) strata, which a higher value would
# cover instead.
#
# From md up only, and not by preference: below md the same cell carries
# SHRINKABLE_COLUMN_CLASS, whose max-w-0 is what lets the name column collapse
# under its content so the actions column survives on a phone. A sticky cell
# will not collapse that way, so pinning below md costs ~200px of horizontal
# scroll on the narrow viewports the allowance exists to protect. The two are
# mutually exclusive, and a pinned column has nothing to hold still on a
# viewport where the table has already been cut to two columns.
PINNED_COLUMN_CLASS = (
    "md:sticky md:start-0 md:z-[2] md:bg-inherit "
    "md:has-[[data-pop-over-panel]:not([hidden])]:z-[3] "
    "md:has-[[data-menu]:not([hidden])]:z-[3] "
    # A box-shadow, never a filter: a filtered cell becomes the containing
    # block for the fixed panels it hosts. Scoped to a region that actually
    # has something scrolled behind the column, so a table that fits shows
    # no seam. The offset is physical where the trigger and the pin are
    # logical, so the direction is mirrored explicitly — otherwise the seam
    # paints into the table's own edge under rtl instead of over the
    # content sliding beneath it.
    "md:[@container_scroll-state(scrollable:inline-start)]:shadow-[6px_0_8px_-2px_rgb(0_0_0/0.28)] "
    "md:rtl:[@container_scroll-state(scrollable:inline-start)]:shadow-[-6px_0_8px_-2px_rgb(0_0_0/0.28)]"
)
NAME_MAX_WIDTH_CLASS = "max-w-[16rem]"
_TRUNCATED_CLIP_CLASS = (
    "block min-w-0 overflow-hidden whitespace-nowrap "
    "group-data-[overflowing]:"
    "[mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)]"
)
# Display is deliberately absent: each caller supplies exactly one display
# utility (see `visibility` in TruncatedText). Baking `hidden` in here and
# overriding it would leave both on the element, where the winner is decided by
# stylesheet order rather than by the class list.
_TRUNCATED_REVEAL_CLASS = (
    "size-6 items-center justify-center hover:cursor-pointer rounded-base shrink-0"
)
# The overflow ellipsis overlays the fade at the truncation point, so it is
# pinned to the host's edge. Only ever shown while the text is clipped, which
# is exactly when that edge is where the text ends.
_TRUNCATED_ELLIPSIS_POSITION_CLASS = "absolute inset-y-0 right-0 my-auto"


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
    # The info button sits in normal flow beside the text, so flex reserves its
    # width for it — no manual padding, and it follows the text instead of
    # stranding itself at the far edge of a wide column. Overflow-only ellipses
    # stay out of layout; their touch mask instead becomes fully transparent
    # under the button.
    clip_class = _TRUNCATED_CLIP_CLASS
    clip_attributes: list[HTMLAttribute] = [
        ("data-truncated-clip", ""),
        ("class", clip_class),
    ]
    if informative and link is None:
        clip_attributes.extend(describedby)
    clip = Span(clip_attributes)[text]

    if link is not None:
        # Not `w-full`: the link shrinks to its text so the reveal button lands
        # beside it rather than at the far edge of a wide column. `min-w-0`
        # keeps flex free to shrink it below its content, which is what
        # constrains the clip and lets the overflow measurement fire at all.
        visible: Node = Link(
            [
                ("href", link),
                ("class", "inline-flex min-w-0 max-w-full items-center gap-2"),
                *describedby,
            ]
        )[leading or "", clip]
    else:
        visible = Fragment(leading or "", clip)

    children: list[Child] = [visible]
    if tap:
        # An informative reveal stands in for a popover, and a popover
        # announces itself on every device — nothing else says the extra
        # content exists. An overflow ellipsis is only a touch stand-in for
        # the fade, which already says the text is clipped.
        position = "" if informative else f"{_TRUNCATED_ELLIPSIS_POSITION_CLASS} "
        visibility = (
            "inline-flex"
            if informative
            else "hidden [@media(hover:none)]:group-data-[overflowing]:inline-flex"
        )
        reveal_icon = "info" if informative else "ellipsis"
        color = (
            _REVEAL_LINKED_COLOR_CLASS
            if link is not None
            else _REVEAL_PLAIN_COLOR_CLASS
        )
        button_attributes: list[HTMLAttribute] = [
            ("type", "button"),
            ("data-truncated-reveal", reveal_icon),
            ("aria-label", reveal_label),
            ("class", f"{_TRUNCATED_REVEAL_CLASS} {color} {position}{visibility}"),
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
# Alignment is NOT baked in here — it comes from _ALIGN_CLASSES via the `align`
# parameter, so a start-aligned button never carries a losing justify-center.
_CONTROL_BASE_CLASS = (
    "font-medium text-type-body hover:cursor-pointer inline-flex items-center "
    f"{DISABLED_CONTROL_CLASS}"
)

# Both axes together: `justify-*` places the flex content, `text-*` the text
# inside it. They must move as a unit — setting only one leaves a wrapped or
# multi-child label disagreeing with its own box.
_ALIGN_CLASSES: dict[ButtonAlign, str] = {
    "center": "justify-center text-center",
    "start": "justify-start text-start",
}

# Shared by EVERY button-shaped variant. Height is the canonical control
# height (min-h-control = 42px, from --height-control), floored not fixed so a
# multi-line control still grows; the inline-flex base centers content in it.
# Only horizontal padding is set here — height no longer depends on font,
# padding, or any `@container` ancestor, so a button is the same 42px in every
# row (the container-query step and its cross-row inconsistency are gone).
CONTROL_SIZE_CLASS = "min-h-control px-3"

_FILLED_VARIANT_CLASS = (
    "gap-2 leading-5 focus:outline-hidden focus:ring-4 rounded-base "
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


def control_button_class(
    *,
    color: ButtonColor = "blue",
    variant: ButtonVariant = "filled",
    align: ButtonAlign = "center",
) -> str:
    """The exact class string :class:`ControlButton` renders for a combination.

    Exists so a consumer that cannot *call* the component still gets the
    component's look from one source. The date picker's calendar is the case:
    its 42 day cells are built client-side in TypeScript, so the day-cell
    variants are composed from this and published to TS by codegen
    (``manage.py gen_element_types``) rather than hand-mirrored in a ``.ts``
    file — which is how they drifted before (square corners on selected and
    adjacent-month cells).

    ControlButton itself renders through this, so the two cannot disagree.
    """
    if variant == "plain":
        # The navbar nav-link owns its whole layout (flex justify-between,
        # md:p-0) and sits outside both the base and the sizing contract, so
        # neither the base nor alignment applies to it.
        return _PLAIN_VARIANT_CLASS
    parts = [_CONTROL_BASE_CLASS, _ALIGN_CLASSES[align]]
    if variant == "outline":
        parts.append(_OUTLINE_VARIANT_CLASS)
    elif variant == "ghost":
        parts.append(_GHOST_VARIANT_CLASS)
    else:
        if variant == "filled":
            parts += [_FILLED_VARIANT_CLASS, _FILLED_COLOR_CLASSES[color]]
        else:
            parts += [_SEGMENTED_VARIANT_CLASS, _SEGMENTED_COLOR_CLASSES[color]]
    return " ".join(parts)


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

    ``align="start"`` left-aligns the content for buttons rendered as a list of
    choices (the date picker's preset column); the default is centered. It is a
    parameter and not a caller ``class_`` because the justify/text utilities
    collide and Tailwind breaks that tie by stylesheet order, not class order.
    ``variant="plain"`` ignores it, owning its own layout.

    Children go via the htpy ``[]`` slot — ``ControlButton(color="red")[label]``
    — which routes into the inner button in post mode. Extra attributes take the
    usual forms: dynamic pairs through the positional slot, static ones as
    kwargs (``hx_get=…``, ``data_x=""``, ``title=…``, ``onclick=…``, ``name=…``).
    """

    def __init__(
        self,
        attrs: AttrsArg | None = None,
        *,
        color: ButtonColor = "blue",
        variant: ButtonVariant = "filled",
        align: ButtonAlign = "center",
        href: str = "",
        method: str = "",
        action: str = "",
        csrf_token: str = "",
        hidden_fields: Children = None,
        type: str = "button",
        _children: Children = None,
        **kwargs: object,
    ) -> None:
        class_attrs: list[HTMLAttribute] = [
            ("class", control_button_class(color=color, variant=variant, align=align))
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
        self._hidden_fields = as_children(hidden_fields)
        self._type = type
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> ControlButton:
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
            form_children: list[Node | str] = []
            if self._csrf_token:
                form_children.append(
                    Safe(
                        '<input type="hidden" name="csrfmiddlewaretoken" '
                        f'value="{self._csrf_token}">'
                    )
                )
            form_children.extend(self._hidden_fields)
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
    hidden_fields: Children
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
                hidden_fields=member.get("hidden_fields"),
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
    attrs: AttrsArg | None = None,
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
    attrs: AttrsArg | None = None,
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
            (
                "shrink-0 rounded border-default-medium bg-neutral-secondary-medium "
                f"text-brand focus:ring-brand {DISABLED_CONTROL_CLASS}"
            ),
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
    attrs: AttrsArg | None = None,
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
# A pill is a token *inside* a control, not a row-control: it must stay shorter
# than the 42px field it sits in (min-h-control here made it fill the field edge
# to edge) and share the field's font (font-condensed here read as squashed next
# to the un-condensed search box).
_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-type-body rounded-base "
    "bg-brand-soft text-heading"
)
_PILL_REMOVE_CLASS = "ml-1 text-body hover:text-heading font-bold cursor-pointer"


def Pill(
    attrs: AttrsArg | None = None,
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

    label_child: Node | str = (
        Span(data_search_select_label="")[label] if label_slot else label
    )
    children: list[Node | str] = [label_child]
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
    "leading-none rounded"
)
_BADGE_SIZE_CLASSES = {
    "sm": "text-type-micro px-1.5 py-0.5",
    "base": "text-type-body px-2 py-0.5",
    "lg": "text-type-heading px-2.5 py-0.5",
}
_BADGE_TONE_CLASSES = {
    "brand": "bg-brand-soft text-heading",
    # Neutral badges commonly sit on both primary and secondary neutral
    # surfaces. Use a strong-enough fill to preserve the chip silhouette without
    # adding an outline that the other badge tones do not have.
    "neutral": "bg-neutral-quaternary text-heading",
    "success": "bg-success-soft text-fg-success-strong",
    "warning": "bg-warning-soft text-fg-warning",
    "danger": "bg-danger-soft text-fg-danger-strong",
}


def Badge(
    content: Child,
    *,
    size: BadgeSize = "base",
    tone: BadgeTone = "brand",
    extra_class: str = "",
    attributes: Attributes | None = None,
) -> Node:
    """A static brand-soft badge for counts and indicators.

    ``size`` picks the text/padding scale (``sm`` / ``base`` / ``lg``), and
    ``tone`` picks a semantic palette while preserving the historical
    brand-soft default. Palette changes belong here rather than in
    ``extra_class``: two competing background utilities resolve by stylesheet
    order, not by the order in the HTML class attribute.
    ``extra_class`` appends positioning utilities (e.g. ``ms-2`` next to a
    heading). For a removable filter tag use :func:`Pill` instead.
    """
    attributes = as_attributes(attributes)
    size_class = _BADGE_SIZE_CLASSES[size]
    tone_class = _BADGE_TONE_CLASSES[tone]
    classes = " ".join(
        part
        for part in (_BADGE_BASE_CLASS, size_class, tone_class, extra_class)
        if part
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


# The <year-picker> custom element renders the stats year grid in TypeScript.
# The builder auto-attaches dist/elements/year-picker.js; its popup is hosted by
# the same date-calendar <drop-down> machinery as the date pickers.
_YearPicker = custom_element_builder("year-picker")

# The down-chevron rendered inside the YearPicker button. Trusted static SVG.
_YEAR_PICKER_CHEVRON = Safe(
    '<svg class="w-4 h-4 ms-2 rtl:rotate-180" aria-hidden="true" '
    'xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 10">'
    '<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" '
    'stroke-width="2" d="M1 5h12m0 0L9 1m4 4L9 9"/></svg>'
)


# Every year cell is a ControlButton with a fixed width so the four columns stay
# aligned regardless of the label. The complete state classes are generated to
# TypeScript because the client clones the template twelve times.
_YEAR_CELL_GEOMETRY_CLASS = "w-14 shrink-0"
YEAR_PICKER_CLASSES: dict[str, str] = {
    "default": f"{control_button_class(variant='ghost')} {_YEAR_CELL_GEOMETRY_CLASS}",
    "selected": (
        f"{control_button_class(color='blue', variant='filled')} "
        f"{_YEAR_CELL_GEOMETRY_CLASS}"
    ),
    "adjacent": (
        f"{control_button_class(variant='ghost')} "
        f"{_YEAR_CELL_GEOMETRY_CLASS} opacity-40"
    ),
    "disabled": (
        f"{control_button_class(variant='ghost')} "
        f"{_YEAR_CELL_GEOMETRY_CLASS} opacity-40"
    ),
    "adjacent-disabled": (
        f"{control_button_class(variant='ghost')} "
        f"{_YEAR_CELL_GEOMETRY_CLASS} opacity-40"
    ),
}


def YearPicker(
    year: int | None = None,
    available_years: tuple[int, ...] = (),
    url_template: str = "",
) -> Node:
    """An in-house four-column stats year picker.

    `year` is the selected year, or ``None`` for the all-time view (the empty
    state). `available_years` are the years to enable in the popup grid.
    `url_template` is a navigation URL containing the literal ``__year__``
    placeholder, substituted with the chosen year in JS (keeps this component
    decoupled from the project's URL names).

    Behavior lives in ``ts/elements/year-picker.ts``; this renders the toggle,
    date-calendar dropdown shell, accessible popup structure, and a native
    ControlButton template for the twelve year cells.
    """
    # custom_elements imports this module, so the dropdown builder and its
    # shared overlay surface are imported lazily after module initialization.
    from common.components.custom_elements import OVERLAY_SURFACE_CLASS, _Dropdown

    label = str(year) if year is not None else "Choose a year"
    selected = str(year) if year is not None else ""
    classes = (
        "solid-brand border-transparent hover:bg-brand-strong"
        if year is not None
        else "bg-neutral-secondary-medium text-heading border border-default-medium "
        "hover:bg-neutral-tertiary-medium focus:ring-4 focus:ring-brand-medium"
    )
    years_csv = ",".join(str(y) for y in available_years)
    popup_id = "year-picker-popup"
    period_id = "year-picker-period"
    popup_class = (
        "absolute z-20 flex w-auto overflow-x-hidden overflow-y-auto rounded-base "
        f"{OVERLAY_SURFACE_CLASS} shadow-sm border border-default-medium"
    )
    picker = _YearPicker(
        [
            ("selected-year", selected),
            ("available-years", years_csv),
            ("url-template", url_template),
            ("class", "inline-block"),
        ]
    )[
        Button(
            [
                ("type", "button"),
                ("data-toggle", ""),
                ("data-year-picker-toggle", ""),
                ("aria-controls", popup_id),
                ("aria-expanded", "false"),
                ("aria-haspopup", "dialog"),
                (
                    "class",
                    (
                        f"inline-flex items-center rounded-base {CONTROL_SIZE_CLASS} "
                        f"text-type-body font-medium {classes}"
                    ),
                ),
            ]
        )[label, _YEAR_PICKER_CHEVRON],
        Div(
            [
                ("data-menu", ""),
                ("data-year-picker-popup", ""),
                ("id", popup_id),
                ("hidden", ""),
                ("role", "group"),
                ("aria-labelledby", period_id),
                ("class", popup_class),
            ]
        )[
            Div(data_year_picker_body="", class_="p-2")[
                Div(class_="flex items-center justify-between gap-2")[
                    ControlButton(
                        [("data-year-picker-prev", "")],
                        variant="ghost",
                        aria_label="Previous decade",
                        class_=_YEAR_CELL_GEOMETRY_CLASS,
                    )["‹"],
                    Span(
                        [
                            ("id", period_id),
                            ("data-year-picker-period", ""),
                            ("class", "text-type-body font-medium text-heading"),
                        ]
                    ),
                    ControlButton(
                        [("data-year-picker-next", "")],
                        variant="ghost",
                        aria_label="Next decade",
                        class_=_YEAR_CELL_GEOMETRY_CLASS,
                    )["›"],
                ],
                Div(
                    class_="grid grid-cols-4 gap-y-0.5 mt-1 w-56",
                    data_year_picker_grid="",
                ),
                Template(data_year_picker_template="year")[
                    ControlButton(
                        [("data-year", "")],
                        variant="ghost",
                        class_=_YEAR_CELL_GEOMETRY_CLASS,
                    )
                ],
            ]
        ],
    ]
    return _Dropdown(
        class_="relative inline-block",
        placement="bottom-end",
        submenu="false",
        behavior="date-calendar",
    )[picker]


# Form-field rendering. The element classes (label/error/checkbox-row + the
# controls, which carry their own classes via PrimitiveWidgetsMixin) live here,
# not in input.css — no selector reaches across the DOM to style a form.
FORM_LABEL_CLASS = "mb-2.5 text-type-label text-heading"
_FIELD_ERROR_CLASS = (
    "mt-4 mb-1 pl-3 py-2 solid-danger w-full text-type-body rounded-base"
)
# Checkbox + its label share a row (unlike block fields), justified apart. The
# explicit gap is a minimum: justify-between absorbs spare width, while narrow
# rows wrap label metadata before it can crowd the non-shrinking control.
_CHECKBOX_ROW_CLASS = "flex flex-row items-center justify-between gap-6 mt-3"


def FieldErrors(errors) -> Node | None:
    """Render a form/field ErrorList as a styled <ul>, or None if empty."""
    items = [Li()[str(error)] for error in errors]
    if not items:
        return None
    return Ul(class_=_FIELD_ERROR_CLASS)[*items]


class FormFieldGroup(NamedTuple):
    """One semantic group rendered by :func:`FormFields`.

    ``fields`` contains Django form field names in display order. ``id`` is
    optional, but useful when a page links directly to a group. Any visible
    form fields omitted from every explicit group are rendered afterwards in
    their original form order, so extending an existing form cannot silently
    hide a newly-added field.
    """

    legend: str
    fields: Sequence[str]
    description: str = ""
    id: str = ""


@dataclass(frozen=True, slots=True)
class FormFieldPresentation:
    """Optional presentation composed around one canonically rendered field."""

    label_extra: Node | None = None
    after_control: Node | None = None
    decorate_control: Callable[[Node], Node] | None = None


def field_label_id(input_id: str) -> str:
    """The DOM id of the ``<label>`` for the control identified by ``input_id``.

    A composite control made of several inputs (a segmented date field) cannot
    take its name from ``<label for>``: the target segment names itself ("year"),
    so the label text is consumed by nothing and a screen reader announces it as
    a standalone object — immediately before the field group, which repeats the
    same string. Such a widget points its group's ``aria-labelledby`` here
    instead, which makes the label the group's one name source.

    Derived rather than passed, because the label and the widget are rendered by
    different code that never meet: the row renderer here, and a Django widget.
    """
    return f"{input_id}-label" if input_id else ""


def _form_field_label(field, label_extra: Node | None = None) -> Node:
    """Render a label, optionally with adjacent label-line metadata."""
    label_class = (
        "text-type-label text-heading" if label_extra is not None else FORM_LABEL_CLASS
    )
    label = Label(
        for_=field.id_for_label,
        id_=field_label_id(field.id_for_label) or None,
        class_=label_class,
    )[str(field.label)]
    if label_extra is None:
        return label
    return Div(
        class_="flex min-w-0 flex-wrap items-center gap-2",
        data_form_field_label_line="",
    )[label, label_extra]


def _form_field_row(
    field,
    presentation: FormFieldPresentation | None = None,
) -> Node:
    """Render one visible ``BoundField`` using the established row contract."""
    presentation = presentation or FormFieldPresentation()
    is_checkbox = getattr(field.field.widget, "input_type", None) == "checkbox"
    label = _form_field_label(field, presentation.label_extra)
    control: Node = Safe(str(field))
    if presentation.decorate_control is not None:
        control = presentation.decorate_control(control)
    errors = FieldErrors(field.errors)

    if is_checkbox:
        if presentation.label_extra is None:
            children: list[Node] = [label, control]
            if errors:
                children.append(errors)
            if presentation.after_control:
                children.append(presentation.after_control)
            return Div(
                class_=_CHECKBOX_ROW_CLASS,
                data_form_checkbox_row="",
            )[*children]

        row = Div(
            class_=_CHECKBOX_ROW_CLASS,
            data_form_checkbox_row="",
        )[label, control]
        children = [row]
        if errors:
            children.append(errors)
        if presentation.after_control:
            children.append(presentation.after_control)
        return Div()[*children]

    children = []
    if errors:
        children.append(errors)
    if presentation.label_extra is not None:
        children.append(Div(class_="mb-2.5")[label])
    else:
        children.append(label)
    children.append(control)
    if presentation.after_control:
        children.append(presentation.after_control)
    return Div()[*children]


def _grouped_form_fields(
    form,
    groups: Sequence[FormFieldGroup],
    presentations: Mapping[str, FormFieldPresentation],
) -> list[Node]:
    """Render validated fieldsets plus any visible, ungrouped remainder."""
    field_names = set(form.fields)
    grouped_names: set[str] = set()
    for group in groups:
        for name in group.fields:
            if name not in field_names:
                raise ValueError(
                    f"FormFields group {group.legend!r} names unknown field {name!r}."
                )
            if name in grouped_names:
                raise ValueError(
                    f"FormFields field {name!r} appears in multiple groups."
                )
            grouped_names.add(name)

    fieldsets: list[Node] = []
    for group in groups:
        group_fields = [form[name] for name in group.fields if not form[name].is_hidden]
        if not group_fields:
            continue
        description_id = f"{group.id}-description" if group.id else ""
        attributes: list[HTMLAttribute] = [
            ("class", "flex flex-col gap-3"),
            ("data-form-field-group", ""),
        ]
        if group.id:
            attributes.append(("id", group.id))
        if description_id and group.description:
            attributes.append(("aria-describedby", description_id))
        group_children: list[Node] = [
            Legend(class_="text-type-section text-heading")[group.legend]
        ]
        if group.description:
            description_attributes: list[HTMLAttribute] = [
                ("class", "text-type-body text-body")
            ]
            if description_id:
                description_attributes.append(("id", description_id))
            group_children.append(P(description_attributes)[group.description])
        group_children.extend(
            _form_field_row(
                field,
                presentations.get(field.name),
            )
            for field in group_fields
        )
        fieldsets.append(Fieldset(attributes)[*group_children])

    # Hidden controls stay outside fieldsets and render exactly once. Visible
    # fields not named by a group follow the fieldsets in their normal order.
    hidden = [Safe(str(field)) for field in form if field.is_hidden]
    remainder = [
        _form_field_row(
            field,
            presentations.get(field.name),
        )
        for field in form
        if not field.is_hidden and field.name not in grouped_names
    ]
    return [*hidden, *fieldsets, *remainder]


def FormFields(
    form,
    *,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
    groups: Sequence[FormFieldGroup] | None = None,
    embedded: Mapping[str, str] | None = None,
) -> Node:
    """Render a Django form's fields as self-styled component rows.

    Replaces ``form.as_div()`` so labels, errors, row layout, and the checkbox
    row carry their own classes (no form styling in input.css). Native controls
    get their classes from ``PrimitiveWidgetsMixin``; composite widgets
    (SearchSelect) self-style. ``presentations`` maps a field name to optional
    label metadata, content after the control, and a control decorator.

    ``groups`` extends this renderer with semantic ``fieldset``/``legend``
    grouping. It never delegates to a parallel renderer: errors, checkbox rows,
    hidden controls, and presentation content keep the exact same path. Unknown
    or duplicate field names raise instead of producing a partially-rendered
    settings form.

    ``embedded`` maps a field name to the *host* field whose row renders it —
    the embedded field's full widget markup (plus its own errors) is appended
    after the host's control instead of getting a labelled row of its own.
    For self-labelling controls that belong visually to another field.
    """
    presentations = presentations or {}
    unknown_presentations = set(presentations) - set(form.fields)
    if unknown_presentations:
        unknown = min(unknown_presentations)
        raise ValueError(f"FormFields presentation names unknown field {unknown!r}.")

    embedded = dict(embedded or {})
    if embedded and groups is not None:
        raise ValueError("FormFields embedded is not supported with groups.")
    for embedded_name, host_name in embedded.items():
        if embedded_name not in form.fields:
            raise ValueError(
                f"FormFields embedded names unknown field {embedded_name!r}."
            )
        if host_name not in form.fields:
            raise ValueError(
                f"FormFields embedded names unknown host field {host_name!r}."
            )

    embedded_by_host: dict[str, list[Node]] = {}
    for embedded_name, host_name in embedded.items():
        embedded_field = form[embedded_name]
        embed_parts: list[Node] = [Safe(str(embedded_field))]
        embed_errors = FieldErrors(embedded_field.errors)
        if embed_errors:
            embed_parts.append(embed_errors)
        embedded_by_host.setdefault(host_name, []).extend(embed_parts)

    def _presentation_with_embeds(
        field_name: str,
    ) -> FormFieldPresentation | None:
        presentation = presentations.get(field_name)
        embeds = embedded_by_host.get(field_name)
        if not embeds:
            return presentation
        extra: Node = Fragment(*embeds)
        if presentation is None:
            return FormFieldPresentation(after_control=extra)
        combined = (
            Fragment(presentation.after_control, extra)
            if presentation.after_control is not None
            else extra
        )
        return replace(presentation, after_control=combined)

    rows: list[Node] = []

    non_field = FieldErrors(form.non_field_errors())
    if non_field:
        rows.append(non_field)

    if groups is not None:
        rows.extend(_grouped_form_fields(form, groups, presentations))
        return Fragment(*rows, separator="\n")

    for field in form:
        if field.is_hidden:
            rows.append(Safe(str(field)))
            continue
        if field.name in embedded:
            continue
        rows.append(
            _form_field_row(
                field,
                _presentation_with_embeds(field.name),
            )
        )

    return Fragment(*rows, separator="\n")


def AddForm(
    form,
    *,
    request,
    fields: Node | SafeText | str | None = None,
    additional_row: Node | SafeText | str = "",
    submit_class: str = "mt-3",
    width_class: str = FORM_MAX_WIDTH_CLASS,
) -> Node:
    """Page body for the generic add/edit form (Python equivalent of add.html).

    `fields` overrides the default ``FormFields(form)`` field markup (used by the
    session form, which lays out its fields manually). `additional_row` holds
    extra submit buttons rendered below the main Submit button. `submit_class`
    is applied to the main Submit button (the session form passes "" to match
    its original markup). `width_class` widens the column for a form that holds
    a grid of its own; every other page keeps the one-column default.
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
            class_=f"form-container w-full {width_class} mx-auto @container",
        )[inner_form]
    ]


def PageHeading(
    children: Children = None,
    badge: str = "",
) -> Element:
    """Page heading (``<h1>``) with optional badge count.

    Carries no margin: the parent owns the distance to the content below, via
    ``gap``. A baked margin also broke the badge/action layouts that put this
    heading in an ``items-center`` flex row — the margin inflated the flex item,
    so the row centred box-plus-margin and the title sat half a margin high.
    """
    children = children or []
    heading_class = "leading-none text-heading"
    badge_html: Node | str = ""

    if badge:
        heading_class = "flex items-center " + heading_class
        badge_html = Badge(badge, size="lg", extra_class="me-2 ms-2")

    return H1(class_=heading_class)[
        *as_children(children), *([badge_html] if badge_html else [])
    ]


def DialogTitle(children: Children = None) -> Element:
    """The one dialog/confirm-page title — ``<h1>`` in :data:`DIALOG_TITLE_CLASS`.

    ``PlainH1`` (not the styled ``H1`` builder) because this title has its own
    size token: ``H1``'s baked ``text-type-title`` would accumulate alongside
    ``text-type-dialog``, leaving two competing size utilities on one element.
    """
    return PlainH1(class_=DIALOG_TITLE_CLASS)[*as_children(children)]


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
    """

    def __init__(
        self,
        modal_id: str,
        _children: Children = None,
    ) -> None:
        self.modal_id = modal_id
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> Modal:
        return Modal(self.modal_id, as_children(children))

    def render(self) -> Node:
        return _ModalDialog(
            id_=self.modal_id,
            role="dialog",
            aria_modal="true",
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
    post_url: str,
    csrf_token: str,
    cancel_url: str,
    confirm_label: str = "Confirm",
    confirm_color: ButtonColor = "red",
    details: Children = None,
) -> Node:
    """Full-page confirmation: a prompt, a POST ``<form>`` (the confirm action)
    and a cancel link back to the origin. The no-JS replacement for the htmx
    confirmation modals — reusable across delete/refund/split/reset flows.

    ``details`` is block content rendered after the prompt (a list of the data a
    delete would take with it); it cannot live in ``message``, which renders
    inside a ``<p>``.
    """
    return Div(
        class_=f"mx-auto w-full {FORM_MAX_WIDTH_CLASS} p-5 @container",
    )[
        Form(method="post", action=post_url)[
            Safe(
                f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            ),
            DialogTitle(title),
            P(class_="text-heading text-center mt-5")[*as_children(message)],
            *(
                [Div(class_="text-heading text-center mt-3")[*as_children(details)]]
                if details
                else []
            ),
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
    *,
    nowrap: bool = False,
) -> Element:
    """Styled table cell. ``nowrap`` pins the cell to one line; the caller
    decides, because wrapping is only forbidden on tables that can scroll."""
    children = children or []
    cell_class = "px-2 sm:px-3 lg:px-4 py-2"
    if nowrap:
        cell_class = f"{cell_class} whitespace-nowrap"
    return Td(class_=cell_class)[*as_children(children)]


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
    column, its body ``<th>``. ``shrinkable`` marks a column that may shrink
    below its content width when the table is crowded; its content is expected
    to self-clip. ``wrap`` opts a column out of the one-line rule data tables
    otherwise impose — for free-text columns whose value has no useful width
    (a session note), where a single line would widen the table without limit.
    ``priority`` orders column dropping when a data table does not fit: lower
    drops first, rightmost first among equals. The first column never drops —
    it is the row header that names every row — and neither does the highest-
    priority column beside it, so a table never collapses to names alone."""

    label: str
    sort_key: str | None = None
    align: Align = "left"
    class_: str = ""
    shrinkable: bool = False
    wrap: bool = False
    priority: int = 1


class TableData(TypedDict):
    """Canonical table shape consumed by :func:`StyledTable` /
    :func:`paginated_table_content`. Every list view builds this."""

    # Names the table's scroll region for assistive tech, e.g. "Sessions".
    # Required, and page-unique: the caption id is derived from this text, so
    # two same-captioned tables on one page would share it.
    caption: str
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


def TableRow(
    data: TableRowData,
    columns: Sequence[Column] | None = None,
    *,
    data_table: bool = False,
) -> Element:
    """Render a styled ``<tr>`` from a :class:`TableRowData`.

    First cell is a ``<th scope="row">``, the rest ``<td>``. The cosmetic row
    ``class`` is fixed here; ``data["attributes"]`` (``id``, ``hx-*`` …) is
    applied on top. For a differently-styled row use the generic ``Tr`` builder.

    ``data_table`` mirrors :func:`StyledTable`'s gate: on a table that can
    scroll, body cells stay on one line unless their column sets ``wrap``. A
    row fragment swapped into such a table must pass both this flag and the
    table's ``columns``, or it renders under a different width policy than the
    rows around it.
    """
    cells = data["cell_data"]

    # Hover lightens the text along with the surface: body-subtle text fails AA
    # on the tertiary hover surface in both themes.
    tr_class = (
        "odd:bg-neutral-primary-soft even:bg-neutral-secondary-medium "
        "border-default-medium hover:bg-neutral-tertiary-medium "
        "hover:text-heading"
    )
    tr_attrs: list[HTMLAttribute] = [("class", tr_class), *data.get("attributes", [])]

    # A ragged row is a documented prod degradation (see StyledTable's DEBUG
    # cell-count guard), so a missing column is read as "no policy", never as
    # an IndexError.
    def column_at(index: int) -> Column | None:
        if columns and index < len(columns):
            return columns[index]
        return None

    cell_elements: list[Node] = []
    for i, cell in enumerate(cells):
        column = column_at(i)
        if i == 0:
            column_class = column.class_ if column else ""
            if column and column.shrinkable:
                column_class = f"{column_class} {SHRINKABLE_COLUMN_CLASS}".strip()
            if data_table:
                column_class = f"{column_class} {PINNED_COLUMN_CLASS}".strip()
            # The row header has always been single-line; only an explicit
            # wrap opt-out releases it.
            wrap_class = "" if column and column.wrap else "whitespace-nowrap "
            cell_elements.append(
                Th(
                    scope="row",
                    class_=(
                        "px-2 sm:px-3 lg:px-6 py-4 font-medium text-heading "
                        f"{wrap_class}"
                        f"{column_class}"
                    ).strip(),
                )[cell]
            )
        else:
            nowrap = data_table and not (column and column.wrap)
            cell_elements.append(TableTd(nowrap=nowrap)[cell])

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
            link = ControlLink(href=_page_url(request, page), class_=page_link_class)[
                str(page)
            ]
        else:
            link = ControlLink(aria_current="page", class_=current_link_class)[
                str(page)
            ]
        page_items.append(Li()[link])

    if page_obj.has_previous():
        prev_link = ControlLink(
            href=_page_url(request, page_obj.previous_page_number()),
            class_=f"{page_link_class} ms-0 rounded-s-base",
        )["Previous"]
    else:
        prev_link = ControlLink(
            aria_current="page",
            class_=f"{disabled_link_class} rounded-s-base",
        )["Previous"]

    if page_obj.has_next():
        next_link = ControlLink(
            href=_page_url(request, page_obj.next_page_number()),
            class_=f"{page_link_class} rounded-e-base",
        )["Next"]
    else:
        next_link = ControlLink(
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
_ResponsiveTable = custom_element_builder("responsive-table")

# The runtime column-drop state is a safelisted nth-child class family in
# input.css (like the align rules), so it has a hard ceiling: a column past it
# could never be hidden.
MAX_DATA_TABLE_COLUMNS = 12

# No-JS fallback for the data-table column drop: while <responsive-table> is
# not defined (JS off or failed to load), middle columns hide below md exactly
# as they always have. The selector stops matching the instant the element
# upgrades, and the element applies its first measured decision synchronously
# inside that same upgrade — the CSS rule and the element's decision are never
# active together, with no frame between them.
_FALLBACK_HIDE_HEADER_CLASS = (
    "max-md:[responsive-table:not(:defined)_&_th:not(:first-child)"
    ":not(:last-child)]:hidden"
)
_FALLBACK_HIDE_BODY_CLASS = (
    "max-md:[responsive-table:not(:defined)_&_td:not(:first-child)"
    ":not(:last-child)]:hidden"
)

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


def _header_cell(
    column: Column,
    sort_terms: Sequence[SortTerm],
    request,
    *,
    data_table: bool = False,
    pinned: bool = False,
) -> Node:
    """One ``<th>``: a static header for a non-sortable column, else a clickable
    sort link wrapped in ``<sort-header>`` with both navigation targets baked in."""
    base_class = "px-2 sm:px-3 lg:px-6 py-3" + (
        " text-right" if column.align == "right" else ""
    )
    if column.class_:
        base_class = f"{base_class} {column.class_}"
    if column.shrinkable:
        base_class = f"{base_class} {SHRINKABLE_COLUMN_CLASS}"
    if data_table and not column.wrap:
        base_class = f"{base_class} whitespace-nowrap"
    if pinned:
        base_class = f"{base_class} {PINNED_COLUMN_CLASS}"
    # The header cell is where <responsive-table> reads the column's drop
    # policy: priority, and the flags that change its width cost (a wrap
    # column measures capped; a shrinkable one is squeezed below md).
    policy_attrs: list[HTMLAttribute] = []
    if data_table:
        policy_attrs.append(("data-priority", str(column.priority)))
        if column.wrap:
            policy_attrs.append(("data-wrap", ""))
        if column.shrinkable:
            policy_attrs.append(("data-shrinkable", ""))
    if column.sort_key is None:
        return Th(policy_attrs, scope="col", class_=base_class)[column.label]

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

    link = ControlLink(
        href=_sort_href(request, collapse_sort(sort_terms, column.sort_key)),
        data_shift_href=_sort_href(request, cycle_sort(sort_terms, column.sort_key)),
        class_=_SORT_HEADER_LINK_CLASS,
    )[column.label, indicator]
    return Th(policy_attrs, scope="col", class_=base_class, aria_sort=aria_sort)[
        _SortHeader()[link]
    ]


PAGE_SIZE_PRESETS = PAGE_SIZE_CHOICES


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
    data_table: bool = False,
    caption: str = "",
    caption_key: str = "",
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

    ``data_table`` marks a table of records that may outgrow the page: its cells
    stay on one line (per-column opt-out via ``Column.wrap``) and its scroll
    wrapper becomes a keyboard-reachable landmark named by ``caption``, which is
    then required. Off by default, because the treatment is wrong for the
    card-shaped key-value tables in the stats page — their value cells wrap by
    design and they get no scroll region to reach.

    ``caption_key`` is what makes the caption's id unique where one page holds
    several tables that a reader would name the same. The id is hashed from the
    caption otherwise, so two equal captions would resolve to one element.
    """
    if data_table and not caption:
        raise ValueError(
            "StyledTable(data_table=True) needs a caption: it names the scroll "
            "region, and an empty name leaves the region unlabelled."
        )
    if data_table and columns and len(columns) > MAX_DATA_TABLE_COLUMNS:
        raise ValueError(
            f"StyledTable(data_table=True) supports at most "
            f"{MAX_DATA_TABLE_COLUMNS} columns: the column-drop classes are a "
            f"safelisted nth-child family, so column "
            f"{MAX_DATA_TABLE_COLUMNS + 1}+ could never be hidden."
        )
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
    # A <caption> is only valid as the table's first child, and it doubles as
    # the scroll region's accessible name. Visually hidden: the heading above
    # each table already says this on screen.
    caption_id = (
        f"table-caption-{randomid(content=caption_key or caption)}"
        if data_table
        else ""
    )
    if data_table:
        table_children.append(Caption(class_="sr-only", id=caption_id)[caption])
    # `columns` still drives the count-guard and align rules when the header is
    # hidden (show_header=False) — e.g. the headerless key-value stats tables.
    if show_header:
        # The surface sits on the row, not on <thead>: the pinned first cell
        # takes its background from its parent row, and a <thead>-level surface
        # would leave it transparent.
        header_row_class = "bg-neutral-tertiary"
        header_row = Tr(class_=header_row_class)[
            [
                _header_cell(
                    column,
                    sort_terms,
                    request,
                    data_table=data_table,
                    pinned=data_table and index == 0,
                )
                for index, column in enumerate(columns)
            ]
        ]
        thead_class = "text-type-micro text-body uppercase"
        if data_table:
            thead_class = f"{thead_class} {_FALLBACK_HIDE_HEADER_CLASS}"
        table_children.append(Thead(class_=thead_class)[header_row])
    # Body-cell alignment is a table-level rule (not per-row) so an htmx-swapped
    # <tr> aligns from the live <tbody> it lands in — the fragment row stays
    # dumb. Driven by Column.align; a right column at position i targets its
    # <td> (the first cell is a <th scope="row">, so td:nth-child(i+1) is right).
    # The nth-child literals are safelisted via @source inline in input.css.
    # In the separated model a <tr> border is ignored, so the divider lives on
    # the cells — which also means it travels with the pinned cell instead of
    # being painted over by it. The color must live on the cells too: border
    # color does not inherit, and without it each cell falls back to
    # currentColor — a bright heading-colored line under the row-header <th>.
    tbody_class = (
        "font-condensed dark:[&_tr:not(:last-child)>*]:border-b "
        "dark:[&_tr:not(:last-child)>*]:border-default-medium"
        if data_table
        else "font-condensed dark:divide-y"
    )
    if data_table:
        tbody_class = f"{tbody_class} {_FALLBACK_HIDE_BODY_CLASS}"
    align_rules = " ".join(
        f"[&_td:nth-child({index + 1})]:text-right"
        for index, column in enumerate(columns)
        if column.align == "right"
    )
    if align_rules:
        tbody_class = f"{tbody_class} {align_rules}"
    table_children.append(
        Tbody(class_=tbody_class)[
            [TableRow(data=row, columns=columns, data_table=data_table) for row in rows]
        ]
    )

    # Data tables separate their borders: Chrome paints no box-shadow on a cell
    # in the collapsed model, so the pinned column's seam would compute and
    # never render. Separated borders also let the row divider belong to the
    # cells, which is what carries it across the sticky column.
    table_class = "w-full text-type-body text-left rtl:text-right text-body-subtle"
    if data_table:
        table_class = f"{table_class} border-separate border-spacing-0"
    table = Table(class_=table_class)[*table_children]

    # The scroll wrapper owns horizontal scroll only; the shell owns the radius
    # and clips this wrapper to it (a rounded clip can't coexist with overflow-x
    # scroll on one element, so they stay on separate elements).
    scroll_class = "relative overflow-x-auto"
    scroll_attributes: list[HTMLAttribute] = []
    if data_table:
        # A one-line table overflows instead of getting taller, so the scroll it
        # produces has to be reachable without a pointer: a named, focusable
        # region is the only thing that makes an overflow container tabbable.
        # The scroll padding reserves the region's start edge, so tabbing to a
        # control that is scrolled out of view never parks it flush there. The
        # reservation is a fixed over-estimate — the name cap plus cell padding
        # — because the first column's real width varies per table and per page.
        # Only from md up: 19rem is wider than a phone's scrollport, where the
        # browser would clamp it into a meaningless snap position anyway.
        # The scroll-state container type lets the pinned column show its seam
        # only while something is scrolled behind it. It is not a containing
        # block, so the fixed panels inside the table are unaffected.
        scroll_class = (
            f"{scroll_class} md:scroll-ps-[19rem] md:[container-type:scroll-state]"
        )
        scroll_attributes = [
            ("role", "region"),
            ("tabindex", "0"),
            ("aria-labelledby", caption_id),
        ]
    region: Node = Div([("class", scroll_class), *scroll_attributes])[table]
    if data_table:
        # The element owns the drop decision: it measures column widths and
        # hides the lowest-priority columns until the table fits the region.
        region = _ResponsiveTable(class_="block")[region]
    inner_children: list[Node] = [region]

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


def ContentContainer(attrs: AttrsArg | None = None, **kwargs: object) -> Element:
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
        data_table=True,
        caption=data["caption"],
    )
