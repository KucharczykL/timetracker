"""Backfilling the baseline events a library's tracked games fold from."""

from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from django.utils import timezone

from games.backfill.playergame import (
    LEGACY_STATUS_TO_PLAYER_STATUS,
    UnmappedLegacyStatus,
    player_status_for,
    transition_effective_time,
)
from games.models import Game, PlayerGameStatus


def test_every_legacy_status_letter_is_mapped():
    #: A sixth letter added to Game.Status fails here rather than at run time.
    assert set(LEGACY_STATUS_TO_PLAYER_STATUS) == set(Game.Status.values)


def test_the_map_names_the_statuses_the_charter_names():
    assert LEGACY_STATUS_TO_PLAYER_STATUS == {
        "u": PlayerGameStatus.UNPLAYED,
        "p": PlayerGameStatus.PLAYED,
        "f": PlayerGameStatus.COMPLETED,
        "r": PlayerGameStatus.RETIRED,
        "a": PlayerGameStatus.ABANDONED,
    }


def test_shelved_has_no_legacy_source():
    assert PlayerGameStatus.SHELVED not in LEGACY_STATUS_TO_PLAYER_STATUS.values()


def test_an_unknown_letter_is_refused_by_name():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_a_null_timestamp_stays_unknown():
    #: The charter puts an undated transition in approximate history only.
    assert transition_effective_time(None).is_unknown


def test_a_dated_timestamp_becomes_the_local_day():
    #: 23:30 UTC is already the next day in Europe/Prague.
    timestamp = datetime(2023, 6, 2, 23, 30, tzinfo=datetime_timezone.utc)
    expected = timezone.localtime(timestamp).date().isoformat()
    assert transition_effective_time(timestamp).serialize() == expected


def test_a_dated_timestamp_is_day_precision_not_a_range():
    timestamp = timezone.now() - timedelta(days=400)
    value = transition_effective_time(timestamp)
    assert value.is_range is False
    assert value.has_known_day is True
