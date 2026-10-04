"""Every floating panel opens in the top layer."""

import re

import pytest

from common.components import Popover, SearchSelect, Span, YearPicker
from common.components.date_range_picker import DateRangeCalendar
from common.components.search_select import ComboboxDropdown

FLOATING_PANELS = {
    "dropdown": (
        lambda: str(ComboboxDropdown(label="Pick", content=Span()["x"], id="pick")),
        'data-menu=""',
    ),
    "tooltip": (
        lambda: str(Popover("hint", wrapped_content="word")),
        "data-pop-over-panel",
    ),
    "year picker": (
        lambda: str(YearPicker(2024, (2024,), "/y/__year__/")),
        "data-year-picker-popup",
    ),
    "calendar popup": (
        lambda: str(DateRangeCalendar(input_name_prefix="day")),
        "data-date-range-calendar",
    ),
    "inline combobox": (
        lambda: str(SearchSelect(name="game", search_url="/s/")),
        "data-search-select-panel",
    ),
}


def _opening_tag(html: str, hook: str) -> str:
    [tag] = re.findall(rf"<div[^>]*{hook}[^>]*>", html)
    return tag


@pytest.mark.parametrize("site", FLOATING_PANELS)
def test_a_floating_panel_is_a_hidden_manual_popover(site):
    build, hook = FLOATING_PANELS[site]
    tag = _opening_tag(build(), hook)

    assert 'popover="manual"' in tag
    assert re.search(r"\bhidden\b", tag)
    assert not re.search(r'class="[^"]*\b(absolute|z-\d+)\b', tag)


def test_the_static_calendar_flows_in_its_panel():
    tag = _opening_tag(
        str(DateRangeCalendar(input_name_prefix="day", static=True)),
        "data-date-range-calendar",
    )

    assert "popover" not in tag
    assert "hidden" not in tag
