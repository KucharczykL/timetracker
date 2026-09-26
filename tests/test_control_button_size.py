"""The compact size and the ghost tone of ControlButton."""

import itertools
import re
from typing import get_args

import pytest

from common.components import (
    COMPACT_SHAPE_CLASSES,
    ButtonShape,
    ControlButton,
    render,
)
from common.components.primitives import SHAPE_CLASSES, control_button_class

COLORS = ("blue", "red", "gray", "green")
VARIANTS = ("filled", "segmented", "outline", "ghost")
SIZES = ("control", "compact")


def _property(token: str) -> tuple[str, str] | None:
    """The (state, property) one utility sets, for the ones that collide."""
    state, _, utility = token.rpartition(":")
    rules = [
        (r"^bg-", "background"),
        (r"^text-type-", "font-size"),
        (r"^text-(?!left|right|center|start|end)", "color"),
        (r"^border-(?!\d|[xytblrse]-)", "border-color"),
        (r"^rounded", "radius"),
        (r"^(p|px|py)-", "padding"),
        (r"^(size|min-h|h)-", "height"),
    ]
    for pattern, name in rules:
        if re.match(pattern, utility):
            return state, name
    return None


@pytest.mark.parametrize(
    "color,variant,size,shape",
    itertools.product(COLORS, VARIANTS, SIZES, get_args(ButtonShape.__value__)),
)
def test_no_string_sets_one_property_twice(color, variant, size, shape):
    classes = control_button_class(
        color=color, variant=variant, size=size, shape=shape
    ).split()
    properties = [found for token in classes if (found := _property(token))]
    assert len(properties) == len(set(properties)), classes


def test_compact_is_a_glyph_square_with_scaled_corners():
    classes = control_button_class(variant="ghost", size="compact").split()
    assert {"size-8", "p-0", "rounded"} <= set(classes)
    assert "min-h-control" not in classes
    assert "rounded-base" not in classes


def test_control_is_the_default_size():
    assert "min-h-control" in control_button_class(variant="ghost").split()


def test_every_shape_has_compact_corners():
    assert set(COMPACT_SHAPE_CLASSES) == set(SHAPE_CLASSES)


def test_a_red_ghost_hovers_danger_and_a_gray_one_does_not():
    red = control_button_class(variant="ghost", color="red", size="compact")
    gray = control_button_class(variant="ghost", color="gray", size="compact")
    assert "hover:bg-danger-soft" in red
    assert "hover:bg-danger-soft" not in gray


def test_compact_ghost_hovers_past_a_highlighted_row():
    classes = control_button_class(variant="ghost", size="compact").split()
    assert "hover:bg-neutral-quaternary-medium" in classes


def test_with_shape_keeps_the_size():
    button = ControlButton(variant="ghost", size="compact")["x"].with_shape("start")
    html = render(button)
    assert "size-8" in html
    assert "rounded-s" in html.split('class="')[1].split('"')[0].split()
