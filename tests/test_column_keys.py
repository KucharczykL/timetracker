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
