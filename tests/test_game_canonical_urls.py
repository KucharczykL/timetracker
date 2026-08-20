import pytest
from django.urls import NoReverseMatch, reverse

from games.models import Game

pytestmark = pytest.mark.django_db


def test_game_absolute_url_uses_its_uuid_and_normalized_current_name(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="  Tom Clancy's H.A.W.X. 2  ",
    )

    assert game.url_slug == "tom-clancys-hawx-2"
    assert game.get_absolute_url() == (f"/tracker/game/{game.id}/tom-clancys-hawx-2/")


def test_game_absolute_url_has_a_nonempty_fallback_for_an_unrepresentable_name(
    owned_library,
):
    game = Game.objects.create(library=owned_library, name="🎮")

    assert game.url_slug == "game"
    assert game.get_absolute_url() == f"/tracker/game/{game.id}/game/"


def test_canonical_game_url_renders_the_detail_page(client, owned_user, owned_library):
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_library, name="Canonical Game")

    response = client.get(game.get_absolute_url())

    assert response.status_code == 200


@pytest.mark.parametrize(
    "route_name", ["games:view_game_by_uuid", "games:view_game_legacy"]
)
def test_retired_game_compatibility_route_names_do_not_reverse(
    owned_library, route_name
):
    game = Game.objects.create(library=owned_library, name="Retired Route")

    with pytest.raises(NoReverseMatch):
        reverse(route_name, args=[game.id])


@pytest.mark.parametrize("retired_suffix", ["/", "/view"])
def test_retired_game_compatibility_paths_return_404_without_redirecting(
    client,
    owned_user,
    owned_library,
    retired_suffix,
):
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_library, name="Retired Route")

    response = client.get(f"/tracker/game/{game.id}{retired_suffix}")

    assert response.status_code == 404
    assert "Location" not in response


def test_view_remains_a_valid_canonical_slug(client, owned_user, owned_library):
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_library, name="View")

    response = client.get(f"/tracker/game/{game.id}/view/")

    assert response.status_code == 200


def test_stale_slug_redirects_permanently_and_preserves_the_query_string(
    client,
    owned_user,
    owned_library,
):
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_library, name="Current Name")
    stale_url = f"/tracker/game/{game.id}/former-name/"

    response = client.get(
        stale_url,
        {"origin": "/tracker/game/list", "page": "2"},
    )

    assert response.status_code == 301
    assert response["Location"] == (
        f"/tracker/game/{game.id}/current-name/?origin=%2Ftracker%2Fgame%2Flist&page=2"
    )


def test_renaming_a_game_makes_its_former_slug_redirect(
    client, owned_user, owned_library
):
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_library, name="Former Name")
    former_url = f"/tracker/game/{game.id}/former-name/"

    game.name = "Replacement Name"
    game.save()

    response = client.get(former_url)
    assert response.status_code == 301
    assert response["Location"] == (f"/tracker/game/{game.id}/replacement-name/")


@pytest.mark.parametrize("suffix", ["/", "/view", "/invented-slug/"])
def test_game_canonicalization_does_not_reveal_foreign_library_games(
    client,
    owned_user,
    django_user_model,
    suffix,
):
    foreign_user = django_user_model.objects.create_user(username="foreign-url-owner")
    foreign_game = Game.objects.create(
        library=foreign_user.library,
        name="Secret Foreign Game",
    )
    client.force_login(owned_user)

    response = client.get(f"/tracker/game/{foreign_game.id}{suffix}")

    assert response.status_code == 404
    assert "Location" not in response
