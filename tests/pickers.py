"""Read a rendered `SearchSelect` out of page markup."""

import re

#: A posted field name.
type PostedName = str


def picker(html: str, name: PostedName) -> str:
    """The `<search-select>` posting `name`, whole."""
    match = re.search(
        rf'<search-select\b[^>]*\bname="{re.escape(name)}".*?</search-select>',
        html,
        re.DOTALL,
    )
    assert match, f"no picker named {name}"
    return match.group(0)


def held(html: str, name: PostedName) -> str | None:
    """The value the picker posting `name` holds."""
    pills = re.search(
        r"<div data-search-select-pills=[^>]*>(.*?)</div>",
        picker(html, name),
        re.DOTALL,
    )
    assert pills
    value = re.search(r'value="([^"]*)"', pills.group(1))
    return value.group(1) if value else None


def search_box(picker_html: str) -> str:
    """The picker's search box tag."""
    match = re.search(r"<input\b[^>]*\bdata-search-select-search\b[^>]*>", picker_html)
    assert match
    return match.group(0)
