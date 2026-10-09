"""The Log a game form: what it refuses, and what each press states."""

import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.http import QueryDict
from graphs import default_graph
from stated_runs import another_run
from tracked_games import create_tracked_game

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.opener_facts import Fixed
from games.catalog_release import (
    NO_DEFAULT_EDITION,
    PRERELEASE_DEFAULT,
    SHARED_GAME_RELEASE,
)
from games.commands.endpoint import ActStatement
from games.log_forms import (
    ANOTHER_GAMES_RUN,
    DATES_REVERSED,
    DAY_REQUIRED,
    REMOVED_GAME,
    ZERO_DURATION,
    LogGameForm,
)
from games.models import (
    EditionKind,
    Game,
    Platform,
    PlayerGame,
    PlayerGameStatus,
)
from games.reads.log_game import HeldFacts
from games.writes.endpoint import KEEP
from games.writes.log_game import HistoricalHours, SessionTiming
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
TODAY = datetime.date(2026, 9, 29)
SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


def _form(library, data=None, **kwargs) -> LogGameForm:
    return LogGameForm(
        data,
        library=library,
        presentation=PRESENTATION,
        today=TODAY,
        prefix=None,
        **kwargs,
    )


def _posted(game=None, **fields) -> dict[str, object]:
    """A press that changes nothing: every seen value posted as shown."""
    posted: dict[str, object] = {
        "submission": SUBMISSION,
        "status": "unplayed",
        "status_seen": "unplayed",
        "platform_seen": "",
        "started_seen": "",
        "completed_seen": "",
        "note_seen": "",
        "mastered_seen": "False",
        "attempt": "0",
        "playtime_kind": "session",
        "duration_hours": "",
        "duration_minutes": "",
    }
    if game is not None:
        posted["game"] = str(game.pk)
    return posted | fields


@pytest.fixture
def game(owned_library):
    return create_tracked_game(owned_library, "Tunic")


@pytest.fixture
def pc(owned_library):
    return Platform.objects.create(library=owned_library, name="PC")


@pytest.fixture
def console(owned_library):
    return Platform.objects.create(library=owned_library, name="Xbox")


def test_a_removed_game_is_refused_on_the_game(owned_library, game):
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        removed_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    )

    form = _form(owned_library, _posted(game))

    assert not form.is_valid()
    assert form.errors["game"] == [REMOVED_GAME]


def test_a_changed_platform_with_no_release_on_a_shared_game_is_refused(
    owned_library, pc
):
    shared = Game.objects.create(library=None, name="Celeste")

    form = _form(owned_library, _posted(shared, platform=str(pc.pk)))

    assert not form.is_valid()
    assert form.errors["platform"] == [SHARED_GAME_RELEASE]


def test_a_changed_platform_on_a_prerelease_default_is_refused(
    owned_library, game, pc, console
):
    default_graph(
        game, owned_library, platform=console, edition_kind=EditionKind.PRERELEASE
    )

    form = _form(owned_library, _posted(game, platform=str(pc.pk)))

    assert not form.is_valid()
    assert form.errors["platform"] == [PRERELEASE_DEFAULT]


def test_several_editions_with_none_default_are_refused(owned_library, game, pc):
    from games.models import Edition

    Edition.objects.create(game=game, name="A", is_default=False)
    Edition.objects.create(game=game, name="B", is_default=False)

    form = _form(owned_library, _posted(game, platform=str(pc.pk)))

    assert not form.is_valid()
    assert form.errors["platform"] == [NO_DEFAULT_EDITION]


def test_an_unchanged_platform_is_never_refused_on_its_release(owned_library, game, pc):
    form = _form(
        owned_library,
        _posted(game, platform=str(pc.pk), platform_seen=str(pc.pk)),
    )

    assert form.is_valid(), form.errors
    assert form.statement().platform_changed is False


def test_reversed_days_are_refused_on_finished_on(owned_library, game):
    data = _posted(
        game,
        started_seen="2026-05-01",
        completed_seen="",
        **_day("started", datetime.date(2026, 5, 1)),
        **_day("completed", datetime.date(2026, 1, 1)),
    )

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["completed"] == [DATES_REVERSED]


def test_a_cleared_start_is_not_checked_against_the_finish(owned_library, game):
    # Clearing the start voids it, so an earlier finish is fine.
    data = _posted(
        game,
        started_seen="2026-05-01",
        **_day("completed", datetime.date(2026, 4, 1)),
    )

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors


def test_a_typed_zero_duration_is_refused(owned_library, game):
    data = _posted(
        game,
        duration_hours="0",
        duration_minutes="0",
        day="2026-09-01",
    )

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["duration"] == [ZERO_DURATION]


def test_an_empty_duration_states_no_playtime(owned_library, game):
    form = _form(owned_library, _posted(game))

    assert form.is_valid(), form.errors
    assert form.statement().playtime is None


def test_a_session_needs_its_day(owned_library, game):
    data = _posted(game, duration_hours="1", duration_minutes="0", day="")

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["day"] == [DAY_REQUIRED]


def test_playtime_states_a_session_or_a_historical_record(owned_library, game):
    session = _form(
        owned_library,
        _posted(
            game,
            duration_hours="2",
            duration_minutes="0",
            day="2026-09-01",
        ),
    )
    assert session.is_valid(), session.errors
    assert session.statement().playtime == SessionTiming(
        day=datetime.date(2026, 9, 1),
        duration=datetime.timedelta(hours=2),
        device_id=None,
    )

    historical = _form(
        owned_library,
        _posted(
            game,
            playtime_kind="historical",
            duration_hours="1",
            duration_minutes="15",
        ),
    )
    assert historical.is_valid(), historical.errors
    assert historical.statement().playtime == HistoricalHours(
        duration=datetime.timedelta(hours=1, minutes=15), device_id=None
    )


def test_a_run_of_another_game_is_refused(owned_library, game):
    other = create_tracked_game(owned_library, "Hades")
    run = another_run(owned_library.user, other)

    form = _form(owned_library, _posted(game, run=str(run.pk)))

    assert not form.is_valid()
    assert form.errors["run"] == [ANOTHER_GAMES_RUN]


def test_an_unchanged_status_states_nothing(owned_library, game):
    form = _form(
        owned_library, _posted(game, status="completed", status_seen="completed")
    )

    assert form.is_valid(), form.errors
    assert form.statement().status is KEEP


def test_a_changed_status_is_stated_with_the_word_the_page_showed(owned_library, game):
    form = _form(
        owned_library,
        _posted(game, status="played", status_seen="unplayed"),
    )

    assert form.is_valid(), form.errors
    statement = form.statement()
    assert statement.status is PlayerGameStatus.PLAYED
    assert statement.seen_status is PlayerGameStatus.UNPLAYED


def test_a_changed_day_states_an_act(owned_library, game):
    data = _posted(game, **_day("started", datetime.date(2026, 3, 4)))

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors
    assert form.statement().started == ActStatement(
        TemporalValue.from_day(datetime.date(2026, 3, 4)), ""
    )


def test_a_day_the_page_showed_states_no_act(owned_library, game):
    day = TemporalValue.from_day(datetime.date(2026, 3, 4))
    data = _posted(
        game,
        started_seen=day.canonical,
        **_day("started", datetime.date(2026, 3, 4)),
    )

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors
    assert form.statement().started is KEEP


def test_a_cleared_day_voids_the_act_it_showed(owned_library, game):
    day = TemporalValue.from_day(datetime.date(2026, 3, 4))

    form = _form(owned_library, _posted(game, started_seen=day.canonical))

    assert form.is_valid(), form.errors
    assert form.statement().started is None


def test_an_act_stated_with_no_day_survives_an_untouched_press(owned_library, game):
    form = _form(owned_library, _posted(game))

    assert form.is_valid(), form.errors
    assert form.statement().started is KEEP
    assert form.statement().completed is KEEP


def test_mastered_is_stated_only_where_it_changes(owned_library, game):
    unchanged = _form(owned_library, _posted(game, mastered="on", mastered_seen="True"))
    assert unchanged.is_valid(), unchanged.errors
    assert unchanged.statement().mastered is KEEP

    changed = _form(owned_library, _posted(game, mastered="on", mastered_seen="False"))
    assert changed.is_valid(), changed.errors
    assert changed.statement().mastered is True


def test_the_note_is_stated_only_where_it_changes(owned_library, game):
    unchanged = _form(owned_library, _posted(game, note="kept", note_seen="kept"))
    assert unchanged.is_valid(), unchanged.errors
    assert unchanged.statement().note is KEEP

    changed = _form(owned_library, _posted(game, note=" hello ", note_seen="kept"))
    assert changed.is_valid(), changed.errors
    assert changed.statement().note == "hello"


def test_the_form_seeds_what_a_held_game_shows(owned_library, game, pc):
    run = another_run(
        owned_library.user,
        game,
        started=ActStatement(TemporalValue.from_day(datetime.date(2026, 2, 2)), ""),
        note="A note",
    )
    held = HeldFacts(
        removed=False,
        status=PlayerGameStatus.COMPLETED,
        run=run,
        started=None,
        completed=None,
        platform=pc,
        mastered=True,
        note="A note",
    )

    form = _form(owned_library, held=held)

    assert form.initial["status"] == "completed"
    assert form.initial["status_seen"] == "completed"
    assert form.initial["platform_seen"] == str(pc.pk)
    assert form.initial["run"] == run.pk
    assert form.initial["started_seen"] == "2026-02-02"
    assert form.initial["mastered"] is True
    assert form.initial["note_seen"] == "A note"


def test_an_untracked_game_shows_unplayed(owned_library):
    held = HeldFacts(
        removed=False,
        status=None,
        run=None,
        started=None,
        completed=None,
        platform=None,
        mastered=False,
        note="",
    )

    form = _form(owned_library, held=held)

    assert form.initial["status"] == "unplayed"
    assert form.initial["status_seen"] == "unplayed"


def test_opener_fact_fixes_the_game(owned_library, game):
    facts = QueryDict(f"game={game.pk}")

    form = _form(owned_library, facts=facts)

    assert form.fields["game"].disabled
    assert form.stated("game", Game) == game
    assert isinstance(form.facts["game"], Fixed)


def test_a_prefilled_game_is_editable(owned_library, game):
    form = _form(owned_library, prefill=game)

    assert not form.fields["game"].disabled
    assert form.initial["game"] == game.pk


def test_an_unknown_run_pick_is_refused_by_the_field(owned_library, game):
    form = _form(owned_library, _posted(game, run=str(uuid.uuid7())))

    assert not form.is_valid()
    assert "run" in form.errors
