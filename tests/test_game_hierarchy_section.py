"""What Game detail says about Editions and Releases."""

import pytest
from django.contrib.auth import get_user_model

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="hierarchy-page", password="p")


@pytest.fixture
def library(user):
    return user.library


@pytest.fixture
def reader(client, user):
    client.force_login(user)

    def read(game):
        return client.get(game.get_absolute_url()).content.decode()

    return read


def one_release(library, *, platform=None, release_date=None, name=""):
    """A Game shaped the way the legacy form leaves one."""
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, name=name, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=release_date,
        is_default=True,
    )
    return game


def test_game_detail_reads_the_one_release_platform_and_date(library, reader):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = one_release(
        library, platform=platform, release_date=TemporalValue.from_month(1984, 6)
    )

    html = reader(game)

    assert "Platform" in html
    assert "Amiga" in html
    assert "Released" in html
    assert "June 1984" in html
    assert "1984-06" not in html


def test_game_detail_says_unspecified_for_a_release_with_no_platform(library, reader):
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Unspecified" in html


def test_game_detail_says_unknown_for_a_release_with_no_date(library, reader):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = one_release(library, platform=platform)

    html = reader(game)

    assert "Unknown" in html


def test_game_detail_reads_no_release_at_all_without_falling_over(library, reader):
    """A Game the service never touched still renders.

    Nothing but a test makes one, and a 500 here would hide
    every other assertion on the page.
    """
    game = Game.objects.create(library=library, name="Bare")

    html = reader(game)

    assert "Unspecified" in html
    assert "Unknown" in html


def test_game_detail_no_longer_reads_the_legacy_platform_column(library, reader):
    """The column stays; this page stops believing it.

    #889 drops it. Until then a Game may carry a column the
    graph disagrees with, and the graph is what a Release states.
    """
    stale = Platform.objects.create(library=library, name="Stale Column")
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(platform=stale)

    html = reader(game)

    assert "Stale Column" not in html


def test_game_detail_no_longer_shows_the_legacy_release_year(library, reader):
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(year_released=1999)

    html = reader(game)

    assert "Release year" not in html
    assert 'id="popover-year"' not in html


def test_game_detail_keeps_the_original_release_of_the_work(library, reader):
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(
        original_release_date=TemporalValue.from_year(1983)
    )

    html = reader(game)

    assert "Original release" in html
    assert "1983" in html
