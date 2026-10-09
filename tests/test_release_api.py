"""The Release picker's search and its create row."""

import uuid
from unittest.mock import patch

import pytest
from django.http import Http404
from graphs import default_graph

from games.api_creation import RowRefused
from games.catalog_compat import LEGACY_IDENTITY_TAKEN
from games.catalog_release import (
    PRERELEASE_DEFAULT,
    SHARED_GAME_RELEASE,
    PlatformRelease,
    platform_refusal,
    release_on,
)
from games.catalog_writes import EditionState, state_catalog_graph
from games.models import Edition, EditionKind, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def ps5():
    return Platform.objects.create(name="PS5", group="Sony")


@pytest.fixture
def graph(owned_library, ps5):
    return default_graph(
        Game(name="Tunic", library=owned_library),
        owned_library,
        platform=ps5,
        release_date=TemporalValue.parse("2021"),
    )


def _search(client, game, q: str = ""):
    return client.get("/api/releases/search", {"game_id": str(game.pk), "q": q})


def _create(client, game, name: str):
    return client.post(
        "/api/releases/",
        {"name": name, "game_id": str(game.pk)},
        content_type="application/json",
    )


def test_search_answers_the_games_releases_labelled(client, owned_user, graph):
    client.force_login(owned_user)

    response = _search(client, graph.game)

    assert response.status_code == 200
    assert response.json() == [
        {"value": str(graph.release.pk), "label": "PS5 · 2021", "data": {}}
    ]


def test_a_label_names_a_named_edition_and_an_unspecified_platform(
    client, owned_user, owned_library
):
    written = default_graph(Game(name="Hades", library=owned_library), owned_library)
    Edition.objects.filter(pk=written.edition.pk).update(name="Deluxe")
    client.force_login(owned_user)

    labels = [option["label"] for option in _search(client, written.game).json()]

    assert labels == ["Unspecified · Deluxe"]


def test_search_narrows_on_the_text(client, owned_user, graph):
    client.force_login(owned_user)

    assert _search(client, graph.game, "ps").json()
    assert _search(client, graph.game, "xbox").json() == []


def test_search_never_answers_another_librarys_game(client, graph, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    assert _search(client, graph.game).status_code == 404


def test_create_states_a_release_on_the_typed_platform(client, owned_user, graph):
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    client.force_login(owned_user)

    response = _create(client, graph.game, "  switch ")

    assert response.status_code == 201
    release = Release.objects.get(edition=graph.edition, platform=switch)
    assert response.json() == {"value": str(release.pk), "label": "Switch"}
    graph.release.refresh_from_db()
    assert graph.release.is_default


def test_create_answers_the_release_that_stands(client, owned_user, graph):
    client.force_login(owned_user)

    response = _create(client, graph.game, "PS5")

    assert response.status_code == 201
    assert response.json()["value"] == str(graph.release.pk)
    assert Release.objects.filter(edition=graph.edition).count() == 1


def test_create_keeps_the_editions_name(client, owned_user, graph):
    Edition.objects.filter(pk=graph.edition.pk).update(name="Deluxe")
    Platform.objects.create(name="Switch", group="Nintendo")
    client.force_login(owned_user)

    _create(client, graph.game, "Switch")

    graph.edition.refresh_from_db()
    assert graph.edition.name == "Deluxe"


def test_an_unknown_platform_is_refused(client, owned_user, graph):
    client.force_login(owned_user)

    response = _create(client, graph.game, "Dreamcast")

    assert response.status_code == 422
    assert "Platforms page" in response.json()["detail"]


def test_two_platforms_of_that_name_are_refused_naming_both(
    client, owned_user, owned_library, graph
):
    Platform.objects.create(name="Switch", group="Nintendo")
    Platform.objects.create(name="switch", group="Handheld", library=owned_library)
    client.force_login(owned_user)

    response = _create(client, graph.game, "Switch")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "shared, Nintendo" in detail
    assert "yours, Handheld" in detail


def test_a_shared_game_is_refused_with_its_sentence(client, owned_user, ps5):
    shared = Game.objects.create(name="Celeste")
    client.force_login(owned_user)

    response = _create(client, shared, "PS5")

    assert response.status_code == 422
    assert response.json()["detail"] == SHARED_GAME_RELEASE


def test_another_librarys_game_is_absent(client, graph, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    assert _create(client, graph.game, "PS5").status_code == 404


def test_a_flat_identity_collision_is_refused_not_a_defect(
    client, owned_user, owned_library, ps5
):
    bare = Game.objects.create(name="Tunic", library=owned_library)
    state_catalog_graph(
        game=bare,
        library=owned_library,
        editions=[EditionState(key="edition", is_default=True)],
    )
    Game.objects.create(name="Tunic", library=owned_library, platform=ps5)
    client.force_login(owned_user)

    response = _create(client, bare, "PS5")

    assert response.status_code == 422
    assert response.json()["detail"] == LEGACY_IDENTITY_TAKEN
    assert not Release.objects.filter(edition__game=bare).exists()


def test_an_edition_without_releases_takes_the_new_one_as_default(
    client, owned_user, owned_library, ps5
):
    bare = Game.objects.create(name="Hades", library=owned_library)
    state_catalog_graph(
        game=bare,
        library=owned_library,
        editions=[EditionState(key="edition", is_default=True, releases=())],
    )
    client.force_login(owned_user)

    _create(client, bare, "PS5")

    release = Release.objects.get(edition__game=bare)
    assert release.is_default
    bare.refresh_from_db()
    assert bare.platform == ps5


def test_create_refuses_an_unknown_key(client, owned_user, graph):
    client.force_login(owned_user)

    response = client.post(
        "/api/releases/",
        {"name": "PS5", "game_id": str(graph.game.pk), "year": 2021},
        content_type="application/json",
    )

    assert response.status_code == 422


def test_create_refuses_a_game_whose_editions_have_no_default(
    client, owned_user, graph
):
    Edition.objects.filter(pk=graph.edition.pk).update(is_default=False)
    Edition.objects.create(game=graph.game, name="Deluxe", is_default=False)
    Platform.objects.create(name="Switch", group="Nintendo")
    client.force_login(owned_user)

    response = _create(client, graph.game, "Switch")

    assert response.status_code == 422
    assert not Release.objects.filter(
        edition__game=graph.game, platform__name="Switch"
    ).exists()


def test_release_on_reuses_a_live_release_and_states_a_new_one(
    owned_library, graph, ps5
):
    switch = Platform.objects.create(name="Switch", group="Nintendo")

    standing = release_on(owned_library, graph.game, ps5)
    made = release_on(owned_library, graph.game, switch)
    again = release_on(owned_library, graph.game, switch)

    assert standing == (graph.release, False)
    assert made.created
    assert made.release.edition == graph.edition
    assert again == (made.release, False)


@pytest.mark.untracked_games
def test_release_on_a_game_gone_since_the_fetch_answers_404(owned_library, ps5):
    fetched = Game.objects.create(library=owned_library, name="Gone")
    Game.objects.filter(pk=fetched.pk).delete()

    with pytest.raises(Http404, match="No such game."):
        release_on(owned_library, fetched, ps5)


@pytest.mark.untracked_games
def test_release_on_a_game_gone_with_its_releases_answers_404(
    owned_library, graph, ps5
):
    """The standing Release went with the Game."""
    Game.objects.filter(pk=graph.game.pk).delete()

    with pytest.raises(Http404, match="No such game."):
        release_on(owned_library, graph.game, ps5)


def test_a_release_gone_at_the_read_back_answers_404(owned_library, graph, ps5):
    gone = PlatformRelease(Release(pk=uuid.uuid7()), created=True)

    with (
        patch("games.catalog_release.write_and_mirror", return_value=gone),
        pytest.raises(Http404, match="No such game."),
    ):
        release_on(owned_library, graph.game, ps5)


@pytest.mark.untracked_games
def test_release_on_refuses_a_prerelease_default_with_the_sentence_the_form_shows(
    owned_library, ps5
):
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    game = Game(name="Demo Game", library=owned_library)
    default_graph(
        game, owned_library, platform=ps5, edition_kind=EditionKind.PRERELEASE
    )

    with pytest.raises(RowRefused) as refused:
        release_on(owned_library, game, switch)

    assert refused.value.sentence == PRERELEASE_DEFAULT
    assert platform_refusal(game, switch) == PRERELEASE_DEFAULT
