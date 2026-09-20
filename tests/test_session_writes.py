"""The request-free write path: one fact per event."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone
from session_rows import session_row, tracked_run

from games.commands.playersession import (
    DurationOnlyTiming,
    TimedTiming,
)
from games.commands.session_reclassification import (
    NEVER_RECLASSIFIED,
    STILL_RUNNING,
    statement_from_session,
)
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.writes.answers import CommandFailed
from games.writes.playersession import (
    SessionDraft,
    clone_session,
    end_session,
    reclassify_session,
    record_session,
    remove_session,
    reset_session,
    restate_session,
    restore_session,
    undo_reclassification,
)

pytestmark = pytest.mark.django_db(transaction=True)

STARTED_AT = datetime(2026, 7, 1, 12, tzinfo=UTC)
ENDED_AT = datetime(2026, 7, 1, 13, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _prague_calendar(owned_user, set_user_setting):
    """The rows `session_rows` seeds count their days in Prague."""
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Hades")


def _events(correlation_id: uuid.UUID) -> list[str]:
    return list(
        LibraryEvent.objects.filter(correlation_id=correlation_id)
        .order_by("recorded_at", "sequence")
        .values_list("event_type", flat=True)
    )


def _draft(run, **overrides) -> SessionDraft:
    fields = {
        "playthrough_id": run.pk,
        "timing": TimedTiming(started_at=STARTED_AT, day_zone="Europe/Prague"),
        "device_id": None,
        "note": "",
        "emulated": False,
    }
    fields.update(overrides)
    return SessionDraft(**fields)


def test_recording_answers_the_new_rows_id(owned_user, owned_library, game):
    run = tracked_run(owned_library, game)
    correlation_id = uuid.uuid7()

    session_id = record_session(
        owned_user, _draft(run, note="first"), correlation_id=correlation_id
    )

    row = PlayerSession.objects.get(pk=session_id)
    assert row.playthrough_id == run.pk
    assert row.note == "first"
    assert _events(correlation_id) == ["library.playersession.created"]


def test_record_session_absorbs_a_repeat_under_one_key(owned_user, owned_library, game):
    run = tracked_run(owned_library, game)

    first = record_session(
        owned_user, _draft(run), correlation_id=uuid.uuid7(), idempotency_key="k-1"
    )
    second = record_session(
        owned_user, _draft(run), correlation_id=uuid.uuid7(), idempotency_key="k-1"
    )

    assert first == second
    assert PlayerSession.objects.filter(playthrough=run).count() == 1


def test_record_session_refuses_a_key_that_names_another_statement(
    owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    record_session(
        owned_user,
        _draft(run, note="first"),
        correlation_id=uuid.uuid7(),
        idempotency_key="k-1",
    )

    with pytest.raises(CommandFailed) as refusal:
        record_session(
            owned_user,
            _draft(run, note="second"),
            correlation_id=uuid.uuid7(),
            idempotency_key="k-1",
        )

    assert refusal.value.status_code == 409
    assert PlayerSession.objects.filter(playthrough=run).count() == 1


def test_an_edit_from_timed_to_duration_only_records_one_correction(
    owned_user, owned_library, game
):
    row = session_row(game, started_at=STARTED_AT, ended_at=ENDED_AT)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        row,
        _draft(
            row.playthrough,
            timing=DurationOnlyTiming(
                day=date(2026, 7, 1), duration=timedelta(hours=2)
            ),
        ),
        correlation_id=correlation_id,
    )

    row.refresh_from_db()
    assert row.timing_mode == "duration_only"
    assert row.stated_day == date(2026, 7, 1)
    assert _events(correlation_id) == ["library.playersession.timing_corrected"]


def test_an_unchanged_edit_records_no_event(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT, ended_at=ENDED_AT)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        row,
        _draft(
            row.playthrough,
            timing=TimedTiming(
                started_at=STARTED_AT, day_zone="Europe/Prague", ended_at=ENDED_AT
            ),
        ),
        correlation_id=correlation_id,
    )

    assert _events(correlation_id) == []


def test_a_note_only_edit_records_one_description(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT, ended_at=ENDED_AT)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        row,
        _draft(
            row.playthrough,
            timing=TimedTiming(
                started_at=STARTED_AT, day_zone="Europe/Prague", ended_at=ENDED_AT
            ),
            note="  boss fight ",
        ),
        correlation_id=correlation_id,
    )

    row.refresh_from_db()
    assert row.note == "boss fight"
    assert _events(correlation_id) == ["library.playersession.note_changed"]


def test_moving_the_run_records_one_move(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT, ended_at=ENDED_AT)
    other = Game.objects.create(library=owned_library, name="Celeste")
    other_run = tracked_run(owned_library, other)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        row,
        _draft(
            other_run,
            timing=TimedTiming(
                started_at=STARTED_AT, day_zone="Europe/Prague", ended_at=ENDED_AT
            ),
        ),
        correlation_id=correlation_id,
    )

    row.refresh_from_db()
    assert row.playthrough_id == other_run.pk
    assert _events(correlation_id) == ["library.playersession.moved"]


def test_finishing_stamps_the_browser_zone(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT)

    end_session(
        owned_user,
        row,
        ended_at=ENDED_AT,
        ended_at_zone="Asia/Tokyo",
        correlation_id=uuid.uuid7(),
    )

    row.refresh_from_db()
    assert row.ended_at == ENDED_AT
    assert row.ended_at_zone == "Asia/Tokyo"


def test_resetting_a_finished_row_is_refused(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT, ended_at=ENDED_AT)

    with pytest.raises(CommandFailed):
        reset_session(
            owned_user,
            row,
            started_at=timezone.now(),
            started_at_zone=None,
            correlation_id=uuid.uuid7(),
        )


def test_resetting_keeps_the_rows_day_zone_and_takes_the_browsers(
    owned_user, owned_library, game
):
    row = session_row(game, started_at=STARTED_AT)
    now = timezone.now().replace(microsecond=0)

    reset_session(
        owned_user,
        row,
        started_at=now,
        started_at_zone="Pacific/Honolulu",
        correlation_id=uuid.uuid7(),
    )

    row.refresh_from_db()
    assert row.started_at == now
    assert row.started_at_zone == "Pacific/Honolulu"
    assert row.day_zone == "Europe/Prague"


def test_removing_marks_the_row(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT)

    remove_session(owned_user, row, correlation_id=uuid.uuid7())

    row.refresh_from_db()
    assert row.removed_at is not None


def test_restoring_clears_the_mark(owned_user, owned_library, game):
    row = session_row(game, started_at=STARTED_AT)
    remove_session(owned_user, row, correlation_id=uuid.uuid7())
    correlation_id = uuid.uuid7()

    restore_session(owned_user, row, correlation_id=correlation_id)

    row.refresh_from_db()
    assert row.removed_at is None
    assert _events(correlation_id) == ["library.playersession.restored"]


def test_restoring_under_a_removed_run_is_answered(owned_user, owned_library, game):
    from stated_runs import another_run

    from games.writes.playthrough import remove_run

    row = session_row(game, started_at=STARTED_AT)
    remove_session(owned_user, row, correlation_id=uuid.uuid7())
    another_run(owned_user, game)
    remove_run(owned_user, row.playthrough, correlation_id=uuid.uuid7())

    with pytest.raises(CommandFailed) as refusal:
        restore_session(owned_user, row, correlation_id=uuid.uuid7())

    assert refusal.value.message == (
        "That playthrough was removed from your library. Restore it before "
        "changing its sessions."
    )
    row.refresh_from_db()
    assert row.removed_at is not None


def test_cloning_lands_on_the_ordinary_run_past_the_bucket(
    owned_user, owned_library, game
):
    """The latest row sits in the bucket; the clone does not."""
    ordinary = tracked_run(owned_library, game)
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=ordinary.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    device = Device.objects.create(library=owned_library, name="Deck")
    session_row(game, started_at=STARTED_AT, device=device, emulated=True)
    PlayerSession.objects.filter(playthrough=ordinary).update(playthrough=bucket)

    session_id = clone_session(
        owned_user,
        game,
        device_id=device.pk,
        emulated=True,
        correlation_id=uuid.uuid7(),
    )

    clone = PlayerSession.objects.get(pk=session_id)
    assert clone.playthrough_id == ordinary.pk
    assert clone.device_id == device.pk
    assert clone.emulated is True
    assert clone.timing_mode == "timed"
    assert clone.ended_at is None
    assert clone.note == ""


# --- Reclassifying, through the write path -----------------------------------


def _reclassified(user, session, correlation_id, key="one-conversion"):
    return reclassify_session(
        user,
        session,
        statement_from_session(session),
        idempotency_key=key,
        correlation_id=correlation_id,
    )


def test_reclassifying_answers_the_records_id(owned_user, owned_library, game):
    run = tracked_run(owned_library, game)
    row = session_row(game, started_at=STARTED_AT, duration_manual=timedelta(hours=9))
    correlation_id = uuid.uuid7()

    record_id = _reclassified(owned_user, row, correlation_id)

    assert HistoricalPlaytime.objects.get(pk=record_id).player_game_id == (
        run.player_game_id
    )
    assert _events(correlation_id) == [
        "library.historicalplaytime.created",
        "library.playersession.reclassified",
    ]


def test_the_same_key_records_one_record(owned_user, owned_library, game):
    tracked_run(owned_library, game)
    row = session_row(game, started_at=STARTED_AT, duration_manual=timedelta(hours=9))

    first = _reclassified(owned_user, row, uuid.uuid7())
    second = _reclassified(owned_user, row, uuid.uuid7())

    assert first == second
    assert HistoricalPlaytime.objects.count() == 1


def test_a_running_row_answers_the_commands_sentence(owned_user, owned_library, game):
    tracked_run(owned_library, game)
    row = session_row(game, started_at=STARTED_AT)

    with pytest.raises(CommandFailed) as refusal:
        reclassify_session(
            owned_user,
            row,
            statement_from_session(row)._replace(duration=timedelta(hours=1)),
            idempotency_key="running",
            correlation_id=uuid.uuid7(),
        )

    assert refusal.value.message == STILL_RUNNING


def test_undoing_returns_the_session(owned_user, owned_library, game):
    tracked_run(owned_library, game)
    row = session_row(game, started_at=STARTED_AT, duration_manual=timedelta(hours=9))
    record_id = _reclassified(owned_user, row, uuid.uuid7())
    correlation_id = uuid.uuid7()

    undo_reclassification(owned_user, row, correlation_id=correlation_id)

    row.refresh_from_db()
    assert row.removed_at is None
    assert HistoricalPlaytime.objects.get(pk=record_id).removed_at is not None
    assert _events(correlation_id) == [
        "library.historicalplaytime.removed",
        "library.playersession.restored",
    ]


def test_undoing_a_session_that_became_nothing_answers_a_sentence(
    owned_user, owned_library, game
):
    tracked_run(owned_library, game)
    row = session_row(game, started_at=STARTED_AT, duration_manual=timedelta(hours=9))

    with pytest.raises(CommandFailed) as refusal:
        undo_reclassification(owned_user, row, correlation_id=uuid.uuid7())

    assert refusal.value.message == NEVER_RECLASSIFIED
