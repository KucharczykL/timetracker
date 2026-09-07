"""#1012: one table row per run."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import Game, Playthrough
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.views.playthrough_rows import playthrough_tabledata
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

#: Every test wants the run #679 states.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def run(owned_user, owned_library) -> Playthrough:
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(player_game__game=game)


@pytest.fixture
def presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def cells_of(owned_library, run, presentation, **options) -> list[str]:
    """Every cell this run renders, stringified."""
    tracked = tracked_game(owned_library, run.player_game.game)
    assert tracked is not None
    runs = list(
        numbered_for(owned_library, [tracked.pk]).select_related("player_game__game")
    )
    data = playthrough_tabledata(runs, presentation, origin=None, **options)
    return [str(cell) for row in data["rows"] for cell in row["cell_data"]]


def test_an_act_that_never_happened_renders_a_dash(owned_library, run, presentation):
    """Both endpoints and the span between them."""
    cells = cells_of(owned_library, run, presentation)

    assert cells.count("-") == 3


def test_a_stated_act_with_no_day_renders_unknown(owned_library, run, presentation):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(), started=None
    )

    cells = cells_of(owned_library, run, presentation)

    assert "Unknown" in "".join(cells)
    assert cells.count("-") == 2


def test_a_stated_act_renders_its_day_at_its_own_precision(
    owned_library, run, presentation
):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(),
        started=TemporalValue.from_month(2026, 3),
    )

    cells = cells_of(owned_library, run, presentation)

    #: The month, not the first day of it: the cell renders
    #: the value at the precision the run states.
    assert "March 2026" in "".join(cells)


def test_a_blank_name_renders_its_display_number(owned_library, run, presentation):
    cells = cells_of(owned_library, run, presentation)

    assert cells[0] == "Playthrough 1"


def test_the_actions_name_the_run(owned_library, run, presentation):
    cells = cells_of(owned_library, run, presentation)

    assert str(run.pk) in cells[-1]


def test_the_days_cell_reads_the_span(owned_library, run, presentation):
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(),
        started=TemporalValue.from_day(date(2026, 1, 1)),
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(date(2026, 1, 3)),
    )

    cells = cells_of(owned_library, run, presentation)

    assert "2" in cells


def test_excluding_the_game_column_drops_its_cell(owned_library, run, presentation):
    tracked = tracked_game(owned_library, run.player_game.game)
    assert tracked is not None
    runs = list(
        numbered_for(owned_library, [tracked.pk]).select_related("player_game__game")
    )

    data = playthrough_tabledata(
        runs, presentation, exclude_columns=["Game"], origin=None
    )

    labels = [column.label for column in data["columns"]]
    cells = [str(cell) for row in data["rows"] for cell in row["cell_data"]]
    assert "Game" not in labels
    assert "Outer Wilds" not in "".join(cells)
