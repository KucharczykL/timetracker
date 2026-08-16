"""Per-timestamp zone fields on Session: NULL semantics and the guarantee
that a stored zone never feeds back into duration or date-bucket math."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone as django_timezone

from games.models import Game, GameStatusChange, Session

pytestmark = pytest.mark.django_db


def _make_session(game: Game, **overrides) -> Session:
    defaults = {
        "game": game,
        "timestamp_start": datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        "timestamp_end": datetime(2026, 7, 1, 14, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Session.objects.create(**defaults)


def test_zone_fields_default_to_null(owned_library):
    session = _make_session(Game.objects.create(library=owned_library, name="Hades"))
    session.refresh_from_db()
    assert session.timestamp_start_timezone is None
    assert session.timestamp_end_timezone is None


def test_zone_fields_store_iana_names(owned_library):
    session = _make_session(
        Game.objects.create(library=owned_library, name="Hades"),
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Europe/Prague",
    )
    session.refresh_from_db()
    assert session.timestamp_start_timezone == "Asia/Tokyo"
    assert session.timestamp_end_timezone == "Europe/Prague"


def test_duration_calculated_ignores_stored_zones(owned_library):
    """duration_calculated is instant arithmetic over UTC values; a stored
    zone must not change it (spec: 'Calculation — no change, verified')."""
    game = Game.objects.create(library=owned_library, name="Hades")
    plain = _make_session(game)
    zoned = _make_session(
        game,
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    plain.refresh_from_db()
    zoned.refresh_from_db()
    assert plain.duration_calculated == timedelta(hours=2, minutes=30)
    assert zoned.duration_calculated == plain.duration_calculated


def test_date_bucketing_ignores_stored_zones(owned_library):
    """__date bucketing resolves in the *active* timezone, never the
    session's own zone — a zoned row lands in the same bucket as its twin."""
    game = Game.objects.create(library=owned_library, name="Hades")
    _make_session(game)
    _make_session(game, timestamp_start_timezone="Pacific/Kiritimati")
    with django_timezone.override("UTC"):
        bucketed = Session.objects.filter(
            timestamp_start__date=datetime(2026, 7, 1, tzinfo=UTC).date()
        )
        assert bucketed.count() == 2


def test_game_status_change_has_no_zone_fields(db):
    """Audit records are server-stamped, not attended events; the zone
    columns are deliberately Session-only."""
    field_names = {field.name for field in GameStatusChange._meta.get_fields()}
    assert "timestamp_start_timezone" not in field_names
    assert "timestamp_timezone" not in field_names
