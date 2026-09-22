"""The icon in the header row, and the panel of boxes it opens."""

import re

from common.components import (
    COLUMN_PICKER_LABEL,
    Column,
    ColumnPicker,
    Safe,
    StyledTable,
    make_row,
)

COLUMNS = [
    Column("Name", "name", shrinkable=True, key="name", hideable=False),
    Column("Year", "year", key="year"),
    Column("Created", "created", key="created"),
]

ACTION_COLUMNS = [
    *COLUMNS,
    Column("Actions", align="right", key="actions", hideable=False),
]


def picker(columns=COLUMNS, hidden=()) -> str:
    return str(
        ColumnPicker(
            columns,
            hidden,
            post_url="/tracker/lists/games/columns/",
            csrf_input=Safe('<input type="hidden" name="csrfmiddlewaretoken">'),
            mode="games",
        )
    )


def _boxes(html: str) -> list[str]:
    return re.findall(r"<input[^>]*type=\"checkbox\"[^>]*>", html)


def test_the_panel_states_one_box_a_column():
    assert len(_boxes(picker())) == len(COLUMNS)


def test_a_column_a_person_shows_states_a_checked_box():
    [name, year, created] = _boxes(picker())

    assert "checked" in year
    assert 'value="year"' in year
    assert "checked" in created


def test_a_hidden_column_states_an_unchecked_box():
    [_, year, _created] = _boxes(picker(hidden={"year"}))

    assert "checked" not in year


def test_a_column_that_refuses_to_hide_states_a_checked_disabled_box():
    [name, *_rest] = _boxes(picker())

    assert "checked" in name
    assert "disabled" in name


def test_a_pinned_column_that_a_row_names_is_shown_all_the_same():
    """Its box posts nothing, so nothing may read the row as the truth."""
    [name, *_rest] = _boxes(picker(hidden={"name"}))

    assert "checked" in name


def test_the_trigger_is_named_and_states_no_visible_word():
    html = picker()
    [trigger, *_rest] = re.findall(r"<button[^>]*>", html)

    assert COLUMN_PICKER_LABEL in trigger
    assert "Columns shown" in html


def test_the_panel_carries_a_plain_post_form():
    html = picker()

    assert 'method="post"' in html
    assert 'action="/tracker/lists/games/columns/"' in html
    assert "csrfmiddlewaretoken" in html


def test_a_reset_posts_as_itself():
    html = picker()

    assert 'name="reset"' in html
    assert 'value="1"' in html


def _table(columns, *, menu: bool) -> str:
    rows = [
        make_row(
            *["cell"] * len(columns),
            key="row-1",
            menu=Safe("<span>menu</span>") if menu else None,
        )
    ]
    return str(
        StyledTable(
            columns=columns,
            rows=rows,
            data_table=True,
            caption="Games",
            column_picker=Safe('<span data-picker=""></span>'),
        )
    )


def _header_cells(html: str) -> list[str]:
    head = re.findall(r"<thead.*?</thead>", html, re.DOTALL)
    return re.findall(r"<th.*?</th>", "".join(head), re.DOTALL)


def test_the_icon_rides_the_trailing_slot_where_the_rows_carry_a_menu():
    cells = _header_cells(_table(COLUMNS, menu=True))

    assert "data-picker" in cells[-1]
    assert "data-row-menu" in cells[-1]


def test_the_icon_rides_the_actions_header_where_no_slot_is():
    cells = _header_cells(_table(ACTION_COLUMNS, menu=False))

    assert "data-picker" in cells[-1]
    assert "Actions" in cells[-1]


def test_no_other_header_cell_carries_it():
    cells = _header_cells(_table(ACTION_COLUMNS, menu=False))

    assert [cell for cell in cells if "data-picker" in cell] == [cells[-1]]
