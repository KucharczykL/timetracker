"""The request-free write path for a record."""

import uuid
from datetime import timedelta

import pytest
from session_rows import tracked_run

from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.events.dispatch import CommandOutcome
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryEvent,
)
from games.writes.historical_playtime import (
    record_historical_playtime,
    remove_historical_playtime,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Hades")


def _statement(run) -> HistoricalPlaytimeStatement:
    return HistoricalPlaytimeStatement(
        duration=timedelta(hours=100),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=(run.pk,),
        device_id=None,
        emulated=False,
        note="",
    )


def test_a_repeat_under_one_key_records_one_row(owned_user, owned_library, game):
    run = tracked_run(owned_library, game)

    first = record_historical_playtime(
        owned_user,
        _statement(run),
        idempotency_key="k-1",
        correlation_id=uuid.uuid7(),
    )
    second = record_historical_playtime(
        owned_user,
        _statement(run),
        idempotency_key="k-1",
        correlation_id=uuid.uuid7(),
    )

    assert first == second
    assert HistoricalPlaytime.objects.count() == 1


def test_a_blank_key_is_refused_rather_than_minted_over(
    owned_user, owned_library, game
):
    """A caller that stated a key gets a refusal, never a second write."""
    run = tracked_run(owned_library, game)

    with pytest.raises(ValueError):
        record_historical_playtime(
            owned_user,
            _statement(run),
            idempotency_key="",
            correlation_id=uuid.uuid7(),
        )

    assert not HistoricalPlaytime.objects.exists()


def _a_record(owned_user, owned_library, game) -> HistoricalPlaytime:
    run = tracked_run(owned_library, game)
    record_id = record_historical_playtime(
        owned_user,
        _statement(run),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )
    return HistoricalPlaytime.objects.get(pk=record_id)


def test_an_idempotent_removal_writes_one_event_and_names_its_source(
    owned_user, owned_library, game
):
    """The runner's two facts: the key absorbs, the source rides."""
    record = _a_record(owned_user, owned_library, game)
    source = {"bulk": {"action": "historicalplaytime.remove"}}

    first = remove_historical_playtime(
        owned_user,
        record,
        correlation_id=uuid.uuid7(),
        idempotency_key="one-removal",
        source_metadata=source,
    )
    repeat = remove_historical_playtime(
        owned_user,
        record,
        correlation_id=uuid.uuid7(),
        idempotency_key="one-removal",
        source_metadata=source,
    )

    assert first.outcome is CommandOutcome.APPENDED
    assert repeat.outcome is CommandOutcome.REPLAYED
    removals = LibraryEvent.objects.filter(
        aggregate_id=record.pk, event_type="library.historicalplaytime.removed"
    )
    assert [event.source_metadata for event in removals] == [source]


def test_removing_a_removed_record_under_a_new_key_answers_unchanged(
    owned_user, owned_library, game
):
    """What tells the runner a row was already so."""
    record = _a_record(owned_user, owned_library, game)
    remove_historical_playtime(owned_user, record, correlation_id=uuid.uuid7())

    repeat = remove_historical_playtime(owned_user, record, correlation_id=uuid.uuid7())

    assert repeat.outcome is CommandOutcome.UNCHANGED
