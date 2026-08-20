import pytest
from django.urls import reverse

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def game_payload(**overrides):
    payload = {
        "name": "Legacy form game",
        "sort_name": "Form game, Legacy",
        "platform": "",
        "year_released": "2002",
        "original_year_released": "2001",
        "status": Game.Status.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
    }
    payload.update(overrides)
    return payload


def test_add_game_writes_legacy_and_default_catalog_graph(
    client, owned_user, owned_library
):
    platform = Platform.objects.create(name="PC")
    client.force_login(owned_user)
    response = client.post(
        reverse("games:add_game"),
        game_payload(platform=str(platform.pk)),
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("games:list_games")
    game = Game.objects.get(name="Legacy form game")
    edition = game.editions.get(is_default=True)
    release = edition.releases.get(is_default=True)
    assert game.library == owned_library
    assert game.original_release_date == TemporalValue.from_year(2001)
    assert release.release_date == TemporalValue.from_year(2002)
    assert release.platform == platform
    assert (game.original_year_released, game.year_released, game.platform) == (
        2001,
        2002,
        platform,
    )
    assert (game.sort_name, game.status, game.mastered, game.wikidata) == (
        "Form game, Legacy",
        Game.Status.PLAYED,
        True,
        "Q123",
    )


def test_edit_game_updates_then_clears_legacy_and_canonical_values(
    client, owned_user, owned_library
):
    first = Platform.objects.create(name="First")
    second = Platform.objects.create(name="Second")
    client.force_login(owned_user)
    client.post(
        reverse("games:add_game"),
        game_payload(name="Editable", platform=str(first.pk)),
    )
    game = Game.objects.get(name="Editable")
    edition_id = game.editions.get(is_default=True).pk
    release_id = game.editions.get(is_default=True).releases.get(is_default=True).pk

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(
            name="Edited",
            platform=str(second.pk),
            original_year_released="2010",
            year_released="2011",
        ),
    )
    assert response.status_code == 302
    game.refresh_from_db()
    release = game.editions.get(is_default=True).releases.get(is_default=True)
    assert (game.editions.get(is_default=True).pk, release.pk) == (
        edition_id,
        release_id,
    )
    assert game.original_release_date == TemporalValue.from_year(2010)
    assert release.release_date == TemporalValue.from_year(2011)
    assert release.platform == second

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(
            name="Edited",
            platform="",
            original_year_released="",
            year_released="",
        ),
    )
    assert response.status_code == 302
    game.refresh_from_db()
    release.refresh_from_db()
    assert (game.original_year_released, game.year_released, game.platform) == (
        None,
        None,
        None,
    )
    assert game.original_release_date is None
    assert release.release_date is None
    assert release.platform is None
    assert Edition.objects.filter(game=game).count() == 1
    assert Release.objects.filter(edition_id=edition_id).count() == 1
