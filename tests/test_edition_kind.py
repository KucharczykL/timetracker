import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from entries import record_entry

from games.catalog_release import release_on_platform
from games.catalog_writes import (
    SHARED_GAME,
    EditionState,
    ReleaseState,
    state_catalog_graph,
)
from games.models import Edition, EditionKind, Game, Platform, Release
from games.reads.releases import edition_words, release_label
from games.views.library_cards import release_words

pytestmark = pytest.mark.django_db


def _state(game, library, *, name="", kind: EditionKind | None = EditionKind.FULL):
    return state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                edition=Edition.objects.filter(game=game).first(),
                name=name,
                kind=kind,
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=Release.objects.filter(edition__game=game).first(),
                        is_default=True,
                    ),
                ),
            )
        ],
    )


@pytest.fixture
def game(owned_library, stated_graph):
    return stated_graph(Game(library=owned_library, name="Demo game"), owned_library)


def test_a_kind_change_alone_writes(owned_library, game):
    _state(game.game, owned_library, kind=EditionKind.PRERELEASE)

    game.edition.refresh_from_db()
    assert game.edition.kind == EditionKind.PRERELEASE


def test_an_unstated_kind_keeps_the_stored_one(owned_library, game):
    Edition.objects.filter(pk=game.edition.pk).update(kind=EditionKind.PRERELEASE)

    _state(game.game, owned_library, kind=None)

    game.edition.refresh_from_db()
    assert game.edition.kind == EditionKind.PRERELEASE


def test_a_release_on_a_new_platform_keeps_a_prerelease(owned_library, game):
    Edition.objects.filter(pk=game.edition.pk).update(kind=EditionKind.PRERELEASE)
    Platform.objects.create(library=owned_library, name="Amiga")

    release_on_platform(owned_library, game.game.pk, "Amiga")

    game.edition.refresh_from_db()
    assert game.edition.kind == EditionKind.PRERELEASE


def test_a_new_edition_takes_its_stated_kind(owned_library):
    written = _state(
        Game.objects.create(library=owned_library, name="Beta only"),
        owned_library,
        kind=EditionKind.PRERELEASE,
    )

    assert written.editions[0].edition.kind == EditionKind.PRERELEASE


def test_a_shared_game_s_edition_kind_is_refused(owned_library):
    shared = Game.objects.create(library=None, name="Shared")

    with pytest.raises(ValidationError) as refused:
        _state(shared, owned_library, kind=EditionKind.PRERELEASE)

    assert SHARED_GAME in refused.value.messages


@pytest.mark.django_db(transaction=True)
def test_the_kind_round_trips_through_the_game_form(
    client, owned_user, stated_graph, game_post
):
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Round trip"), owned_user.library
    )
    posted = game_post("Round trip")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-kind"] = "prerelease"
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    url = reverse("games:edit_game", args=[graph.game.pk])

    assert client.post(url, data=posted).status_code == 302

    graph.edition.refresh_from_db()
    assert graph.edition.kind == EditionKind.PRERELEASE
    page = client.get(url).content.decode()
    assert 'name="edition-0-kind"' in page
    assert '<option value="prerelease" selected>' in page


def test_edition_words_name_an_unnamed_prerelease():
    assert edition_words(Edition(name="Gold")) == "Gold"
    assert edition_words(Edition(kind=EditionKind.PRERELEASE)) == "Prerelease"
    assert edition_words(Edition(name="Beta", kind=EditionKind.PRERELEASE)) == "Beta"
    assert edition_words(Edition()) == ""


def test_the_release_label_says_prerelease(owned_library, game):
    owned_platform = Platform.objects.create(library=owned_library, name="Amiga")
    Edition.objects.filter(pk=game.edition.pk).update(kind=EditionKind.PRERELEASE)
    Release.objects.filter(pk=game.release.pk).update(platform=owned_platform)
    release = Release.objects.select_related("edition", "platform").get(
        pk=game.release.pk
    )

    assert release_label(release) == f"{owned_platform.name} · Prerelease"


def test_a_prerelease_copy_says_prerelease(owned_library, game):
    Edition.objects.filter(pk=game.edition.pk).update(kind=EditionKind.PRERELEASE)
    game.release.edition.refresh_from_db()

    entry = record_entry(owned_library, game.release)

    assert release_words(entry) == "Unspecified · Prerelease"


def test_a_lone_prerelease_edition_brings_the_editions_table(
    client, owned_user, stated_graph
):
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Only a demo"), owned_user.library
    )
    Edition.objects.filter(pk=graph.edition.pk).update(kind=EditionKind.PRERELEASE)

    page = client.get(graph.game.get_absolute_url()).content.decode()

    table = page[page.index("Editions of Only a demo") :]
    assert ">Prerelease</span>" in table[: table.index("</table>")]
