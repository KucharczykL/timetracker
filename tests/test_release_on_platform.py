"""Which Release a copy moves to on a platform."""

import pytest
from entries import record_entry

from games.models import Edition, EditionKind, Game, Platform, Release
from games.reads.releases import (
    NoRelease,
    OnPlatform,
    SeveralReleases,
    release_on_platform,
)
from games.removal import remove

pytestmark = pytest.mark.django_db


@pytest.fixture
def ps5():
    return Platform.objects.create(name="PS5", group="Sony")


@pytest.fixture
def switch():
    return Platform.objects.create(name="Switch", group="Nintendo")


@pytest.fixture
def graph(owned_library, stated_graph, ps5):
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


@pytest.fixture
def copy(owned_library, graph):
    return record_entry(owned_library, graph.release)


def _answer(owned_library, copy, platform):
    return release_on_platform(
        owned_library, copy, None if platform is None else platform.pk
    )


def test_a_copy_on_the_platform_keeps_its_release(owned_library, copy, graph, ps5):
    assert _answer(owned_library, copy, ps5) == OnPlatform(graph.release)


def test_the_one_release_on_the_platform_answers(owned_library, copy, graph, switch):
    target = Release.objects.create(edition=graph.edition, platform=switch)

    assert _answer(owned_library, copy, switch) == OnPlatform(target)


def test_no_release_on_the_platform_answers_none(owned_library, copy, switch):
    assert _answer(owned_library, copy, switch) == NoRelease()


def test_the_copys_own_edition_wins(owned_library, copy, graph, switch):
    other = Edition.objects.create(game=graph.game, name="Deluxe")
    Release.objects.create(edition=other, platform=switch)
    own = Release.objects.create(edition=graph.edition, platform=switch)

    assert _answer(owned_library, copy, switch) == OnPlatform(own)


def test_another_edition_answers_where_the_own_holds_none(
    owned_library, copy, graph, switch
):
    other = Edition.objects.create(game=graph.game, name="Deluxe")
    target = Release.objects.create(edition=other, platform=switch)

    assert _answer(owned_library, copy, switch) == OnPlatform(target)


def test_two_releases_in_the_own_edition_are_several(
    owned_library, copy, graph, switch
):
    Release.objects.create(edition=graph.edition, platform=switch)
    Release.objects.create(edition=graph.edition, platform=switch)

    assert _answer(owned_library, copy, switch) == SeveralReleases()


def test_two_other_editions_are_several(owned_library, copy, graph, switch):
    for name in ("Deluxe", "Collector's"):
        edition = Edition.objects.create(game=graph.game, name=name)
        Release.objects.create(edition=edition, platform=switch)

    assert _answer(owned_library, copy, switch) == SeveralReleases()


def test_a_prerelease_edition_is_not_a_candidate(owned_library, copy, graph, switch):
    demo = Edition.objects.create(game=graph.game, kind=EditionKind.PRERELEASE)
    Release.objects.create(edition=demo, platform=switch)

    assert _answer(owned_library, copy, switch) == NoRelease()


def test_a_removed_release_is_not_a_candidate(owned_library, copy, graph, switch):
    remove(Release.objects.create(edition=graph.edition, platform=switch))

    assert _answer(owned_library, copy, switch) == NoRelease()


def test_a_removed_platform_has_no_candidate(owned_library, copy, graph, switch):
    Release.objects.create(edition=graph.edition, platform=switch)
    remove(switch)

    assert _answer(owned_library, copy, switch) == NoRelease()


def test_unspecified_answers_the_release_with_no_platform(owned_library, copy, graph):
    target = Release.objects.create(edition=graph.edition, platform=None)

    assert _answer(owned_library, copy, None) == OnPlatform(target)


def test_another_games_release_is_not_a_candidate(
    owned_library, copy, stated_graph, switch
):
    stated_graph(
        Game(name="Hades", library=owned_library), owned_library, platform=switch
    )

    assert _answer(owned_library, copy, switch) == NoRelease()
