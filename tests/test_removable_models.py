"""One rule over every removable model.

A model added to the registry later cannot skip it.
"""

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from django.db.models import Model
from django.utils import timezone

from games.models import (
    Device,
    FilterPreset,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    Session,
    UserLibrary,
)
from games.removal import REMOVABLE_MODELS, remove, restore

pytestmark = pytest.mark.django_db


def _game(library: UserLibrary) -> Game:
    return Game.objects.create(library=library, name="Outer Wilds")


def _platform(library: UserLibrary) -> Platform:
    return Platform.objects.create(library=library, name="Playdate")


def _device(library: UserLibrary) -> Device:
    return Device.objects.create(library=library, name="Deck", type=Device.HANDHELD)


def _session(library: UserLibrary) -> Session:
    return Session.objects.create(
        game=_game(library),
        timestamp_start=timezone.now(),
        timestamp_end=timezone.now() + timedelta(hours=1),
    )


def _play_event(library: UserLibrary) -> PlayEvent:
    return PlayEvent.objects.create(game=_game(library))


def _purchase(library: UserLibrary) -> Purchase:
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
    )
    purchase.games.set([_game(library)])
    return purchase


def _filter_preset(library: UserLibrary) -> FilterPreset:
    return FilterPreset.objects.create(library=library, name="Backlog", mode="games")


Builder = Callable[[UserLibrary], Model]

BUILDERS: dict[type[Model], Builder] = {
    Game: _game,
    Platform: _platform,
    Device: _device,
    Session: _session,
    PlayEvent: _play_event,
    Purchase: _purchase,
    FilterPreset: _filter_preset,
}


def make_instance(model: type[Model], library: UserLibrary) -> Model:
    return BUILDERS[model](library)


def test_every_removable_model_has_a_builder():
    assert set(REMOVABLE_MODELS) == set(BUILDERS)


@pytest.mark.parametrize("model", REMOVABLE_MODELS, ids=lambda m: m.__name__)
def test_for_library_hides_a_removed_row(owned_library, model):
    instance = make_instance(model, owned_library)

    remove(instance)

    assert not model.objects.for_library(owned_library).filter(pk=instance.pk).exists()
    assert model.objects.filter(pk=instance.pk).exists()


@pytest.mark.parametrize("model", REMOVABLE_MODELS, ids=lambda m: m.__name__)
def test_restore_brings_it_back(owned_library, model):
    instance = make_instance(model, owned_library)
    remove(instance)

    restore(instance)

    assert model.objects.for_library(owned_library).filter(pk=instance.pk).exists()


def test_every_removable_model_has_the_column():
    for model in REMOVABLE_MODELS:
        assert model._meta.get_field("removed_at").null
