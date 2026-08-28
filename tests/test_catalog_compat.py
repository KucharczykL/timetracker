import pytest
from django.core.exceptions import ValidationError

from games.catalog_compat import save_legacy_game_form
from games.catalog_writes import save_private_game
from games.external_references import save_external_reference
from games.forms import GameForm
from games.models import ExternalReference, Game, PlayerGameStatus, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def game_form(*, library, instance=None, **overrides) -> GameForm:
    data = {
        "name": "Legacy adapter game",
        "sort_name": "Adapter game, Legacy",
        "platform": "",
        "year_released": "2002",
        "original_year_released": "2001",
        "status": PlayerGameStatus.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
    }
    data.update(overrides)
    return GameForm(data=data, instance=instance, library=library)


def test_legacy_wikidata_create_canonicalizes_and_synchronizes(owned_library):
    form = game_form(library=owned_library, wikidata=" q123 ")

    assert form.is_valid()
    game = save_legacy_game_form(form)

    game.refresh_from_db()
    reference = ExternalReference.objects.get(
        provider="wikidata", entity_kind="game", provider_key="Q123"
    )
    assert game.wikidata == "Q123"
    assert reference.game_id == game.pk


def test_legacy_wikidata_unchanged_edit_retains_reference_identity(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    reference_id = ExternalReference.objects.get(game=game).pk

    edit_form = game_form(library=owned_library, instance=game)
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    assert ExternalReference.objects.get(game=game).pk == reference_id


def test_legacy_wikidata_changed_edit_replaces_the_mapping(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    old_reference = ExternalReference.objects.get(game=game)

    edit_form = game_form(library=owned_library, instance=game, wikidata="Q456")
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    assert not ExternalReference.objects.filter(pk=old_reference.pk).exists()
    assert (
        ExternalReference.objects.get(
            provider="wikidata", entity_kind="game", provider_key="Q456"
        ).game_id
        == game.pk
    )


def test_legacy_wikidata_clearing_removes_the_mapping(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)

    edit_form = game_form(library=owned_library, instance=game, wikidata="   ")
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    game.refresh_from_db()
    assert game.wikidata == ""
    assert not ExternalReference.objects.filter(game=game).exists()


def test_legacy_wikidata_conflict_rolls_back_the_game_graph_and_old_reference(
    owned_library,
):
    create_form = game_form(library=owned_library, name="Before conflict")
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    old_reference = ExternalReference.objects.get(game=game)
    edition_id = game.editions.get(is_default=True).pk
    release_id = game.editions.get(is_default=True).releases.get(is_default=True).pk

    edit_form = game_form(
        library=owned_library,
        instance=game,
        name="After conflict",
        wikidata="Q456",
    )
    assert edit_form.is_valid()
    owner = Game.objects.create(library=owned_library, name="Conflict owner")
    save_external_reference(provider="wikidata", provider_key="Q456", target=owner)

    with pytest.raises(ValidationError, match="already maps to another catalog target"):
        save_legacy_game_form(edit_form)

    stored_game = Game.objects.get(pk=game.pk)
    assert (stored_game.name, stored_game.wikidata) == ("Before conflict", "Q123")
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert Release.objects.get(pk=release_id).edition_id == edition_id
    assert ExternalReference.objects.get(pk=old_reference.pk).game_id == game.pk


def test_legacy_wikidata_reference_failure_rolls_back_new_and_existing_graphs(
    owned_library, monkeypatch
):
    existing_form = game_form(library=owned_library, name="Before reference failure")
    assert existing_form.is_valid()
    existing_game = save_legacy_game_form(existing_form)
    old_reference = ExternalReference.objects.get(game=existing_game)
    edition_id = existing_game.editions.get(is_default=True).pk
    release_id = (
        existing_game.editions.get(is_default=True).releases.get(is_default=True).pk
    )

    def fail_reference_save(*args, **kwargs):
        raise RuntimeError("forced reference save failure")

    monkeypatch.setattr(ExternalReference, "save", fail_reference_save)
    new_form = game_form(
        library=owned_library,
        name="New reference failure",
        wikidata="Q789",
    )
    assert new_form.is_valid()
    with pytest.raises(RuntimeError, match="forced reference save failure"):
        save_legacy_game_form(new_form)

    edit_form = game_form(
        library=owned_library,
        instance=existing_game,
        name="After reference failure",
        wikidata="Q456",
    )
    assert edit_form.is_valid()
    with pytest.raises(RuntimeError, match="forced reference save failure"):
        save_legacy_game_form(edit_form)

    stored_game = Game.objects.get(pk=existing_game.pk)
    assert not Game.objects.filter(name="New reference failure").exists()
    assert (stored_game.name, stored_game.wikidata) == (
        "Before reference failure",
        "Q123",
    )
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert Release.objects.get(pk=release_id).edition_id == edition_id
    assert (
        ExternalReference.objects.get(pk=old_reference.pk).game_id == existing_game.pk
    )


def test_save_private_game_does_not_create_a_legacy_wikidata_reference(owned_library):
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Durable writer only",
            wikidata="Q123",
        ),
        original_release_date=None,
        release_date=TemporalValue.from_year(2001),
        platform=None,
    )

    assert graph.game.wikidata == "Q123"
    assert not ExternalReference.objects.filter(game=graph.game).exists()
