"""What Game detail says about the graph."""

import re
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from games.models import Edition, Game, Platform, PlayerGame, PlayerGameStatus, Release
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


def editions_table(html: str) -> str:
    """The Editions table, from its caption to its end."""
    start = html.index("Editions of ")
    return html[start : html.index("</table>", start)]


def edition_rows(html: str) -> list[str]:
    """One string per body row of that table."""
    body = editions_table(html).split("<tbody", 1)[1]
    return re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL)


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

    assert "Editions" in html
    assert "Amiga (1984), DOS (1988)" in html


def test_game_detail_gives_every_edition_one_table(library, reader):
    """One table over the whole graph, thus one caption."""
    game = two_releases(library)
    Edition.objects.create(game=game, name="Plus")

    html = reader(game)

    assert html.count("<caption") == 1


def test_game_detail_names_each_of_two_editions(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Edition.objects.create(game=game, name="Plus")
    Release.objects.create(edition=gold, is_default=True)

    html = reader(game)

    assert "Gold" in html
    assert "Plus" in html
    assert "No releases yet." in html


def test_game_detail_names_an_unnamed_sibling_after_the_work(library, reader):
    """An unnamed Edition presents as the Game."""
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game, name="Plus")

    rows = edition_rows(reader(game))

    assert len(rows) == 2
    assert "Elite" in rows[0]
    assert "Plus" in rows[1]


def test_game_detail_names_a_lone_edition_that_states_its_own_name(library, reader):
    """The name that brings the section, printed."""
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Release.objects.create(edition=gold, platform=platform, is_default=True)

    rows = edition_rows(reader(game))

    assert len(rows) == 1
    assert "Gold" in rows[0]
    #: No date, thus the Platform stands alone.
    assert "Amiga<" in rows[0]


def test_game_detail_says_the_editions_section_is_under_construction(library, reader):
    """The shape is a placeholder, thus it says so."""
    game = two_releases(library)

    html = reader(game)

    assert "Under construction." in html
    assert "no playtime is shown here" in html


def test_game_detail_says_nothing_under_construction_on_a_plain_game(library, reader):
    """No section, no notice: an ordinary Game is finished."""
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Under construction." not in html


def test_game_detail_names_the_editions_table_after_the_game(library, reader):
    """A caption id is hashed, thus two alike collide.

    The scroll region names its caption through `aria-labelledby`,
    so the caption is keyed on the Game rather than on a name two
    Games may share.
    """
    game = Game.objects.create(library=library, name="Elite")
    first = Edition.objects.create(game=game, is_default=True)
    second = Edition.objects.create(game=game)
    Release.objects.create(edition=first, is_default=True)
    Release.objects.create(edition=second)

    html = reader(game)
    ids = re.findall(r'<caption[^>]*id="([^"]+)"', html)

    assert len(ids) == 1
    assert f'aria-labelledby="{ids[0]}"' in html


def test_game_detail_leaves_out_a_removed_edition(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    gone = Edition.objects.create(game=game, name="Withdrawn")
    remove(gone)

    html = reader(game)

    assert "Withdrawn" not in html


# --- one table over every Edition ---


def test_game_detail_gives_each_edition_one_row(library, reader):
    """A row per Edition, and one cell naming every Platform under it."""
    amiga = Platform.objects.create(library=library, name="Amiga")
    dos = Platform.objects.create(library=library, name="DOS")
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Release.objects.create(
        edition=gold,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )
    Release.objects.create(
        edition=gold, platform=dos, release_date=TemporalValue.from_year(1988)
    )
    Edition.objects.create(game=game, name="Plus")

    rows = edition_rows(reader(game))

    assert len(rows) == 2
    assert "Gold" in rows[0]
    assert "Amiga (1984), DOS (1988)" in rows[0]
    assert "Plus" in rows[1]


def test_the_editions_table_sends_every_edit_to_the_game_form(library, reader):
    """The section reads; the form writes."""
    game = two_releases(library)

    html = reader(game)

    assert reverse("games:edit_game", args=[game.pk]) in editions_table(html)
    assert "Add edition" not in html
    assert "Add release" not in html
    assert "Remove" not in editions_table(html)


def test_a_plain_game_gets_no_editions_table(library, reader):
    """One unnamed Edition and one Release: the header says it all."""
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Editions of " not in html


def test_the_notice_says_a_second_platform_stops_here(library, reader):
    """The games list draws one Release, and the page admits it."""
    game = two_releases(library)

    html = reader(game)

    assert "does not reach the games list" in html


# --- the one control a private game carries ---


def test_a_plain_game_offers_no_catalog_control(library, reader):
    """The header reads the Release; the form edits it."""
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Edit release" not in html
    assert "Add release" not in html
    assert "Add edition" not in html


def test_a_shared_game_offers_no_edit_at_all(library, reader):
    """Nobody writes another library's catalog."""
    shared = Game.objects.create(library=None, name="Shared")
    edition = Edition.objects.create(game=shared, name="Gold", is_default=True)
    Release.objects.create(edition=edition, is_default=True)
    Edition.objects.create(game=shared, name="Plus")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.PLAYED,
    )

    table = editions_table(reader(shared))

    assert "Gold" in table
    assert "Actions" not in table
    assert reverse("games:edit_game", args=[shared.pk]) not in table
