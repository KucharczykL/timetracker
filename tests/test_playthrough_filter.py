"""#1013: the filter reads the projection."""

import uuid

import pytest
from django.utils import timezone

from games.models import Game, Playthrough, PlaythroughKind
from games.reads.playthrough_runs import library_runs

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_library(django_user_model):
    """A second library, whose runs this one never reads."""
    owner = django_user_model.objects.create_user(username="other-owner", password="p")
    return owner.library


def test_the_scope_states_all_four_things(owned_library, other_library):
    """A removed run, an imported one and another library's
    reach no page and no count."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    run = Playthrough.objects.get(player_game__game=game)
    imported = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    removed = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
        removed_at=timezone.now(),
    )
    theirs = Playthrough.objects.get(
        player_game__game=Game.objects.create(library=other_library, name="Tunic")
    )

    scoped = set(library_runs(owned_library).values_list("pk", flat=True))

    assert run.pk in scoped
    assert imported.pk not in scoped
    assert removed.pk not in scoped
    assert theirs.pk not in scoped


def test_the_scope_states_the_library_beside_the_parent(owned_library, other_library):
    """A run naming another library's tracked game is the drift
    `audit_library_ownership` reports, and neither library reads
    it."""
    game = Game.objects.create(library=other_library, name="Hollow Knight")
    theirs = Playthrough.objects.get(player_game__game=game)
    crossed = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=theirs.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    assert crossed.pk not in set(
        library_runs(owned_library).values_list("pk", flat=True)
    )
    assert crossed.pk not in set(
        library_runs(other_library).values_list("pk", flat=True)
    )
