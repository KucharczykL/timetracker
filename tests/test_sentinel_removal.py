"""NULL is the single representation of "no platform" / "no device" (issue
#290): no sentinel rows are auto-created, deletes SET_NULL instead of
cascading or substituting, and the conditional unique constraint keeps the
platformless-dedup guarantee that ordinary uniqueness cannot provide when the
platform is NULL."""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from games.models import Device, Game, Platform, PlayerGameStatus, Purchase, Session

pytestmark = pytest.mark.django_db


def test_game_without_platform_stays_null(owned_library):
    game = Game.objects.create(library=owned_library, name="Homebrew")
    game.refresh_from_db()
    assert game.platform is None
    assert Platform.objects.count() == 0


def test_session_without_device_stays_null(owned_library):
    game = Game.objects.create(library=owned_library, name="Homebrew")
    session = Session.objects.create(
        game=game, timestamp_start=timezone.now(), duration_manual=timedelta(0)
    )
    session.refresh_from_db()
    assert session.device is None
    assert Device.objects.count() == 0


def test_purchase_without_platform_stays_null_with_explicit_currency(
    owned_library,
):
    game = Game.objects.create(library=owned_library, name="Homebrew")
    purchase = Purchase.objects.create(
        library=owned_library,
        date_purchased=timezone.now().date(),
        price_currency="CZK",
    )
    purchase.games.add(game)
    purchase.refresh_from_db()
    assert purchase.platform is None
    assert purchase.price_currency == "CZK"


def test_platform_delete_sets_null_and_keeps_purchases(owned_library):
    platform = Platform.objects.create(name="Steam")
    game = Game.objects.create(library=owned_library, name="Hades", platform=platform)
    purchase = Purchase.objects.create(
        price_currency="CZK",
        library=owned_library,
        date_purchased=timezone.now().date(),
        platform=platform,
    )
    purchase.games.add(game)

    platform.delete()

    # The old CASCADE on Purchase.platform would have destroyed the purchase
    # (and its price history) here.
    assert Purchase.objects.count() == 1
    game.refresh_from_db()
    purchase.refresh_from_db()
    assert game.platform is None
    assert purchase.platform is None


def test_device_delete_sets_null_on_sessions(owned_library):
    device = Device.objects.create(
        library=owned_library, name="Deck", type=Device.HANDHELD
    )
    game = Game.objects.create(library=owned_library, name="Hades")
    session = Session.objects.create(
        game=game,
        device=device,
        timestamp_start=timezone.now(),
        duration_manual=timedelta(0),
    )

    device.delete()

    session.refresh_from_db()
    assert session.device is None


def test_platformless_duplicate_name_year_rejected(owned_library):
    Game.objects.create(library=owned_library, name="Tetris", year_released=1984)
    with pytest.raises(IntegrityError):
        Game.objects.create(library=owned_library, name="Tetris", year_released=1984)


def test_platformless_duplicate_via_add_game_form_shows_error(
    client, django_user_model
):
    # The conditional UniqueConstraint must surface as a form error, not an
    # IntegrityError 500. The year left the form with #969, so the pair is
    # stated by the inline Release row and guarded by the mirror.
    from django.urls import reverse

    from games.catalog_compat import LEGACY_IDENTITY_TAKEN
    from timetracker.temporal import temporal_input_name

    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    Game.objects.create(library=user.library, name="Tetris", year_released=1984)

    response = client.post(
        reverse("games:add_game"),
        {
            "name": "Tetris",
            "sort_name": "",
            "platform": "",
            "status": PlayerGameStatus.UNPLAYED,
            "wikidata": "",
            temporal_input_name("release_date", "kind"): "date",
            temporal_input_name("release_date", "start_year"): "1984",
        },
    )

    assert response.status_code == 200  # re-rendered form, not a redirect/500
    assert LEGACY_IDENTITY_TAKEN in response.content.decode()
    assert Game.objects.count() == 1


def test_exclude_platform_keeps_platformless_games(owned_library):
    # "Exclude platform X" keeps games with no platform — the visible behavior
    # the sentinel used to provide by accident, now stated explicitly in the
    # criterion's Q tree (issue #290).
    from common.criteria import Modifier, UUIDMultiCriterion
    from games.filters import GameFilter

    steam = Platform.objects.create(name="Steam")
    Game.objects.create(library=owned_library, name="Hades", platform=steam)
    platformless = Game.objects.create(library=owned_library, name="Homebrew")

    excluded = GameFilter(
        platform=UUIDMultiCriterion(value=[steam.id], modifier=Modifier.EXCLUDES)
    )
    assert list(Game.objects.filter(excluded.to_q())) == [platformless]


def test_same_name_year_allowed_across_platforms_and_against_platformless(
    owned_library,
):
    platform_a = Platform.objects.create(name="Game Boy")
    platform_b = Platform.objects.create(name="NES")
    Game.objects.create(library=owned_library, name="Tetris", year_released=1984)
    Game.objects.create(
        library=owned_library,
        name="Tetris",
        year_released=1984,
        platform=platform_a,
    )
    Game.objects.create(
        library=owned_library,
        name="Tetris",
        year_released=1984,
        platform=platform_b,
    )
    assert Game.objects.count() == 3
