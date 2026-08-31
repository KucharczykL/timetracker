"""What Game detail says about the graph."""

import pytest
from django.contrib.auth import get_user_model

from games.models import Edition, Game, Platform, Release
from games.removal import remove
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
    """The shape the legacy form leaves."""
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
    """A Game the service never touched renders."""
    game = Game.objects.create(library=library, name="Bare")

    html = reader(game)

    assert "Unspecified" in html
    assert "Unknown" in html


def test_game_detail_no_longer_reads_the_legacy_platform_column(library, reader):
    """The column stays; the page ignores it."""
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


def two_releases(library):
    """One unnamed Edition, two Releases: a table."""
    amiga = Platform.objects.create(library=library, name="Amiga")
    dos = Platform.objects.create(library=library, name="DOS")
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )
    Release.objects.create(
        edition=edition, platform=dos, release_date=TemporalValue.from_year(1988)
    )
    return game


def test_game_detail_tables_a_second_release(library, reader):
    game = two_releases(library)

    html = reader(game)

    assert "Releases" in html
    assert "Amiga" in html
    assert "DOS" in html
    assert "1988" in html


def test_game_detail_gives_one_unnamed_edition_no_heading(library, reader):
    """The Game's name above its only Edition."""
    game = two_releases(library)

    html = reader(game)

    assert html.count("Releases of this edition") == 1
    assert 'text-type-subheading text-heading">Elite</span>' not in html


def test_game_detail_heads_each_of_two_editions(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Edition.objects.create(game=game, name="Plus")
    Release.objects.create(edition=gold, is_default=True)

    html = reader(game)

    assert "Gold" in html
    assert "Plus" in html
    assert "No releases yet." in html


def test_game_detail_heads_an_unnamed_sibling_with_the_work(library, reader):
    """An unnamed Edition presents as the Game."""
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game, name="Plus")

    html = reader(game)

    assert 'text-type-subheading text-heading">Plus</span>' in html
    assert 'text-type-subheading text-heading">Elite</span>' in html


def test_game_detail_heads_a_lone_edition_that_states_its_own_name(library, reader):
    """The name that brings the section, printed."""
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Release.objects.create(edition=gold, platform=platform, is_default=True)

    html = reader(game)

    assert 'text-type-subheading text-heading">Gold</span>' in html


def test_game_detail_leaves_out_a_removed_edition(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    gone = Edition.objects.create(game=game, name="Withdrawn")
    remove(gone)

    html = reader(game)

    assert "Withdrawn" not in html
