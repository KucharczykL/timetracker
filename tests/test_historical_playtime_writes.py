"""The request-free write path for a record."""

import uuid
from datetime import timedelta

import pytest
from session_rows import tracked_run

from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.models import Game, HistoricalPlaytime, HistoricalPlaytimeProvenance
from games.writes.historical_playtime import record_historical_playtime

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
