"""Guards for the typography token system (docs/superpowers/specs/2026-07-19-typography-token-system-design.md)."""
from pathlib import Path

import pytest

BASE_CSS = Path(__file__).resolve().parent.parent / "games" / "static" / "base.css"

TOKENS = [
    "text-type-title", "text-type-heading", "text-type-dialog",
    "text-type-subheading", "text-type-section", "text-type-body",
    "text-type-label", "text-type-micro", "text-type-micro-caps",
    "text-type-input",
]


@pytest.mark.parametrize("token", TOKENS)
def test_token_utility_is_generated(token):
    """Each role token compiles to a real utility class in the built CSS.

    base.css is a build artifact — run `make css` after editing input.css.
    """
    assert BASE_CSS.exists(), "run `make css` first"
    css = BASE_CSS.read_text()
    assert f".{token}" in css, f"{token} missing from base.css — is it used anywhere / defined in @theme?"
