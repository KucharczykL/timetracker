"""Read a rendered `SearchSelect` out of page markup."""

import re

from common.components.unset_field import PostedName

#: One `<search-select>`'s markup.
type PickerMarkup = str


def picker(html: str, name: PostedName) -> PickerMarkup:
    """The `<search-select>` posting `name`, whole."""
    match = re.search(
        rf'<search-select\b[^>]*\bname="{re.escape(name)}".*?</search-select>',
        html,
        re.DOTALL,
    )
    assert match, f"no picker named {name}"
    return match.group(0)


def held(html: str, name: PostedName) -> str | None:
    """A single-select's posted value; "" for none."""
    pills = re.search(
        r"<div data-search-select-pills=[^>]*>(.*?)</div>",
        picker(html, name),
        re.DOTALL,
    )
    assert pills
    value = re.search(r'value="([^"]*)"', pills.group(1))
    return value.group(1) if value else None


def search_box(picker_html: PickerMarkup) -> str:
    """The picker's search box tag."""
    match = re.search(r"<input\b[^>]*\bdata-search-select-search\b[^>]*>", picker_html)
    assert match
    return match.group(0)
