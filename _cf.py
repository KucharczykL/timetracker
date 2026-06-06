import hashlib
from functools import lru_cache
from typing import Any

from django.db import models
from django.middleware.csrf import get_token
from django.template.defaultfilters import floatformat
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import conditional_escape, escape
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


@lru_cache(maxsize=4096)
def _render_element(
    tag_name: str,
    attrs_key: tuple[tuple[str, str], ...],
    children_key: tuple[tuple[str, bool], ...],
) -> str:
    """Pure, memoized HTML builder behind `Component`.

    Inputs are fully hashable and fully determine the output, so identical
    elements are rendered once. `attrs_key` is (name, stringified value) pairs
    (attribute values are always escaped). `children_key` is (child, is_safe)
    pairs: SafeText children pass through, plain strings are escaped. The
    `is_safe` flag is part of the key on purpose — otherwise a safe ``"<b>"``
    and an unsafe ``"<b>"`` (equal as strings) would collide and one would
    render with the wrong escaping.
    """
    children_blob = "\n".join(
        child if is_safe else escape(child) for child, is_safe in children_key
    )
    if attrs_key:
        attributes_blob = " " + " ".join(
            f'{name}="{escape(value)}"' for name, value in attrs_key
        )
    else:
        attributes_blob = ""
    return f"<{tag_name}{attributes_blob}>{children_blob}</{tag_name}>"


def Component(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    tag_name: str = "",
) -> SafeText:
    """Render an HTML element. Attribute values are always escaped; children are
    escaped unless they are `SafeText` (so nested components pass through),
    preventing accidental HTML injection. Rendering is memoized via
    `_render_element`."""
    attributes = attributes or []
    children = children or []
    if not tag_name:
        raise ValueError("tag_name is required.")
    if isinstance(children, str):
        children = [children]
    attrs_key = tuple((name, str(value)) for name, value in attributes)
    children_key = tuple((child, isinstance(child, SafeText)) for child in children)
    return mark_safe(_render_element(tag_name, attrs_key, children_key))


def randomid(seed: str = "", content: str = "", length: int = 10) -> str:
    if not seed and not content:
        return seed
    hash_input = f"{seed}:{content}" if seed else content
    content_hash = hashlib.sha1(hash_input.encode()).hexdigest()
    base = (
        content_hash[:length]
        if not seed
        else content_hash[: max(0, length - len(seed))]
    )
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


def CsrfInput(request) -> SafeText:
    """Hidden CSRF input, equivalent to the `{% csrf_token %}` template tag."""
    return mark_safe(
        f'<input type="hidden" name="csrfmiddlewaretoken" value="{get_token(request)}">'
    )


def ModuleScript(filename: str) -> SafeText:
    """A `<script type="module">` tag pointing at a static JS file."""
    return mark_safe(
        f'<script type="module" src="{static("js/" + filename)}"></script>'
    )


def AddForm(
    form,
    *,
    request,
    fields: SafeText | str | None = None,
    additional_row: SafeText | str = "",
    submit_class: str = "mt-3",
) -> SafeText:
    """Page body for the generic add/edit form (Python equivalent of add.html).

    `fields` overrides the default ``form.as_div()`` field markup (used by the
    session form, which lays out its fields manually). `additional_row` holds
    extra submit buttons rendered below the main Submit button. `submit_class`
    is applied to the main Submit button (the session form passes "" to match
    its original markup).
    """
    field_markup = fields if fields is not None else mark_safe(form.as_div())
    submit_attrs = [("class", submit_class)] if submit_class else []

    inner_form = Component(
        tag_name="form",
        attributes=[("method", "post"), ("enctype", "multipart/form-data")],
        children=[
            CsrfInput(request),
            field_markup,
            Div(children=[Button(submit_attrs, "Submit", type="submit")]),
            Div(
                [("class", "submit-button-container")],
                [additional_row] if additional_row else [],
            ),
        ],
    )

    return Div(
        [("id", "add-form"), ("class", "max-width-container")],
        [
            Div(
                [("id", "add-form"), ("class", "form-container max-w-xl mx-auto")],
                [inner_form],
            )
        ],
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
        children=(children if isinstance(children, list) else [children])
        + ([badge_html] if badge_html else []),
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
                children=(children if isinstance(children, list) else [children]),
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


def _page_url(request, page) -> str:
    """Current querystring with `page` replaced (mirrors {% param_replace %})."""
    if request is None:
        return f"?page={page}"
    params = request.GET.copy()
    params["page"] = page
    return "?" + params.urlencode()


def _pagination_nav(page_obj, elided_page_range, request) -> str:
    pages_html = ""
    for page in elided_page_range:
        if page != page_obj.number:
            pages_html += (
                f'<li><a href="{_page_url(request, page)}" '
                'class="flex items-center justify-center px-3 h-8 leading-tight text-gray-500 '
                "bg-white border border-gray-300 hover:bg-gray-100 hover:text-gray-700 "
                "dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
                f'dark:hover:text-white">{conditional_escape(page)}</a></li>'
            )
        else:
            pages_html += (
                '<li><a aria-current="page" '
                'class="cursor-not-allowed flex items-center justify-center px-3 h-8 leading-tight '
                "text-white border bg-gray-400 border-gray-300 dark:bg-gray-900 dark:border-gray-700 "
                f'dark:text-gray-200">{conditional_escape(page)}</a></li>'
            )

    if page_obj.has_previous():
        prev_html = (
            f'<a href="{_page_url(request, page_obj.previous_page_number())}" '
            'class="flex items-center justify-center px-3 h-8 ms-0 leading-tight text-gray-500 '
            "bg-white border border-gray-300 rounded-s-lg hover:bg-gray-100 hover:text-gray-700 "
            "dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
            'dark:hover:text-white">Previous</a>'
        )
    else:
        prev_html = (
            '<a aria-current="page" class="cursor-not-allowed flex items-center justify-center '
            "px-3 h-8 leading-tight text-gray-300 bg-white border border-gray-300 rounded-s-lg "
            'dark:bg-gray-800 dark:border-gray-700 dark:text-gray-600">Previous</a>'
        )

    if page_obj.has_next():
        next_html = (
            f'<a href="{_page_url(request, page_obj.next_page_number())}" '
            'class="flex items-center justify-center px-3 h-8 leading-tight text-gray-500 '
            "bg-white border border-gray-300 rounded-e-lg hover:bg-gray-100 hover:text-gray-700 "
            "dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 "
            'dark:hover:text-white">Next</a>'
        )
    else:
        next_html = (
            '<a aria-current="page" class="cursor-not-allowed flex items-center justify-center '
            "px-3 h-8 leading-tight text-gray-300 bg-white border border-gray-300 rounded-e-lg "
            'dark:bg-gray-800 dark:border-gray-700 dark:text-gray-600">Next</a>'
        )

    return (
        '<nav class="flex items-center flex-col md:flex-row md:justify-between px-6 py-4 '
        'dark:bg-gray-900 sm:rounded-b-lg" aria-label="Table navigation">'
        '<span class="text-sm text-center font-normal text-gray-500 dark:text-gray-400 mb-4 '
        'md:mb-0 block w-full md:inline md:w-auto">'
        f'<span class="font-semibold text-gray-900 dark:text-white">{page_obj.start_index()}</span>—'
        f'<span class="font-semibold text-gray-900 dark:text-white">{page_obj.end_index()}</span> of '
        f'<span class="font-semibold text-gray-900 dark:text-white">{page_obj.paginator.count}</span></span>'
        '<ul class="inline-flex -space-x-px rtl:space-x-reverse text-sm h-8"><li>'
        f"{prev_html}{pages_html}{next_html}"
        "</li></ul></nav>"
    )


def SimpleTable(
    columns: list[str] | None = None,
    rows: list | None = None,
    header_action: SafeText | str | None = None,
    page_obj=None,
    elided_page_range=None,
    request=None,
) -> SafeText:
    """Paginated table. Python equivalent of the old simple_table.html."""
    columns = columns or []
    rows = rows or []

    header_html = ""
    if header_action:
        header_html = str(TableHeader(children=[header_action]))

    columns_html = "".join(
        f'<th scope="col" class="px-6 py-3">{conditional_escape(col)}</th>'
        for col in columns
    )
    rows_html = "".join(str(TableRow(data=row)) for row in rows)

    pagination_html = ""
    if page_obj and elided_page_range:
        pagination_html = _pagination_nav(page_obj, elided_page_range, request)

    return mark_safe(
        '<div class="shadow-md" hx-boost="false">'
        '<div class="relative overflow-x-auto sm:rounded-t-lg">'
        '<table class="w-full text-sm text-left rtl:text-right text-gray-500 dark:text-gray-400">'
        f"{header_html}"
        '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 '
        'dark:text-gray-400 max-sm:[&_th:not(:first-child):not(:last-child)]:hidden">'
        f"<tr>{columns_html}</tr></thead>"
        '<tbody class="dark:divide-y max-sm:[&_td:not(:first-child):not(:last-child)]:hidden">'
        f"{rows_html}</tbody></table></div>"
        f"{pagination_html}</div>"
    )


def paginated_table_content(
    data: dict,
    *,
    page_obj=None,
    elided_page_range=None,
    request=None,
) -> SafeText:
    """Standard list-page body: a max-width Div wrapping a SimpleTable.

    `data` is the table dict with keys ``columns``, ``rows`` and
    ``header_action`` (the same shape every list view already builds).
    """
    return Div(
        [
            (
                "class",
                "2xl:max-w-(--breakpoint-2xl) xl:max-w-(--breakpoint-xl) "
                "md:max-w-(--breakpoint-md) sm:max-w-(--breakpoint-sm) self-center",
            )
        ],
        [
            SimpleTable(
                columns=data["columns"],
                rows=data["rows"],
                header_action=data["header_action"],
                page_obj=page_obj,
                elided_page_range=elided_page_range,
                request=request,
            )
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
    icon = (
        (purchase.platform.icon if purchase.platform else "unspecified")
        if game_count == 1
        else "unspecified"
    )
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


def GameStatusSelector(game, game_statuses, csrf_token: str) -> SafeText:
    """Alpine.js dropdown to change a game's status."""
    options_html = "\n".join(
        f"<template x-if=\"status == '{value}'\">"
        f"{GameStatus(status=value, children=[label], display='flex')}"
        f"</template>"
        for value, label in game_statuses
    )
    list_items = "\n".join(
        f"<li><a href=\"#\" @click.prevent.stop=\"setStatus('{value}', '{label}'); open = false;\" "
        f'class="block px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 '
        f'dark:focus:ring-blue-500 dark:focus:text-white rounded-sm no-underline! border-0!" '
        f":class=\"{{'font-bold': status === '{value}'}}\">"
        f"{GameStatus(status=value, children=[label], display='flex', class_='text-slate-300')}"
        f"</a></li>"
        for value, label in game_statuses
    )

    return mark_safe(f"""
<div class="flex gap-2 items-center"
     x-data="{{
         status: '{game.status}',
         status_display: '{game.get_status_display()}',
         open: false,
         saving: false,
         setStatus(newStatus, newStatusDisplay) {{
             this.status = newStatus;
             this.status_display = newStatusDisplay;
             this.saving = true;
             fetchWithHtmxTriggers(`/api/games/{game.id}/status`, {{
                 method: 'PATCH',
                 headers: {{
                     'Content-Type': 'application/json',
                     'X-CSRFToken': '{csrf_token}'
                 }},
                 body: JSON.stringify({{ status: newStatus }})
             }})
             .then(() => {{
                 document.body.dispatchEvent(new CustomEvent('status-changed'));
             }})
             .catch(() => {{
                 console.error('Failed to update status');
             }})
             .finally(() => this.saving = false);
         }}
     }}">
    {_dropdown_button_html(options_html, list_items)}
</div>
""")


def SessionDeviceSelector(session, session_devices, csrf_token: str) -> SafeText:
    """Alpine.js dropdown to change a session's device."""
    device_id = session.device_id or "null"
    device_name = (session.device.name if session.device else "Unknown").replace(
        "'", "\\'"
    )

    list_items = "\n".join(
        f'<li><a href="#" @click.prevent.stop="setDevice({d.id}, \'{d.name.replace(chr(39), chr(92) + chr(39))}\'); open = false;" '
        f'class="block px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 '
        f'dark:focus:ring-blue-500 dark:focus:text-white rounded-sm no-underline! border-0!" '
        f":class=\"{{'font-bold': deviceId === {d.id}}}\">{d.name}</a></li>"
        for d in session_devices
    )

    return mark_safe(f"""
<div class="flex gap-2 items-center"
     x-data="{{
         originalDeviceId: {device_id},
         originalDeviceName: '{device_name}',
         deviceId: {device_id},
         deviceName: '{device_name}',
         open: false,
         saving: false,
         setDevice(newDeviceId, newDeviceName) {{
               this.deviceId = newDeviceId;
               this.deviceName = newDeviceName;
               this.saving = true;
                fetchWithHtmxTriggers(`/api/session/{session.id}/device`, {{
                    method: 'PATCH',
                    headers: {{
                        'Content-Type': 'application/json',
                        'X-CSRFToken': '{csrf_token}'
                    }},
                    body: JSON.stringify({{ device_id: newDeviceId }})
                }})
               .then((res) => {{
                   document.body.dispatchEvent(new CustomEvent('device-changed'));
               }})
               .catch(() => {{
                   this.deviceName = this.originalDeviceName;
                   this.deviceId = this.originalDeviceId;
                   console.error('Failed to update device');
               }})
               .finally(() => this.saving = false);
          }}
     }}">
    {
        _dropdown_button_html(
            '<span x-text="deviceName"></span>' + str(Icon("arrowdown")), list_items
        )
    }
</div>
""")


def _dropdown_button_html(button_content: str, list_items: str) -> str:
    """Shared dropdown button + list structure for Alpine.js selectors."""
    return (
        '<div class="inline-flex rounded-md shadow-2xs" role="group" @click.outside="open = false">'
        '<button type="button" @click="open = !open" '
        'class="relative px-4 py-2 text-sm font-medium bg-white border border-gray-200 '
        "rounded-lg hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-2 "
        "focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 "
        'dark:focus:text-white align-middle hover:cursor-pointer">'
        f'<span class="flex flex-row gap-4 justify-between items-center">{button_content}</span>'
        '<div class="absolute top-[105%] left-0 w-full whitespace-nowrap z-10 text-sm '
        "font-medium bg-gray-800/20 backdrop-blur-lg rounded-md rounded-t-none border "
        'border-gray-200 dark:border-gray-700" x-show="open" style="display: none;">'
        '<ul class="[&_li:first-of-type_a]:rounded-none [&_li:last-of-type_a]:rounded-t-none">'
        f"{list_items}"
        "</ul>"
        "</div>"
        "</button>"
        "</div>"
    )


# ── Filter bar (shared shell + per-entity field builders) ───────────────────

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


def _filter_get_choice(existing: dict, field: str) -> tuple[list[str], list[str], str]:
    raw = existing.get(field, {})
    if not isinstance(raw, dict):
        return [], [], ""
    val = raw.get("value", [])
    excl = raw.get("excludes", [])
    mod = raw.get("modifier", "")
    if isinstance(val, str):
        val = [val]
    if isinstance(excl, str):
        excl = [excl]
    return [str(v) for v in (val or [])], [str(v) for v in (excl or [])], mod or ""


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
            Component(
                tag_name="label",
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
    return Component(
        tag_name="label",
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


def _filter_range_inputs(cls, min_id, max_id, min_v, max_v, dmin, dmax, step="1"):
    """Twin <input type=range> slider (used by the game filter bar)."""
    mv = min_v or str(dmin)
    xv = max_v or str(dmax)
    return Component(
        tag_name="div",
        attributes=[("class", f"range-slider {cls} relative h-6 mt-1 mb-2")],
        children=[
            mark_safe(
                f'<input type="range" class="range-min absolute w-full pointer-events-none '
                f"appearance-none bg-transparent h-2 "
                f"[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 "
                f"[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full "
                f"[&::-webkit-slider-thumb]:bg-brand [&::-webkit-slider-thumb]:cursor-pointer "
                f'[&::-webkit-slider-thumb]:relative [&::-webkit-slider-thumb]:z-10" '
                f'data-target="{min_id}" data-peer="{max_id}" '
                f'min="{dmin}" max="{dmax}" value="{mv}" step="{step}">'
                f'<input type="range" class="range-max absolute w-full pointer-events-none '
                f"appearance-none bg-transparent h-2 "
                f"[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 "
                f"[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full "
                f"[&::-webkit-slider-thumb]:bg-brand [&::-webkit-slider-thumb]:cursor-pointer "
                f'[&::-webkit-slider-thumb]:relative [&::-webkit-slider-thumb]:z-20" '
                f'data-target="{max_id}" data-peer="{min_id}" '
                f'min="{dmin}" max="{dmax}" value="{xv}" step="{step}">'
            ),
        ],
    )


def _filter_range_handles(cls, min_id, max_id, lo, hi, step="1"):
    """Handle-based slider (used by the session & purchase filter bars)."""
    return Component(
        tag_name="div",
        attributes=[
            ("class", f"range-slider {cls} relative h-10 mt-1 mb-2 select-none"),
            ("data-min", str(lo)),
            ("data-max", str(hi)),
            ("data-step", str(step)),
        ],
        children=[
            mark_safe(
                '<div class="absolute top-1/2 -translate-y-1/2 w-full h-2 rounded-full bg-neutral-secondary-medium border border-default-medium"></div><div class="range-track-fill absolute top-1/2 -translate-y-1/2 h-2 bg-brand rounded-full" style="left:0;width:100%"></div>'
                + f'<div class="range-handle-min absolute top-1/2 -translate-y-1/2 w-5 h-5 bg-brand rounded-full border-2 border-white shadow cursor-pointer hover:scale-110 transition-transform" data-target="{min_id}" style="left:0"></div><div class="range-handle-max absolute top-1/2 -translate-y-1/2 w-5 h-5 bg-brand rounded-full border-2 border-white shadow cursor-pointer hover:scale-110 transition-transform" data-target="{max_id}" style="left:100%"></div>'
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
            Component(
                tag_name="span",
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
                    Component(
                        tag_name="span",
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
    platform_options: list[tuple[int, str]] | None = None,
    preset_list_url: str = "",
    preset_save_url: str = "",
) -> SafeText:
    """Collapsible filter bar for the Game list."""
    from games.models import Game, Platform

    if status_options is None:
        status_options = [(s.value, s.label) for s in Game.Status]
    if platform_options is None:
        platform_options = list(
            Platform.objects.order_by("name").values_list("id", "name")
        )

    existing = _filter_parse(filter_json)
    status_sel, status_excl, status_mod = _filter_get_choice(existing, "status")
    plat_sel, plat_excl, plat_mod = _filter_get_choice(existing, "platform")
    plat_opts_str = [(str(k), v) for k, v in platform_options]

    year_rel = existing.get("year_released", {})
    year_min = str(year_rel.get("value", "")) if isinstance(year_rel, dict) else ""
    year_max = str(year_rel.get("value2", "")) if isinstance(year_rel, dict) else ""
    mastered_val = (
        existing.get("mastered", {}).get("value", False)
        if isinstance(existing.get("mastered"), dict)
        else False
    )
    playtime = existing.get("playtime_minutes", {})
    playtime_min = (
        _filter_mins_to_hrs(playtime.get("value", ""))
        if isinstance(playtime, dict)
        else ""
    )
    playtime_max = (
        _filter_mins_to_hrs(playtime.get("value2", ""))
        if isinstance(playtime, dict)
        else ""
    )

    try:
        year_agg = Game.objects.aggregate(
            yr_min=models.Min("year_released"), yr_max=models.Max("year_released")
        )
    except Exception:
        year_agg = {}
    try:
        pt_agg = Game.objects.aggregate(pt_max=models.Max("playtime"))
    except Exception:
        pt_agg = {}
    yr_data_min = max(int(year_agg.get("yr_min") or 1970), 1970)
    yr_data_max = min(int(year_agg.get("yr_max") or 2030), 2030)
    pt_data_max = (
        int((pt_agg.get("pt_max") or 0).total_seconds() / 3600)
        if pt_agg.get("pt_max")
        else 200
    )

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Status",
                    SelectableFilter(
                        "status",
                        status_options,
                        status_sel,
                        status_excl,
                        status_mod,
                        nullable=not Game._meta.get_field("status").has_default(),
                    ),
                ),
                _filter_field(
                    "Platform",
                    SelectableFilter(
                        "platform",
                        plat_opts_str,
                        plat_sel,
                        plat_excl,
                        plat_mod,
                        nullable=Game._meta.get_field("platform").null,
                    ),
                ),
                _filter_number("Year Min", "filter-year-min", year_min, "e.g. 2020"),
                _filter_number("Year Max", "filter-year-max", year_max, "e.g. 2024"),
            ],
        ),
        _filter_range_inputs(
            "year-range",
            "filter-year-min",
            "filter-year-max",
            year_min,
            year_max,
            yr_data_min,
            yr_data_max,
        ),
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_number(
                    "Playtime Min (hrs)", "filter-playtime-min", playtime_min, "e.g. 1"
                ),
                _filter_number(
                    "Playtime Max (hrs)",
                    "filter-playtime-max",
                    playtime_max,
                    "e.g. 100",
                ),
                Component(
                    tag_name="div",
                    attributes=[("class", "flex items-end pb-1")],
                    children=[
                        _filter_checkbox("filter-mastered", "Mastered", mastered_val)
                    ],
                ),
            ],
        ),
        _filter_range_inputs(
            "playtime-range",
            "filter-playtime-min",
            "filter-playtime-max",
            playtime_min or "0",
            playtime_max or str(pt_data_max),
            0,
            pt_data_max,
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


# ── SelectableFilter widget ────────────────────────────────────────────────


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

    active_mod_html = ""
    inactive_mod_html = ""
    mod_opts = [("NOT_NULL", "(Any)")]
    if nullable:
        mod_opts.append(("IS_NULL", "(None)"))
    for mod_val, mod_label in mod_opts:
        if modifier == mod_val:
            active_mod_html = (
                f'<span class="sf-modifier-tag active" data-modifier="{mod_val}">'
                f"{mod_label}</span> "
            )
        else:
            inactive_mod_html += (
                f'<div class="sf-option sf-modifier-option" data-modifier="{mod_val}" '
                f'data-label="{mod_label}">'
                f'<span class="sf-option-label">{mod_label}</span></div>'
            )

    selected_html = ""
    for val in selected:
        label = _find_label(options, val)
        selected_html += (
            f'<span class="sf-tag" data-value="{escape(val)}" data-type="include">'
            f'<span class="sf-tag-text text-body">\u2713 {escape(label)}</span>'
            f'<button type="button" class="sf-remove">\u00d7</button></span> '
        )
    for val in excluded:
        label = _find_label(options, val)
        selected_html += (
            f'<span class="sf-tag sf-excluded" data-value="{escape(val)}" data-type="exclude">'
            f'<span class="sf-tag-text text-body">\u2717 {escape(label)}</span>'
            f'<button type="button" class="sf-remove">\u00d7</button></span> '
        )

    options_html = ""
    for val, label in options:
        options_html += (
            f'<div class="sf-option" data-value="{escape(val)}" data-label="{escape(label)}">'
            f'<span class="sf-option-label">{escape(label)}</span>'
            f'<span class="sf-option-buttons">'
            f'<button type="button" class="sf-btn-include" data-action="include" title="Include">+</button>'
            f'<button type="button" class="sf-btn-exclude" data-action="exclude" title="Exclude">\u2212</button>'
            f"</span></div>"
        )

    return Component(
        tag_name="div",
        attributes=[
            (
                "class",
                "sf-container border border-default-medium rounded-base bg-neutral-secondary-medium",
            ),
            ("data-selectable-filter", field_name),
            *([("data-modifier", modifier)] if modifier else []),
        ],
        children=[
            Component(
                tag_name="div",
                attributes=[
                    ("class", "sf-selected flex flex-wrap gap-1 p-2 min-h-[28px]"),
                ],
                children=[mark_safe(active_mod_html + selected_html)],
            ),
            Component(
                tag_name="input",
                attributes=[
                    ("type", "text"),
                    (
                        "class",
                        "sf-search block w-full border-0 border-t border-default-medium "
                        "bg-transparent text-sm text-heading p-2 focus:ring-0 focus:outline-hidden",
                    ),
                    ("placeholder", "Search\u2026"),
                ],
            ),
            Component(
                tag_name="div",
                attributes=[
                    ("class", "sf-options max-h-40 overflow-y-auto p-1 text-body"),
                ],
                children=[mark_safe(inactive_mod_html + options_html)],
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
    from games.models import Device, Game, Session

    game_opts = [
        (str(k), v) for k, v in Game.objects.order_by("name").values_list("id", "name")
    ]
    dev_opts = [
        (str(k), v)
        for k, v in Device.objects.order_by("name").values_list("id", "name")
    ]
    existing = _filter_parse(filter_json)
    gs, ge, gm = _filter_get_choice(existing, "game")
    ds, de, dm = _filter_get_choice(existing, "device")

    dur = existing.get("duration_minutes", {})
    dmin = _filter_mins_to_hrs(dur.get("value", "")) if isinstance(dur, dict) else ""
    dmax = _filter_mins_to_hrs(dur.get("value2", "")) if isinstance(dur, dict) else ""
    em = (
        existing.get("emulated", {}).get("value", False)
        if isinstance(existing.get("emulated"), dict)
        else False
    )
    ac = (
        existing.get("is_active", {}).get("value", False)
        if isinstance(existing.get("is_active"), dict)
        else False
    )
    try:
        a = Session.objects.aggregate(m=models.Max("duration_total"))
        ddm = max(
            int((a.get("m") or 0).total_seconds() / 3600) if a.get("m") else 200, 1
        )
    except Exception:
        ddm = 200

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    SelectableFilter(
                        "game",
                        game_opts,
                        gs,
                        ge,
                        gm,
                        nullable=not Game._meta.get_field("name").has_default(),
                    ),
                ),
                _filter_field(
                    "Device",
                    SelectableFilter(
                        "device",
                        dev_opts,
                        ds,
                        de,
                        dm,
                        nullable=Session._meta.get_field("device").null,
                    ),
                ),
                _filter_number(
                    "Duration Min (hrs)", "filter-playtime-min", dmin, "e.g. 0.5"
                ),
                _filter_number(
                    "Duration Max (hrs)", "filter-playtime-max", dmax, "e.g. 10"
                ),
            ],
        ),
        _filter_range_handles(
            "dur-range", "filter-playtime-min", "filter-playtime-max", 0, ddm
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-emulated", "Emulated", em),
                _filter_checkbox("filter-active", "Active", ac),
            ],
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def PurchaseFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Purchase list."""
    from games.models import Game, Platform, Purchase

    game_opts = [
        (str(k), v) for k, v in Game.objects.order_by("name").values_list("id", "name")
    ]
    plat_opts = [
        (str(k), v)
        for k, v in Platform.objects.order_by("name").values_list("id", "name")
    ]
    type_opts = [(t[0], t[1]) for t in Purchase.TYPES]
    own_opts = [(t[0], t[1]) for t in Purchase.OWNERSHIP_TYPES]
    existing = _filter_parse(filter_json)
    gs, ge, gm = _filter_get_choice(existing, "games")
    ps, pe, pm = _filter_get_choice(existing, "platform")
    ts, te, tm = _filter_get_choice(existing, "type")
    os_, oe, om = _filter_get_choice(existing, "ownership_type")
    price = existing.get("price", {})
    pmin = str(price.get("value", "")) if isinstance(price, dict) else ""
    pmax = str(price.get("value2", "")) if isinstance(price, dict) else ""
    rf = (
        existing.get("is_refunded", {}).get("value", False)
        if isinstance(existing.get("is_refunded"), dict)
        else False
    )
    try:
        a = Purchase.objects.aggregate(lo=models.Min("price"), hi=models.Max("price"))
        plo, phi = int(a.get("lo") or 0), max(int(a.get("hi") or 100), 1)
    except Exception:
        plo, phi = 0, 100

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    SelectableFilter("games", game_opts, gs, ge, gm, nullable=False),
                ),
                _filter_field(
                    "Platform",
                    SelectableFilter(
                        "platform",
                        plat_opts,
                        ps,
                        pe,
                        pm,
                        nullable=Purchase._meta.get_field("platform").null,
                    ),
                ),
                _filter_field(
                    "Type",
                    SelectableFilter(
                        "type",
                        type_opts,
                        ts,
                        te,
                        tm,
                        nullable=not Purchase._meta.get_field("type").has_default(),
                    ),
                ),
                _filter_field(
                    "Ownership",
                    SelectableFilter(
                        "ownership_type",
                        own_opts,
                        os_,
                        oe,
                        om,
                        nullable=not Purchase._meta.get_field(
                            "ownership_type"
                        ).has_default(),
                    ),
                ),
            ],
        ),
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_number("Price Min", "filter-price-min", pmin, "0.00"),
                _filter_number("Price Max", "filter-price-max", pmax, "100.00"),
                _filter_checkbox("filter-refunded", "Refunded", rf),
            ],
        ),
        _filter_range_handles(
            "price-range", "filter-price-min", "filter-price-max", plo, phi
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)
