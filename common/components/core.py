"""Escaping core: the Component builder and its memoised renderer."""

import hashlib
from functools import lru_cache

from django.utils.html import escape
from django.utils.safestring import SafeText, mark_safe


HTMLAttribute = tuple[str, str | int | bool]


HTMLTag = str


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
