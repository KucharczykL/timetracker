"""What one library sees under one Game."""

import pytest
from django.contrib.auth import get_user_model

from games.models import Edition, Game, Platform, Release
from games.reads.catalog_hierarchy import game_hierarchy
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def library():
    return get_user_model().objects.create_user(username="hierarchy-reader").library


@pytest.fixture
def stranger():
    return get_user_model().objects.create_user(username="hierarchy-stranger").library


def test_game_hierarchy_groups_releases_under_their_editions(library):
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold")
    plus = Edition.objects.create(game=game, name="Plus")
    gold_release = Release.objects.create(edition=gold)
    plus_release = Release.objects.create(edition=plus)

    entries = game_hierarchy(game, library)

    assert [(entry.edition, entry.releases) for entry in entries] == [
        (gold, (gold_release,)),
        (plus, (plus_release,)),
    ]


def test_game_hierarchy_puts_the_default_first(library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, name="Alpha")
    standard = Edition.objects.create(game=game, name="Zulu", is_default=True)

    entries = game_hierarchy(game, library)

    assert entries[0].edition == standard


def test_game_hierarchy_orders_releases_by_their_earliest_day(library):
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game)
    later = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1985)
    )
    earlier = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1984)
    )
    undated = Release.objects.create(edition=edition)

    entries = game_hierarchy(game, library)

    assert entries[0].releases == (earlier, later, undated)


def test_game_hierarchy_leaves_out_a_removed_edition_and_a_removed_release(library):
    game = Game.objects.create(library=library, name="Elite")
    kept = Edition.objects.create(game=game, name="Kept")
    gone = Edition.objects.create(game=game, name="Gone")
    kept_release = Release.objects.create(edition=kept)
    gone_release = Release.objects.create(edition=kept)
    Release.objects.create(edition=gone)
    remove(gone)
    remove(gone_release)

    entries = game_hierarchy(game, library)

    assert entries == ((kept, (kept_release,)),)


def test_game_hierarchy_gives_another_library_nothing(library, stranger):
    game = Game.objects.create(library=library, name="Private")
    edition = Edition.objects.create(game=game)
    Release.objects.create(edition=edition)

    assert game_hierarchy(game, stranger) == ()


def test_game_hierarchy_shows_a_shared_game_to_every_library(library, stranger):
    shared = Game.objects.create(name="Shared")
    edition = Edition.objects.create(game=shared)
    release = Release.objects.create(edition=edition)

    for reader in (library, stranger):
        assert game_hierarchy(shared, reader) == ((edition, (release,)),)


def test_game_hierarchy_carries_the_platform_and_the_name_with_it(
    library, django_assert_num_queries
):
    """Two queries, whatever the graph holds."""
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    first = Edition.objects.create(game=game, name="Gold")
    second = Edition.objects.create(game=game, name="Plus")
    Release.objects.create(edition=first, platform=platform)
    Release.objects.create(edition=second)

    with django_assert_num_queries(2):
        entries = game_hierarchy(game, library)
        read = [
            (entry.edition.display_name, entry.releases[0].platform)
            for entry in entries
        ]

    assert read == [("Gold", platform), ("Plus", None)]
