"""NULL is the single representation of "no platform" / "no device" (issue
#290): no sentinel rows are auto-created, deletes SET_NULL instead of
cascading or substituting, and the conditional unique constraint keeps the
platformless-dedup guarantee unique_together can't provide (SQLite treats
NULLs as pairwise distinct)."""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from games.models import Device, Game, Platform, Purchase, Session

pytestmark = pytest.mark.django_db


def test_game_without_platform_stays_null():
    game = Game.objects.create(name="Homebrew")
    game.refresh_from_db()
    assert game.platform is None
    assert Platform.objects.count() == 0


def test_session_without_device_stays_null():
    game = Game.objects.create(name="Homebrew")
    session = Session.objects.create(
        game=game, timestamp_start=timezone.now(), duration_manual=timedelta(0)
    )
    session.refresh_from_db()
    assert session.device is None
    assert Device.objects.count() == 0


def test_purchase_without_platform_stays_null_currency_still_defaults():
    game = Game.objects.create(name="Homebrew")
    purchase = Purchase.objects.create(
        date_purchased=timezone.now().date(), price_currency=""
    )
    purchase.games.add(game)
    purchase.refresh_from_db()
    assert purchase.platform is None
    assert purchase.price_currency  # DEFAULT_CURRENCY fallback survives


def test_platform_delete_sets_null_and_keeps_purchases():
    platform = Platform.objects.create(name="Steam")
    game = Game.objects.create(name="Hades", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=timezone.now().date(), platform=platform
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


def test_device_delete_sets_null_on_sessions():
    device = Device.objects.create(name="Deck", type=Device.HANDHELD)
    game = Game.objects.create(name="Hades")
    session = Session.objects.create(
        game=game,
        device=device,
        timestamp_start=timezone.now(),
        duration_manual=timedelta(0),
    )

    device.delete()

    session.refresh_from_db()
    assert session.device is None


def test_platformless_duplicate_name_year_rejected():
    Game.objects.create(name="Tetris", year_released=1984)
    with pytest.raises(IntegrityError):
        Game.objects.create(name="Tetris", year_released=1984)


def test_exclude_platform_keeps_platformless_games():
    # SQL NOT IN never matches NULL; the criterion layer adds the isnull arm so
    # "exclude platform X" keeps games with no platform (the visible behavior
    # the sentinel used to provide by accident).
    from common.criteria import Modifier, MultiCriterion
    from games.filters import GameFilter

    steam = Platform.objects.create(name="Steam")
    Game.objects.create(name="Hades", platform=steam)
    platformless = Game.objects.create(name="Homebrew")

    excluded = GameFilter(
        platform=MultiCriterion(value=[steam.id], modifier=Modifier.EXCLUDES)
    )
    assert list(Game.objects.filter(excluded.to_q())) == [platformless]


def test_same_name_year_allowed_across_platforms_and_against_platformless():
    platform_a = Platform.objects.create(name="Game Boy")
    platform_b = Platform.objects.create(name="NES")
    Game.objects.create(name="Tetris", year_released=1984)
    Game.objects.create(name="Tetris", year_released=1984, platform=platform_a)
    Game.objects.create(name="Tetris", year_released=1984, platform=platform_b)
    assert Game.objects.count() == 3
