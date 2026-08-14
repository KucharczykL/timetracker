from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.models import (
    Device,
    FilterPreset,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
    UserLibrary,
    UserLibraryPreferences,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def libraries():
    user_model = get_user_model()
    owner_a = user_model.objects.create_user(username="library-a")
    owner_b = user_model.objects.create_user(username="library-b")
    return UserLibrary.objects.get(user=owner_a), UserLibrary.objects.get(user=owner_b)


def test_direct_and_derived_records_filter_by_library(libraries):
    library_a, library_b = libraries
    device_a = Device.objects.create(library=library_a, name="A device")
    Device.objects.create(library=library_b, name="B device")
    platform_a = Platform.objects.create(library=library_a, name="A platform")
    game_a = Game.objects.create(library=library_a, name="A game", platform=platform_a)
    game_b = Game.objects.create(library=library_b, name="B game")
    purchase_a = Purchase.objects.create(
        library=library_a,
        date_purchased=datetime(2025, 1, 1, tzinfo=UTC).date(),
        price_currency="CZK",
    )
    Purchase.objects.create(
        library=library_b,
        date_purchased=datetime(2025, 1, 1, tzinfo=UTC).date(),
        price_currency="CZK",
    )
    FilterPreset.objects.create(library=library_a, name="A preset", mode="games")
    FilterPreset.objects.create(library=library_b, name="B preset", mode="games")
    session_a = Session.objects.create(
        game=game_a,
        device=device_a,
        timestamp_start=datetime(2025, 1, 1, tzinfo=UTC),
    )
    Session.objects.create(
        game=game_b, timestamp_start=datetime(2025, 1, 1, tzinfo=UTC)
    )
    event_a = PlayEvent.objects.create(game=game_a)
    GameStatusChange.objects.create(game=game_a, new_status=Game.Status.PLAYED)

    assert Game.objects.for_library(library_a).get() == game_a
    assert Purchase.objects.for_library(library_a).get() == purchase_a
    assert Device.objects.for_library(library_a).get() == device_a
    assert FilterPreset.objects.for_library(library_a).get().name == "A preset"
    assert Session.objects.for_library(library_a).get() == session_a
    assert PlayEvent.objects.for_library(library_a).get() == event_a
    assert GameStatusChange.objects.for_library(library_a).count() == 1


def test_session_requires_a_game():
    with pytest.raises(IntegrityError):
        Session.objects.create(timestamp_start=datetime(2025, 1, 1, tzinfo=UTC))


def test_game_names_are_unique_only_within_a_library(libraries):
    library_a, library_b = libraries
    Game.objects.create(library=library_a, name="Same", year_released=2025)
    Game.objects.create(library=library_b, name="Same", year_released=2025)

    with pytest.raises(IntegrityError):
        Game.objects.create(library=library_a, name="Same", year_released=2025)


def test_platform_visibility_and_normalized_duplicate_rejection(libraries):
    library_a, library_b = libraries
    shared = Platform.objects.create(name=" Steam ", group=" PC ")
    private_a = Platform.objects.create(library=library_a, name="A private")
    private_b = Platform.objects.create(library=library_b, name="B private")

    visible = Platform.objects.visible_to(library_a)
    assert visible.contains(shared)
    assert visible.contains(private_a)
    assert not visible.contains(private_b)

    with pytest.raises(IntegrityError), transaction.atomic():
        Platform.objects.create(name="steam", group="pc")
    with pytest.raises(ValidationError):
        Platform.objects.create(library=library_a, name="STEAM", group="PC")
    Platform.objects.create(library=library_b, name=" a PRIVATE ", group="")


def test_library_preference_device_changes_only_update_timestamp_on_change(libraries):
    library_a, _ = libraries
    device = Device.objects.create(library=library_a, name="Default")
    unchanged_at = timezone.now() - timedelta(days=1)
    preferences = UserLibraryPreferences.objects.create(
        library=library_a,
        default_device=device,
        updated_at=unchanged_at,
    )

    assert preferences.library_id == library_a.pk
    assert preferences.pk == library_a.pk
    assert not preferences.set_default_device(device)
    preferences.refresh_from_db()
    assert preferences.updated_at == unchanged_at

    assert preferences.set_default_device(None)
    preferences.refresh_from_db()
    assert preferences.default_device_id is None
    assert preferences.updated_at > unchanged_at
