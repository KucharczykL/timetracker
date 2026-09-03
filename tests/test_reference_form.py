"""The External references area, as one bound thing."""

import pytest
from django.urls import reverse

from games.external_references import KEY_TAKEN, state_external_references
from games.models import ExternalReference, Game
from games.reference_form import ReferenceSetForm, reference_field_name

pytestmark = pytest.mark.django_db


def test_the_registry_states_the_fields(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    form = ReferenceSetForm(None, target=game, library=owned_library)

    assert list(form.fields) == ["reference_wikidata"]
    assert form.fields["reference_wikidata"].label == "Wikidata"
    assert "Q123" in form.fields["reference_wikidata"].help_text


def test_an_unbound_form_reads_the_live_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    form = ReferenceSetForm(None, target=game, library=owned_library)

    assert form.initial["reference_wikidata"] == "Q123"


def test_a_malformed_key_lands_on_its_own_box(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    form = ReferenceSetForm(
        {"reference_wikidata": "banana"}, target=game, library=owned_library
    )

    assert not form.is_valid()
    assert "Q123" in form.errors["reference_wikidata"][0]


def test_a_valid_key_is_written(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    form = ReferenceSetForm(
        {"reference_wikidata": " q123 "}, target=game, library=owned_library
    )
    assert form.is_valid(), form.errors

    form.write()

    assert (
        ExternalReference.objects.get(game=game, removed_at=None).provider_key == "Q123"
    )


def test_a_blank_box_removes_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    form = ReferenceSetForm(
        {"reference_wikidata": ""}, target=game, library=owned_library
    )
    assert form.is_valid(), form.errors

    form.write()

    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()


def test_a_service_refusal_answers_onto_its_box(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )
    form = ReferenceSetForm(
        {"reference_wikidata": "Q123"}, target=second, library=owned_library
    )
    assert form.is_valid(), form.errors

    with pytest.raises(Exception) as refusal:
        form.write()

    assert form.answer(refusal.value)
    assert form.errors["reference_wikidata"] == [KEY_TAKEN]


def test_a_refusal_naming_no_provider_is_a_non_field_error(owned_library):
    shared = Game.objects.create(name="Elite", library=None)
    form = ReferenceSetForm(
        {"reference_wikidata": "Q123"}, target=shared, library=owned_library
    )
    assert form.is_valid(), form.errors

    with pytest.raises(Exception) as refusal:
        form.write()

    assert form.answer(refusal.value)
    assert form.errors["__all__"]


def test_the_field_name_is_the_provider(owned_library):
    assert reference_field_name("wikidata") == "reference_wikidata"


#: The view dispatches a PlayerGame command, and
#: `run_in_transaction` refuses to nest.
view_tests = pytest.mark.django_db(transaction=True)


@view_tests
def test_add_game_writes_the_key_the_area_states(client, owned_user, game_post):
    client.force_login(owned_user)

    client.post(
        reverse("games:add_game"),
        game_post("Elite", reference_wikidata="q123"),
    )

    game = Game.objects.get(name="Elite")
    assert game.wikidata == "Q123"
    assert (
        ExternalReference.objects.get(game=game, removed_at=None).provider_key == "Q123"
    )


@view_tests
def test_a_taken_key_answers_on_the_game_form(client, owned_user, game_post):
    client.force_login(owned_user)
    held = Game.objects.create(name="Held", library=owned_user.library)
    state_external_references(
        target=held, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    response = client.post(
        reverse("games:add_game"),
        game_post("Elite", reference_wikidata="Q123"),
    )

    assert response.status_code == 200
    assert KEY_TAKEN in response.content.decode()
    assert not Game.objects.filter(name="Elite").exists()


@view_tests
def test_clearing_the_box_removes_the_reference(client, owned_user, game_post):
    client.force_login(owned_user)
    game = Game.objects.create(name="Elite", library=owned_user.library)
    state_external_references(
        target=game, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_post("Elite", reference_wikidata=""),
    )

    game.refresh_from_db()
    assert game.wikidata == ""
    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()


@view_tests
def test_an_unchanged_key_keeps_the_reference_it_had(client, owned_user, game_post):
    """A resubmit states the same key, thus nothing is written."""
    client.force_login(owned_user)
    game = Game.objects.create(name="Elite", library=owned_user.library)
    state_external_references(
        target=game, library=owned_user.library, keys={"wikidata": "Q123"}
    )
    reference_id = ExternalReference.objects.get(game=game, removed_at=None).pk

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_post("Elite", reference_wikidata="Q123"),
    )

    assert ExternalReference.objects.get(game=game, removed_at=None).pk == reference_id


@view_tests
def test_a_taken_key_takes_the_rename_back(client, owned_user, game_post):
    """One transaction: the reference refuses and the columns follow."""
    client.force_login(owned_user)
    held = Game.objects.create(name="Held", library=owned_user.library)
    state_external_references(
        target=held, library=owned_user.library, keys={"wikidata": "Q123"}
    )
    game = Game.objects.create(name="Before conflict", library=owned_user.library)

    response = client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_post("After conflict", reference_wikidata="Q123"),
    )

    assert response.status_code == 200
    game.refresh_from_db()
    assert game.name == "Before conflict"
