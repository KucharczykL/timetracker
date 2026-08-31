import json
import uuid
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from common.criteria import FilterError, _comparison_group_for, comparable_columns
from games.forms import GameForm
from games.models import (
    Edition,
    Game,
    Platform,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Release,
    Session,
)
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def test_catalog_visibility_is_opt_in_and_derives_through_the_hierarchy():
    """A missing shared-owner branch must not broaden private query contracts."""
    user_model = get_user_model()
    library_a = user_model.objects.create_user(username="catalog-a").library
    library_b = user_model.objects.create_user(username="catalog-b").library
    private_a = Game.objects.create(library=library_a, name="Private A")
    private_b = Game.objects.create(library=library_b, name="Private B")
    shared = Game.objects.create(name="Shared")
    private_a_edition = Edition.objects.create(game=private_a)
    private_b_edition = Edition.objects.create(game=private_b)
    shared_edition = Edition.objects.create(game=shared)
    private_a_release = Release.objects.create(edition=private_a_edition)
    private_b_release = Release.objects.create(edition=private_b_edition)
    shared_release = Release.objects.create(edition=shared_edition)

    assert set(Game.objects.for_library(library_a)) == {private_a}
    assert set(Game.objects.visible_to(library_a)) == {private_a, shared}
    assert set(Edition.objects.for_library(library_a)) == {private_a_edition}
    assert set(Edition.objects.visible_to(library_a)) == {
        private_a_edition,
        shared_edition,
    }
    assert set(Release.objects.for_library(library_a)) == {private_a_release}
    assert set(Release.objects.visible_to(library_a)) == {
        private_a_release,
        shared_release,
    }
    assert not Game.objects.visible_to(library_a).contains(private_b)
    assert not Edition.objects.visible_to(library_a).contains(private_b_edition)
    assert not Release.objects.visible_to(library_a).contains(private_b_release)


def test_shared_and_private_games_can_share_a_name_but_private_duplicates_fail():
    """A missing private uniqueness constraint would permit same-owner duplicates."""
    user_model = get_user_model()
    library = user_model.objects.create_user(username="catalog-owner").library

    shared = Game.objects.create(name="Coexisting", year_released=1998)
    private = Game.objects.create(
        library=library,
        name="Coexisting",
        year_released=1998,
    )

    assert {shared.library_id, private.library_id} == {None, library.pk}
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.create(
            library=library,
            name="Coexisting",
            year_released=1998,
        )


def test_catalog_hierarchy_preserves_game_identity_and_allows_multiplicity(
    owned_library,
):
    game_id = uuid.uuid7()
    game = Game.objects.create(id=game_id, library=owned_library, name="Portal 2")
    standard = Edition.objects.create(game=game)
    deluxe = Edition.objects.create(game=game)
    standard_releases = [
        Release.objects.create(edition=standard),
        Release.objects.create(edition=standard),
    ]
    deluxe_release = Release.objects.create(edition=deluxe)

    assert game.pk == game_id
    assert game.editions.count() == 2
    assert standard.releases.count() == 2
    assert deluxe.releases.get() == deluxe_release
    assert {
        row.pk.version for row in (standard, deluxe, *standard_releases, deluxe_release)
    } == {7}


def test_game_and_release_temporal_values_preserve_ranges_and_unknown(
    owned_library,
):
    game = Game.objects.create(
        library=owned_library,
        name="Range Game",
        original_release_date=TemporalValue.parse("1987/1989-03"),
    )
    edition = Edition.objects.create(game=game)
    known = Release.objects.create(
        edition=edition,
        release_date=TemporalValue.parse("1998-04/2000"),
    )
    unknown = Release.objects.create(edition=edition, release_date=None)

    game.refresh_from_db()
    known.refresh_from_db()
    unknown.refresh_from_db()

    assert game.original_release_date == TemporalValue.parse("1987/1989-03")
    assert (
        game.original_release_date_lower,
        game.original_release_date_upper,
        game.original_release_date_kind,
        game.original_release_date_precision,
        game.original_release_date_start_kind,
        game.original_release_date_end_kind,
        game.original_release_date_start_precision,
        game.original_release_date_end_precision,
    ) == (
        date(1987, 1, 1),
        date(1989, 3, 31),
        "range",
        None,
        "known",
        "known",
        "year",
        "month",
    )
    assert known.release_date == TemporalValue.parse("1998-04/2000")
    assert (
        known.release_date_lower,
        known.release_date_upper,
        known.release_date_kind,
        known.release_date_precision,
        known.release_date_start_kind,
        known.release_date_end_kind,
        known.release_date_start_precision,
        known.release_date_end_precision,
    ) == (
        date(1998, 4, 1),
        date(2000, 12, 31),
        "range",
        None,
        "known",
        "known",
        "month",
        "year",
    )
    assert unknown.release_date is None
    assert unknown.release_date_lower is None
    assert unknown.release_date_upper is None
    assert unknown.release_date_kind == "unknown"
    assert unknown.release_date_precision is None
    assert unknown.release_date_start_kind is None
    assert unknown.release_date_end_kind is None
    assert unknown.release_date_start_precision is None
    assert unknown.release_date_end_precision is None


def test_game_and_release_preserve_year_precision(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Year Game",
        original_release_date=TemporalValue.from_year(1987),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.from_year(1998),
    )
    game.refresh_from_db()
    release.refresh_from_db()

    assert (
        game.original_release_date_lower,
        game.original_release_date_upper,
        game.original_release_date_kind,
        game.original_release_date_precision,
    ) == (date(1987, 1, 1), date(1987, 12, 31), "atomic", "year")
    assert (
        release.release_date_lower,
        release.release_date_upper,
        release.release_date_kind,
        release.release_date_precision,
    ) == (date(1998, 1, 1), date(1998, 12, 31), "atomic", "year")


@pytest.mark.untracked_games
def test_catalog_hierarchy_delete_behavior_is_explicit(owned_library):
    platform = Platform.objects.create(name="Delete Platform")
    game = Game.objects.create(library=owned_library, name="Delete Game")
    first_edition = Edition.objects.create(game=game)
    platform_release = Release.objects.create(edition=first_edition, platform=platform)

    platform.delete()
    platform_release.refresh_from_db()
    assert platform_release.platform_id is None

    first_release_id = platform_release.pk
    first_edition.delete()
    assert not Release.objects.filter(pk=first_release_id).exists()

    second_edition = Edition.objects.create(game=game)
    second_release = Release.objects.create(edition=second_edition)
    second_edition_id = second_edition.pk
    second_release_id = second_release.pk
    game.delete()
    assert not Edition.objects.filter(pk=second_edition_id).exists()
    assert not Release.objects.filter(pk=second_release_id).exists()


def test_release_save_allows_shared_and_same_library_platforms(owned_library):
    """Rejecting a visible Platform would break valid catalog graphs."""
    private_platform = Platform.objects.create(
        library=owned_library, name="Private Platform"
    )
    shared_platform = Platform.objects.create(name="Shared Platform")
    private_game = Game.objects.create(library=owned_library, name="Private Game")
    private_edition = Edition.objects.create(game=private_game)
    shared_game = Game.objects.create(name="Shared Game")
    shared_edition = Edition.objects.create(game=shared_game)

    private_same_library = Release.objects.create(
        edition=private_edition, platform=private_platform
    )
    private_shared = Release.objects.create(
        edition=private_edition, platform=shared_platform
    )
    shared = Release.objects.create(edition=shared_edition, platform=shared_platform)

    assert (
        private_same_library.platform,
        private_shared.platform,
        shared.platform,
    ) == (private_platform, shared_platform, shared_platform)


def test_release_save_rejects_foreign_platform_from_private_graph(
    owned_library, django_user_model
):
    """Removing release ownership validation permits another library's Platform."""
    other = django_user_model.objects.create_user(username="release-foreign-owner")
    foreign_platform = Platform.objects.create(
        library=other.library, name="Foreign Platform"
    )
    private_game = Game.objects.create(library=owned_library, name="Private Game")
    release = Release(edition=Edition.objects.create(game=private_game))

    with pytest.raises(ValidationError, match="another library"):
        release.platform = foreign_platform
        release.save()

    assert not Release.objects.filter(pk=release.pk).exists()


def test_release_save_rejects_private_platform_from_shared_graph(owned_library):
    """Removing release ownership validation leaks a private Platform into shared data."""
    private_platform = Platform.objects.create(
        library=owned_library, name="Private Platform"
    )
    shared_game = Game.objects.create(name="Shared Game")
    release = Release(edition=Edition.objects.create(game=shared_game))

    with pytest.raises(ValidationError, match="another library"):
        release.platform = private_platform
        release.save()

    assert not Release.objects.filter(pk=release.pk).exists()


def test_legacy_game_form_remains_authoritative_and_creates_no_graph(
    owned_library,
):
    platform = Platform.objects.create(name="Legacy Platform")
    form = GameForm(
        data={
            "name": "Legacy Game",
            "sort_name": "Legacy Game",
            "platform": str(platform.pk),
            "year_released": "2001",
            "original_year_released": "2000",
            "status": PlayerGameStatus.UNPLAYED,
            "wikidata": "",
        },
        library=owned_library,
    )

    assert "original_release_date" not in form.fields
    assert form.is_valid(), form.errors.as_json()
    game = form.save()
    assert (game.platform_id, game.year_released, game.original_year_released) == (
        platform.pk,
        2001,
        2000,
    )
    assert game.original_release_date is None
    assert not game.editions.exists()


def test_catalog_hierarchy_ownership_and_delete_metadata_are_explicit():
    assert "library" not in {field.name for field in Edition._meta.get_fields()}
    assert "library" not in {field.name for field in Release._meta.get_fields()}

    game_field = Edition._meta.get_field("game")
    edition_field = Release._meta.get_field("edition")
    platform_field = Release._meta.get_field("platform")
    assert game_field.null is False
    assert game_field.remote_field.on_delete is models.CASCADE
    assert edition_field.null is False
    assert edition_field.remote_field.on_delete is models.CASCADE
    assert platform_field.null is True
    assert platform_field.remote_field.on_delete is models.SET_NULL
    assert platform_field.remote_field.related_name == "+"
    assert not any(
        field.auto_created and field.related_model is Release
        for field in Platform._meta.get_fields()
    )


def test_generated_temporal_projections_are_not_fixture_serialized(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Serialized Game",
        original_release_date=TemporalValue.from_year(1998),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.from_year(1999),
    )
    game_payload, release_payload = [
        row["fields"]
        for row in json.loads(serializers.serialize("json", [game, release]))
    ]

    assert game_payload["original_release_date"] == "1998"
    assert not any(name.startswith("original_release_date_") for name in game_payload)
    assert release_payload["release_date"] == "1999"
    assert not any(name.startswith("release_date_") for name in release_payload)


def test_qualifier_columns_project_beside_the_bounds_they_do_not_move(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Qualified Game",
        original_release_date=TemporalValue.parse("198X~"),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.parse("1984?/1986%"),
    )
    game.refresh_from_db()
    release.refresh_from_db()

    assert game.original_release_date_qualifier == "approximate"
    assert game.original_release_date_start_qualifier is None
    assert game.original_release_date_end_qualifier is None
    assert game.original_release_date_lower == date(1980, 1, 1)
    assert game.original_release_date_upper == date(1989, 12, 31)
    assert game.original_release_date_precision == "decade"

    assert release.release_date_qualifier is None
    assert release.release_date_start_qualifier == "uncertain"
    assert release.release_date_end_qualifier == "both"


@pytest.mark.parametrize(
    "model", [Game, Session, Purchase, PlayEvent, Platform, Release]
)
def test_temporal_schema_does_not_expand_comparison_choices(model):
    values = {column["value"] for column in comparable_columns(model)}
    assert not any(
        "original_release_date" in value or "release_date" in value for value in values
    )

    with pytest.raises(FilterError):
        _comparison_group_for(Game, "original_release_date_lower")


def test_a_catalog_child_holds_a_mark_of_its_own():
    """#967 removes one of many; the mark is where it lands."""
    for model in (Edition, Release):
        field = model._meta.get_field("removed_at")
        assert (field.null, field.blank, field.default, field.editable) == (
            True,
            True,
            None,
            False,
        )


def _index_named(model, name):
    return next(index for index in model._meta.indexes if index.name == name)


def test_a_catalog_child_indexes_the_live_children_of_one_parent():
    """A list reads one parent's live children, and nothing else."""
    edition_index = _index_named(Edition, "live_edition_per_game_idx")
    release_index = _index_named(Release, "live_release_per_edition_idx")

    assert (edition_index.fields, edition_index.condition) == (
        ["game"],
        models.Q(removed_at__isnull=True),
    )
    assert (release_index.fields, release_index.condition) == (
        ["edition"],
        models.Q(removed_at__isnull=True),
    )


# --- an Edition holds a name of its own --------------------------------------


def test_an_edition_holds_an_optional_name(owned_library):
    """A name is text, and no name is the ordinary case."""
    game = Game.objects.create(library=owned_library, name="Deus Ex")

    edition = Edition.objects.create(game=game)

    assert edition.name == ""
    assert Edition._meta.get_field("name").blank is True


def test_an_unnamed_edition_presents_as_the_game(owned_library):
    game = Game.objects.create(library=owned_library, name="Deus Ex")

    unnamed = Edition.objects.create(game=game)
    named = Edition.objects.create(game=game, name="Game of the Year")

    assert unnamed.display_name == "Deus Ex"
    assert named.display_name == "Game of the Year"


def test_two_live_editions_of_one_game_cannot_share_a_name(owned_library):
    """The comparison ignores case and surrounding space."""
    game = Game.objects.create(library=owned_library, name="Deus Ex")
    Edition.objects.create(game=game, name="Game of the Year")

    with pytest.raises(IntegrityError), transaction.atomic():
        Edition.objects.create(game=game, name=" game of the year ")


def test_two_unnamed_editions_of_one_game_stay(owned_library):
    """No name is not a name, thus it claims no slot."""
    game = Game.objects.create(library=owned_library, name="Deus Ex")

    Edition.objects.create(game=game)
    Edition.objects.create(game=game)

    assert Edition.objects.filter(game=game).count() == 2


def test_two_games_may_hold_the_same_edition_name(owned_library):
    first = Game.objects.create(library=owned_library, name="Deus Ex")
    second = Game.objects.create(library=owned_library, name="Thief")

    Edition.objects.create(game=first, name="Game of the Year")
    Edition.objects.create(game=second, name="Game of the Year")

    assert Edition.objects.filter(name="Game of the Year").count() == 2


def test_a_removed_editions_name_is_free_again(owned_library):
    game = Game.objects.create(library=owned_library, name="Deus Ex")
    first = Edition.objects.create(game=game, name="Game of the Year")
    remove(first)

    second = Edition.objects.create(game=game, name="Game of the Year")

    assert Edition.objects.for_library(owned_library).get() == second
