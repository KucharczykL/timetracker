"""The second line a record row states below md."""

from zoneinfo import ZoneInfo

import pytest
from historical_playtime_rows import record_row
from session_rows import tracked_run

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.duration_presentation import DurationPresentation, duration_format_profile
from games.models import Device, Game, HistoricalPlaytime
from games.reads.historical_playtime_page import run_labels_for
from games.views.historical_playtime import historical_playtime_tabledata

pytestmark = pytest.mark.django_db


@pytest.fixture
def record(owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")
    device = Device.objects.create(library=owned_library, name="Steam Deck")
    written = record_row(
        [tracked_run(owned_library, game)], when="2026-01-02", device=device
    )
    #: The field converts the day on the way back, as the read path sees it.
    return HistoricalPlaytime.objects.select_related("device", "player_game").get(
        pk=written.pk
    )


def summary_of(owned_library, record, **options) -> str:
    data = historical_playtime_tabledata(
        [record],
        run_labels_for(owned_library, [record]),
        DateTimePresentation(
            DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
        ),
        DurationPresentation(
            profile=duration_format_profile("hours_minutes"), locale="en-us"
        ),
        origin=None,
        **options,
    )
    [row] = data["rows"]
    return row["summary"]


def test_the_list_summary_states_the_day_the_duration_and_the_device(
    owned_library, record
):
    summary = summary_of(owned_library, record)

    assert "2026-01-02" in summary
    assert "Steam Deck" in summary


def test_the_summary_states_no_column_the_person_hid(owned_library, record):
    """Below md every column but the first has dropped, so this line is the
    one place a hidden column could come back."""
    summary = summary_of(owned_library, record, hidden=("when", "duration", "device"))

    assert summary == ""


def test_game_detail_spends_the_line_on_the_rest(owned_library, record):
    """It leads with the day, so the line states what the day leaves."""
    summary = summary_of(owned_library, record, hidden=("name", "created"))

    assert "Estimated" in summary
    assert "Steam Deck" in summary
