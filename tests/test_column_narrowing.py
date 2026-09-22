"""The helper that takes a hidden column and its cells out together."""

import pytest

from common.components import Column, drop_columns

COLUMNS = [
    Column("Name", "name", shrinkable=True, key="name", hideable=False),
    Column("Year", "year", key="year"),
    Column("Status", "status", key="status"),
    Column("Created", "created", key="created"),
]

ROWS = [
    ["Katamari", "2004", "Playing", "today"],
    ["Portal", "2007", "Finished", "yesterday"],
]


def test_a_named_column_and_its_cells_go_together():
    columns, rows = drop_columns(COLUMNS, ROWS, {"year"})

    assert [column.key for column in columns] == ["name", "status", "created"]
    assert rows == [
        ["Katamari", "Playing", "today"],
        ["Portal", "Finished", "yesterday"],
    ]


def test_two_columns_apart_keep_every_other_cell_in_order():
    columns, rows = drop_columns(COLUMNS, ROWS, {"year", "created"})

    assert [column.key for column in columns] == ["name", "status"]
    assert rows == [["Katamari", "Playing"], ["Portal", "Finished"]]


def test_a_key_no_column_claims_drops_nothing():
    columns, rows = drop_columns(COLUMNS, ROWS, {"platform"})

    assert [column.key for column in columns] == [column.key for column in COLUMNS]
    assert rows == ROWS


def test_an_empty_set_drops_nothing():
    columns, rows = drop_columns(COLUMNS, ROWS, frozenset())

    assert columns == COLUMNS
    assert rows == ROWS


def test_every_row_answers_one_cell_per_kept_column():
    columns, rows = drop_columns(COLUMNS, ROWS, {"name", "status"})

    assert all(len(row) == len(columns) for row in rows)


def test_a_page_takes_the_column_that_names_the_rows():
    """Game detail leads with the day, because every row names one game."""
    columns, rows = drop_columns(COLUMNS, ROWS, {"name"})

    assert [column.key for column in columns] == ["year", "status", "created"]
    assert rows == [["2004", "Playing", "today"], ["2007", "Finished", "yesterday"]]


def test_the_columns_it_answers_are_not_the_ones_it_was_given():
    columns, _ = drop_columns(COLUMNS, ROWS, {"year"})
    columns.append(Column("Note", key="note"))

    assert len(COLUMNS) == 4


def test_a_row_that_states_the_wrong_number_of_cells_is_refused():
    """A ragged row renders each cell under the wrong header, silently."""
    short = [["Katamari", "2004", "Playing"]]

    with pytest.raises(ValueError, match="cells against"):
        drop_columns(COLUMNS, short, {"year"})
