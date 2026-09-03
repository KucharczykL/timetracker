"""The External references area, as one bound thing."""

import pytest

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
