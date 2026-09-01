"""What one row of the Game form states, and what it refuses."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_form import (
    EditionRowForm,
    ReleaseRowForm,
    edition_prefix,
    release_count_field,
    release_prefix,
)
from games.models import Platform
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


@pytest.fixture
def owned_platform(owned_library):
    return Platform.objects.create(library=owned_library, name="Nintendo Switch")


@pytest.fixture
def other_library_platform(django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    return Platform.objects.create(library=stranger.library, name="Neighbour Box")


def release_row(data=None, *, edition=0, release=0, library):
    return ReleaseRowForm(
        data,
        prefix=release_prefix(edition, release),
        library=library,
        presentation=PRESENTATION,
    )


def test_the_naming_helpers_agree_with_the_prefixes_they_state():
    assert edition_prefix(2) == "edition-2"
    assert release_prefix(0, 1) == "edition-0-release-1"
    assert release_count_field(0) == "edition-0-releases-count"


def test_a_row_names_its_inputs_by_its_index():
    form = EditionRowForm(prefix=edition_prefix(2))

    assert form["name"].html_name == "edition-2-name"
    assert form["edition_id"].html_name == "edition-2-edition_id"


def test_a_release_row_carries_its_index_into_the_temporal_control(owned_library):
    """The whole point of using Django's prefix rather than our own."""
    form = release_row(edition=0, release=1, library=owned_library)

    assert form["release_date"].html_name == "edition-0-release-1-release_date"
    assert (
        temporal_input_name(form["release_date"].html_name, "start_year")
        == "edition-0-release-1-release_date-year"
    )


def test_a_release_row_reads_a_stored_temporal_value_back(owned_library):
    name = "edition-0-release-0-release_date"
    posted = {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): "2020",
        temporal_input_name(name, "start_month"): "05",
        temporal_input_name(name, "start_day"): "29",
    }
    form = release_row(posted, library=owned_library)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["release_date"] == TemporalValue.from_day(
        date(2020, 5, 29)
    )


def test_a_row_marked_removed_says_so():
    form = EditionRowForm({"edition-0-removed": "on"}, prefix=edition_prefix(0))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["removed"] is True


def test_a_row_not_marked_removed_says_that_too():
    form = EditionRowForm({"edition-0-name": "Deluxe"}, prefix=edition_prefix(0))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["removed"] is False
    assert form.cleaned_data["name"] == "Deluxe"


def test_an_edition_name_is_stripped():
    form = EditionRowForm({"edition-0-name": "  Deluxe  "}, prefix=edition_prefix(0))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["name"] == "Deluxe"


def test_a_release_row_offers_only_platforms_the_library_sees(
    owned_library, other_library_platform, owned_platform
):
    form = release_row(library=owned_library)
    offered = list(form.fields["platform"].queryset)

    assert owned_platform in offered
    assert other_library_platform not in offered


def test_a_release_row_refuses_another_library_s_platform(
    owned_library, other_library_platform
):
    form = release_row(
        {"edition-0-release-0-platform": str(other_library_platform.pk)},
        library=owned_library,
    )

    assert not form.is_valid()
    assert "platform" in form.errors


def test_a_release_row_takes_no_platform_as_a_fact(owned_library):
    form = release_row({}, library=owned_library)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["platform"] is None


def test_a_release_row_renders_a_plain_select_not_a_combobox(owned_library):
    """A cloned row cannot rewrite a composite widget's wrapper id."""
    rendered = str(release_row(library=owned_library)["platform"])

    assert "<select" in rendered
    assert "search-select" not in rendered
