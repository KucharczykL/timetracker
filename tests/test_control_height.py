"""Guards for the unified control-height scale (#436).

Every interactive row-control floors to one height (min-h-control = 42px, from
the --height-control theme token) so height is font- and container-independent.
See docs/visual-conventions.md.
"""

from pathlib import Path

from common.components import render
from common.components.filters import _NUMBER_FILTER_INPUT_CLASS
from common.components.primitives import CONTROL_SIZE_CLASS, ControlButton
from common.components.search_select import _CONTAINER_CLASS
from games.forms import INPUT_CLASS, SELECT_CLASS

REPO = Path(__file__).resolve().parent.parent
BASE_CSS = REPO / "games" / "static" / "base.css"

# The size-governing class constants every row-control draws its height from.
HEIGHT_BEARING_CONSTANTS = {
    "CONTROL_SIZE_CLASS": CONTROL_SIZE_CLASS,
    "INPUT_CLASS": INPUT_CLASS,
    "SELECT_CLASS": SELECT_CLASS,
    "SearchSelect._CONTAINER_CLASS": _CONTAINER_CLASS,
    "_NUMBER_FILTER_INPUT_CLASS": _NUMBER_FILTER_INPUT_CLASS,
}


def test_height_token_is_generated():
    """min-h-control compiles into the built CSS (from --height-control in @theme).

    base.css is a build artifact — run `make css` after editing input.css.
    """
    assert BASE_CSS.exists(), "run `make css` first"
    assert ".min-h-control" in BASE_CSS.read_text(), (
        "min-h-control missing from base.css — is --height-control in @theme, "
        "and the utility used anywhere?"
    )


def test_size_constants_use_the_height_token():
    for name, value in HEIGHT_BEARING_CONSTANTS.items():
        assert "min-h-control" in value, f"{name} must floor to min-h-control"
        # The old padding-based heights must not creep back onto a row-control.
        assert "py-2.5" not in value, f"{name} reintroduced the 46px form-field padding"


def test_control_height_is_container_independent():
    # No @container step on the shared height: a control is 42px in every row,
    # regardless of any @container ancestor (the old cross-row 38-vs-42 bug).
    assert "@md:" not in CONTROL_SIZE_CLASS


def test_button_variants_emit_the_height_token():
    for variant in ("filled", "segmented", "outline", "ghost"):
        assert "min-h-control" in render(ControlButton(variant=variant)["x"]), variant


# The old 46px form-field vertical padding. Its reappearance on a control means
# that control fell off the shared-height scale. Multiline textarea is the one
# legitimate exception (marked `control-ok` inline).
_REGRESSION_PADDING = "py-2.5"
_GUARDED = [
    REPO / "common" / "components",
    REPO / "games" / "forms.py",
    REPO / "games" / "views",
]


def _py_files():
    for path in _GUARDED:
        if path.is_file():
            yield path
        else:
            yield from path.rglob("*.py")


def test_no_form_field_padding_on_controls():
    offenders = []
    for f in _py_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "control-ok" in line:
                continue
            if _REGRESSION_PADDING in line:
                offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "py-2.5 on a control — use min-h-control (or add `# control-ok: reason` "
        "for a genuine multiline exception):\n" + "\n".join(offenders)
    )
