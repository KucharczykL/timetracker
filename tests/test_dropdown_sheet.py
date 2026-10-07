"""The narrow-viewport sheet a dropdown may carry."""

import re
from zoneinfo import ZoneInfo

import pytest

from common.components import (
    DatePicker,
    DateRangePicker,
    DateTimePicker,
    Dropdown,
)
from common.components.custom_elements import BottomSheet
from common.components.primitives import Button, Div, YearPicker
from common.components.quick_filter import QuickFilterBar
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
SHEET = re.compile(r"<dialog[^>]*data-dropdown-sheet[^>]*>")
SENTINEL = re.compile(r"<span[^>]*data-dropdown-narrow[^>]*>")


def sheets(html: str) -> list[str]:
    return SHEET.findall(html)


def sheet_title(html: str) -> str:
    match = re.search(r"<h2[^>]*data-dropdown-sheet-title[^>]*>([^<]*)</h2>", html)
    assert match, html
    return match.group(1)


def dropdown(**kwargs: object) -> str:
    return str(
        Dropdown(
            trigger_element=Button(type="button")["Open"],
            target_element=Div()["panel"],
            id="example",
            **kwargs,  # type: ignore[arg-type]
        )
    )


def test_a_dropdown_without_a_title_carries_no_sheet():
    html = dropdown()
    assert sheets(html) == []
    assert not SENTINEL.search(html)


def test_a_titled_dropdown_carries_one_sheet_and_its_sentinel():
    html = dropdown(sheet_title="Day")
    [dialog] = sheets(html)
    assert "data-menu" not in dialog
    assert "data-bottom-sheet" not in dialog
    assert "aria-labelledby" not in dialog
    assert sheet_title(html) == "Day"
    assert ' id="' not in re.search(r"<h2[^>]*>", html).group(0)  # type: ignore[union-attr]
    assert "hidden max-sm:block" in SENTINEL.search(html).group(0)  # type: ignore[union-attr]


def test_the_section_sheet_keeps_its_own_shape():
    html = str(
        BottomSheet(
            trigger_element=Button(type="button")["Sections"],
            title="Sections",
            children=["body"],
            id="settings-sheet",
        )
    )
    assert sheets(html) == []
    assert "max-h-[min(80dvh,32rem)]" in html


@pytest.mark.parametrize(
    "picker",
    [
        DatePicker(presentation=PRESENTATION, label="Started", name="started"),
        DateTimePicker(presentation=PRESENTATION, label="Started", name="started"),
        DateRangePicker(
            presentation=PRESENTATION, label="Started", input_name_prefix="started"
        ),
    ],
    ids=["date", "datetime", "range"],
)
def test_each_calendar_carries_a_sheet_titled_by_its_label(picker):
    html = str(picker)
    assert len(sheets(html)) == 1
    assert sheet_title(html) == "Started"


def test_the_year_picker_carries_a_sheet():
    html = str(
        YearPicker(year=2024, available_years=(2024,), url_template="/stats/__year__/")
    )
    assert len(sheets(html)) == 1
    assert sheet_title(html) == "Year"


@pytest.mark.django_db
def test_every_quick_facet_carries_a_sheet():
    html = str(QuickFilterBar(mode="sessions", presentation=PRESENTATION))
    facets = re.findall(r"<drop-down[^>]*data-quick-facet", html)
    assert facets
    assert len(sheets(html)) == len(facets)


@pytest.mark.parametrize(
    ("picker", "has_close"),
    [
        (DatePicker(presentation=PRESENTATION, label="Day", name="day"), True),
        (DateTimePicker(presentation=PRESENTATION, label="Start", name="start"), True),
        (
            DateRangePicker(
                presentation=PRESENTATION, label="Day", input_name_prefix="day"
            ),
            False,
        ),
    ],
    ids=["date", "datetime", "range"],
)
def test_a_single_date_calendar_offers_close_in_the_sheet_alone(picker, has_close):
    html = str(picker)
    close = re.search(
        r'<span class="hidden group-data-\[dropdown-host=sheet\]/dropdown:contents">'
        r"<button[^>]*data-date-range-close",
        html,
    )
    assert bool(close) is has_close
    assert html.count("data-date-range-close") == int(has_close)


@pytest.mark.django_db
def test_every_quick_facet_applies_the_bar():
    html = str(QuickFilterBar(mode="sessions", presentation=PRESENTATION))
    facets = re.findall(r"<drop-down[^>]*data-quick-facet", html)
    applies = re.findall(
        r'<button type="submit"[^>]*data-(?:quick-facet|date-range)-apply', html
    )
    assert len(applies) == len(facets)
    assert html.count("data-date-range-apply") == 1
