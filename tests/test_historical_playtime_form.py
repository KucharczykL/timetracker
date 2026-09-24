"""The form parses and narrows choices; the command decides."""

import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from devices import create_device, remove_device
from django.utils import timezone
from historical_playtime_posts import posted_record
from stated_runs import another_run

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.historical_playtime import (
    AT_LEAST_A_SECOND,
    WHEN_NO_SUCH_DATE,
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playthrough import RemovePlaythrough
from games.events.dispatch import dispatch
from games.forms import HistoricalPlaytimeForm
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Playthrough,
    PlaythroughKind,
)
from games.writes.answers import CommandFailed
from games.writes.historical_playtime import record_historical_playtime
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


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
    bound = form(
        owned_library, game, posted_record([run.pk], hours="120", minutes="30")
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=120, minutes=30)


def test_a_blank_duration_reaches_the_command_as_zero(owned_library, game, run):
    bound = form(owned_library, game, posted_record([run.pk], hours="", minutes=""))
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(0)


def test_the_largest_duration_is_accepted(owned_library, game, run):
    bound = form(
        owned_library, game, posted_record([run.pk], hours="99999", minutes="59")
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=99999, minutes=59)


@pytest.mark.parametrize(
    ("hours", "minutes"), [("1", "60"), ("-1", "0"), ("100000", "0")]
)
def test_numbers_out_of_range_are_refused(owned_library, game, run, hours, minutes):
    bound = form(
        owned_library, game, posted_record([run.pk], hours=hours, minutes=minutes)
    )
    assert not bound.is_valid()
    assert "duration" in bound.errors


def test_unchanged_hours_and_minutes_keep_the_stored_seconds(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk])
    bound = form(
        owned_library, game, posted_record([run.pk], hours="1", minutes="30"), record
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=1, minutes=30, seconds=20)


def test_changed_minutes_drop_the_stored_seconds(owned_user, owned_library, game, run):
    record = recorded(owned_user, [run.pk])
    bound = form(
        owned_library, game, posted_record([run.pk], hours="1", minutes="31"), record
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=1, minutes=31)


def test_blank_inputs_on_a_record_under_a_minute_are_zero(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk], duration=timedelta(seconds=20))
    bound = form(
        owned_library, game, posted_record([run.pk], hours="", minutes=""), record
    )
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
        posted_record([run.pk], provenance="externally_measured"),
    )
    assert not refused.is_valid()


def test_a_date_that_does_not_exist_gets_the_commands_sentence(
    owned_library, game, run
):
    bound = form(
        owned_library,
        game,
        posted_record(
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
        posted_record(
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
    bound = form(owned_library, game, posted_record([run.pk]))
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
    bound = form(owned_library, game, posted_record([second.pk]))
    assert bound.is_valid(), bound.errors


def test_a_held_removed_device_stays_selectable(owned_user, owned_library, game, run):
    device = create_device(library=owned_library, name="Old PC")
    record = recorded(owned_user, [run.pk], device_id=device.pk)
    remove_device(device)
    edited = form(owned_library, game, record=record)
    assert "Old PC" in str(edited["device"])
    bound = form(
        owned_library,
        game,
        posted_record([run.pk], hours="1", minutes="30", device=str(device.pk)),
        record,
    )
    assert bound.is_valid(), bound.errors
    assert bound.statement().device_id == device.pk


def test_another_removed_device_is_refused(owned_library, game, run):
    device = create_device(library=owned_library, name="Old PC")
    remove_device(device)
    bound = form(owned_library, game, posted_record([run.pk], device=str(device.pk)))
    assert not bound.is_valid()
    assert "device" in bound.errors


def test_a_crlf_note_cleans_to_lf(owned_library, game, run):
    bound = form(owned_library, game, posted_record([run.pk], note="one\r\ntwo"))
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
    bound = form(owned_user.library, game, posted_record([run.pk]))
    assert bound.is_valid(), bound.errors
    record_id = record_historical_playtime(
        owned_user,
        bound.statement(),
        idempotency_key=bound.submission_key(),
        correlation_id=uuid.uuid7(),
    )
    assert HistoricalPlaytime.objects.get().pk == record_id


def test_a_refusal_is_an_answer(owned_user, game, run):
    bound = form(owned_user.library, game, posted_record([run.pk], hours="0"))
    assert bound.is_valid(), bound.errors
    with pytest.raises(CommandFailed) as failed:
        record_historical_playtime(
            owned_user,
            bound.statement(),
            idempotency_key=bound.submission_key(),
            correlation_id=uuid.uuid7(),
        )
    assert failed.value.message == AT_LEAST_A_SECOND


def test_no_playthrough_is_a_field_error(owned_library, game, run):
    """The field names what is missing."""
    bound = form(owned_library, game, posted_record([]))
    assert not bound.is_valid()
    assert "playthroughs" in bound.errors


def test_edit_renders_the_stored_hours_and_minutes(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk])
    html = str(form(owned_library, game, record=record)["duration"])
    assert 'name="duration_hours" id="id_duration_hours" value="1"' in html
    assert 'name="duration_minutes" id="id_duration_minutes" value="30"' in html


def test_an_estimated_record_is_offered_two_provenances(
    owned_user, owned_library, game, run
):
    record = recorded(owned_user, [run.pk])
    choices = form(owned_library, game, record=record).fields["provenance"].choices
    assert [value for value, _ in choices] == ["estimated", "manually_entered"]


def test_emulated_reaches_the_statement(owned_library, game, run):
    bound = form(owned_library, game, posted_record([run.pk], emulated="on"))
    assert bound.is_valid(), bound.errors
    assert bound.statement().emulated is True


def test_another_librarys_run_is_refused(owned_library, game, run, django_user_model):
    other = django_user_model.objects.create_user(username="someone-else")
    theirs = Game.objects.create(library=other.library, name="Theirs")
    their_run = Playthrough.objects.get(player_game__game=theirs)
    bound = form(owned_library, game, posted_record([their_run.pk]))
    assert not bound.is_valid()
    assert "playthroughs" in bound.errors


def test_another_librarys_device_is_refused(
    owned_library, game, run, django_user_model
):
    other = django_user_model.objects.create_user(username="someone-else")
    device = create_device(library=other.library, name="Theirs")
    bound = form(owned_library, game, posted_record([run.pk], device=str(device.pk)))
    assert not bound.is_valid()
    assert "device" in bound.errors


def test_edit_refuses_a_removed_device_it_does_not_hold(
    owned_user, owned_library, game, run
):
    held = create_device(library=owned_library, name="Held")
    other = create_device(library=owned_library, name="Other")
    record = recorded(owned_user, [run.pk], device_id=held.pk)
    remove_device(held)
    remove_device(other)
    bound = form(
        owned_library, game, posted_record([run.pk], device=str(other.pk)), record
    )
    assert not bound.is_valid()
    assert "device" in bound.errors


def test_a_device_that_is_no_id_is_a_field_error(owned_library, game, run):
    bound = form(owned_library, game, posted_record([run.pk], device="not-an-id"))
    assert not bound.is_valid()
    assert "device" in bound.errors
    #: Re-rendering the refused form must not raise.
    assert "not-an-id" not in str(bound["device"])


def test_add_needs_its_submission_key(owned_library, game, run):
    data = posted_record([run.pk])
    del data["submission"]
    bound = form(owned_library, game, data)
    assert not bound.is_valid()
    assert "submission" in bound.errors


def test_add_renders_a_fresh_key_and_edit_none(owned_user, owned_library, game, run):
    first = form(owned_library, game)["submission"].value()
    second = form(owned_library, game)["submission"].value()
    assert first != second
    record = recorded(owned_user, [run.pk])
    assert "submission" not in form(owned_library, game, record=record).fields


# --- Seeding from a session ---------------------------------------------------


def a_session(library, run, **columns):
    from session_rows import duration_only_row

    return duration_only_row(
        run, date(2026, 3, 5), timedelta(hours=9, minutes=30), **columns
    )


def test_a_session_seeds_its_own_run_and_not_the_latest(
    owned_user, owned_library, game, run
):
    """The seed wins over the Add default."""
    another = another_run(owned_user, game)
    session = a_session(owned_library, run)

    bound = HistoricalPlaytimeForm(
        library=owned_library, game=game, presentation=PRESENTATION, session=session
    )

    assert bound.initial["playthroughs"] == [str(run.pk)]
    assert str(another.pk) != str(run.pk)


def test_a_session_seeds_every_fact_it_states(owned_library, game, run):
    device = create_device(library=owned_library, name="Vita")
    session = a_session(owned_library, run, device=device, note="off a screenshot")

    bound = HistoricalPlaytimeForm(
        library=owned_library, game=game, presentation=PRESENTATION, session=session
    )

    assert bound.initial["duration"] == timedelta(hours=9, minutes=30)
    assert bound.initial["when"].canonical == "2026-03-05"
    assert bound.initial["device"] == device.pk
    assert bound.initial["note"] == "off a screenshot"
    assert (
        bound.initial["provenance"]
        == HistoricalPlaytimeProvenance.MANUALLY_ENTERED.value
    )


def test_a_session_in_the_bucket_posted_without_a_run_is_a_field_error(
    owned_user, owned_library, game, run
):
    bucket = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    session = a_session(owned_library, bucket)
    bound = HistoricalPlaytimeForm(
        posted_record([], hours="9", minutes="30"),
        library=owned_library,
        game=game,
        presentation=PRESENTATION,
        session=session,
    )

    assert not bound.is_valid()
    assert "playthroughs" in bound.errors


def test_a_session_keeps_its_seconds_when_the_minutes_are_unchanged(
    owned_library, game, run
):
    from session_rows import duration_only_row

    session = duration_only_row(
        run, date(2026, 3, 5), timedelta(hours=9, minutes=30, seconds=7)
    )
    bound = HistoricalPlaytimeForm(
        posted_record([run.pk], hours="9", minutes="30"),
        library=owned_library,
        game=game,
        presentation=PRESENTATION,
        session=session,
    )

    assert bound.is_valid(), bound.errors
    assert bound.statement().duration == timedelta(hours=9, minutes=30, seconds=7)


def test_a_session_takes_the_provenance_the_caller_states(owned_library, game, run):
    session = a_session(owned_library, run)

    bound = HistoricalPlaytimeForm(
        library=owned_library,
        game=game,
        presentation=PRESENTATION,
        session=session,
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
    )

    assert bound.initial["provenance"] == HistoricalPlaytimeProvenance.ESTIMATED.value


def test_a_session_keeps_its_removed_device_among_the_choices(owned_library, game, run):
    device = create_device(library=owned_library, name="Vita")
    session = a_session(owned_library, run, device=device)
    remove_device(device)

    bound = HistoricalPlaytimeForm(
        library=owned_library, game=game, presentation=PRESENTATION, session=session
    )

    assert device in bound.fields["device"].queryset


def test_a_session_form_still_states_a_submission(owned_library, game, run):
    """No Unchanged; a repeat needs the key."""
    session = a_session(owned_library, run)

    bound = HistoricalPlaytimeForm(
        library=owned_library, game=game, presentation=PRESENTATION, session=session
    )

    assert "submission" in bound.fields
    assert bound.initial["submission"]


def test_a_record_and_a_session_together_are_refused(
    owned_library, game, run, owned_user
):
    record = recorded(owned_user, [run.pk])
    session = a_session(owned_library, run)

    with pytest.raises(TypeError):
        HistoricalPlaytimeForm(
            library=owned_library,
            game=game,
            presentation=PRESENTATION,
            record=record,
            session=session,
        )


def test_the_device_picker_offers_to_make_a_device(owned_library, game):
    """The same field as the session form, and the same gap."""
    form = HistoricalPlaytimeForm(
        library=owned_library, game=game, presentation=PRESENTATION
    )

    assert 'create-url="/api/devices/"' in str(form["device"])
