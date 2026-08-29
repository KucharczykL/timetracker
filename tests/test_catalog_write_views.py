from html.parser import HTMLParser

import pytest
from django.urls import reverse

from games.external_references import save_external_reference
from games.forms import GameForm
from games.models import (
    Edition,
    ExternalReference,
    Game,
    Platform,
    PlayerGameStatus,
    Release,
)
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


class AnchorCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href = None
            self._text = []


def game_payload(**overrides):
    payload = {
        "name": "Legacy form game",
        "sort_name": "Form game, Legacy",
        "platform": "",
        "year_released": "2002",
        "original_year_released": "2001",
        "status": PlayerGameStatus.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
    }
    payload.update(overrides)
    return payload


def inject_wikidata_conflict_after_validation(monkeypatch, *, library, provider_key):
    original_is_valid = GameForm.is_valid
    conflict_injected = False

    def is_valid_with_competing_write(form):
        nonlocal conflict_injected
        is_valid = original_is_valid(form)
        if is_valid and not conflict_injected:
            competing_game = Game.objects.create(
                library=library, name=f"Concurrent {provider_key} owner"
            )
            save_external_reference(
                provider="wikidata",
                provider_key=provider_key,
                target=competing_game,
            )
            conflict_injected = True
        return is_valid

    monkeypatch.setattr(GameForm, "is_valid", is_valid_with_competing_write)


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
    #: Status and mastery are the projection's, not this graph's.
    assert (game.sort_name, game.wikidata) == ("Form game, Legacy", "Q123")


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


def test_game_views_canonicalize_wikidata_on_add_and_edit(
    client, owned_user, owned_library
):
    client.force_login(owned_user)
    add_response = client.post(
        reverse("games:add_game"), game_payload(wikidata=" q123 ")
    )

    assert add_response.status_code == 302
    game = Game.objects.get(name="Legacy form game")
    assert game.wikidata == "Q123"
    assert ExternalReference.objects.get(game=game).provider_key == "Q123"

    edit_response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(wikidata=" q456 "),
    )

    assert edit_response.status_code == 302
    game.refresh_from_db()
    assert game.wikidata == "Q456"
    assert ExternalReference.objects.get(game=game).provider_key == "Q456"


def test_game_wikidata_form_field_and_list_column_render_the_canonical_link(
    client, owned_user, owned_library
):
    game = Game.objects.create(
        library=owned_library, name="Linked Wikidata", wikidata="Q123"
    )
    Game.objects.create(library=owned_library, name="Blank Wikidata", wikidata="")
    client.force_login(owned_user)

    add_response = client.get(reverse("games:add_game"))
    list_response = client.get(reverse("games:list_games"))
    html = list_response.content.decode()
    anchors = AnchorCollector()
    anchors.feed(html)

    assert add_response.status_code == 200
    assert 'name="wikidata"' in add_response.content.decode()
    assert "Wikidata" in html
    assert (
        "https://www.wikidata.org/wiki/Q123",
        "Q123",
    ) in anchors.anchors
    assert 'href="https://www.wikidata.org/wiki/Q123"' in html
    assert ExternalReference.objects.filter(game=game).count() == 0
    assert "https://www.wikidata.org/wiki/" not in html.replace(
        'href="https://www.wikidata.org/wiki/Q123"', ""
    )


def test_game_add_rejects_invalid_wikidata_without_writes(
    client, owned_user, owned_library
):
    client.force_login(owned_user)

    response = client.post(reverse("games:add_game"), game_payload(wikidata="Q0"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="wikidata"' in html
    assert "Enter a Wikidata entity ID such as Q123." in html
    assert not Game.objects.filter(library=owned_library).exists()
    assert not ExternalReference.objects.exists()


def test_game_add_rejects_a_duplicate_wikidata_key_as_a_field_error(
    client, owned_user, owned_library
):
    existing = Game.objects.create(library=owned_library, name="Existing Wikidata")
    save_external_reference(provider="wikidata", provider_key="Q123", target=existing)
    client.force_login(owned_user)

    response = client.post(reverse("games:add_game"), game_payload(wikidata=" q123 "))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="wikidata"' in html
    assert "This Wikidata entity ID already belongs to another game." in html
    assert Game.objects.filter(library=owned_library).count() == 1
    assert ExternalReference.objects.get(game=existing).provider_key == "Q123"


def test_game_add_renders_a_write_time_wikidata_conflict_as_a_field_error(
    client, monkeypatch, owned_user, owned_library
):
    """A key claimed after validation must not turn the add request into a 500."""
    client.force_login(owned_user)
    inject_wikidata_conflict_after_validation(
        monkeypatch, library=owned_library, provider_key="Q123"
    )

    response = client.post(reverse("games:add_game"), game_payload())

    assert response.status_code == 200
    assert "This Wikidata entity ID already belongs to another game." in (
        response.content.decode()
    )
    assert not Game.objects.filter(name="Legacy form game").exists()
    assert ExternalReference.objects.get(provider_key="Q123").game.name == (
        "Concurrent Q123 owner"
    )


def test_game_edit_renders_a_write_time_wikidata_conflict_and_rolls_back(
    client, monkeypatch, owned_user, owned_library
):
    """A key claimed after validation must preserve the edited Game's old graph."""
    game = Game.objects.create(
        library=owned_library, name="Original name", wikidata="Q123"
    )
    original_reference = save_external_reference(
        provider="wikidata", provider_key="Q123", target=game
    )
    client.force_login(owned_user)
    inject_wikidata_conflict_after_validation(
        monkeypatch, library=owned_library, provider_key="Q456"
    )

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(name="Changed name", wikidata="Q456"),
    )

    assert response.status_code == 200
    assert "This Wikidata entity ID already belongs to another game." in (
        response.content.decode()
    )
    game.refresh_from_db()
    original_reference.refresh_from_db()
    assert (game.name, game.wikidata) == ("Original name", "Q123")
    assert original_reference.game_id == game.pk
    assert ExternalReference.objects.get(provider_key="Q456").game.name == (
        "Concurrent Q456 owner"
    )
