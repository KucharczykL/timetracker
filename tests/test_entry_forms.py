"""The forms a copy is recorded, restated, ended and resumed with."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from entries import end_entry_access, record_entry

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.opener_facts import Fixed
from games.commands.endpoint import ActStatement, WayActStatement
from games.end_ways import EndWay
from games.entry_forms import (
    CHANGED_SINCE_OPENED,
    RELEASE_OF_ANOTHER_GAME,
    EntryAddForm,
    EntryEditForm,
    EntryEndEditForm,
    EntryEndForm,
    EntryResumeForm,
    end_seen,
)
from games.models import Game, Platform
from games.writes.endpoint import KEEP
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
TODAY = datetime.date(2026, 9, 29)
MAY = TemporalValue.parse("2021-05")


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release, acquired=MAY)


def _add(owned_library, graph, data=None, **kwargs):
    return EntryAddForm(
        data,
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
        prefix="library-add",
        **kwargs,
    )


def test_add_on_a_game_cleans_to_a_draft(owned_library, graph):
    form = _add(
        owned_library,
        graph,
        {
            "library-add-release": str(graph.release.pk),
            "library-add-access": "borrowed",
            "library-add-format": "physical",
            "library-add-note": " from Ana ",
            "library-add-submission": "01928e5e-4f6b-7c3a-8e9d-000000000001",
            "library-add-price": "none",
            **_day("library-add-acquired", datetime.date(2026, 9, 1)),
        },
        facts={"library-add-game": str(graph.game.pk)},
    )

    assert form.is_valid(), form.errors
    draft = form.draft()
    assert draft.release_id == graph.release.pk
    assert (draft.access, draft.format, draft.note) == (
        "borrowed",
        "physical",
        "from Ana",
    )
    assert draft.acquired == ActStatement(TemporalValue.parse("2026-09-01"), "")
    assert form.submission_key().startswith("copy-add-")


def test_add_seeds_the_acquired_day_with_today(owned_library, graph):
    form = _add(owned_library, graph, facts={"library-add-game": str(graph.game.pk)})

    assert form.fields["acquired"].initial == TemporalValue.parse("2026-09-29")


def test_add_seeds_digital(owned_library, graph):
    assert (
        _add(owned_library, graph, facts={"library-add-game": str(graph.game.pk)})[
            "format"
        ].initial
        == "digital"
    )


def test_add_on_a_game_seeds_its_default_release_among_several(
    owned_library, graph, stated_graph
):
    from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph

    state_catalog_graph(
        game=graph.game,
        library=owned_library,
        editions=[
            EditionState(
                key="edition",
                edition=graph.edition,
                is_default=True,
                releases=(
                    ReleaseState(key="default", release=graph.release, is_default=True),
                    ReleaseState(
                        key="other",
                        platform=Platform.objects.create(name="PS5", group="Sony"),
                    ),
                ),
            )
        ],
    )

    form = _add(owned_library, graph, facts={"library-add-game": str(graph.game.pk)})

    assert form.initial["release"] == graph.release.pk


def test_add_on_a_game_states_it(owned_library, graph):
    form = _add(owned_library, graph, facts={"library-add-game": str(graph.game.pk)})

    assert form.fields["game"].disabled
    assert form.facts["game"] == Fixed(graph.game, graph.game.search_label)


def test_add_without_a_game_reads_the_prefixed_game_field(owned_library, graph):
    form = _add(owned_library, graph)

    widget = form.fields["release"].widget
    assert widget.params == {"game_id": {"field": "library-add-game"}}
    assert widget.create is not None


def test_add_offers_no_create_row_on_a_shared_game(owned_library):
    shared = Game.objects.create(name="Celeste")

    form = _add(owned_library, None, facts={"library-add-game": str(shared.pk)})

    assert form.fields["release"].widget.create is None


def test_add_refuses_a_release_of_another_game(owned_library, graph, stated_graph):
    other = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    form = _add(
        owned_library,
        graph,
        {
            "library-add-game": str(graph.game.pk),
            "library-add-release": str(other.release.pk),
            "library-add-access": "owned",
            "library-add-format": "digital",
            "library-add-submission": "01928e5e-4f6b-7c3a-8e9d-000000000001",
        },
    )

    assert not form.is_valid()
    assert form.errors["release"] == [RELEASE_OF_ANOTHER_GAME]


def _edit(owned_library, entry, data=None):
    return EntryEditForm(
        data, entry=entry, library=owned_library, presentation=PRESENTATION
    )


def _edit_post(entry, **changes) -> dict[str, str]:
    return {
        "release": str(entry.release_id),
        "access": entry.access,
        "format": entry.format,
        "note": entry.note,
        temporal_input_name("acquired", "kind"): "date",
        temporal_input_name("acquired", "start_year"): "2021",
        temporal_input_name("acquired", "start_month"): "5",
    } | changes


def test_edit_holds_no_end_field(owned_library, entry):
    assert set(_edit(owned_library, entry).fields) == {
        "release",
        "format",
        "access",
        "acquired",
        "note",
    }


def test_an_unmoved_acquisition_is_kept(owned_library, entry):
    form = _edit(owned_library, entry, _edit_post(entry))

    assert form.is_valid(), form.errors
    assert form.acquired() is KEEP


def test_a_moved_acquisition_keeps_its_note(owned_library, graph):
    entry = record_entry(
        owned_library, graph.release, acquired=MAY, acquisition_note="gift"
    )
    posted = _edit_post(entry) | _day("acquired", datetime.date(2021, 6, 1))

    form = _edit(owned_library, entry, posted)

    assert form.is_valid(), form.errors
    assert form.acquired() == ActStatement(TemporalValue.parse("2021-06-01"), "gift")


def _end_edit(entry, data=None):
    return EntryEndEditForm(data, entry=entry, presentation=PRESENTATION)


def test_edit_end_starts_from_the_standing_end(owned_library, entry):
    entry = end_entry_access(
        entry, way=EndWay.SOLD, ended=TemporalValue.parse("2022"), note="eBay"
    )

    form = _end_edit(entry)

    assert (form["way"].initial, form["note"].initial) == ("sold", "eBay")


def test_edit_end_restates_the_whole_end(owned_library, entry):
    entry = end_entry_access(entry)
    form = _end_edit(
        entry,
        {
            "way": "sold",
            "note": " eBay ",
            "access_end_seen": end_seen(entry),
            **_day("ended", datetime.date(2022, 3, 4)),
        },
    )

    assert form.is_valid(), form.errors
    assert form.access_end() == WayActStatement(
        TemporalValue.parse("2022-03-04"), EndWay.SOLD, "eBay"
    )


def test_edit_end_refuses_an_end_that_moved_since_the_page(owned_library, entry):
    entry = end_entry_access(entry)
    form = _end_edit(
        entry,
        {
            "way": "sold",
            "access_end_seen": "",
            **_day("ended", datetime.date(2022, 3, 4)),
        },
    )

    assert not form.is_valid()
    assert form.non_field_errors() == [CHANGED_SINCE_OPENED]


def test_end_offers_not_said_first(owned_library, entry):
    form = EntryEndForm(entry=entry, presentation=PRESENTATION, today=TODAY)

    assert form.fields["way"].choices[0] == ("unstated", "Not said")


def test_end_holds_not_said_untouched(owned_library, entry):
    form = EntryEndForm(entry=entry, presentation=PRESENTATION, today=TODAY)

    assert form["way"].value() == "unstated"


def test_edit_end_of_a_held_copy_is_a_defect(owned_library, entry):
    with pytest.raises(ValueError):
        _end_edit(entry)


def test_end_cleans_to_a_statement(owned_library, entry):
    prefix = f"copy-{entry.pk}-end"
    form = EntryEndForm(
        {
            f"{prefix}-way": "lost",
            f"{prefix}-note": "",
            f"{prefix}-access_end_seen": "",
            f"{prefix}-submission": "01928e5e-4f6b-7c3a-8e9d-000000000002",
            **_day(f"{prefix}-ended", TODAY),
        },
        entry=entry,
        presentation=PRESENTATION,
        today=TODAY,
        prefix=prefix,
    )

    assert form.is_valid(), form.errors
    assert form.statement() == WayActStatement(
        TemporalValue.parse("2026-09-29"), EndWay.LOST, ""
    )
    assert form.submission_key().startswith("copy-end-")


def test_resume_refuses_an_end_that_moved(owned_library, entry):
    entry = end_entry_access(entry)
    prefix = f"copy-{entry.pk}-resume"
    form = EntryResumeForm(
        {
            f"{prefix}-note": "",
            f"{prefix}-access_end_seen": "",
            f"{prefix}-submission": "01928e5e-4f6b-7c3a-8e9d-000000000003",
            **_day(f"{prefix}-resumed", TODAY),
        },
        entry=entry,
        presentation=PRESENTATION,
        today=TODAY,
        prefix=prefix,
    )

    assert not form.is_valid()
    assert form.non_field_errors() == [CHANGED_SINCE_OPENED]
