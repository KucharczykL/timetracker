"""ControlButton sizes and ghost tones."""

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
SIZES = ("control", "compact", "row")


def _property(token: str) -> tuple[str, str] | None:
    """The (state, property) a utility sets."""
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


def _tag_with(html: str, marker: str) -> str:
    position = html.index(marker)
    return html[html.rindex("<", 0, position) : html.index(">", position)]


def _compact_ghost(tag: str) -> bool:
    return all(token in tag for token in ("size-8", "rounded", "bg-transparent"))


def test_the_clear_button_is_a_compact_ghost():
    from common.components import SearchSelect

    html = str(SearchSelect(name="game", selected=[{"value": "1", "label": "One"}]))
    tag = _tag_with(html, "data-search-select-clear")
    assert _compact_ghost(tag)
    assert "peer-disabled:hidden" in tag


def test_row_actions_are_compact_ghosts_in_the_row():
    from common.components import FilterSelect, PresetSelect

    filter_html = str(FilterSelect(field_name="status", options=[("f", "Finished")]))
    include = _tag_with(filter_html, 'data-search-select-action="include"')
    assert "size-6.5" in include and "-my-0.75" in include
    assert "rounded" in include and "bg-transparent" in include
    assert 'tabindex="-1"' in include
    preset_html = str(PresetSelect(api_url="/api/presets/", mode="games"))
    remove = _tag_with(preset_html, 'data-search-select-action="delete"')
    assert "size-6.5" in remove and "hover:bg-danger-soft" in remove


def test_the_comparison_remove_is_a_red_compact_ghost():
    from common.components.filters import comparison_row_template

    html = str(comparison_row_template([]))
    tag = _tag_with(html, "data-fc-remove")
    assert _compact_ghost(tag) and "hover:bg-danger-soft" in tag


def test_the_year_toggle_is_a_control_button():
    from common.components import YearPicker

    chosen = _tag_with(
        str(YearPicker(2024, (2024,), "/y/__year__/")), "data-year-picker-toggle"
    )
    empty = _tag_with(
        str(YearPicker(None, (2024,), "/y/__year__/")), "data-year-picker-toggle"
    )
    assert "min-h-control" in chosen and "solid-brand" in chosen
    assert "bg-neutral-primary-medium" in empty


def test_row_is_a_26px_glyph_square_with_the_compact_tone():
    row = control_button_class(variant="ghost", size="row").split()
    compact = control_button_class(variant="ghost", size="compact").split()
    assert {"size-6.5", "p-0", "rounded"} <= set(row)
    assert set(row) - {"size-6.5"} == set(compact) - {"size-8"}
