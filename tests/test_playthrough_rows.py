"""#1012: one table row per run."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.playthrough import ActStatement
from games.models import Game, Playthrough, Session
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.views.playthrough_rows import playthrough_tabledata
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import RunDraft, restate_run
from timetracker.temporal import TemporalValue

#: The real TrackGame states the run, not the fixture.
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


def numbered_runs(owned_library, run):
    """The runs as the screen reads them."""
    tracked = tracked_game(owned_library, run.player_game.game)
    assert tracked is not None
    return list(
        numbered_for(owned_library, [tracked.pk], with_condition=True).select_related(
            "player_game__game"
        )
    )


def tabledata_of(owned_library, run, presentation, **options):
    """The table this run renders, numbered."""
    runs = numbered_runs(owned_library, run)
    options.setdefault("csrf_token", "token")
    return playthrough_tabledata(runs, presentation, origin=None, **options)


def cells_of(owned_library, run, presentation, **options) -> list[str]:
    """Every cell this run renders, stringified."""
    data = tabledata_of(owned_library, run, presentation, **options)
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
    """The pinned first column clips its name."""
    cells = cells_of(owned_library, run, presentation)

    assert "<truncated-text" in cells[0]
    assert "Playthrough 1" in cells[0]


def test_the_columns_sort_only_where_the_caller_says_so(
    owned_library, run, presentation
):
    """Game detail reads no `?sort=` at all."""
    static = tabledata_of(owned_library, run, presentation)
    sortable = tabledata_of(owned_library, run, presentation, sortable=True)

    assert {column.sort_key for column in static["columns"]} == {None}
    assert {
        column.label: column.sort_key
        for column in sortable["columns"]
        if column.sort_key is not None
    } == {
        "Game": "name",
        "Started": "started",
        "Completed": "completed",
        "Days to finish": "days",
        "Created": "created",
    }


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

    #: The first, second and third: three days.
    assert "3" in cells


def test_excluding_the_game_column_drops_its_cell(owned_library, run, presentation):
    runs = numbered_runs(owned_library, run)

    data = playthrough_tabledata(
        runs, presentation, exclude_columns=["Game"], origin=None, csrf_token="token"
    )

    labels = [column.label for column in data["columns"]]
    cells = [str(cell) for row in data["rows"] for cell in row["cell_data"]]
    assert "Game" not in labels
    assert "Outer Wilds" not in "".join(cells)


def _state_start(owned_user, run) -> None:
    restate_run(
        owned_user,
        run,
        RunDraft(
            started=ActStatement(TemporalValue.from_day(date(2026, 1, 2))),
            completed=None,
            note=run.note,
        ),
        correlation_id=new_correlation_id(),
    )
    run.refresh_from_db()


def _state_completion(owned_user, run) -> None:
    restate_run(
        owned_user,
        run,
        RunDraft(
            started=None,
            completed=ActStatement(TemporalValue.from_day(date(2026, 2, 3))),
            note=run.note,
        ),
        correlation_id=new_correlation_id(),
    )
    run.refresh_from_db()


def actions_of(owned_library, run, presentation, **options) -> str:
    """The one row's last cell, stringified."""
    data = tabledata_of(owned_library, run, presentation, **options)
    [row] = data["rows"]
    return str(row["cell_data"][-1])


def test_a_run_with_no_start_offers_start(owned_library, run, presentation):
    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/start" in actions
    assert f"/playthrough/{run.pk}/complete" not in actions
    assert 'method="post"' in actions
    assert "token" in actions


def test_a_started_run_offers_complete(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/complete" in actions
    assert f"/playthrough/{run.pk}/start" not in actions


def test_the_complete_button_names_the_status_it_states(
    owned_user, owned_library, run, presentation
):
    """The press always states Completed, so its title says so."""
    _state_start(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert "also marks the game Completed" in actions


def test_a_finished_run_offers_neither(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)
    _state_completion(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/start" not in actions
    assert f"/playthrough/{run.pk}/complete" not in actions


def test_a_run_completed_before_today_offers_no_start(
    owned_user, owned_library, run, presentation
):
    """The completion alone rules a start out.

    Starting today would finish the run before it
    began, which the command refuses, so offering
    the button promises an act it cannot deliver.
    """
    _state_completion(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/start" not in actions
    assert f"/playthrough/{run.pk}/complete" not in actions
    assert f"/playthrough/edit/{run.pk}" in actions


def test_a_playing_run_prints_its_badge_and_its_recency(
    owned_library, run, presentation
):
    Session.objects.create(
        game=run.player_game.game,
        timestamp_start=timezone.now() - timedelta(days=4),
    )

    html = "".join(cells_of(owned_library, run, presentation))

    assert "Playing" in html
    assert "4 days ago" in html


def test_a_never_played_run_prints_no_recency(owned_library, run, presentation):
    html = "".join(cells_of(owned_library, run, presentation))

    assert "Never played" in html
    assert "ago" not in html


def test_runs_read_without_the_clock_are_refused(owned_library, run, presentation):
    """A missing alias is a bad read."""
    tracked = tracked_game(owned_library, run.player_game.game)
    assert tracked is not None
    runs = list(
        numbered_for(owned_library, [tracked.pk]).select_related("player_game__game")
    )

    with pytest.raises(ValueError, match="carries no condition alias"):
        playthrough_tabledata(runs, presentation, origin=None, csrf_token="token")


def test_a_completed_run_prints_a_dash_for_its_activity(
    owned_user, owned_library, run, presentation
):
    """No clock speaks about a finished run."""
    _state_completion(owned_user, run)

    data = tabledata_of(owned_library, run, presentation)
    labels = [column.label for column in data["columns"]]
    [row] = data["rows"]

    assert str(row["cell_data"][labels.index("Activity")]) == "-"
