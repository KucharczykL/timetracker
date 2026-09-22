"""#1012: one table row per run."""

import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from bulk_posts import act_url
from django.utils import timezone
from session_rows import timed_row

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.bulk_playthrough_acts import COMPLETE_RUNS, START_RUNS
from games.commands.playthrough import ActStatement
from games.models import Game, Playthrough
from games.reads.playthrough_activity import activity_clock
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.views.playthrough_rows import playthrough_tabledata
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import RunDraft, restate_run
from timetracker.temporal import TemporalEndpoint, TemporalValue

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
    options.setdefault("clock", activity_clock(owned_library))
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
        "Playthrough": "playthrough",
        "Game": "name",
        "Started": "started",
        "Completed": "completed",
        "Days to finish": "days",
        "Created": "created",
    }


def test_the_acts_name_the_run(owned_library, run, presentation):
    """Read off the menu: the acts are no cell of their own."""
    assert str(run.pk) in actions_of(owned_library, run, presentation)


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
        runs,
        presentation,
        exclude_columns=["Game"],
        clock=activity_clock(owned_library),
        origin=None,
        csrf_token="token",
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
    """The one row's menu, stringified.

    The acts are no column, so this reads the slot rather than the last cell:
    that index is the Created date now.
    """
    data = tabledata_of(owned_library, run, presentation, **options)
    [row] = data["rows"]
    return str(row["menu"])


def test_the_builder_declares_no_actions_column(owned_library, run, presentation):
    data = tabledata_of(owned_library, run, presentation)

    assert "Actions" not in [column.label for column in data["columns"]]
    [row] = data["rows"]
    assert len(row["cell_data"]) == len(data["columns"])


def test_every_run_offers_edit_and_remove(owned_library, run, presentation):
    """The words sit in a span of their own: each item leads with a glyph."""
    actions = actions_of(owned_library, run, presentation)

    assert ">Edit</span>" in actions
    assert ">Remove</span>" in actions


def test_a_run_with_no_start_offers_start(owned_library, run, presentation):
    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert act_url(START_RUNS) in actions
    assert act_url(COMPLETE_RUNS) not in actions
    assert str(run.pk) in actions
    assert 'method="post"' in actions
    assert "token" in actions


def test_a_started_run_offers_complete(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert act_url(COMPLETE_RUNS) in actions
    assert act_url(START_RUNS) not in actions


def test_an_item_reads_the_act_it_posts_to(
    owned_user, owned_library, run, presentation
):
    """One act reads the same in the tray and in the menu."""
    _state_start(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert COMPLETE_RUNS.label in actions
    #: The confirmation states the status the act also records.
    assert "also marks the game Completed" not in actions


def test_a_finished_run_offers_neither(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)
    _state_completion(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert act_url(START_RUNS) not in actions
    assert act_url(COMPLETE_RUNS) not in actions


def test_a_run_completed_before_today_offers_no_start(
    owned_user, owned_library, run, presentation
):
    """The completion alone rules a start out.

    The gate is narrower than the command, which takes a
    start at today on a run completed today: a finished
    run is not one a person is starting now.
    """
    _state_completion(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert act_url(START_RUNS) not in actions
    assert act_url(COMPLETE_RUNS) not in actions
    assert f"/playthrough/edit/{run.pk}" in actions


def test_a_playing_run_prints_its_badge_and_its_recency(
    owned_library, run, presentation
):
    started_at = timezone.now() - timedelta(days=4)
    timed_row(run, started_at, started_at + timedelta(hours=1))

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
        playthrough_tabledata(
            runs,
            presentation,
            clock=activity_clock(owned_library),
            origin=None,
            csrf_token="token",
        )


def test_a_completed_run_prints_a_dash_for_its_activity(
    owned_user, owned_library, run, presentation
):
    """No clock speaks about a finished run."""
    _state_completion(owned_user, run)

    data = tabledata_of(owned_library, run, presentation)
    labels = [column.label for column in data["columns"]]
    [row] = data["rows"]

    assert str(row["cell_data"][labels.index("Activity")]) == "-"


def test_the_recency_does_not_move_with_the_viewers_zone(owned_library, run):
    """The word and the phrase beside it read one clock.

    The day is counted on the library's calendar, so the
    viewer's presentation zone has no say in how long ago.
    """
    started_at = timezone.now() - timedelta(days=4)
    timed_row(run, started_at, started_at + timedelta(hours=1))

    phrases = set()
    for zone in ("Pacific/Kiritimati", "Pacific/Niue", "UTC"):
        elsewhere = DateTimePresentation(
            DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo(zone)
        )
        html = "".join(cells_of(owned_library, run, elsewhere))
        assert "Playing" in html
        phrases.update(re.findall(r"\d+ days ago", html))

    assert phrases == {"4 days ago"}


def summary_of(owned_library, run, presentation, **options) -> str:
    """The one row's second line."""
    data = tabledata_of(owned_library, run, presentation, **options)
    [row] = data["rows"]
    return row["summary"]


def _state_days(run, started, completed) -> None:
    """Both endpoints, as values the grammar may refuse to state."""
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=None if started is None else timezone.now(),
        started=started,
        completion_recorded_at=None if completed is None else timezone.now(),
        completed=completed,
    )


def test_the_list_summary_names_the_game(owned_library, run, presentation):
    assert summary_of(owned_library, run, presentation).startswith("Outer Wilds")


def test_game_detail_states_no_game_part(owned_library, run, presentation):
    """Every row there names the same game already."""
    summary = summary_of(owned_library, run, presentation, exclude_columns=["Game"])

    assert "Outer Wilds" not in summary


def test_two_known_days_read_as_one_range(owned_library, run, presentation):
    _state_days(
        run,
        TemporalValue.from_day(date(2026, 3, 5)),
        TemporalValue.from_day(date(2026, 4, 2)),
    )

    assert "2026-03-05 – 2026-04-02" in summary_of(owned_library, run, presentation)


def test_a_start_alone_reads_since(owned_library, run, presentation):
    _state_days(run, TemporalValue.from_day(date(2026, 3, 5)), None)

    assert "since 2026-03-05" in summary_of(owned_library, run, presentation)


def test_a_completion_alone_reads_until(owned_library, run, presentation):
    _state_days(run, None, TemporalValue.from_day(date(2026, 4, 2)))

    assert "until 2026-04-02" in summary_of(owned_library, run, presentation)


def test_neither_endpoint_states_no_span(owned_library, run, presentation):
    """The activity is the whole line."""
    assert summary_of(owned_library, run, presentation) == "Outer Wilds, Never played"


def test_a_range_endpoint_states_each_act_apart(owned_library, run, presentation):
    """Two ranges joined would read as one wrong range."""
    _state_days(
        run,
        TemporalValue.range(
            start=TemporalEndpoint.known(TemporalValue.from_day(date(2026, 3, 1))),
            end=TemporalEndpoint.known(TemporalValue.from_day(date(2026, 3, 5))),
        ),
        TemporalValue.from_day(date(2026, 4, 2)),
    )

    summary = summary_of(owned_library, run, presentation)

    assert "Started 2026-03-01 – 2026-03-05" in summary
    assert "Completed 2026-04-02" in summary


def test_an_unknown_day_states_no_part(owned_library, run, presentation):
    """A slot reading `Unknown` is a slot the clip takes."""
    _state_days(run, None, None)
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=timezone.now(), started=None
    )

    assert "Unknown" not in summary_of(owned_library, run, presentation)


def test_a_completed_run_states_no_activity_part(
    owned_user, owned_library, run, presentation
):
    _state_start(owned_user, run)
    _state_completion(owned_user, run)

    summary = summary_of(owned_library, run, presentation)

    assert "Playing" not in summary
    assert "Dormant" not in summary
    assert "Never played" not in summary


def test_the_activity_part_states_the_word_and_the_recency(
    owned_library, run, presentation
):
    started_at = timezone.now() - timedelta(days=4)
    timed_row(run, started_at, started_at + timedelta(hours=1))

    assert "Playing 4 days ago" in summary_of(owned_library, run, presentation)
