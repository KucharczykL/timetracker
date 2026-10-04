"""Floating panels open in the top layer."""

import re
from collections.abc import Callable
from typing import NamedTuple
from zoneinfo import ZoneInfo

import pytest

from common.components import (
    BottomSheet,
    ControlButton,
    DatePicker,
    DropdownActionItem,
    DropdownSubmenuItem,
    FilterSelect,
    Popover,
    SearchSelect,
    Span,
    TruncatedText,
    YearPicker,
    render,
)
from common.components.date_range_picker import DateRangeCalendar
from common.components.search_select import ComboboxDropdown
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


class FloatingPanel(NamedTuple):
    build: Callable[[], str]
    #: An attribute only the panel's opening tag carries.
    hook: str


FLOATING_PANELS = {
    "dropdown": FloatingPanel(
        lambda: str(ComboboxDropdown(label="Pick", content=Span()["x"], id="pick")),
        'data-menu=""',
    ),
    "submenu": FloatingPanel(
        lambda: str(
            DropdownSubmenuItem("More", items=[DropdownActionItem()["Deep"]], id="more")
        ),
        'data-menu=""',
    ),
    "tooltip": FloatingPanel(
        lambda: str(Popover("hint", wrapped_content="word")),
        "data-pop-over-panel",
    ),
    "truncated tooltip": FloatingPanel(
        lambda: str(TruncatedText("A long name", reveal="always")),
        "data-pop-over-panel",
    ),
    "year picker": FloatingPanel(
        lambda: str(YearPicker(2024, (2024,), "/y/__year__/")),
        "data-year-picker-popup",
    ),
    "calendar popup": FloatingPanel(
        lambda: str(DateRangeCalendar(input_name_prefix="day")),
        "data-date-range-calendar",
    ),
    "date picker": FloatingPanel(
        lambda: str(DatePicker(presentation=PRESENTATION, label="Day", name="day")),
        "data-date-range-calendar",
    ),
    "inline combobox": FloatingPanel(
        lambda: str(SearchSelect(name="game", search_url="/s/")),
        "data-search-select-panel",
    ),
    "filter field": FloatingPanel(
        lambda: str(FilterSelect(field_name="type", options=[("g", "Game")])),
        "data-search-select-panel",
    ),
}


def _opening_tags(html: str, hook: str) -> list[str]:
    return re.findall(rf"<div[^>]*{hook}[^>]*>", html)


@pytest.mark.parametrize("site", FLOATING_PANELS)
def test_a_floating_panel_is_a_hidden_manual_popover(site):
    panel = FLOATING_PANELS[site]
    [tag, *_nested] = _opening_tags(panel.build(), panel.hook)

    assert 'popover="manual"' in tag
    assert re.search(r"\bhidden\b", tag)
    [classes] = re.findall(r'class="([^"]*)"', tag) or [""]
    assert not {"absolute", "isolate"} & set(classes.split())
    assert not re.search(r"(^|\s)z-(\d+|\[[^\]]*\])(\s|$)", classes)


def test_the_static_calendar_flows_in_its_panel():
    [tag] = _opening_tags(
        str(DateRangeCalendar(input_name_prefix="day", static=True)),
        "data-date-range-calendar",
    )

    assert "popover" not in tag
    assert "hidden" not in tag


def test_the_bottom_sheet_is_a_dialog_not_a_popover():
    html = render(
        BottomSheet(
            trigger_element=ControlButton()["Open"].as_element(),
            title="Sections",
            children=Span()["body"],
            id="sheet",
        )
    )
    [dialog] = re.findall(r"<dialog[^>]*>", html)

    assert "popover" not in dialog
