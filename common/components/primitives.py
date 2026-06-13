"""Generic HTML primitives (no domain knowledge).

Generic leaf elements (``Div``, ``Span``, ``Td`` …) are *not* hand-written one
per tag: they are generated from a whitelist via :func:`_html_element`, each a
thin builder over the single :class:`Element` node class. Only elements that add
classes or behaviour (``Button``, ``Pill``, ``Checkbox`` …) are written out.
Everything returns a :class:`Node`; string-built widgets return :class:`Safe`.
"""

from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import conditional_escape
from django.utils.safestring import SafeText, mark_safe

from common.components.core import (
    Attributes,
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
    collect_media,
    randomid,
)
from common.icons import get_icon
from common.utils import truncate

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


# ── Generic leaf elements ────────────────────────────────────────────────────
# A whitelist of plain tags, each turned into a builder over `Element`. The
# tag name is data, not a separate class/function body. Add a tag = one line.


def _attrs_from_kwargs(attrs: dict[str, object]) -> list[HTMLAttribute]:
    """Translate htpy-style attribute kwargs to (name, value) pairs.

    ``class_`` -> ``class`` (trailing underscore stripped); ``hx_get`` ->
    ``hx-get`` (inner underscores to hyphens); ``True`` -> bare attribute;
    ``False`` / ``None`` -> omitted."""
    result: list[HTMLAttribute] = []
    for key, value in attrs.items():
        if value is None or value is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        result.append((name, name if value is True else value))  # type: ignore[arg-type]
    return result


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
        attributes: Attributes | None = None,
        children: Children = None,
        **attrs: object,
    ) -> Element:
        merged = as_attributes(attributes) + _attrs_from_kwargs(attrs)
        node = Element(tag_name, merged, children)
        return node.with_media(media) if media else node

    element.__name__ = element.__qualname__ = tag_name[:1].upper() + tag_name[1:]
    element.__doc__ = f"Builder for the <{tag_name}> element."
    return element


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

    div = Div(
        attributes=[
            ("data-popover", ""),
            ("id", id),
            ("role", "tooltip"),
            ("class", popover_tooltip_class),
        ],
        children=[
            Div(
                attributes=[("class", "px-3 py-2")],
                children=[popover_content],
            ),
            Div(attributes=[("data-popper-arrow", "")]),
            Safe(  # nosec — intentional HTML comment for Tailwind JIT
                "<!-- for Tailwind CSS to generate decoration-dotted CSS "
                "from Python component -->"
            ),
            Span(
                attributes=[("class", "hidden decoration-dotted")],
            ),
        ],
    )

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


def PopoverTruncated(
    input_string: str,
    popover_content: Child = "",
    popover_if_not_truncated: bool = False,
    length: int = 30,
    ellipsis: str = "…",
    endpart: str = "",
) -> "Node | str":
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
    attributes: Attributes | None = None,
    children: Children = None,
    url_name: str | None = None,
    href: str | None = None,
) -> Element:
    """
    Returns an anchor <a> tag.

    Accepts one of two mutually-exclusive URL specifications:
        - url_name: URL pattern name, resolved via reverse()
        - href: Literal path string passed through as-is
    """
    attributes = as_attributes(attributes)
    children = children or []
    if url_name is not None and href is not None:
        raise ValueError("Provide exactly one of 'url_name' or 'href', not both.")

    additional_attributes = []
    if url_name is not None:
        additional_attributes = [("href", reverse(url_name))]
    elif href is not None:
        additional_attributes = [("href", href)]
    return Element(
        "a", attributes=attributes + additional_attributes, children=children
    )


def Button(
    attributes: Attributes | None = None,
    children: Children = None,
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
    **attrs: object,
) -> Element:
    attributes = as_attributes(attributes) + _attrs_from_kwargs(attrs)
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

    return Element(
        "button",
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
) -> Element:
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

    button = Element(
        "button",
        attributes=[
            ("type", "button"),
            ("title", title),
            ("class", color_classes + " hover:cursor-pointer"),
        ],
        children=[slot],
    )

    return Element("a", attributes=a_attrs, children=[button])


def ButtonGroup(buttons: list[dict] | None = None) -> Element:
    """Generate a button group div.

    Each button dict accepts: href, slot (required), color, title, hx_get, hx_target.
    Empty dicts (no slot) are silently skipped — matching the template behavior
    for conditional buttons (e.g., end-session only when session is active).
    """
    buttons = buttons or []
    children: list[Node] = []
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

    return Div(
        attributes=[("class", "inline-flex rounded-md shadow-xs"), ("role", "group")],
        children=children,
    )


def Input(
    type: str = "text",
    attributes: Attributes | None = None,
    children: Children = None,
) -> Element:
    attributes = as_attributes(attributes)
    children = children or []
    return Element("input", attributes=attributes + [("type", type)], children=children)


def Checkbox(
    name: str,
    label: str | None = None,
    checked: bool = False,
    value: str = "1",
    attributes: Attributes | None = None,
) -> Node:
    """A filter-agnostic Checkbox component."""
    attributes = as_attributes(attributes)
    input_attrs = [
        ("name", name),
        ("value", value),
        (
            "class",
            "rounded border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand",
        ),
    ] + attributes
    if checked:
        input_attrs.append(("checked", "true"))

    input_el = Input(type="checkbox", attributes=input_attrs)
    if label is None:
        return input_el

    return Label(
        attributes=[
            ("class", "flex items-center gap-2 text-sm text-heading cursor-pointer")
        ],
        children=[input_el, label],
    )


def Radio(
    name: str,
    label: str | None = None,
    checked: bool = False,
    value: str = "",
    attributes: Attributes | None = None,
) -> Node:
    """A filter-agnostic Radio component."""
    attributes = as_attributes(attributes)
    input_attrs = [
        ("name", name),
        ("value", value),
        (
            "class",
            "rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand",
        ),
    ] + attributes
    if checked:
        input_attrs.append(("checked", "true"))

    input_el = Input(type="radio", attributes=input_attrs)
    if label is None:
        return input_el

    return Label(
        attributes=[
            ("class", "flex items-center gap-1 text-sm text-heading cursor-pointer")
        ],
        children=[input_el, label],
    )


# Inline Tailwind utilities for Pill (mirrors the .sf-tag / .sf-remove rules in
# input.css, written inline so styling stays encapsulated in the component). The
# JS that builds pills client-side (search_select.js) MUST emit these exact class
# strings byte-for-byte so Tailwind generates them and server/JS pills match.
_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-brand/15 text-heading"
)
_PILL_REMOVE_CLASS = "ml-1 text-body hover:text-heading font-bold cursor-pointer"


def Pill(
    label: str,
    *,
    value: str = "",
    removable: bool = False,
    extra_class: str = "",
    label_slot: bool = False,
    attributes: Attributes | None = None,
) -> Node:
    """A small label pill, optionally removable (× button).

    Styling is inline Tailwind utilities; ``data-pill`` / ``data-pill-remove``
    are JS hooks only (no CSS attached). ``value`` (when set) becomes
    ``data-value``; extra ``attributes`` are appended to the outer span.

    ``label_slot=True`` wraps the label in a ``<span data-search-select-label>`` so JS can
    fill it when cloning the pill from a server-rendered ``<template>`` (keeps the
    markup single-sourced — see ``search_select.py``).
    """
    attributes = as_attributes(attributes)
    pill_class = f"{_PILL_CLASS} {extra_class}".strip()
    pill_attrs: list[HTMLAttribute] = [("class", pill_class), ("data-pill", "")]
    if value != "":
        pill_attrs.append(("data-value", str(value)))
    pill_attrs.extend(attributes)

    label_child: "Node | str" = (
        Span(attributes=[("data-search-select-label", "")], children=[label])
        if label_slot
        else label
    )
    children: list["Node | str"] = [label_child]
    if removable:
        children.append(
            Element(
                "button",
                attributes=[
                    ("type", "button"),
                    ("data-pill-remove", ""),
                    ("class", _PILL_REMOVE_CLASS),
                    ("aria-label", "Remove"),
                ],
                children=["×"],
            )
        )

    return Span(attributes=pill_attrs, children=children)


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


# Media for the Flowbite-datepicker year picker (vendored UMD bundle). Declared
# on the YearPicker node so Page() loads it wherever a YearPicker appears.
_YEAR_PICKER_MEDIA = Media(js_external=("datepicker.umd.js",))


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

    The Flowbite-datepicker UMD bundle is declared as ``media`` on the returned
    node, so ``Page()`` loads it automatically.
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
    return Safe(
        f"""<div class="relative inline-block" x-data="{{ pickerOpen: false }}"
     @keydown.escape.window="pickerOpen = false">
    <button type="button"
            x-on:click="pickerOpen = !pickerOpen; $refs.pickerInput._pickerInstance && ($refs.pickerInput._pickerInstance.active ? $refs.pickerInput._pickerInstance.hide() : $refs.pickerInput._pickerInstance.show())"
            class="inline-flex items-center rounded-base px-4 py-2 text-sm font-medium {classes}">
        {label}
        <svg class="w-4 h-4 ms-2 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 10">
            <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 5h12m0 0L9 1m4 4L9 9"/>
        </svg>
    </button>
    <input type="text" x-ref="pickerInput" id="year-picker-input"
           class="absolute opacity-0 pointer-events-none"
           style="width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); border: 0;"
           data-available-years="{years_csv}"
           data-selected-year="{selected}"
           data-url-template="{url_template}">
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {{
    const pickerEl = document.getElementById('year-picker-input');
    if (!pickerEl || pickerEl._pickerInstance) return;

    const selectedYear = pickerEl.dataset.selectedYear;
    const urlTemplate = pickerEl.dataset.urlTemplate;
    const currentYear = new Date().getFullYear();
    const availableYears = new Set(pickerEl.dataset.availableYears
        .split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)));

    const picker = new Datepicker(pickerEl, {{
        pickLevel: 2,
        format: 'yyyy',
        minDate: new Date(1999, 0, 1),
        maxDate: new Date(currentYear, 11, 31),
        autohide: false,
        orientation: 'bottom end',
        showOnClick: false,
        showOnFocus: false,
        beforeShowYear: (date) => ({{ enabled: availableYears.has(date.getFullYear()) }})
    }});
    pickerEl._pickerInstance = picker;

    picker.element.addEventListener('changeDate', (e) => {{
        const year = e.detail.date?.getFullYear();
        if (year && urlTemplate) {{
            window.location.href = urlTemplate.replace('__year__', year);
        }}
    }});

    if (selectedYear) {{
        picker.dates = [new Date(parseInt(selectedYear), 0, 1)];
        picker.update();
    }}
}});
</script>""",
        media=_YEAR_PICKER_MEDIA,
    )


def AddForm(
    form,
    *,
    request,
    fields: Node | SafeText | str | None = None,
    additional_row: Node | SafeText | str = "",
    submit_class: str = "mt-3",
) -> Node:
    """Page body for the generic add/edit form (Python equivalent of add.html).

    `fields` overrides the default ``form.as_div()`` field markup (used by the
    session form, which lays out its fields manually). `additional_row` holds
    extra submit buttons rendered below the main Submit button. `submit_class`
    is applied to the main Submit button (the session form passes "" to match
    its original markup).
    """
    field_markup = fields if fields is not None else Safe(form.as_div())
    submit_attrs = [("class", submit_class)] if submit_class else []

    inner_form = Element(
        "form",
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
) -> Element:
    """Generate a search form with icon, input field, and submit button."""
    return Element(
        "form",
        attributes=[("class", "max-w-md")],
        children=[
            Label(
                attributes=[
                    ("for", "search"),
                    ("class", "block mb-2.5 text-sm font-medium text-heading sr-only"),
                ],
                children=["Search"],
            ),
            Div(
                attributes=[("class", "relative")],
                children=[
                    Safe(
                        '<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none">'
                        '<svg class="w-4 h-4 text-body" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" '
                        'fill="none" viewBox="0 0 24 24">'
                        '<path stroke="currentColor" stroke-linecap="round" stroke-width="2" '
                        'd="m21 21-3.5-3.5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z"/>'
                        "</svg></div>"
                    ),
                    Input(
                        type="search",
                        attributes=[
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
                    Element(
                        "button",
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


def H1(
    children: Children = None,
    badge: str = "",
) -> Element:
    """Heading with optional badge count."""
    children = children or []
    heading_class = "mb-4 text-3xl font-extrabold leading-none tracking-tight text-gray-900 dark:text-white"
    badge_html: Node | str = ""

    if badge:
        heading_class = "flex items-center " + heading_class
        badge_html = Span(
            attributes=[
                (
                    "class",
                    "bg-blue-100 text-blue-800 text-2xl font-semibold me-2 "
                    "px-2.5 py-0.5 rounded-sm dark:bg-blue-200 dark:text-blue-800 ms-2",
                ),
            ],
            children=[badge],
        )

    return Element(
        "h1",
        attributes=[("class", heading_class)],
        children=as_children(children) + ([badge_html] if badge_html else []),
    )


def Modal(
    modal_id: str,
    children: Children = None,
) -> Node:
    """Modal overlay with container. Content (form, buttons) goes in children."""
    children = children or []
    return Div(
        attributes=[
            ("id", modal_id),
            (
                "class",
                "fixed inset-0 bg-black/70 dark:bg-gray-600/50 overflow-y-auto "
                "h-full w-full flex items-center justify-center",
            ),
        ],
        children=[
            Div(
                attributes=[
                    (
                        "class",
                        "relative mx-auto p-5 border-accent border w-full max-w-md "
                        "shadow-lg/50 rounded-md bg-white dark:bg-gray-900",
                    ),
                ],
                children=as_children(children),
            ),
        ],
    )


def TableTd(
    children: Children = None,
) -> Element:
    """Styled table cell."""
    children = children or []
    return Td(
        attributes=[("class", "px-6 py-4 min-w-20-char max-w-20-char")],
        children=as_children(children),
    )


def TableRow(data: dict | list | None = None) -> Element:
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

    cell_elements: list[Node] = []
    for i, cell in enumerate(cells):
        if i == 0:
            cell_elements.append(
                Th(
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

    return Tr(attributes=tr_attrs, children=cell_elements)


def Icon(
    name: str,
    attributes: Attributes | None = None,
) -> Node:
    return Safe(get_icon(name))


def TableHeader(
    children: Children = None,
) -> Element:
    """Table caption."""
    children = children or []
    return Element(
        "caption",
        attributes=[
            (
                "class",
                "p-2 text-lg font-semibold rtl:text-left text-right "
                "text-gray-900 bg-white dark:text-white dark:bg-gray-900",
            ),
        ],
        children=as_children(children),
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
    header_action: Child | None = None,
    page_obj=None,
    elided_page_range=None,
    request=None,
) -> Node:
    """Paginated table. Python equivalent of the old simple_table.html."""
    columns = columns or []
    rows = rows or []

    # Rows/header are stringified into the table markup, so their components'
    # declared Media would be lost; collect it from the nodes first and attach
    # it to the returned node so Page() still emits each cell component's JS
    # (e.g. a <game-status-selector> in a cell).
    media = Media()

    header_html = ""
    if header_action:
        header_node = TableHeader(children=[header_action])
        header_html = str(header_node)
        media = media + collect_media(header_node)

    columns_html = "".join(
        f'<th scope="col" class="px-6 py-3">{conditional_escape(col)}</th>'
        for col in columns
    )
    row_nodes = [TableRow(data=row) for row in rows]
    rows_html = "".join(str(node) for node in row_nodes)
    for node in row_nodes:
        media = media + collect_media(node)

    pagination_html = ""
    if page_obj and elided_page_range:
        pagination_html = _pagination_nav(page_obj, elided_page_range, request)

    return Safe(
        '<div class="shadow-md" hx-boost="false">'
        '<div class="relative overflow-x-auto sm:rounded-t-lg">'
        '<table class="w-full text-sm text-left rtl:text-right text-gray-500 dark:text-gray-400">'
        f"{header_html}"
        '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 '
        'dark:text-gray-400 max-sm:[&_th:not(:first-child):not(:last-child)]:hidden">'
        f"<tr>{columns_html}</tr></thead>"
        '<tbody class="dark:divide-y max-sm:[&_td:not(:first-child):not(:last-child)]:hidden">'
        f"{rows_html}</tbody></table></div>"
        f"{pagination_html}</div>",
        media=media,
    )


def paginated_table_content(
    data: dict,
    *,
    page_obj=None,
    elided_page_range=None,
    request=None,
) -> Node:
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
