"""The face a field-hosted picker shows below sm, and its sheet."""

import re

import pytest

from common.components import FilterSelect, SearchSelect, TimeZoneRow
from common.components.primitives import Button
from common.components.search_select import (
    DialogCreate,
    _face_value,
    _HeldFace,
    presets_member,
)

SHEET = re.compile(r"<dialog[^>]*data-dropdown-sheet[^>]*>")
FACE_VALUE = re.compile(
    r"<span([^>]*data-search-select-face-value[^>]*)>([^<]*)</span>"
)


def face_value(html: str) -> tuple[str, bool]:
    match = FACE_VALUE.search(html)
    assert match, html
    return match.group(2), "data-placeholder" in match.group(1)


def tag_with(html: str, marker: str) -> list[str]:
    return re.findall(rf"<[a-z-]+[^>]*{marker}[^>]*>", html)


def test_a_field_picker_renders_its_face_and_one_untitled_sheet():
    html = str(SearchSelect(name="game", search_url="/api/games/search"))
    assert len(SHEET.findall(html)) == 1
    assert re.search(r"<h2[^>]*data-dropdown-sheet-title[^>]*></h2>", html)
    face = html.index("data-search-select-face=")
    assert face < html.index("<search-select")
    [open_button] = tag_with(html, "data-search-select-face-open")
    assert 'aria-haspopup="dialog"' in open_button
    assert 'aria-expanded="false"' in open_button
    assert 'type="button"' in open_button
    face_class = tag_with(html, 'data-search-select-face=""')[0]
    assert "sm:hidden in-data-[dropdown-sheetless]:hidden" in face_class
    assert (
        "max-sm:not-data-[dropdown-host=sheet]:not-in-data-[dropdown-sheetless]:hidden"
        in html
    )


def test_a_dialog_picker_has_no_face_and_no_sheet():
    html = str(SearchSelect(name="zone", search_url="/x", panel=True))
    assert "data-search-select-face" not in html
    assert not SHEET.search(html)


def test_the_face_shows_the_held_label():
    html = str(
        SearchSelect(
            name="game",
            selected=[{"value": 1, "label": "Celeste", "data": {}}],
            search_url="/x",
        )
    )
    assert face_value(html) == ("Celeste", False)


def test_the_face_shows_none_when_none_is_held():
    html = str(SearchSelect(name="device", search_url="/x", none_label="No device"))
    assert face_value(html) == ("No device", False)


def test_the_face_shows_a_muted_placeholder_when_empty():
    html = str(SearchSelect(name="game", search_url="/x", placeholder="Pick a game"))
    assert face_value(html) == ("Pick a game", True)


def test_a_multi_face_joins_its_labels():
    html = str(
        SearchSelect(
            name="tags",
            multi_select=True,
            selected=[
                {"value": 1, "label": "One", "data": {}},
                {"value": 2, "label": "Two", "data": {}},
            ],
            search_url="/x",
        )
    )
    assert face_value(html) == ("One, Two", False)


def test_a_filter_face_names_included_and_excluded_values():
    html = str(
        FilterSelect(
            field_name="platform",
            options=[("1", "PC"), ("2", "Switch")],
            included=[("1", "PC")],
            excluded=[("2", "Switch")],
        )
    )
    assert face_value(html) == ("PC, not Switch", False)
    assert "data-search-select-face-clear" not in html


def test_the_face_clear_mirrors_the_widget_clear():
    empty = str(SearchSelect(name="game", search_url="/x"))
    [clear] = tag_with(empty, "data-search-select-face-clear")
    assert " hidden" in clear
    held = str(
        SearchSelect(
            name="game",
            selected=[{"value": 1, "label": "Celeste", "data": {}}],
            search_url="/x",
        )
    )
    [clear] = tag_with(held, "data-search-select-face-clear")
    assert " hidden" not in clear
    unclearable = str(SearchSelect(name="game", search_url="/x", clearable=False))
    assert "data-search-select-face-clear" not in unclearable


def test_the_face_offers_a_plus_only_with_a_dialog_create():
    plain = str(SearchSelect(name="game", search_url="/x"))
    assert "data-search-select-face-create" not in plain
    html = str(
        SearchSelect(
            name="game",
            search_url="/x",
            dialog_create=DialogCreate(url="/games/add", label="New game"),
        )
    )
    links = tag_with(html, "data-search-select-dialog-create")
    assert len(links) == 2
    [face_link] = [link for link in links if "data-search-select-face-create" in link]
    [widget_link] = [link for link in links if link is not face_link]
    assert 'href="/games/add"' in face_link
    assert "in-data-[dropdown-host=sheet]:hidden!" in widget_link
    assert "in-data-[dropdown-host=sheet]:hidden!" not in face_link


def test_the_listbox_yields_its_height_to_the_sheet():
    html = str(SearchSelect(name="game", search_url="/x"))
    [listbox] = tag_with(html, 'role="listbox"')
    assert "group-data-[dropdown-host=sheet]/dropdown:max-h-none!" in listbox


def test_the_presets_panel_opens_as_a_sheet():
    member = presets_member(api_url="/api/presets/", mode="games", id="presets")
    html = str(member["opens"](Button(type="button")["Presets"]))
    assert len(SHEET.findall(html)) == 1
    assert re.search(r"<h2[^>]*data-dropdown-sheet-title[^>]*>Presets</h2>", html)


def test_the_time_zone_row_opens_as_a_sheet():
    html = str(
        TimeZoneRow(
            field_name="zone",
            label="Start time zone",
            stored_zone="",
            display_zone="Europe/Prague",
            capture_default=True,
        )
    )
    assert len(SHEET.findall(html)) == 1
    assert re.search(
        r"<h2[^>]*data-dropdown-sheet-title[^>]*>Start time zone</h2>", html
    )


def test_a_filter_face_leads_with_its_modifier():
    html = str(
        FilterSelect(
            field_name="platform",
            options=[("1", "PC")],
            included=[("1", "PC")],
            modifier="INCLUDES_ALL",
            modifier_options=[("INCLUDES_ALL", "(All)")],
        )
    )
    assert face_value(html) == ("(All), PC", False)


def test_a_held_face_names_its_value():
    with pytest.raises(ValueError):
        _HeldFace("")


def test_blank_labels_leave_the_placeholder():
    assert _face_value(["", ""], "Pick one").placeholder == "Pick one"


STEADY = "group-data-[sheet-steady]/sheet:h-dvh"


def test_a_picker_sheet_keeps_its_height():
    assert STEADY in str(SearchSelect(name="game", search_url="/x"))
    member = presets_member(api_url="/api/presets/", mode="games", id="presets")
    assert STEADY in str(member["opens"](Button(type="button")["Presets"]))


def test_a_panel_listbox_fills_the_sheet_above_its_footer():
    html = str(SearchSelect(name="zone", search_url="/x", panel=True))
    [listbox] = tag_with(html, 'role="listbox"')
    assert (
        "group-data-[dropdown-host=sheet]/dropdown:max-h-[calc(var(--sheet-visible-height,100dvh)*0.9-13rem)]!"
    ) in listbox


def test_the_sheet_stamp_lands_on_the_listbox_group():
    html = str(SearchSelect(name="game", search_url="/x"))
    [panel] = tag_with(html, "data-search-select-panel")
    assert "data-menu" in panel
    assert "group/dropdown" in panel


def test_the_time_zone_sheet_keeps_its_height():
    html = str(
        TimeZoneRow(
            field_name="zone",
            label="Start time zone",
            stored_zone="",
            display_zone="Europe/Prague",
            capture_default=True,
        )
    )
    assert STEADY in html
