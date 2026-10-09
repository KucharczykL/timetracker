"""The Log a game form: each section's checks, and what it states."""

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
from games.commands.endpoint import ActStatement
from games.log_forms import (
    DATES_REVERSED,
    DAY_REQUIRED,
    PICK_A_RUN,
    ZERO_DURATION,
    LogGameForm,
)
from games.models import Game, PlayerGameStatus
from games.reads.log_game import HeldFacts
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


@pytest.fixture
def game(owned_library):
    return create_tracked_game(owned_library, "Tunic")


@pytest.fixture
def release(owned_library, game):
    return default_graph(game, owned_library).release


@pytest.fixture
def other_release(owned_library):
    other = create_tracked_game(owned_library, "Hades")
    return default_graph(other, owned_library).release


def _form(owned_library, data=None, **kwargs):
    return LogGameForm(
        data,
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
        prefix=None,
        **kwargs,
    )


def _posted(**fields) -> dict[str, object]:
    """A press with nothing ticked: every section left as it is."""
    return {
        "submission": SUBMISSION,
        "price": "paid",
        "playtime_kind": "session",
    } | fields


def _copy_fields(release) -> dict[str, object]:
    return {
        "sections": ["copy"],
        "release": str(release.pk),
        "access": "owned",
        "format": "digital",
        "price": "none",
        **_day("acquired", datetime.date(2026, 9, 1)),
    }


def test_unticked_copy_with_paid_and_no_amount_is_valid(owned_library, game):
    form = _form(owned_library, _posted(game=str(game.pk), price="paid"))

    assert form.is_valid(), form.errors
    statement = form.statement()
    assert statement.sections == frozenset()
    assert statement.copy is None
    assert statement.purchase is None


def test_ticked_copy_paid_without_amount_is_refused_on_amount(
    owned_library, game, release
):
    data = _posted(game=str(game.pk), **(_copy_fields(release) | {"price": "paid"}))

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert "amount" in form.errors


def test_ticked_copy_names_no_release_of_another_game(
    owned_library, game, other_release
):
    data = _posted(game=str(game.pk), **_copy_fields(other_release))

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert "release" in form.errors


def test_ticked_copy_with_no_price_states_a_copy_without_purchase(
    owned_library, game, release
):
    form = _form(owned_library, _posted(game=str(game.pk), **_copy_fields(release)))

    assert form.is_valid(), form.errors
    statement = form.statement()
    assert statement.copy is not None
    assert statement.copy.release_id == release.pk
    assert statement.purchase is None


def test_ticked_copy_with_a_price_states_a_purchase(owned_library, game, release):
    data = _posted(
        game=str(game.pk),
        **(
            _copy_fields(release)
            | {"price": "paid", "amount": "12.50", "currency": "eur"}
        ),
    )

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors
    purchase = form.statement().purchase
    assert purchase is not None
    assert str(purchase.price.amount) == "12.50"
    assert purchase.price.currency == "EUR"


def test_ticked_dates_reversed_are_refused_on_completed(owned_library, game):
    data = _posted(
        game=str(game.pk),
        sections=["dates"],
        **_day("started", datetime.date(2026, 5, 1)),
        **_day("completed", datetime.date(2026, 1, 1)),
    )

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["completed"] == [DATES_REVERSED]


def test_ticked_playtime_needs_a_day_in_session_form(owned_library, game):
    data = _posted(
        game=str(game.pk),
        sections=["playtime"],
        duration_hours="1",
        duration_minutes="30",
    )

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["day"] == [DAY_REQUIRED]


def test_ticked_playtime_refuses_zero_duration(owned_library, game):
    data = _posted(
        game=str(game.pk),
        sections=["playtime"],
        day="2026-09-01",
        duration_hours="",
        duration_minutes="",
    )

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["duration"] == [ZERO_DURATION]


def test_unticked_playtime_drops_its_zero_duration(owned_library, game):
    data = _posted(game=str(game.pk), duration_hours="", duration_minutes="", day="x")

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors


def test_playtime_states_a_session_or_a_historical_record(owned_library, game):
    session = _form(
        owned_library,
        _posted(
            game=str(game.pk),
            sections=["playtime"],
            day="2026-09-01",
            duration_hours="2",
            duration_minutes="0",
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
            game=str(game.pk),
            sections=["playtime"],
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
    data = _posted(game=str(game.pk), sections=["more"], playthrough=str(run.pk))

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert "playthrough" in form.errors


def test_several_runs_with_none_picked_are_refused(owned_library, game):
    another_run(owned_library.user, game)
    data = _posted(game=str(game.pk), sections=["more"], note="A note", playthrough="")

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert form.errors["playthrough"] == [PICK_A_RUN]


def test_status_none_row_reads_what_the_game_holds(owned_library, game):
    held = HeldFacts(
        copies=(),
        run=None,
        status=PlayerGameStatus.COMPLETED,
        mastered=False,
        playtime=datetime.timedelta(0),
    )

    form = _form(owned_library, held=held)

    assert form.fields["status"].choices[0] == ("", "Leave as is: Completed")


def test_status_none_row_reads_plainly_without_a_held_game(owned_library):
    form = _form(owned_library)

    assert form.fields["status"].choices[0] == ("", "Leave as is")


def test_a_chosen_status_is_stated_and_the_none_row_states_nothing(owned_library, game):
    picked = _form(owned_library, _posted(game=str(game.pk), status="completed"))
    assert picked.is_valid(), picked.errors
    assert picked.statement().status is PlayerGameStatus.COMPLETED

    none = _form(owned_library, _posted(game=str(game.pk), status=""))
    assert none.is_valid(), none.errors
    assert none.statement().status is None


def test_opener_fact_fixes_the_game(owned_library, game):
    facts = QueryDict(f"game={game.pk}")

    form = _form(owned_library, facts=facts)

    assert form.fields["game"].disabled
    assert form.stated("game", Game) == game
    assert isinstance(form.facts["game"], Fixed)


def test_held_run_seeds_the_run_and_its_seen_days(owned_library, game):
    run = another_run(owned_library.user, game)
    held = HeldFacts(
        copies=(),
        run=run,
        status=None,
        mastered=True,
        playtime=datetime.timedelta(0),
    )

    form = _form(owned_library, held=held)

    assert form.initial["playthrough"] == run.pk
    assert form.initial["mastered"] is True
    assert form.initial["started_seen"] == ""


def test_mastered_is_stated_only_where_it_changes(owned_library, game):
    unchanged = _form(
        owned_library,
        _posted(
            game=str(game.pk),
            sections=["more"],
            mastered="on",
            mastered_seen="True",
        ),
    )
    assert unchanged.is_valid(), unchanged.errors
    assert unchanged.statement().mastered is None

    changed = _form(
        owned_library,
        _posted(
            game=str(game.pk),
            sections=["more"],
            mastered="on",
            mastered_seen="False",
        ),
    )
    assert changed.is_valid(), changed.errors
    assert changed.statement().mastered is True


def test_a_day_the_page_showed_states_no_act(owned_library, game):
    day = TemporalValue.from_day(datetime.date(2026, 3, 4))
    data = _posted(
        game=str(game.pk),
        sections=["dates"],
        started_seen=day.canonical,
        **_day("started", datetime.date(2026, 3, 4)),
    )

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors
    assert form.statement().started is None


def test_a_changed_day_states_an_act(owned_library, game):
    data = _posted(
        game=str(game.pk),
        sections=["dates"],
        started_seen="",
        **_day("started", datetime.date(2026, 3, 4)),
    )

    form = _form(owned_library, data)

    assert form.is_valid(), form.errors
    started = form.statement().started
    assert started == ActStatement(
        TemporalValue.from_day(datetime.date(2026, 3, 4)), ""
    )


def test_saved_sections_are_not_offered_again(owned_library, game):
    form = _form(owned_library, {"saved": ["copy"]}, facts=None)

    assert form.is_bound
    offered = [value for value, _ in form.fields["sections"].choices]
    assert "copy" not in offered
    assert "dates" in offered


def test_the_run_note_is_stated_only_where_more_is_ticked(owned_library, game):
    form = _form(
        owned_library,
        _posted(game=str(game.pk), note=" hello ", sections=[]),
    )

    assert form.is_valid(), form.errors
    assert form.statement().note is None


def test_an_unknown_run_pick_is_refused_by_the_field(owned_library, game):
    data = _posted(game=str(game.pk), sections=["more"], playthrough=str(uuid.uuid7()))

    form = _form(owned_library, data)

    assert not form.is_valid()
    assert "playthrough" in form.errors


def test_statement_reads_the_day_when_the_playtime_is_ticked(owned_library, game):
    data = _posted(
        game=str(game.pk),
        sections=["playtime"],
        day="2026-09-01",
        duration_hours="1",
        duration_minutes="0",
    )
    form = _form(owned_library, data)
    assert form.is_valid(), form.errors

    assert form.statement().game == game
