from random import choices as random_choices
from string import ascii_lowercase
from typing import Any, Callable

from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

HTMLAttribute = tuple[str, str | int | bool]
HTMLTag = str


def Component(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    template: str = "",
    tag_name: str = "",
) -> HTMLTag:
    if not tag_name and not template:
        raise ValueError("One of template or tag_name is required.")
    if isinstance(children, str):
        children = [children]
    childrenBlob = "\n".join(children)
    if len(attributes) == 0:
        attributesBlob = ""
    else:
        attributesList = [f'{name}="{value}"' for name, value in attributes]
        # make attribute list into a string
        # and insert space between tag and attribute list
        attributesBlob = f" {" ".join(attributesList)}"
    tag: str = ""
    if tag_name != "":
        tag = f"<{tag_name}{attributesBlob}>{childrenBlob}</{tag_name}>"
    elif template != "":
        tag = render_to_string(
            template,
            {name: value for name, value in attributes}
            | {"slot": mark_safe("\n".join(children))},
        )
    return mark_safe(tag)


def randomid(seed: str = "", length: int = 10) -> str:
    return seed + "".join(random_choices(ascii_lowercase, k=length))


def Popover(
    popover_content: str,
    wrapped_content: str = "",
    children: list[HTMLTag] = [],
    attributes: list[HTMLAttribute] = [],
) -> str:
    if not wrapped_content and not children:
        raise ValueError("One of wrapped_content or children is required.")
    id = randomid()
    return Component(
        attributes=attributes
        + [
            ("id", id),
            ("wrapped_content", wrapped_content),
            ("popover_content", popover_content),
        ],
        children=children,
        template="cotton/popover.html",
    )


def A(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    url: str | Callable[..., Any] = "",
):
    """
    Returns the HTML tag "a".
    "url" can either be:
        - URL (string)
        - path name passed to reverse() (string)
        - function
    """
    additional_attributes = []
    if url:
        if type(url) is str:
            try:
                url_result = reverse(url)
            except NoReverseMatch:
                url_result = url
        elif callable(url):
            url_result = url()
        else:
            raise TypeError("'url' is neither str nor function.")
        additional_attributes = [("href", url_result)]
    return Component(
        tag_name="a", attributes=attributes + additional_attributes, children=children
    )


def Button(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    size: str = "base",
    icon: bool = False,
    color: str = "blue",
):
    return Component(
        template="cotton/button.html",
        attributes=attributes + [("size", size), ("icon", icon), ("color", color)],
        children=children,
    )


def Div(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
):
    return Component(tag_name="div", attributes=attributes, children=children)


def Icon(
    name: str,
    attributes: list[HTMLAttribute] = [],
):
    return Component(template=f"cotton/icon/{name}.html", attributes=attributes)
