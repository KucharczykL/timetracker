from datetime import UTC, datetime, timedelta

import pytest

from games.models import Game, Platform, Session

pytestmark = pytest.mark.django_db


def test_session_duration_querysets_partition_calculated_zero_rows(owned_library):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(library=owned_library, name="Hades", platform=platform)
    manual_only = Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 1, 1, 12, tzinfo=UTC),
        timestamp_end=datetime(2024, 1, 1, 12, tzinfo=UTC),
        duration_manual=timedelta(minutes=30),
    )
    elapsed = Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 1, 2, 12, tzinfo=UTC),
        timestamp_end=datetime(2024, 1, 2, 13, tzinfo=UTC),
    )

    assert list(Session.objects.only_manual()) == [manual_only]
    assert list(Session.objects.without_manual()) == [elapsed]


@pytest.mark.parametrize(
    "queryset",
    [Session.objects.only_manual(), Session.objects.without_manual()],
)
def test_session_duration_querysets_use_interval_equality(queryset):
    lookup = queryset.query.where.children[0]
    if hasattr(lookup, "children"):
        lookup = lookup.children[0]

    assert lookup.lookup_name == "exact"
    assert lookup.rhs == timedelta(0)
