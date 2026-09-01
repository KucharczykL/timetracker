"""The flat Game columns shadow the graph that now owns them."""

import pytest
from django.core.exceptions import ValidationError

from games.catalog_compat import (
    LEGACY_IDENTITY_TAKEN,
    mirror_legacy_columns,
    write_and_mirror,
)
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def test_the_mirror_copies_the_default_release_onto_the_flat_columns(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_month(1984, 6),
        is_default=True,
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id == platform.pk
    assert game.year_released == 1984


def test_the_mirror_keeps_the_precision_of_the_original_date(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Elite",
        original_release_date=TemporalValue.from_month(1983, 9),
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.original_year_released == 1983
    assert game.original_release_date == TemporalValue.from_month(1983, 9)


def test_the_mirror_clears_the_columns_when_the_release_states_nothing(owned_library):
    game = Game.objects.create(library=owned_library, name="Elite", year_released=1999)
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(edition=edition, is_default=True)

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id is None
    assert game.year_released is None


def test_the_mirror_refuses_to_collide_with_another_live_game(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    Game.objects.create(
        library=owned_library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )

    with pytest.raises(ValidationError) as refusal:
        mirror_legacy_columns(second)

    assert LEGACY_IDENTITY_TAKEN in refusal.value.messages


def test_a_refused_mirror_leaves_the_write_undone(owned_library):
    """One transaction: the mirror's refusal takes the write with it."""
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    Game.objects.create(
        library=owned_library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)

    with pytest.raises(ValidationError):
        write_and_mirror(
            second,
            lambda: Release.objects.create(
                edition=edition,
                platform=platform,
                release_date=TemporalValue.from_year(1984),
                is_default=True,
            ),
        )

    assert not Release.objects.filter(edition=edition).exists()
