import unicodedata
from datetime import date
from typing import TYPE_CHECKING, Any, Generator, NamedTuple, TypeVar

from django.core.paginator import Page, Paginator

if TYPE_CHECKING:
    # Type-only import: common/ is the lower layer and must not depend on games/
    # at runtime. paginate() only duck-reads find.page / find.per_page.
    from games.filters import FindFilter


def paginate(queryset, find: "FindFilter"):
    """Standard list-view pagination, driven by a resolved ``FindFilter``.

    Slices ``queryset`` to ``find.page`` / ``find.per_page`` and returns
    ``(object_list, page_obj, elided_page_range)`` ready to hand to
    ``paginated_table_content``. ``find.per_page == 0`` disables pagination —
    the whole queryset comes back with ``page_obj=None`` (no nav rendered).
    """
    object_list = queryset
    page_obj: Page | None = None
    if find.per_page != 0:
        page_obj = Paginator(queryset, find.per_page).get_page(find.page)
        object_list = page_obj.object_list
    elided_page_range = (
        page_obj.paginator.get_elided_page_range(find.page, on_each_side=1, on_ends=1)
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


def _rstrip_boundary(text: str) -> str:
    """Trim trailing whitespace and punctuation/symbols so a truncated string
    never ends on a dangling separator (space, dash, colon, …) before the
    ellipsis. Covers ASCII hyphens and Unicode en/em dashes alike."""
    while text and (text[-1].isspace() or unicodedata.category(text[-1])[0] in "PS"):
        text = text[:-1]
    return text


def truncate_(input_string: str, length: int = 30, ellipsis: str = "…") -> str:
    return (
        (f"{_rstrip_boundary(input_string[: length - len(ellipsis)])}{ellipsis}")
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
        return f"{_rstrip_boundary(input_string[: max_content_length - len(ellipsis)])}{ellipsis}{endpart}"

    return (
        f"{input_string}{endpart}"
        if len(input_string) + len(endpart) <= length
        else f"{_rstrip_boundary(input_string[: length - len(ellipsis) - len(endpart)])}{ellipsis}{endpart}"
    )


class Truncation(NamedTuple):
    display: str
    was_truncated: bool


def truncate_info(
    input_string: str, length: int = 30, ellipsis: str = "…", endpart: str = ""
) -> Truncation:
    """Truncate like :func:`truncate`, but also report whether content was cut.

    ``was_truncated`` is only True when characters of ``input_string`` were
    dropped — appending ``endpart`` alone does not count.
    """
    display = truncate(input_string, length, ellipsis, endpart)
    return Truncation(display, was_truncated=display != f"{input_string}{endpart}")


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
