"""Per-timestamp zone fields on Session: NULL semantics and the guarantee
that a stored zone never feeds back into duration or date-bucket math."""

from datetime import UTC, datetime, timedelta

import pytest
from django.apps import apps
from django.utils import timezone as django_timezone

from games.models import Game, Session

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


def test_no_other_model_carries_a_zone_column(db):
    """A zone is recorded for what a person attended, which is a session.

    Everything else is stamped by the server in one zone, so a column naming
    another would have nothing to hold.
    """
    for model in apps.get_app_config("games").get_models():
        if model is Session:
            continue
        field_names = {field.name for field in model._meta.get_fields()}
        assert not {name for name in field_names if name.endswith("_timezone")}, (
            f"{model.__name__} carries a zone column"
        )
