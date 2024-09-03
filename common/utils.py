from random import choices
from string import ascii_lowercase
from typing import Any, Callable

from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe


def Popover(
    wrapped_content: str,
    popover_content: str = "",
) -> str:
    id = randomid()
    if popover_content == "":
        popover_content = wrapped_content
    content = f"<span data-popover-target={id}>{wrapped_content}</span>"
    result = mark_safe(
        str(content)
        + render_to_string(
            "cotton/popover.html",
            {
                "id": id,
                "slot": popover_content,
            },
        )
    )
    return result


HTMLAttribute = tuple[str, str]
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
    attributesList = [f'{name} = "{value}"' for name, value in attributes]
    attributesBlob = " ".join(attributesList)
    tag: str = ""
    if tag_name != "":
        tag = f"<a {attributesBlob}>{childrenBlob}</a>"
    elif template != "":
        tag = render_to_string(
            template,
            {name: value for name, value in attributes} | {"slot": "\n".join(children)},
        )
    return mark_safe(tag)


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
):
    return Component(
        template="cotton/button.html", attributes=attributes, children=children
    )


def safe_division(numerator: int | float, denominator: int | float) -> int | float:
    """
    Divides without triggering division by zero exception.
    Returns 0 if denominator is 0.
    """
    try:
        return numerator / denominator
    except ZeroDivisionError:
        return 0


def safe_getattr(obj: object, attr_chain: str, default: Any | None = None) -> object:
    """
    Safely get the nested attribute from an object.

    Parameters:
    obj (object): The object from which to retrieve the attribute.
    attr_chain (str): The chain of attributes, separated by dots.
    default: The default value to return if any attribute in the chain does not exist.

    Returns:
    The value of the nested attribute if it exists, otherwise the default value.
    """
    attrs = attr_chain.split(".")
    for attr in attrs:
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            return default
    return obj


def truncate(input_string: str, length: int = 30, ellipsis: str = "…") -> str:
    return (
        (f"{input_string[:length-len(ellipsis)]}{ellipsis}")
        if len(input_string) > 30
        else input_string
    )


def truncate_with_popover(input_string: str) -> str:
    if (truncated := truncate(input_string)) != input_string:
        print(f"Not the same after: {truncated=}")
        return Popover(wrapped_content=truncated, popover_content=input_string)
    else:
        print("Strings are the same!")
        return input_string


def randomid(seed: str = "", length: int = 10) -> str:
    return seed + "".join(choices(ascii_lowercase, k=length))
