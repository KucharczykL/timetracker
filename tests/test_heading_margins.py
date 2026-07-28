"""Guard for docs/visual-conventions.md §3: parents own spacing via ``gap``;
components never bake margins.

Headings are the case that drifted. §7's original call had the H1/H2/H3 builders
bake ``mb-2`` and ``PageHeading`` bake ``mb-4``, which contradicted §3 outright
and produced real defects: a baked margin inflates the flex item in an
``items-center`` row, so a heading beside a button centred half a margin high,
and pages whose parent already declared a ``gap`` rendered double-spaced.

Only the heading element's **own** class is checked. Margin utilities on inner
nodes are legitimate — the badge's ``me-2 ms-2`` spaces it from the title text
inside the heading, which is internal layout, not the heading pushing away the
content below it.
"""

import re

import pytest

from common.components import render
from common.components.primitives import (
    DIALOG_TITLE_CLASS,
    H1,
    H2,
    H3,
    DialogTitle,
    PageHeading,
)

# Any margin utility, with optional variant prefix (sm:, @md:, dark:) and
# optional negative sign: m-1, mb-2, -mt-1, @md:my-4, ms-auto …
MARGIN_UTILITY = re.compile(
    r"(?<![\w-])(?:[a-z@\[\]:.-]+:)?-?m[trblxyse]?-(?:\[[^\]]+\]|[\w.]+)(?![\w-])"
)


def own_class(html: str, tag: str) -> str:
    """The class attribute of the outermost ``tag`` in ``html``."""
    match = re.search(rf"<{tag}\b[^>]*>", html)
    assert match, f"no <{tag}> in {html[:120]}"
    class_match = re.search(r'class="([^"]*)"', match.group(0))
    return class_match.group(1) if class_match else ""


def assert_no_baked_margin(html: str, tag: str, label: str) -> None:
    classes = own_class(html, tag)
    offenders = MARGIN_UTILITY.findall(classes)
    assert not offenders, (
        f"{label} bakes a margin ({', '.join(offenders)}) in its own class "
        f"{classes!r} — give the parent a `gap` instead "
        f"(docs/visual-conventions.md §3)."
    )


@pytest.mark.parametrize(
    ("builder", "tag", "label"),
    [
        (H1, "h1", "H1"),
        (H2, "h2", "H2"),
        (H3, "h3", "H3"),
    ],
)
def test_heading_builders_bake_no_margin(builder, tag, label):
    assert_no_baked_margin(render(builder()["Title"]), tag, label)


def test_page_heading_bakes_no_margin():
    assert_no_baked_margin(render(PageHeading(["Title"])), "h1", "PageHeading")


def test_page_heading_with_badge_bakes_no_margin():
    """The badge variant switches the heading to a flex row — the case where a
    baked margin skewed vertical centring against a sibling button."""
    assert_no_baked_margin(
        render(PageHeading(["Title"], badge="3")), "h1", "PageHeading(badge=…)"
    )


def test_dialog_title_bakes_no_margin():
    assert_no_baked_margin(render(DialogTitle(["Title"])), "h1", "DialogTitle")
    assert not MARGIN_UTILITY.findall(DIALOG_TITLE_CLASS)


def test_guard_detects_a_reintroduced_margin():
    """The regex must actually catch the utilities that were removed here, or this
    whole file passes vacuously."""
    for reintroduced in ("mb-2", "mb-4", "@md:mt-6", "-mb-1", "my-2", "ms-auto"):
        assert MARGIN_UTILITY.findall(f"text-type-title {reintroduced}"), reintroduced


def test_guard_ignores_non_margin_classes():
    """Utilities that merely start with m must not trip it."""
    for benign in ("min-h-control", "max-w-7xl", "mask-none", "text-type-title"):
        assert not MARGIN_UTILITY.findall(benign), benign
