from random import choices
from string import ascii_lowercase
from typing import Any

from django.template.loader import render_to_string
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
