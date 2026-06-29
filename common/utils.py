from datetime import date
from functools import wraps
from typing import Any, Generator, TypeVar
from urllib.parse import urlencode

from django.core.paginator import Page, Paginator
from django.http import HttpRequest
from django.shortcuts import redirect


def paginate(request: HttpRequest, queryset, per_page: int = 10):
    """Standard list-view pagination.

    Reads ``page`` and ``limit`` from the query string (``limit=0`` disables
    pagination) and returns ``(object_list, page_obj, elided_page_range)`` ready
    to hand to ``paginated_table_content``.
    """
    page_number = request.GET.get("page", 1)
    limit = int(request.GET.get("limit", per_page))
    object_list = queryset
    page_obj: Page | None = None
    if limit != 0:
        page_obj = Paginator(queryset, limit).get_page(page_number)
        object_list = page_obj.object_list
    elided_page_range = (
        page_obj.paginator.get_elided_page_range(page_number, on_each_side=1, on_ends=1)
        if page_obj
        else None
    )
    return object_list, page_obj, elided_page_range


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


def truncate_(input_string: str, length: int = 30, ellipsis: str = "…") -> str:
    return (
        (f"{input_string[: length - len(ellipsis)].rstrip()}{ellipsis}")
        if len(input_string) > length
        else input_string
    )


def truncate(
    input_string: str, length: int = 30, ellipsis: str = "…", endpart: str = ""
) -> str:
    max_content_length = length - len(endpart)
    if max_content_length < 0:
        raise ValueError("Length cannot be shorter than the length of endpart.")

    if len(input_string) > max_content_length:
        return f"{input_string[: max_content_length - len(ellipsis)].rstrip()}{ellipsis}{endpart}"

    return (
        f"{input_string}{endpart}"
        if len(input_string) + len(endpart) <= length
        else f"{input_string[: length - len(ellipsis) - len(endpart)].rstrip()}{ellipsis}{endpart}"
    )


T = TypeVar("T", str, int, date)


def generate_split_ranges(
    value_list: list[T], split_points: list[T]
) -> Generator[tuple[T, T], None, None]:
    for x in range(0, len(split_points) + 1):
        if x == 0:
            start = 0
        elif x >= len(split_points):
            start = value_list.index(split_points[x - 1]) + 1
        else:
            start = value_list.index(split_points[x - 1]) + 1
        try:
            end = value_list.index(split_points[x])
        except IndexError:
            end = len(value_list)
        yield (value_list[start], value_list[end - 1])


def format_float_or_int(number: int | float):
    return int(number) if float(number).is_integer() else f"{number:03.2f}"


def label_with_details(name: str, *details: object, separator: str = ", ") -> str:
    """Build a ``"Name (detail, detail)"`` label from a name and optional details.

    Falsy details (``None``, ``""``, ``0``) are dropped; the rest are stringified
    and joined with ``separator`` inside parentheses. With no details remaining,
    the bare ``name`` is returned without parentheses.
    """
    present = [str(detail) for detail in details if detail]
    return f"{name} ({separator.join(present)})" if present else name


def redirect_to(default_view: str, *default_args):
    """
    A decorator that redirects the user back to the referring page or a default view if no 'next' parameter is provided.

    :param default_view: The name of the default view to redirect to if 'next' is missing.
    :param default_args: Any arguments required for the default view.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args, **kwargs):
            next_url = request.GET.get("next")
            if not next_url:
                from django.urls import (
                    reverse,  # Import inside function to avoid circular imports
                )

                next_url = reverse(default_view, args=default_args)

            # Execute the original view logic for its side effects, then
            # redirect to `next_url` instead of returning its response.
            view_func(request, *args, **kwargs)
            return redirect(next_url)

        return wrapped_view

    return decorator


def add_next_param_to_url(url: str, nexturl: str) -> str:
    return f"{url}?{urlencode({'next': nexturl})}"
