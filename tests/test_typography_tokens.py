"""Guards for the typography token system (docs/superpowers/specs/2026-07-19-typography-token-system-design.md)."""

import re
from pathlib import Path

import pytest

from common.components import render
from common.components.primitives import (
    H1,
    H2,
    H3,
    DIALOG_TITLE_CLASS,
    MICRO_LABEL_CLASS,
)

BASE_CSS = Path(__file__).resolve().parent.parent / "games" / "static" / "base.css"

TOKENS = [
    "text-type-title",
    "text-type-heading",
    "text-type-dialog",
    "text-type-subheading",
    "text-type-section",
    "text-type-body",
    "text-type-label",
    "text-type-micro",
    "text-type-micro-caps",
    "text-type-input",
]


@pytest.mark.parametrize("token", TOKENS)
def test_token_utility_is_generated(token):
    """Each role token compiles to a real utility class in the built CSS.

    base.css is a build artifact — run `make css` after editing input.css.
    """
    assert BASE_CSS.exists(), "run `make css` first"
    css = BASE_CSS.read_text()
    assert f".{token}" in css, (
        f"{token} missing from base.css — is it used anywhere / defined in @theme?"
    )


def test_heading_builders_emit_tokens():
    assert "text-type-title" in render(H1()["x"])
    assert "text-type-heading" in render(H2()["x"])
    assert "text-type-subheading" in render(H3()["x"])


def test_named_constants_use_tokens():
    assert DIALOG_TITLE_CLASS.split()[0] == "text-type-dialog"
    assert MICRO_LABEL_CLASS.split()[0] == "text-type-micro-caps"
    # size utility removed from both:
    for raw in ("text-2xl", "text-xs"):
        assert raw not in DIALOG_TITLE_CLASS and raw not in MICRO_LABEL_CLASS


REPO = Path(__file__).resolve().parent.parent
GUARDED = [
    REPO / "common" / "components",
    REPO / "common" / "layout.py",
    REPO / "games" / "forms.py",
    REPO / "games" / "views",
]
# Raw font-size utilities (with optional variant prefixes like sm: @md:) —
# the type system owns size via text-type-*. font-* weights stay legal.
RAW_SIZE = re.compile(
    r"(?<![\w-])(?:[a-z@\[\]:.-]+:)?text-(?:xs|sm|base|lg|xl|\dxl|\[[^\]]+\])(?![\w-])"
)


def _py_files():
    for path in GUARDED:
        if path.is_file():
            yield path
        else:
            yield from path.rglob("*.py")


def test_no_raw_size_utilities_in_components():
    offenders = []
    for f in _py_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "# type-ok" in line:
                continue
            if RAW_SIZE.search(line):
                offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "raw size utilities — use text-type-* (or add `# type-ok: reason`):\n"
        + "\n".join(offenders)
    )
