"""What one row of the Game form states, and what it refuses."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_form import (
    DUPLICATE_NAME_IN_FORM,
    EDITION_COUNT_FIELD,
    LAST_EDITION_IN_FORM,
    LAST_RELEASE,
    MARK_FIELD,
    MARK_ON_A_REMOVED_ROW,
    NO_MARK,
    UNNAMED_SIBLING_EDITION,
    CatalogGraphForm,
    EditionRowForm,
    ReleaseRowForm,
    edition_prefix,
    release_count_field,
    release_prefix,
)
from games.catalog_writes import add_edition, add_release, save_private_game
from games.models import Game, Platform
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


def temporal_payload(prefix, year=None):
    """The inputs one temporal control posts for a whole year."""
    if year is None:
        return {temporal_input_name(prefix, "kind"): "date"}
    return {
        temporal_input_name(prefix, "kind"): "date",
        temporal_input_name(prefix, "start_year"): str(year),
    }


def release(release_id="", platform=None, year=None, removed=False):
    """One release row, the way `posted` wants it."""
    return {
        "release_id": release_id,
        "platform": platform,
        "year": year,
        "removed": removed,
    }


def block(edition_id="", name="", removed=False, releases=None):
    """One edition block, the way `posted` wants it."""
    return {
        "edition_id": edition_id,
        "name": name,
        "removed": removed,
        "releases": [release()] if releases is None else list(releases),
    }


def posted(*blocks, mark="edition-0-release-0"):
    """The flat POST body a graph of `blocks` submits."""
    data = {EDITION_COUNT_FIELD: str(len(blocks))}
    if mark:
        data[MARK_FIELD] = mark
    for index, one in enumerate(blocks):
        prefix = edition_prefix(index)
        data[f"{prefix}-edition_id"] = str(one["edition_id"] or "")
        data[f"{prefix}-name"] = one["name"]
        if one["removed"]:
            data[f"{prefix}-removed"] = "on"
        data[release_count_field(index)] = str(len(one["releases"]))
        for row_index, row in enumerate(one["releases"]):
            row_prefix = release_prefix(index, row_index)
            data[f"{row_prefix}-release_id"] = str(row["release_id"] or "")
            if row["platform"] is not None:
                data[f"{row_prefix}-platform"] = str(row["platform"].pk)
            if row["removed"]:
                data[f"{row_prefix}-removed"] = "on"
            data |= temporal_payload(f"{row_prefix}-release_date", row["year"])
    return data


def graph_form(data=None, *, game, library):
    return CatalogGraphForm(data, game=game, library=library, presentation=PRESENTATION)


@pytest.fixture
def plain_game(owned_library):
    """One Game with the one default graph the app always leaves."""
    return save_private_game(
        game=Game(library=owned_library, name="Portal"),
        original_release_date=None,
        release_date=TemporalValue.from_year(2007),
        platform=None,
    )


def test_the_graph_binds_a_plain_game_unbound(owned_library, plain_game):
    form = graph_form(game=plain_game.game, library=owned_library)

    assert len(form.blocks) == 1
    assert len(form.blocks[0].rows) == 1
    assert form.blocks[0].edition == plain_game.edition
    assert form.blocks[0].rows[0].instance == plain_game.release
    assert form.mark == "edition-0-release-0"


def test_the_graph_puts_the_default_edition_first_and_marks_its_release(
    owned_library, plain_game
):
    second = add_edition(game=plain_game.game, library=owned_library, name="Anthology")
    add_release(edition=second, library=owned_library)

    form = graph_form(game=plain_game.game, library=owned_library)

    assert [b.edition for b in form.blocks] == [plain_game.edition, second]
    assert form.mark == "edition-0-release-0"
    marked = form.marked()
    assert marked is not None
    assert marked[0].edition == plain_game.edition
    assert marked[1].instance == plain_game.release


def test_the_graph_offers_one_blank_row_for_a_game_holding_no_edition(owned_library):
    """No app path leaves one, and a stale fixture loads plenty."""
    orphan = Game.objects.create(library=owned_library, name="Fixture")

    form = graph_form(game=orphan, library=owned_library)

    assert len(form.blocks) == 1
    assert form.blocks[0].edition is None
    assert len(form.blocks[0].rows) == 1
    assert form.blocks[0].rows[0].instance is None
    assert form.mark == "edition-0-release-0"


def test_the_graph_refuses_a_submit_naming_no_release(owned_library, plain_game):
    form = graph_form(
        posted(block(), mark=""), game=plain_game.game, library=owned_library
    )

    assert not form.is_valid()
    assert NO_MARK in form.form_errors


def test_the_graph_refuses_a_mark_on_a_row_being_removed(owned_library, plain_game):
    form = graph_form(
        posted(block(releases=[release(removed=True), release(year=2011)])),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    assert MARK_ON_A_REMOVED_ROW in form.form_errors


def test_the_graph_refuses_an_edition_losing_its_last_release(
    owned_library, plain_game
):
    form = graph_form(
        posted(block(releases=[release(removed=True)]), mark=""),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    assert LAST_RELEASE in form.blocks[0].form.errors["__all__"]


def test_the_graph_refuses_removing_every_edition(owned_library, plain_game):
    form = graph_form(
        posted(block(removed=True), mark=""),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    assert LAST_EDITION_IN_FORM in form.form_errors


def test_the_graph_refuses_two_surviving_unnamed_editions(owned_library, plain_game):
    form = graph_form(
        posted(block(), block()),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    assert UNNAMED_SIBLING_EDITION in form.blocks[1].form.errors["name"]


def test_the_graph_refuses_two_surviving_editions_sharing_a_name(
    owned_library, plain_game
):
    form = graph_form(
        posted(block(name="Deluxe"), block(name="deluxe")),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    assert DUPLICATE_NAME_IN_FORM in form.blocks[1].form.errors["name"]


def test_the_graph_treats_another_library_s_release_id_as_a_new_row(
    owned_library, plain_game, django_user_model
):
    stranger = django_user_model.objects.create_user(username="graphling", password="p")
    theirs = save_private_game(
        game=Game(library=stranger.library, name="Theirs"),
        original_release_date=None,
        release_date=None,
        platform=None,
    )

    form = graph_form(
        posted(block(releases=[release(release_id=theirs.release.pk)])),
        game=plain_game.game,
        library=owned_library,
    )

    assert form.is_valid(), form.form_errors
    assert form.blocks[0].rows[0].instance is None
