"""Every list's columns state a key, and two of them refuse to hide."""

import pytest

from games.views.device import DEVICE_COLUMNS
from games.views.game import game_list_columns
from games.views.historical_playtime import historical_playtime_columns
from games.views.platform import PLATFORM_COLUMNS
from games.views.playthrough_rows import playthrough_columns
from games.views.purchase import PURCHASE_COLUMNS
from games.views.session import SESSION_COLUMNS

DECLARED = {
    "games": game_list_columns("Playtime"),
    "sessions": SESSION_COLUMNS,
    "purchases": PURCHASE_COLUMNS,
    "playthroughs": playthrough_columns(sortable=True),
    "historical_playtime": historical_playtime_columns(sortable=True),
    "devices": DEVICE_COLUMNS,
    "platforms": PLATFORM_COLUMNS,
}

MODES = sorted(DECLARED)


@pytest.mark.parametrize("mode", MODES)
def test_every_column_states_a_key(mode):
    assert all(column.key for column in DECLARED[mode])


@pytest.mark.parametrize("mode", MODES)
def test_one_list_states_each_key_once(mode):
    keys = [column.key for column in DECLARED[mode]]

    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("mode", MODES)
def test_the_first_column_refuses_to_hide(mode):
    assert DECLARED[mode][0].hideable is False


@pytest.mark.parametrize("mode", MODES)
def test_an_actions_column_refuses_to_hide(mode):
    acts = [column for column in DECLARED[mode] if column.key == "actions"]

    assert all(column.hideable is False for column in acts)


@pytest.mark.parametrize("mode", MODES)
def test_every_other_column_hides(mode):
    middle = DECLARED[mode][1:]

    assert all(column.hideable for column in middle if column.key != "actions")


def test_the_game_lists_playtime_key_outlives_its_label():
    narrowed = game_list_columns("Playtime (matching)")

    assert [column.key for column in narrowed] == [
        column.key for column in DECLARED["games"]
    ]
    assert any(column.key == "playtime" for column in narrowed)


@pytest.mark.parametrize("mode", MODES)
def test_a_column_that_refuses_to_hide_never_starts_hidden(mode):
    """The two rules would contradict: nothing could ever show it again."""
    pinned = [column for column in DECLARED[mode] if not column.hideable]

    assert all(not column.hidden_by_default for column in pinned)


@pytest.mark.parametrize("mode", MODES)
def test_a_list_starts_with_more_than_the_columns_it_pins(mode):
    """A default that hid everything hideable would read as a broken page."""
    shown = [column for column in DECLARED[mode] if not column.hidden_by_default]

    assert len(shown) > len([c for c in DECLARED[mode] if not c.hideable])


@pytest.mark.parametrize("mode", MODES)
def test_the_created_timestamp_starts_hidden(mode):
    [created] = [column for column in DECLARED[mode] if column.key == "created"]

    assert created.hidden_by_default
