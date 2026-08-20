import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.catalog_writes import save_private_game
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def test_default_markers_allow_one_default_and_multiple_nondefaults(owned_library):
    game = Game.objects.create(library=owned_library, name="Defaults")
    default_edition = Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game)
    Edition.objects.create(game=game)
    Release.objects.create(edition=default_edition, is_default=True)
    Release.objects.create(edition=default_edition)
    Release.objects.create(edition=default_edition)

    assert game.editions.filter(is_default=True).get() == default_edition
    assert default_edition.releases.filter(is_default=True).count() == 1
    assert Edition._meta.get_field("is_default").editable is False
    assert Release._meta.get_field("is_default").editable is False

    with pytest.raises(IntegrityError), transaction.atomic():
        Edition.objects.create(game=game, is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Release.objects.create(edition=default_edition, is_default=True)


def test_save_private_game_creates_one_default_graph(owned_library):
    platform = Platform.objects.create(name="PC")
    graph = save_private_game(
        game=Game(library=owned_library, name="Portal"),
        original_release_date=TemporalValue.from_year(2007),
        release_date=TemporalValue.from_year(2008),
        platform=platform,
    )

    graph.game.refresh_from_db()
    graph.release.refresh_from_db()
    assert graph.edition == graph.game.editions.get(is_default=True)
    assert graph.release == graph.edition.releases.get(is_default=True)
    assert graph.game.original_release_date == TemporalValue.from_year(2007)
    assert graph.release.release_date == TemporalValue.from_year(2008)
    assert graph.release.platform == platform
    assert {
        graph.game.pk.version,
        graph.edition.pk.version,
        graph.release.pk.version,
    } == {7}

    repeated = save_private_game(
        game=graph.game,
        original_release_date=TemporalValue.from_year(2007),
        release_date=TemporalValue.from_year(2008),
        platform=platform,
    )
    assert repeated.edition.pk == graph.edition.pk
    assert repeated.release.pk == graph.release.pk
    assert Edition.objects.filter(game=graph.game).count() == 1
    assert Release.objects.filter(edition=graph.edition).count() == 1


def test_save_private_game_updates_and_clears_the_same_default_graph(owned_library):
    platform = Platform.objects.create(name="First")
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Before",
            original_year_released=1998,
            year_released=1999,
            platform=platform,
        ),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=platform,
    )
    edition_id, release_id = graph.edition.pk, graph.release.pk

    graph.game.name = "After"
    graph.game.original_year_released = None
    graph.game.year_released = None
    graph.game.platform = None
    updated = save_private_game(
        game=graph.game,
        original_release_date=None,
        release_date=None,
        platform=None,
    )
    updated.game.refresh_from_db()
    updated.release.refresh_from_db()

    assert (updated.edition.pk, updated.release.pk) == (edition_id, release_id)
    assert updated.game.name == "After"
    assert updated.game.original_release_date is None
    assert updated.release.release_date is None
    assert updated.release.platform is None
    assert (
        updated.game.original_year_released,
        updated.game.year_released,
        updated.game.platform,
    ) == (None, None, None)


def test_save_private_game_does_not_adopt_unmarked_children(owned_library):
    game = Game.objects.create(library=owned_library, name="Unmarked")
    unmarked_edition = Edition.objects.create(game=game)
    unmarked_release = Release.objects.create(edition=unmarked_edition)

    graph = save_private_game(
        game=game,
        original_release_date=None,
        release_date=None,
        platform=None,
    )

    assert graph.edition.pk != unmarked_edition.pk
    assert graph.release.pk != unmarked_release.pk
    assert game.editions.filter(is_default=True).count() == 1
    assert Edition.objects.filter(game=game).count() == 2


def test_save_private_game_rejects_a_foreign_private_platform(
    owned_library, django_user_model
):
    other = django_user_model.objects.create_user(username="other-catalog-owner")
    foreign = Platform.objects.create(library=other.library, name="Foreign")
    graph = save_private_game(
        game=Game(library=owned_library, name="Owned catalog game"),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=None,
    )
    graph.game.name = "Rejected"

    with pytest.raises(ValidationError, match="another library"):
        save_private_game(
            game=graph.game,
            original_release_date=None,
            release_date=None,
            platform=foreign,
        )

    stored_game = Game.objects.get(pk=graph.game.pk)
    stored_release = Release.objects.get(pk=graph.release.pk)
    assert stored_game.name == "Owned catalog game"
    assert stored_game.original_release_date == TemporalValue.from_year(1998)
    assert stored_game.editions.get(is_default=True).pk == graph.edition.pk
    assert stored_release.release_date == TemporalValue.from_year(1999)
    assert stored_release.platform_id is None


def test_save_private_game_rejects_a_persisted_shared_game():
    """Removing the null-owner guard lets the private writer mutate shared data."""
    game = Game.objects.create(name="Shared catalog game")
    game.name = "Rejected shared catalog game"

    with pytest.raises(ValidationError, match="requires a library owner"):
        save_private_game(
            game=game,
            original_release_date=TemporalValue.from_year(1998),
            release_date=TemporalValue.from_year(1999),
            platform=None,
        )

    stored_game = Game.objects.get(pk=game.pk)
    assert stored_game.library_id is None
    assert stored_game.name == "Shared catalog game"
    assert stored_game.original_release_date is None
    assert not stored_game.editions.filter(is_default=True).exists()


def test_save_private_game_rejects_persisted_owner_transfer(
    owned_library, django_user_model
):
    """Ignoring the locked owner transfers a private graph to another library."""
    other = django_user_model.objects.create_user(username="new-catalog-owner")
    graph = save_private_game(
        game=Game(library=owned_library, name="Owned catalog game"),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=None,
    )
    graph.game.library = other.library
    graph.game.name = "Transferred catalog game"

    with pytest.raises(ValidationError, match="library owner"):
        save_private_game(
            game=graph.game,
            original_release_date=None,
            release_date=None,
            platform=None,
        )

    stored_game = Game.objects.get(pk=graph.game.pk)
    stored_release = Release.objects.get(pk=graph.release.pk)
    assert stored_game.library_id == owned_library.pk
    assert stored_game.name == "Owned catalog game"
    assert stored_game.original_release_date == TemporalValue.from_year(1998)
    assert stored_game.editions.get(is_default=True).pk == graph.edition.pk
    assert stored_release.release_date == TemporalValue.from_year(1999)


def test_save_private_game_rolls_back_new_game_when_release_write_fails(
    owned_library, monkeypatch
):
    def fail_save(*args, **kwargs):
        raise RuntimeError("forced release failure")

    monkeypatch.setattr(Release, "save", fail_save)
    with pytest.raises(RuntimeError, match="forced release failure"):
        save_private_game(
            game=Game(
                library=owned_library,
                name="Rolled back",
                year_released=2001,
            ),
            original_release_date=None,
            release_date=TemporalValue.from_year(2001),
            platform=None,
        )

    assert not Game.objects.filter(name="Rolled back").exists()
    assert Edition.objects.count() == 0
    assert Release.objects.count() == 0


def test_save_private_game_rolls_back_existing_compatibility_and_catalog_fields(
    owned_library, monkeypatch
):
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Before failure",
            original_year_released=1998,
            year_released=1999,
        ),
        original_release_date=TemporalValue.from_year(1998),
        release_date=TemporalValue.from_year(1999),
        platform=None,
    )
    game_id, edition_id, release_id = (
        graph.game.pk,
        graph.edition.pk,
        graph.release.pk,
    )
    original_release_save = Release.save

    def fail_existing_release(instance, *args, **kwargs):
        if instance.pk == release_id:
            raise RuntimeError("forced release failure")
        return original_release_save(instance, *args, **kwargs)

    monkeypatch.setattr(Release, "save", fail_existing_release)
    graph.game.name = "After failure"
    graph.game.original_year_released = None
    graph.game.year_released = None
    with pytest.raises(RuntimeError, match="forced release failure"):
        save_private_game(
            game=graph.game,
            original_release_date=None,
            release_date=None,
            platform=None,
        )

    stored_game = Game.objects.get(pk=game_id)
    stored_release = Release.objects.get(pk=release_id)
    assert stored_game.name == "Before failure"
    assert stored_game.original_year_released == 1998
    assert stored_game.year_released == 1999
    assert stored_game.original_release_date == TemporalValue.from_year(1998)
    assert stored_release.release_date == TemporalValue.from_year(1999)
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert stored_release.pk == release_id
