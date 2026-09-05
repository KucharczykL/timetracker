"""Every reference out of a projection table."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone
from test_projection_targets import declare_projection_models

from games import projections
from games.checks import check_projection_references
from games.models import Game, PlayerGame, Playthrough, ProjectionModel
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    ProjectionReference,
    cross_library_violations,
    projection_references,
    stale_projection_references,
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


@isolate_apps("games")
def test_a_reference_to_a_row_no_library_owns_is_not_walked():
    """A device model with no library crosses no boundary."""
    shelf, _ = declare_projection_models()

    class Vendor(models.Model):
        id = models.UUIDField(primary_key=True)

        class Meta:
            app_label = "games"
            db_table = "test_projection_vendor"

    class Listing(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE)

        class Meta:
            app_label = "games"
            db_table = "test_projection_listing"

    found = projection_references(apps=shelf._meta.apps)

    assert ("Listing", "vendor") not in named(found)


def test_a_reverse_relation_named_library_does_not_scope_a_model():
    """`get_field` answers for a reverse relation.

    `UserLibrary.user` is `related_name="library"`, so a walk that did
    not ask for a concrete field would read the user model as scoped and
    then build a lookup no column answers.
    """
    user_model = get_user_model()

    assert user_model._meta.get_field("library").concrete is False
    assert not projections._is_library_scoped(user_model)


def test_a_reference_the_model_does_not_hold_is_refused():
    """The factory is the only construction path."""
    with pytest.raises(TypeError, match="not a foreign key"):
        ProjectionReference.on(PlayerGame, "status")


def test_a_reference_to_an_unscoped_row_is_refused():
    with pytest.raises(TypeError, match="holds no library"):
        ProjectionReference.on(Playthrough, "library")


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
    assert cross_library_violations([owned_library.pk]) == []


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
    assert cross_library_violations([owned_library.pk]) == []


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

    reported = cross_library_violations([owned_library.pk])

    assert reported == [
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
    ]


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_removed_row_still_names_the_other_library(
    owned_library, other_library, tracked_pair
):
    """The audit reads the base manager.

    A stamp takes the row off every screen and out of nothing else: the
    key is still there, and the swap still refuses.
    """
    _game, tracked = tracked_pair
    run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=other_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    reported = cross_library_violations([owned_library.pk])

    assert reported == [
        f"Playthrough.player_game: {run.pk} names PlayerGame {tracked.pk}"
    ]


def test_the_real_registry_reports_no_unaudited_reference():
    assert check_projection_references() == []


def test_the_check_is_registered_and_reads_the_real_registry(monkeypatch):
    """Without the registration, nothing runs this.

    Every other test calls the function, which an unregistered check
    answers just as well. Emptying the registry is what makes
    `run_checks()` say whether Django knows it.
    """
    monkeypatch.setattr(projections, "AUDITED_PROJECTION_REFERENCES", ())

    reported = [str(message.id) for message in run_checks()]

    assert reported == ["games.E009", "games.E009"]


@isolate_apps("games")
def test_the_check_answers_its_own_app_label():
    """The filter passes the app the reference is in."""
    shelf, _ = declare_projection_models()

    class GamesConfig:
        label = "games"

    messages = check_projection_references(
        app_configs=[GamesConfig()], apps=shelf._meta.apps
    )

    assert [str(message.id) for message in messages] == ["games.E009"]


@isolate_apps("games")
def test_an_unaudited_reference_is_refused():
    """The check reads the registry it is handed.

    `isolate_apps` swaps `Options.default_apps` and leaves
    `django.apps.apps` alone, so the synthetic models are invisible to
    the global registry. That is also why no shipped test regresses.
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


def test_a_registered_pair_the_walk_does_not_find_is_stale(monkeypatch):
    """The walk excludes `PlayerGame.library`.

    Registering it is the shape a pair takes after the field it names is
    renamed or dropped: the completeness check passes, and the query the
    audit builds from it raises a FieldError instead.
    """
    stale = ProjectionReference(PlayerGame, PlayerGame._meta.get_field("library"))
    monkeypatch.setattr(
        projections,
        "AUDITED_PROJECTION_REFERENCES",
        (*AUDITED_PROJECTION_REFERENCES, stale),
    )

    assert stale_projection_references() == (stale,)

    messages = check_projection_references()

    assert [str(message.id) for message in messages] == ["games.E010"]
    assert "PlayerGame.library" in messages[0].msg


@isolate_apps("games")
def test_a_pair_another_registry_holds_is_not_stale():
    """The registry under check holds neither shipped projection."""
    shelf, _ = declare_projection_models()

    assert stale_projection_references(apps=shelf._meta.apps) == ()
