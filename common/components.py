import hashlib
import json
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.template import TemplateDoesNotExist
from django.template.defaultfilters import floatformat
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import conditional_escape
from django.utils.safestring import SafeText, mark_safe

from common.icons import get_icon
from common.utils import truncate
from games.models import Game, Purchase, Session

HTMLAttribute = tuple[str, str | int | bool]
HTMLTag = str

_COLOR_CLASSES = {
    "blue": "text-white bg-brand box-border border border-transparent hover:bg-brand-strong focus:ring-4 focus:ring-brand-medium",
    "red": "bg-red-700 dark:bg-red-600 dark:focus:ring-red-900 dark:hover:bg-red-700 focus:ring-red-300 hover:bg-red-800 text-white",
    "gray": "bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-600 dark:focus:ring-gray-700 dark:hover:bg-gray-700 dark:hover:text-white dark:text-gray-400 focus:ring-gray-100 hover:bg-gray-100 hover:text-blue-700 text-gray-900 border",
    "green": "bg-green-700 dark:bg-green-600 dark:focus:ring-green-800 dark:hover:bg-green-700 focus:ring-green-300 hover:bg-green-800 text-white",
}

_SIZE_CLASSES = {
    "xs": "px-3 py-2 text-xs shadow-xs",
    "sm": "px-3 py-2 text-sm",
    "base": "px-5 py-2.5 text-sm",
    "lg": "px-5 py-3 text-base",
    "xl": "px-6 py-3.5 text-base",
}


def _render_cached_impl(template: str, context_json: str) -> str:
    context = json.loads(context_json)
    context["slot"] = mark_safe(context["slot"])
    return render_to_string(template, context)


if not settings.DEBUG:
    _render_cached = lru_cache(maxsize=4096)(_render_cached_impl)
else:
    _render_cached = _render_cached_impl


def enable_cache():
    """Wrap _render_cached with LRU cache (for testing in DEBUG mode)."""
    global _render_cached
    _render_cached = lru_cache(maxsize=4096)(_render_cached_impl)


def Component(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    template: str = "",
    tag_name: str = "",
) -> SafeText:
    attributes = attributes or []
    children = children or []
    if not tag_name and not template:
        raise ValueError("One of template or tag_name is required.")
    if isinstance(children, str):
        children = [children]
    childrenBlob = "\n".join(conditional_escape(child) for child in children)
    if len(attributes) == 0:
        attributesBlob = ""
    else:
        attributesList = [f'{name}="{conditional_escape(str(value))}"' for name, value in attributes]
        attributesBlob = f" {' '.join(attributesList)}"
    tag: str = ""
    if tag_name != "":
        tag = f"<{tag_name}{attributesBlob}>{childrenBlob}</{tag_name}>"
    elif template != "":
        context = {name: value for name, value in attributes} | {"slot": "\n".join(children)}
        tag = _render_cached(template, json.dumps(context, sort_keys=True))
    return mark_safe(tag)


def randomid(seed: str = "", content: str = "", length: int = 10) -> str:
    if not seed and not content:
        return seed
    hash_input = f"{seed}:{content}" if seed else content
    content_hash = hashlib.sha1(hash_input.encode()).hexdigest()
    base = content_hash[:length] if not seed else content_hash[:max(0, length - len(seed))]
    return seed + base


def _popover_html(
    id: str,
    popover_content: str,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    slot: str = "",
) -> SafeText:
    """Generate popover HTML using Component(tag_name=...).

    Single source of truth for popover HTML structure.
    Used by Popover() and the python_popover template tag bridge.
    """
    display_content = wrapped_content if wrapped_content else slot

    span = Component(
        tag_name="span",
        attributes=[
            ("data-popover-target", id),
            ("class", wrapped_classes),
        ],
        children=[display_content] if display_content else [],
    )

    popover_tooltip_class = (
        "absolute z-10 invisible inline-block text-sm text-white "
        "transition-opacity duration-300 bg-white border border-purple-200 "
        "rounded-lg shadow-xs opacity-0 dark:text-white dark:border-purple-600 "
        "dark:bg-purple-800"
    )

    div = Component(
        tag_name="div",
        attributes=[
            ("data-popover", ""),
            ("id", id),
            ("role", "tooltip"),
            ("class", popover_tooltip_class),
        ],
        children=[
            Component(
                tag_name="div",
                attributes=[("class", "px-3 py-2")],
                children=[popover_content],
            ),
            Component(tag_name="div", attributes=[("data-popper-arrow", "")]),
            mark_safe(  # nosec — intentional HTML comment for Tailwind JIT
                "<!-- for Tailwind CSS to generate decoration-dotted CSS "
                "from Python component -->"
            ),
            Component(
                tag_name="span",
                attributes=[("class", "hidden decoration-dotted")],
            ),
        ],
    )

    return mark_safe(span + "\n" + div)


def Popover(
    popover_content: str,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    children: list[HTMLTag] | None = None,
    attributes: list[HTMLAttribute] | None = None,
    id: str = "",
) -> str:
    children = children or []
    if not wrapped_content and not children:
        raise ValueError("One of wrapped_content or children is required.")
    if not id:
        id = randomid(content=f"{wrapped_content}:{popover_content}:{wrapped_classes}")

    slot = mark_safe("\n".join(children))
    return _popover_html(
        id=id,
        popover_content=popover_content,
        wrapped_content=wrapped_content,
        wrapped_classes=wrapped_classes,
        slot=slot,
    )


def PopoverTruncated(
    input_string: str,
    popover_content: str = "",
    popover_if_not_truncated: bool = False,
    length: int = 30,
    ellipsis: str = "…",
    endpart: str = "",
) -> str:
    """
    Returns `input_string` truncated after `length` of characters
    and displays the untruncated text in a popover HTML element.
    The truncated text ends in `ellipsis`, and optionally
    an always-visible `endpart` can be specified.
    `popover_content` can be specified if:
    1. It needs to be always displayed regardless if text is truncated.
    2. It needs to differ from `input_string`.
    """
    if (truncated := truncate(input_string, length, ellipsis, endpart)) != input_string:
        return Popover(
            wrapped_content=truncated,
            popover_content=popover_content if popover_content else input_string,
        )
    else:
        if popover_content and popover_if_not_truncated:
            return Popover(
                wrapped_content=input_string,
                popover_content=popover_content if popover_content else "",
            )
        else:
            return input_string


def A(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    url_name: str | None = None,
    href: str | None = None,
) -> SafeText:
    """
    Returns an anchor <a> tag.

    Accepts one of two mutually-exclusive URL specifications:
        - url_name: URL pattern name, resolved via reverse()
        - href: Literal path string passed through as-is
    """
    attributes = attributes or []
    children = children or []
    if url_name is not None and href is not None:
        raise ValueError("Provide exactly one of 'url_name' or 'href', not both.")

    additional_attributes = []
    if url_name is not None:
        additional_attributes = [("href", reverse(url_name))]
    elif href is not None:
        additional_attributes = [("href", href)]
    return Component(
        tag_name="a", attributes=attributes + additional_attributes, children=children
    )


def Button(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    size: str = "base",
    icon: bool = False,
    color: str = "blue",
    type: str = "button",
    hx_get: str = "",
    hx_target: str = "",
    hx_swap: str = "",
    title: str = "",
    onclick: str = "",
    name: str = "",
) -> SafeText:
    attributes = attributes or []
    children = children or []

    # Separate custom class from other generic attributes
    custom_class = ""
    other_attrs: list[HTMLAttribute] = []
    for attr_name, attr_value in attributes:
        if attr_name == "class":
            custom_class = str(attr_value)
        else:
            other_attrs.append((attr_name, attr_value))

    # Build class string: custom class first, then base, color, size, icon
    class_parts: list[str] = []
    if custom_class:
        class_parts.append(custom_class)
    class_parts.append(
        "hover:cursor-pointer leading-5 focus:outline-hidden focus:ring-4 "
        "font-medium mb-2 me-2 rounded-base"
    )
    class_parts.append(_COLOR_CLASSES.get(color, _COLOR_CLASSES["blue"]))
    class_parts.append(_SIZE_CLASSES.get(size, _SIZE_CLASSES["base"]))
    if icon:
        class_parts.append("inline-flex text-center items-center gap-2")

    # Build the full attribute list for the button tag
    button_attrs: list[HTMLAttribute] = [
        ("type", type),
        ("class", " ".join(class_parts)),
    ]
    if hx_get:
        button_attrs.append(("hx-get", hx_get))
    if hx_target:
        button_attrs.append(("hx-target", hx_target))
    if hx_swap:
        button_attrs.append(("hx-swap", hx_swap))
    if title:
        button_attrs.append(("title", title))
    if onclick:
        button_attrs.append(("onclick", onclick))
    if name:
        button_attrs.append(("name", name))
    button_attrs.extend(other_attrs)

    return Component(
        tag_name="button",
        attributes=button_attrs,
        children=children,
    )


_GROUP_BUTTON_COLORS = {
    "gray": (
        "px-2 py-1 text-xs font-medium text-gray-900 bg-white border "
        "border-gray-200 hover:bg-gray-100 hover:text-blue-700 focus:z-10 "
        "focus:ring-2 focus:ring-blue-700 focus:text-blue-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-white "
        "dark:hover:text-white dark:hover:bg-gray-700 "
        "dark:focus:ring-blue-500 dark:focus:text-white"
    ),
    "red": (
        "px-2 py-1 text-xs font-medium text-gray-900 bg-white border "
        "border-gray-200 hover:bg-red-500 hover:text-white focus:z-10 "
        "focus:ring-2 focus:ring-blue-700 focus:text-blue-700 "
        "dark:bg-gray-800 dark:border-gray-700 dark:text-white "
        "dark:hover:text-white dark:hover:border-red-700 "
        "dark:hover:bg-red-700 dark:focus:ring-blue-500 dark:focus:text-white"
    ),
    "green": (
        "px-2 py-1 text-xs font-medium text-gray-900 bg-white border "
        "border-gray-200 hover:bg-green-500 hover:border-green-600 "
        "hover:text-white focus:z-10 focus:ring-2 focus:ring-green-700 "
        "focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:text-white dark:hover:text-white dark:hover:border-green-700 "
        "dark:hover:bg-green-600 dark:focus:ring-green-500 "
        "dark:focus:text-white"
    ),
}


def _button_group_button(
    href: str,
    slot: str,
    color: str = "gray",
    title: str = "",
    hx_get: str = "",
    hx_target: str = "",
) -> SafeText:
    """Generate a single button-group button (inner <button> inside <a>)."""
    color_classes = _GROUP_BUTTON_COLORS.get(color, _GROUP_BUTTON_COLORS["gray"])

    a_attrs: list[HTMLAttribute] = [("href", href)]
    if hx_get:
        a_attrs.append(("hx-get", hx_get))
    if hx_target:
        a_attrs.append(("hx-target", hx_target))
    a_attrs.append(
        (
            "class",
            "[&:first-of-type_button]:rounded-s-lg "
            "[&:last-of-type_button]:rounded-e-lg",
        )
    )

    button = Component(
        tag_name="button",
        attributes=[
            ("type", "button"),
            ("title", title),
            ("class", color_classes + " hover:cursor-pointer"),
        ],
        children=[slot],
    )

    return Component(tag_name="a", attributes=a_attrs, children=[button])


def ButtonGroup(buttons: list[dict] | None = None) -> SafeText:
    """Generate a button group div.

    Each button dict accepts: href, slot (required), color, title, hx_get, hx_target.
    Empty dicts (no slot) are silently skipped — matching the template behavior
    for conditional buttons (e.g., end-session only when session is active).
    """
    buttons = buttons or []
    children: list[SafeText] = []
    for btn in buttons:
        if not btn or not btn.get("slot"):
            continue
        children.append(
            _button_group_button(
                href=btn.get("href", "#"),
                slot=btn["slot"],
                color=btn.get("color", "gray"),
                title=btn.get("title", ""),
                hx_get=btn.get("hx_get", ""),
                hx_target=btn.get("hx_target", ""),
            )
        )

    return Component(
        tag_name="div",
        attributes=[("class", "inline-flex rounded-md shadow-xs"), ("role", "group")],
        children=children,
    )


def Div(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(tag_name="div", attributes=attributes, children=children)


def Input(
    type: str = "text",
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(
        tag_name="input", attributes=attributes + [("type", type)], children=children
    )


def Form(
    action="",
    method="get",
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(
        tag_name="form",
        attributes=attributes + [("action", action), ("method", method)],
        children=children,
    )


def SearchField(
    search_string: str = "",
    id: str = "search_string",
    placeholder: str = "Search",
) -> SafeText:
    """Generate a search form with icon, input field, and submit button."""
    return Component(
        tag_name="form",
        attributes=[("class", "max-w-md")],
        children=[
            Component(
                tag_name="label",
                attributes=[
                    ("for", "search"),
                    ("class", "block mb-2.5 text-sm font-medium text-heading sr-only"),
                ],
                children=["Search"],
            ),
            Component(
                tag_name="div",
                attributes=[("class", "relative")],
                children=[
                    mark_safe(
                        '<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none">'
                        '<svg class="w-4 h-4 text-body" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" '
                        'fill="none" viewBox="0 0 24 24">'
                        '<path stroke="currentColor" stroke-linecap="round" stroke-width="2" '
                        'd="m21 21-3.5-3.5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z"/>'
                        "</svg></div>"
                    ),
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "search"),
                            ("id", id),
                            ("name", id),
                            ("value", search_string),
                            (
                                "class",
                                "block w-full p-3 ps-9 bg-neutral-secondary-medium "
                                "border border-default-medium text-heading text-sm "
                                "rounded-base focus:ring-brand focus:border-brand "
                                "shadow-xs placeholder:text-body",
                            ),
                            ("placeholder", placeholder),
                            ("required", ""),
                        ],
                    ),
                    Component(
                        tag_name="button",
                        attributes=[
                            ("type", "submit"),
                            (
                                "class",
                                "absolute end-1.5 bottom-1.5 text-white bg-brand "
                                "hover:bg-brand-strong box-border border border-transparent "
                                "focus:ring-4 focus:ring-brand-medium shadow-xs font-medium "
                                "leading-5 rounded text-xs px-3 py-1.5 focus:outline-none "
                                "cursor-pointer",
                            ),
                        ],
                        children=["Search"],
                    ),
                ],
            ),
        ],
    )


def GameLink(
    game_id: int,
    name: str = "",
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Link to a game's detail page. Uses children (slot) if provided, otherwise name."""
    from django.urls import reverse

    children = children or []
    display = children if children else [name]
    link = reverse("games:view_game", args=[game_id])

    return Component(
        tag_name="span",
        attributes=[("class", "truncate-container")],
        children=[
            Component(
                tag_name="a",
                attributes=[
                    ("href", link),
                    ("class", "underline decoration-slate-500 sm:decoration-2"),
                ],
                children=display if isinstance(display, list) else [display],
            ),
        ],
    )


_STATUS_COLORS = {
    "u": "bg-gray-500",
    "p": "bg-orange-400",
    "f": "bg-green-500",
    "a": "bg-red-500",
    "r": "bg-purple-500",
}


def GameStatus(
    children: list[HTMLTag] | HTMLTag | None = None,
    status: str = "u",
    display: str = "",
    class_: str = "",
) -> SafeText:
    """Colored status dot with label. Status codes: u/p/f/a/r."""
    children = children or []
    outer_class = (
        f"{'flex' if display == 'flex' else 'inline-flex'} "
        "gap-2 items-center align-middle"
    )
    if class_:
        outer_class += f" {class_}"
    dot_color = _STATUS_COLORS.get(status, _STATUS_COLORS["u"])

    dot = Component(
        tag_name="span",
        attributes=[("class", f"rounded-xl w-3 h-3 {dot_color}")],
        children=["\xa0"],
    )

    return Component(
        tag_name="span",
        attributes=[("class", outer_class)],
        children=[dot] + (children if isinstance(children, list) else [children]),
    )


def PriceConverted(
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Wrap content in a span that indicates the price was converted."""
    children = children or []
    return Component(
        tag_name="span",
        attributes=[
            ("title", "Price is a result of conversion and rounding."),
            ("class", "decoration-dotted underline"),
        ],
        children=children if isinstance(children, list) else [children],
    )


def H1(
    children: list[HTMLTag] | HTMLTag | None = None,
    badge: str = "",
) -> SafeText:
    """Heading with optional badge count."""
    children = children or []
    heading_class = "mb-4 text-3xl font-extrabold leading-none tracking-tight text-gray-900 dark:text-white"
    badge_html = ""

    if badge:
        heading_class = "flex items-center " + heading_class
        badge_html = Component(
            tag_name="span",
            attributes=[
                (
                    "class",
                    "bg-blue-100 text-blue-800 text-2xl font-semibold me-2 "
                    "px-2.5 py-0.5 rounded-sm dark:bg-blue-200 dark:text-blue-800 ms-2",
                ),
            ],
            children=[badge],
        )

    return Component(
        tag_name="h1",
        attributes=[("class", heading_class)],
        children=(children if isinstance(children, list) else [children]) + ([badge_html] if badge_html else []),
    )


def Modal(
    modal_id: str,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Modal overlay with container. Content (form, buttons) goes in children."""
    children = children or []
    outer = Component(
        tag_name="div",
        attributes=[
            ("id", modal_id),
            (
                "class",
                "fixed inset-0 bg-black/70 dark:bg-gray-600/50 overflow-y-auto "
                "h-full w-full flex items-center justify-center",
            ),
        ],
        children=[
            Component(
                tag_name="div",
                attributes=[
                    (
                        "class",
                        "relative mx-auto p-5 border-accent border w-full max-w-md "
                        "shadow-lg/50 rounded-md bg-white dark:bg-gray-900",
                    ),
                ],
                children=(
                    children if isinstance(children, list) else [children]
                ),
            ),
        ],
    )
    return mark_safe(str(outer))


def TableTd(
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Styled table cell."""
    children = children or []
    return Component(
        tag_name="td",
        attributes=[("class", "px-6 py-4 min-w-20-char max-w-20-char")],
        children=children if isinstance(children, list) else [children],
    )


def TableRow(data: dict | list | None = None) -> SafeText:
    """Generate a <tr> from a row data dict or list.

    Dict form: {"row_id": "...", "cell_data": [...], "hx_trigger": ..., ...}
    - first cell is <th>, rest <td>.
    List form: [...] — all cells are <td>.
    """
    if data is None:
        data = {}
    if isinstance(data, dict):
        row_id = data.get("row_id", "")
        cells = data.get("cell_data", [])
    else:
        row_id = ""
        cells = data

    tr_class = (
        "odd:bg-white dark:odd:bg-gray-900 even:bg-gray-50 "
        "dark:even:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 "
        "dark:hover:bg-gray-600 [&_a]:underline [&_a]:underline-offset-4 "
        "[&_a]:decoration-2 [&_td:last-child]:text-right"
    )
    tr_attrs: list[HTMLAttribute] = [("class", tr_class)]
    if row_id:
        tr_attrs.append(("id", row_id))
    if isinstance(data, dict):
        if data.get("hx_trigger"):
            tr_attrs.append(("hx-trigger", data["hx_trigger"]))
        if data.get("hx_get"):
            tr_attrs.append(("hx-get", data["hx_get"]))
        if data.get("hx_select"):
            tr_attrs.append(("hx-select", data["hx_select"]))
        if data.get("hx_swap"):
            tr_attrs.append(("hx-swap", data["hx_swap"]))

    cell_elements: list[SafeText] = []
    for i, cell in enumerate(cells):
        if i == 0:
            cell_elements.append(
                Component(
                    tag_name="th",
                    attributes=[
                        ("scope", "row"),
                        (
                            "class",
                            "px-6 py-4 font-medium text-gray-900 "
                            "whitespace-nowrap dark:text-white",
                        ),
                    ],
                    children=[cell],
                )
            )
        else:
            cell_elements.append(TableTd(children=[cell]))

    return Component(tag_name="tr", attributes=tr_attrs, children=cell_elements)


def Icon(
    name: str,
    attributes: list[HTMLAttribute] | None = None,
) -> SafeText:
    return mark_safe(get_icon(name))


def TableHeader(
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Table caption."""
    children = children or []
    return Component(
        tag_name="caption",
        attributes=[
            (
                "class",
                "p-2 text-lg font-semibold rtl:text-left text-right "
                "text-gray-900 bg-white dark:text-white dark:bg-gray-900",
            ),
        ],
        children=children if isinstance(children, list) else [children],
    )


def Table(columns: list[str] | None = None, children=None) -> SafeText:
    """Standalone table with header and body slot.

    Currently unused — superseded by simple_table. Kept for optional future use.
    """
    columns = columns or []
    children = children or []
    return Component(
        tag_name="div",
        attributes=[("class", "relative overflow-x-auto shadow-md sm:rounded-lg")],
        children=[
            Component(
                tag_name="table",
                attributes=[
                    (
                        "class",
                        "w-full text-sm text-left rtl:text-right "
                        "text-gray-500 dark:text-gray-400",
                    ),
                ],
                children=[
                    Component(
                        tag_name="thead",
                        attributes=[
                            (
                                "class",
                                "text-xs text-gray-700 uppercase bg-gray-50 "
                                "dark:bg-gray-700 dark:text-gray-400",
                            ),
                        ],
                        children=[
                            Component(
                                tag_name="tr",
                                children=[
                                    Component(
                                        tag_name="th",
                                        attributes=[
                                            ("scope", "col"),
                                            ("class", "px-6 py-3"),
                                        ],
                                        children=[col],
                                    )
                                    for col in columns
                                ],
                            ),
                        ],
                    ),
                    Component(
                        tag_name="tbody",
                        children=(
                            children
                            if isinstance(children, list)
                            else [children]
                        ),
                    ),
                ],
            ),
        ],
    )


def LinkedPurchase(purchase: Purchase) -> SafeText:
    link = reverse("games:view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content = ""
    game_count = purchase.games.count()
    popover_if_not_truncated = False
    if game_count == 1:
        link_content += purchase.games.first().name
        popover_content = link_content
    if game_count > 1:
        if purchase.name:
            link_content += f"{purchase.name}"
            popover_content += f"<h1>{purchase.name}</h1><br>"
        else:
            link_content += f"{game_count} games"
            popover_if_not_truncated = True
        popover_content += f"""
        <ul class="list-disc list-inside">
            {"".join(f"<li>{game.name}</li>" for game in purchase.games.all())}
        </ul>
        """
    icon = purchase.platform.icon if game_count == 1 else "unspecified"
    if link_content == "":
        raise ValueError("link_content is empty!!")
    a_content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                icon,
                [("title", "Multiple")],
            ),
            PopoverTruncated(
                input_string=link_content,
                popover_content=mark_safe(popover_content),
                popover_if_not_truncated=popover_if_not_truncated,
            ),
        ],
    )
    return A(href=link, children=[a_content])


def NameWithIcon(
    name: str = "",
    game: Game | None = None,
    session: Session | None = None,
    linkify: bool = True,
    emulated: bool = False,
) -> SafeText:
    _name, platform, final_emulated, create_link, link = _resolve_name_with_icon(
        name, game, session, linkify
    )

    content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                platform.icon,
                [("title", platform.name)],
            )
            if platform
            else "",
            Icon("emulated", [("title", "Emulated")]) if final_emulated else "",
            PopoverTruncated(_name),
        ],
    )

    return (
        A(
            href=link,
            children=[content],
        )
        if create_link
        else content
    )


def _resolve_name_with_icon(
    name: str,
    game: Game | None,
    session: Session | None,
    linkify: bool,
) -> tuple[str, Any, bool, bool, str]:
    create_link = False
    link = ""
    platform = None
    final_emulated = False

    if session is not None:
        game = session.game
        platform = game.platform
        final_emulated = session.emulated
        if linkify:
            create_link = True
            link = reverse("games:view_game", args=[int(game.pk)])
    elif game is not None:
        platform = game.platform
        if linkify:
            create_link = True
            link = reverse("games:view_game", args=[int(game.pk)])

    _name = name or (game.name if game else "")

    return _name, platform, final_emulated, create_link, link


def PurchasePrice(purchase) -> SafeText:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
    )



