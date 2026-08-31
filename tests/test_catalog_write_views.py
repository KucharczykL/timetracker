from html.parser import HTMLParser

import pytest
from django.urls import reverse

from games.catalog_writes import LAST_EDITION
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
from games.removal import remove
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)


def temporal_payload(prefix: str, **parts: str) -> dict[str, str]:
    """The inputs one temporal control posts."""
    return {temporal_input_name(prefix, key): value for key, value in parts.items()}


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
    """The Game form and, on Add, the inline Release row beside it."""
    payload = {
        "name": "Legacy form game",
        "sort_name": "Form game, Legacy",
        "platform": "",
        "status": PlayerGameStatus.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
    }
    payload |= temporal_payload("original_release_date", kind="date", start_year="2001")
    payload |= temporal_payload("release_date", kind="date", start_year="2002")
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
    #: Status and mastery belong to the projection.
    assert (game.sort_name, game.wikidata) == ("Form game, Legacy", "Q123")


def test_edit_game_states_then_clears_the_original_release(
    client, owned_user, owned_library
):
    first = Platform.objects.create(name="First")
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
        game_payload(name="Edited")
        | temporal_payload("original_release_date", kind="date", start_year="2010"),
    )
    assert response.status_code == 302
    game.refresh_from_db()
    release = game.editions.get(is_default=True).releases.get(is_default=True)
    assert (game.editions.get(is_default=True).pk, release.pk) == (
        edition_id,
        release_id,
    )
    assert game.original_release_date == TemporalValue.from_year(2010)
    assert game.original_year_released == 2010

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(name="Edited")
        | temporal_payload("original_release_date", kind="", start_year=""),
    )
    assert response.status_code == 302
    game.refresh_from_db()
    release.refresh_from_db()
    assert game.original_release_date is None
    assert game.original_year_released is None
    assert Edition.objects.filter(game=game).count() == 1
    assert Release.objects.filter(edition_id=edition_id).count() == 1


def test_add_game_states_the_platform_through_the_inline_release(
    client, owned_user, owned_library
):
    platform = Platform.objects.create(name="Amiga")
    client.force_login(owned_user)
    payload = game_payload(platform=str(platform.pk)) | temporal_payload(
        "release_date", kind="date", start_year="1984", start_month="6"
    )

    client.post(reverse("games:add_game"), payload)

    game = Game.objects.get(name=payload["name"])
    release = Release.objects.get(edition__game=game)
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_month(1984, 6)
    #: The flat columns shadow it until #889.
    assert game.platform_id == platform.pk
    assert game.year_released == 1984


def test_add_game_states_the_original_release_at_its_own_precision(
    client, owned_user, owned_library
):
    client.force_login(owned_user)
    payload = game_payload() | temporal_payload(
        "original_release_date", kind="date", start_year="1983", start_month="9"
    )

    client.post(reverse("games:add_game"), payload)

    game = Game.objects.get(name=payload["name"])
    assert game.original_release_date == TemporalValue.from_month(1983, 9)
    assert game.original_year_released == 1983


def test_edit_game_keeps_a_month_on_the_original_release(
    client, owned_user, owned_library
):
    """The trap issue comment 1 named: an unrelated edit downgraded it."""
    client.force_login(owned_user)
    client.post(
        reverse("games:add_game"),
        game_payload(name="Elite")
        | temporal_payload(
            "original_release_date", kind="date", start_year="1983", start_month="9"
        ),
    )
    game = Game.objects.get(name="Elite")

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(name="Elite II")
        | temporal_payload(
            "original_release_date", kind="date", start_year="1983", start_month="9"
        ),
    )

    game.refresh_from_db()
    assert game.original_release_date == TemporalValue.from_month(1983, 9)


def test_edit_game_leaves_the_default_release_alone(client, owned_user, owned_library):
    """An edit states no Release, thus it changes none."""
    platform = Platform.objects.create(name="Amiga")
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )
    client.force_login(owned_user)

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_payload(name="Elite", wikidata=""),
    )

    release = Release.objects.get(edition=edition)
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_year(1984)


def test_add_game_hosts_the_temporal_element(client, owned_user, owned_library):
    client.force_login(owned_user)

    html = client.get(reverse("games:add_game")).content.decode()

    assert "<temporal-field" in html
    assert "dist/elements/temporal-field.js" in html


# --- the six catalog routes -------------------------------------------------


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="other-catalog-owner", password="p"
    ).library


@pytest.fixture
def signed_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_add_edition_writes_one_and_returns_to_the_game(signed_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    Edition.objects.create(game=game, is_default=True)

    response = signed_in.post(
        reverse("games:add_edition", args=[game.pk]), {"name": "Gold"}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == game.get_absolute_url()
    assert Edition.objects.filter(game=game, name="Gold").exists()


def test_edit_edition_states_the_whole_row(signed_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    edition = Edition.objects.create(game=game, name="Gold")

    signed_in.post(reverse("games:edit_edition", args=[edition.pk]), {"name": "Plus"})

    edition.refresh_from_db()
    assert edition.name == "Plus"


def test_remove_edition_stamps_rather_than_destroys(signed_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    edition = Edition.objects.create(game=game, name="Gold")

    signed_in.post(reverse("games:remove_edition", args=[edition.pk]))

    edition.refresh_from_db()
    assert edition.removed_at is not None


def test_removing_the_last_edition_says_why_on_the_page(signed_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)

    response = signed_in.post(reverse("games:remove_edition", args=[edition.pk]))

    assert response.status_code == 409
    assert LAST_EDITION in response.content.decode()
    edition.refresh_from_db()
    assert edition.removed_at is None


def test_add_release_writes_one_under_its_edition(signed_in, owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    posted = {"platform": str(platform.pk)} | temporal_payload(
        "release_date", kind="date", start_year="1984"
    )

    signed_in.post(reverse("games:add_release", args=[edition.pk]), posted)

    release = Release.objects.get(edition=edition)
    assert release.release_date == TemporalValue.from_year(1984)
    #: The flat columns followed it.
    game.refresh_from_db()
    assert (game.platform_id, game.year_released) == (platform.pk, 1984)


def test_edit_release_states_the_whole_row(signed_in, owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )

    signed_in.post(
        reverse("games:edit_release", args=[release.pk]),
        {"platform": "", "is_default": "on"}
        | temporal_payload("release_date", kind="date", start_year="1985"),
    )

    release.refresh_from_db()
    assert release.release_date == TemporalValue.from_year(1985)
    assert release.platform_id is None


def test_remove_release_stamps_rather_than_destroys(signed_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(edition=edition, is_default=True)
    second = Release.objects.create(edition=edition)

    signed_in.post(reverse("games:remove_release", args=[second.pk]))

    second.refresh_from_db()
    assert second.removed_at is not None


def test_a_shared_game_answers_404_to_every_catalog_route(signed_in):
    shared = Game.objects.create(library=None, name="Shared")
    edition = Edition.objects.create(game=shared, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)

    for url in (
        reverse("games:add_edition", args=[shared.pk]),
        reverse("games:edit_edition", args=[edition.pk]),
        reverse("games:remove_edition", args=[edition.pk]),
        reverse("games:add_release", args=[edition.pk]),
        reverse("games:edit_release", args=[release.pk]),
        reverse("games:remove_release", args=[release.pk]),
    ):
        assert signed_in.get(url).status_code == 404, url


def test_another_library_cannot_reach_an_edition(signed_in, other_library):
    game = Game.objects.create(library=other_library, name="Theirs")
    edition = Edition.objects.create(game=game, is_default=True)

    assert (
        signed_in.get(reverse("games:edit_edition", args=[edition.pk])).status_code
        == 404
    )


def test_a_removed_game_hides_its_editions_from_the_routes(signed_in, owned_library):
    """A Release reads its ancestors' marks, thus a removed Game hides both."""
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    remove(game)

    assert (
        signed_in.get(reverse("games:add_release", args=[edition.pk])).status_code
        == 404
    )


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
