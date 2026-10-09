"""The narrow-viewport sheet a dropdown may carry."""

import re
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from html_answers import sheetless_dropdown_faults

from common.components import (
    ControlButton,
    DatePicker,
    DateRangePicker,
    DateTimePicker,
    Dropdown,
    DropdownSubmenuItem,
    RowActionMenu,
    SelectDropdown,
    SplitButtonDropdown,
)
from common.components.custom_elements import (
    SHEET_ATTRIBUTES,
    SHEET_HOST_VALUE,
    BottomSheet,
    ButtonDropdown,
    SelectOption,
    SheetSpec,
    _assemble,
)
from common.components.primitives import Button, Div, YearPicker
from common.components.quick_filter import QUICK_FACETS, QuickFilterBar
from common.components.search_select import ComboboxDropdown
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
    kwargs.setdefault("sheet", SheetSpec("Example"))
    return str(
        Dropdown(
            trigger_element=Button(type="button")["Open"],
            target_element=Div()["panel"],
            id="example",
            **kwargs,  # type: ignore[arg-type]
        )
    )


def test_a_dropdown_without_a_sheet_is_refused_outside_the_sheet_behavior():
    with pytest.raises(ValueError):
        _assemble(
            Button(type="button")["Open"],
            Div()["panel"],
            id="example",
            placement="bottom-start",
            submenu=False,
            wrapper_class="relative inline-flex",
            sheet=None,
        )


#: Each builder's sheet title, from the site that states it.
SHEET_TITLE_SITES = {
    "row action menu": lambda: RowActionMenu([], label="Game actions", id="row"),
    "button dropdown": lambda: ButtonDropdown(
        label="Acts", items=[], id="acts", aria_label="Model"
    ),
    "button dropdown label": lambda: ButtonDropdown(label="Acts", items=[], id="acts"),
    "split button": lambda: SplitButtonDropdown(
        primary=ControlButton()["Add"],
        items=[],
        id="split",
        aria_label="More ways to add",
    ),
    "select dropdown": lambda: SelectDropdown(
        current_label="Played",
        options=[SelectOption("p", "Played", True)],
        id="status",
        patch_url="/api/games/1/status",
        body_key="status",
        event="status-changed",
        csrf="t",
        sheet_title="Status",
    ),
    "submenu item": lambda: DropdownSubmenuItem("More", items=[], id="more"),
    "combobox": lambda: ComboboxDropdown(
        label="Game", content=Div()["x"], id="game", sheet=SheetSpec("Game")
    ),
}

SHEET_TITLES = {
    "row action menu": "Game actions",
    "button dropdown": "Model",
    "button dropdown label": "Acts",
    "split button": "More ways to add",
    "select dropdown": "Status",
    "submenu item": "More",
    "combobox": "Game",
}


@pytest.mark.parametrize("site", SHEET_TITLE_SITES)
def test_each_builder_titles_its_sheet(site):
    html = str(SHEET_TITLE_SITES[site]())
    assert sheet_title(html) == SHEET_TITLES[site]


def test_a_titled_dropdown_carries_one_sheet_and_its_sentinel():
    html = dropdown(sheet=SheetSpec("Day"))
    [dialog] = sheets(html)
    assert "data-menu" not in dialog
    assert "data-bottom-sheet" not in dialog
    assert "aria-labelledby" not in dialog
    assert sheet_title(html) == "Day"
    assert ' id="' not in re.search(r"<h2[^>]*>", html).group(0)  # type: ignore[union-attr]
    assert "hidden max-sm:block" in SENTINEL.search(html).group(0)  # type: ignore[union-attr]


HEIGHT = "h-[min(90dvh,calc(var(--sheet-visible-height,100dvh)*0.9))]"


def test_a_dropdown_sheet_rises_above_the_keyboard():
    html = dropdown(sheet=SheetSpec("Day"))
    assert "mb-[var(--sheet-keyboard-inset,0px)]" in html
    assert f"max-{HEIGHT}" in html


def test_a_steady_dropdown_sheet_fills_the_screen():
    html = dropdown(sheet=SheetSpec("Day"))
    assert (
        "group-data-[sheet-steady]/sheet:h-[var(--sheet-visible-height,100dvh)]" in html
    )
    assert "group-data-[sheet-steady]/sheet:max-h-none" in html


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
@pytest.mark.parametrize("mode", sorted(QUICK_FACETS))
def test_every_quick_facet_carries_a_sheet(mode):
    html = str(QuickFilterBar(mode=mode, presentation=PRESENTATION))
    own = OwnSheets()
    own.feed(html)
    facets = [count for is_facet, count in own.hosts if is_facet]
    assert facets
    assert facets == [1] * len(facets)


class OwnSheets(HTMLParser):
    """Each ``<drop-down>``'s own sheet count."""

    def __init__(self) -> None:
        super().__init__()
        #: Open hosts: facet flag, own sheets.
        self.stack: list[list] = []
        self.hosts: list[tuple[bool, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        if tag == "drop-down":
            self.stack.append(["data-quick-facet" in names, 0])
        elif tag == "dialog" and SHEET_ATTRIBUTES["sheet"] in names:
            self.stack[-1][1] += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "drop-down":
            is_facet, count = self.stack.pop()
            self.hosts.append((is_facet, count))


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
    wrapper = re.search(
        r'<span class="([^"]*)"><button[^>]*data-date-range-close', html
    )
    assert bool(wrapper) is has_close
    if wrapper:
        classes = wrapper.group(1).split()
        assert "hidden" in classes
        assert "group-data-[dropdown-host=sheet]/dropdown:contents" in classes
    assert html.count("data-date-range-close") == int(has_close)


@pytest.mark.django_db
@pytest.mark.parametrize("mode", sorted(QUICK_FACETS))
def test_every_quick_facet_applies_the_bar(mode):
    html = str(QuickFilterBar(mode=mode, presentation=PRESENTATION))
    facets = re.findall(r"<drop-down[^>]*data-quick-facet", html)
    applies = re.findall(
        r'<button type="submit"[^>]*data-(?:quick-facet|date-range)-apply', html
    )
    assert len(applies) == len(facets)
    dates = re.findall(
        r"<drop-down[^>]*data-quick-facet[^>]*>(?:(?!</drop-down>).)*?data-static-calendar",
        html,
        re.DOTALL,
    )
    assert html.count("data-date-range-apply") == len(dates)


def test_the_sheet_behavior_refuses_a_second_sheet():
    with pytest.raises(ValueError):
        dropdown(behavior="sheet", sheet=SheetSpec("Sections"))


def test_every_sheet_variant_names_the_generated_host():
    """Tailwind needs literals; they follow the mapping."""
    attribute = SHEET_ATTRIBUTES["host"].removeprefix("data-")
    stated = f"data-[{attribute}={SHEET_HOST_VALUE}]"
    variant = re.compile(r"data-\[([a-z-]+)=([a-z]+)\]")
    sources = Path(__file__).resolve().parent.parent / "common" / "components"
    named = {
        match.group(0)
        for path in sources.glob("*.py")
        for match in variant.finditer(path.read_text())
        if "host" in match.group(1)
    }
    assert named == {stated}


@pytest.mark.parametrize("title", ["", None])
def test_a_sheet_needs_a_title(title):
    with pytest.raises(ValueError):
        SheetSpec(title)


def test_a_sheet_leads_its_header_with_a_hidden_back_control():
    html = dropdown(sheet=SheetSpec("Day"))
    [back] = re.findall(r"<button[^>]*data-sheet-back[^>]*>", html)
    assert re.search(r"\shidden(\s|=|>)", back)
    assert 'data-sheet-back-label=""' in html
    assert html.index("data-sheet-back=") < html.index("data-dropdown-sheet-title")


def test_a_sheet_level_backdrop_is_transparent():
    html = dropdown(sheet=SheetSpec("Day"))
    assert "data-sheet-level:backdrop:opacity-0!" in html


def test_the_answer_check_refuses_a_sheetless_drop_down():
    html = (
        '<drop-down behavior="menu"><button aria-label="Row actions">x</button>'
        "<div>panel</div></drop-down>"
    )
    [fault] = sheetless_dropdown_faults(html)
    assert "behavior='menu'" in fault
    assert "aria-label='Row actions'" in fault


def test_the_answer_check_passes_a_drop_down_with_its_own_sheet():
    html = dropdown(sheet=SheetSpec("Day"))
    assert sheetless_dropdown_faults(html) == []


def test_the_answer_check_leaves_the_sheet_behavior_alone():
    html = '<drop-down behavior="sheet"><div>panel</div></drop-down>'
    assert sheetless_dropdown_faults(html) == []


def test_the_answer_check_names_a_nested_sheetless_drop_down_alone():
    outer = dropdown(sheet=SheetSpec("Day"))
    inner = (
        '<drop-down behavior="menu"><button aria-label="Inner">x</button></drop-down>'
    )
    html = outer[: -len("</drop-down>")] + inner + "</drop-down>"
    [fault] = sheetless_dropdown_faults(html)
    assert "aria-label='Inner'" in fault
