"""What the Edition and Release forms refuse, and how they say it."""

from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_writes import DUPLICATE_EDITION_NAME, DUPLICATE_RELEASE
from games.forms import UNNAMED_SIBLING_EDITION, EditionForm, ReleaseForm
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


@pytest.fixture
def game(owned_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    return game


def release_payload(**parts: str) -> dict[str, str]:
    """The inputs the release control posts."""
    return {
        temporal_input_name("release_date", key): value for key, value in parts.items()
    }


def test_a_second_edition_must_state_a_name(owned_library, game):
    form = EditionForm({"name": ""}, library=owned_library, game=game)

    assert not form.is_valid()
    assert UNNAMED_SIBLING_EDITION in form.errors["name"]


def test_a_lone_edition_may_stay_unnamed(owned_library):
    bare = Game.objects.create(library=owned_library, name="Bare")
    form = EditionForm({"name": ""}, library=owned_library, game=bare)

    assert form.is_valid(), form.errors


def test_an_edition_may_state_its_own_empty_name_again(owned_library):
    lone = Game.objects.create(library=owned_library, name="Lone")
    edition = Edition.objects.create(game=lone, is_default=True)
    form = EditionForm(
        {"name": "", "is_default": "on"},
        library=owned_library,
        game=lone,
        instance=edition,
    )

    assert form.is_valid(), form.errors


def test_the_form_says_what_the_service_refused(owned_library, game):
    Edition.objects.create(game=game, name="Gold")
    renamed = Edition.objects.create(game=game, name="Plus")
    form = EditionForm(
        {"name": "Gold"}, library=owned_library, game=game, instance=renamed
    )

    assert form.is_valid()
    assert form.write() is None
    assert DUPLICATE_EDITION_NAME in form.errors["__all__"]


def test_an_added_duplicate_name_gives_back_the_edition_already_there(
    owned_library, game
):
    """The service is idempotent by name, thus a repeat writes no row."""
    standing = Edition.objects.create(game=game, name="Gold")
    form = EditionForm({"name": "Gold"}, library=owned_library, game=game)

    assert form.is_valid()
    assert form.write() == standing
    assert Edition.objects.filter(game=game, name="Gold").count() == 1


def test_the_current_default_edition_cannot_be_demoted_in_the_form(owned_library, game):
    default = Edition.objects.get(game=game, is_default=True)
    form = EditionForm(library=owned_library, game=game, instance=default)

    assert form.fields["is_default"].disabled
    assert form.fields["is_default"].initial is True


def test_an_edition_write_states_the_whole_row(owned_library, game):
    form = EditionForm({"name": "Gold"}, library=owned_library, game=game)

    assert form.is_valid()
    edition = form.write()

    assert edition is not None
    assert (edition.name, edition.is_default) == ("Gold", False)


def test_a_release_form_writes_through_the_service(owned_library, game):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    edition = Edition.objects.get(game=game, is_default=True)
    posted = {"platform": str(platform.pk)} | release_payload(
        kind="date", start_year="1984"
    )
    form = ReleaseForm(
        posted, library=owned_library, presentation=PRESENTATION, edition=edition
    )

    assert form.is_valid(), form.errors
    release = form.write()

    assert release is not None
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_year(1984)
    #: The flat columns followed it.
    game.refresh_from_db()
    assert game.year_released == 1984


def test_a_release_form_says_what_the_service_refused(owned_library, game):
    edition = Edition.objects.get(game=game, is_default=True)
    Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1984), is_default=True
    )
    edited = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1985)
    )
    form = ReleaseForm(
        release_payload(kind="date", start_year="1984"),
        library=owned_library,
        presentation=PRESENTATION,
        edition=edition,
        instance=edited,
    )

    assert form.is_valid(), form.errors
    assert form.write() is None
    assert DUPLICATE_RELEASE in form.errors["__all__"]


def test_the_current_default_release_cannot_be_demoted_in_the_form(owned_library, game):
    edition = Edition.objects.get(game=game, is_default=True)
    default = Release.objects.create(edition=edition, is_default=True)
    form = ReleaseForm(
        library=owned_library,
        presentation=PRESENTATION,
        edition=edition,
        instance=default,
    )

    assert form.fields["is_default"].disabled
    assert form.fields["is_default"].initial is True


def test_a_bound_release_form_states_what_the_row_holds(owned_library, game):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    edition = Edition.objects.get(game=game, is_default=True)
    stored = Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_month(1984, 6),
    )

    form = ReleaseForm(
        library=owned_library,
        presentation=PRESENTATION,
        edition=edition,
        instance=stored,
    )

    assert form.initial["platform"] == platform.pk
    assert form.initial["release_date"] == TemporalValue.from_month(1984, 6)
