"""Every reference out of a projection table, enumerated."""

import uuid

import pytest
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone
from test_projection_targets import declare_projection_models

from games.checks import check_projection_references
from games.models import Game, PlayerGame, Playthrough
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    cross_library_violations,
    projection_references,
    unaudited_projection_references,
)


def named(references):
    """`(model name, field name)` per reference, for a readable assertion."""
    return [
        (reference.model.__name__, reference.field.name) for reference in references
    ]


def test_the_walk_finds_every_outward_reference():
    """Both keys out of a projection, and neither library column."""
    assert named(projection_references()) == [
        ("PlayerGame", "game"),
        ("Playthrough", "player_game"),
    ]


def test_the_library_column_is_not_a_reference():
    """`UserLibrary` has no library of its own."""
    assert "library" not in {
        reference.field.name for reference in projection_references()
    }


def test_every_reference_is_audited():
    """The registry and the walk agree."""
    assert unaudited_projection_references() == ()
    assert named(AUDITED_PROJECTION_REFERENCES) == named(projection_references())


@isolate_apps("games")
def test_an_unregistered_reference_is_unaudited():
    """`Entry.shelf` is a foreign key nobody registered."""
    shelf, _entry = declare_projection_models()

    unaudited = unaudited_projection_references(apps=shelf._meta.apps)

    assert named(unaudited) == [("Entry", "shelf")]


@isolate_apps("games")
def test_a_cascade_reference_is_walked_too():
    """`CASCADE` across libraries is worse than `RESTRICT`, not better."""
    shelf, entry = declare_projection_models()

    found = projection_references(apps=shelf._meta.apps)

    assert entry._meta.get_field("shelf").remote_field.on_delete is models.CASCADE
    assert ("Entry", "shelf") in named(found)


@pytest.fixture
def other_library(django_user_model):
    """A second owner, for the cross-library cases."""
    return django_user_model.objects.create_user(
        username="reference-outsider", password="p"
    ).library


@pytest.fixture
def tracked_pair(owned_library):
    """One library's game and the row that tracks it."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )
    return game, tracked


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_matching_library_is_no_violation(owned_library, tracked_pair):
    assert (
        cross_library_violations(AUDITED_PROJECTION_REFERENCES, [owned_library.pk])
        == []
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_game_with_no_library_is_no_violation(owned_library):
    """A shared catalog row crosses no boundary."""
    shared = Game.objects.create(name="Tunic")
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    assert shared.library_id is None
    assert (
        cross_library_violations(AUDITED_PROJECTION_REFERENCES, [owned_library.pk])
        == []
    )


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_reference_across_libraries_is_reported(
    owned_library, other_library, tracked_pair
):
    """The row and the row it names, both ids."""
    _game, tracked = tracked_pair
    run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=other_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )

    reported = cross_library_violations(
        AUDITED_PROJECTION_REFERENCES, [owned_library.pk]
    )

    assert reported == [
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
    ]


def test_the_real_registry_reports_no_unaudited_reference():
    assert check_projection_references() == []


@isolate_apps("games")
def test_an_unaudited_reference_is_refused():
    """The check reads the isolated registry it is handed.

    `run_checks()` would prove nothing here: `isolate_apps` swaps
    `Options.default_apps` and leaves `django.apps.apps` alone, so the
    synthetic models are invisible to the global registry. That is also
    why no shipped check test regresses.
    """
    shelf, _ = declare_projection_models()

    messages = check_projection_references(apps=shelf._meta.apps)

    assert [str(message.id) for message in messages] == ["games.E009"]
    assert "Entry.shelf" in messages[0].msg
    assert "CASCADE" in messages[0].msg


@isolate_apps("games")
def test_the_check_honours_an_app_label_filter():
    """A check asked about another app answers nothing."""
    shelf, _ = declare_projection_models()

    class OtherConfig:
        label = "not_games"

    messages = check_projection_references(
        app_configs=[OtherConfig()], apps=shelf._meta.apps
    )

    assert messages == []
