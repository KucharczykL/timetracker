"""The historical playtime form parses; the command decides."""

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from stated_runs import another_run

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.historical_playtime import (
    AT_LEAST_ONE_RUN,
    WHEN_NO_SUCH_DATE,
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playthrough import RemovePlaythrough
from games.events.dispatch import dispatch
from games.forms import HistoricalPlaytimeForm
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Playthrough,
    PlaythroughKind,
)
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.historical_playtime import record_historical_playtime
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

type PostedData = dict[str, str | list[str]]


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


def posted(run_ids, *, hours="100", minutes="0", **overrides) -> PostedData:
    data: PostedData = {
        "playthroughs": [str(run_id) for run_id in run_ids],
        "duration_hours": hours,
        "duration_minutes": minutes,
        temporal_input_name("when", "kind"): "unknown",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED.value,
        "device": "",
        "note": "",
    }
    data.update(overrides)
    return data


def form(library, game, data=None, record=None) -> HistoricalPlaytimeForm:
    return HistoricalPlaytimeForm(
        data, library=library, game=game, presentation=PRESENTATION, record=record
    )


def recorded(user, run_ids, **changes) -> HistoricalPlaytime:
    statement = HistoricalPlaytimeStatement(
        duration=timedelta(hours=1, minutes=30, seconds=20),
        when=None,
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=tuple(run_ids),
        device_id=None,
        emulated=False,
        note="",
    )._replace(**changes)
    dispatch(
        RecordHistoricalPlaytime(statement=statement),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.latest("created_at")


def test_hours_and_minutes_clean_to_a_duration(owned_library, game, run):
    bound = form(owned_library, game, posted([run.pk], hours="120", minutes="30"))
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=120, minutes=30)


def test_a_blank_duration_reaches_the_command_as_zero(owned_library, game, run):
    bound = form(owned_library, game, posted([run.pk], hours="", minutes=""))
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(0)


@pytest.mark.parametrize(
    ("hours", "minutes"), [("1", "60"), ("-1", "0"), ("100000", "0")]
)
def test_numbers_out_of_range_are_refused(owned_library, game, run, hours, minutes):
    bound = form(owned_library, game, posted([run.pk], hours=hours, minutes=minutes))
    assert not bound.is_valid()
    assert "duration" in bound.errors


def test_unchanged_hours_and_minutes_keep_the_stored_seconds(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk])
    bound = form(owned_library, game, posted([run.pk], hours="1", minutes="30"), record)
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=1, minutes=30, seconds=20)


def test_changed_minutes_drop_the_stored_seconds(owned_user, owned_library, game, run):
    record = recorded(owned_user, [run.pk])
    bound = form(owned_library, game, posted([run.pk], hours="1", minutes="31"), record)
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=1, minutes=31)


def test_blank_inputs_on_a_record_under_a_minute_are_zero(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk], duration=timedelta(seconds=20))
    bound = form(owned_library, game, posted([run.pk], hours="", minutes=""), record)
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(0)


def test_add_offers_two_provenances_with_estimated_first(owned_library, game, run):
    unbound = form(owned_library, game)
    assert [value for value, _ in unbound.fields["provenance"].choices] == [
        "estimated",
        "manually_entered",
    ]
    assert unbound["provenance"].value() == "estimated"


def test_edit_offers_externally_measured_only_where_held(
    owned_user, owned_library, game, run
):
    record = recorded(
        owned_user,
        [run.pk],
        provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
    )
    edited = form(owned_library, game, record=record)
    assert [value for value, _ in edited.fields["provenance"].choices] == [
        "estimated",
        "manually_entered",
        "externally_measured",
    ]
    assert edited["provenance"].value() == "externally_measured"
    refused = form(
        owned_library,
        game,
        posted([run.pk], provenance="externally_measured"),
    )
    assert not refused.is_valid()


def test_a_date_that_does_not_exist_gets_the_commands_sentence(
    owned_library, game, run
):
    bound = form(
        owned_library,
        game,
        posted(
            [run.pk],
            **{
                temporal_input_name("when", "kind"): "date",
                temporal_input_name("when", "start_year"): "2005",
                temporal_input_name("when", "start_month"): "2",
                temporal_input_name("when", "start_day"): "30",
            },
        ),
    )
    assert not bound.is_valid()
    assert bound.errors["when"] == [WHEN_NO_SUCH_DATE]


def test_a_known_when_is_stated_canonically(owned_library, game, run):
    bound = form(
        owned_library,
        game,
        posted(
            [run.pk],
            **{
                temporal_input_name("when", "kind"): "date",
                temporal_input_name("when", "start_year"): "2005",
            },
        ),
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().when == "2005"


def test_an_unknown_when_is_stated_as_none(owned_library, game, run):
    bound = form(owned_library, game, posted([run.pk]))
    assert bound.is_valid(), bound.errors
    assert bound.statement().when is None


def test_add_checks_the_latest_run(owned_user, owned_library, game, run):
    later = another_run(owned_user, game)
    assert form(owned_library, game)["playthroughs"].value() == [str(later.pk)]


def test_choices_are_the_games_live_ordinary_runs_by_number(
    owned_user, owned_library, game, run
):
    second = another_run(owned_user, game)
    third = another_run(owned_user, game)
    dispatch(
        RemovePlaythrough(playthrough_id=third.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-third",
    )
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=run.created_at,
    )
    assert list(form(owned_library, game).fields["playthroughs"].choices) == [
        (str(run.pk), "Playthrough 1"),
        (str(second.pk), "Playthrough 2"),
    ]


def test_a_posted_removed_run_is_left_to_the_command(
    owned_user, owned_library, game, run
):
    second = another_run(owned_user, game)
    dispatch(
        RemovePlaythrough(playthrough_id=second.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-second",
    )
    bound = form(owned_library, game, posted([second.pk]))
    assert bound.is_valid(), bound.errors


def test_a_held_removed_device_stays_selectable(owned_user, owned_library, game, run):
    device = Device.objects.create(library=owned_library, name="Old PC")
    record = recorded(owned_user, [run.pk], device_id=device.pk)
    remove(device)
    edited = form(owned_library, game, record=record)
    assert "Old PC" in str(edited["device"])
    bound = form(
        owned_library,
        game,
        posted([run.pk], hours="1", minutes="30", device=str(device.pk)),
        record,
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().device_id == device.pk


def test_another_removed_device_is_refused(owned_library, game, run):
    device = Device.objects.create(library=owned_library, name="Old PC")
    remove(device)
    bound = form(owned_library, game, posted([run.pk], device=str(device.pk)))
    assert not bound.is_valid()
    assert "device" in bound.errors


def test_a_crlf_note_cleans_to_lf(owned_library, game, run):
    bound = form(owned_library, game, posted([run.pk], note="one\r\ntwo"))
    assert bound.is_valid(), bound.errors
    assert bound.statement().note == "one\ntwo"


def test_choice_lists_render_as_labelled_groups(owned_library, game, run):
    html = str(form(owned_library, game)["playthroughs"])
    assert html.count("<fieldset") == 1
    assert 'aria-labelledby="id_playthroughs-label"' in html
    assert 'type="checkbox"' in html
    assert "w-full" not in html
    provenance = str(form(owned_library, game)["provenance"])
    assert provenance.count('type="radio"') == 2


def test_recording_answers_the_new_id(owned_user, game, run):
    bound = form(owned_user.library, game, posted([run.pk]))
    assert bound.is_valid(), bound.errors
    record_id = record_historical_playtime(
        owned_user, bound.statement(), correlation_id=uuid.uuid7()
    )
    assert HistoricalPlaytime.objects.get().pk == record_id


def test_a_refusal_is_an_answer(owned_user, game, run):
    bound = form(owned_user.library, game, posted([]))
    assert bound.is_valid(), bound.errors
    with pytest.raises(CommandFailed) as failed:
        record_historical_playtime(
            owned_user, bound.statement(), correlation_id=uuid.uuid7()
        )
    assert failed.value.message == AT_LEAST_ONE_RUN
