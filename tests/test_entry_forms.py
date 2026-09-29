"""The forms a copy is recorded, restated, ended and resumed with."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from entries import end_entry_access, record_entry

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.endpoint import ActStatement, WayActStatement
from games.end_ways import EndWay
from games.entry_forms import (
    CHANGED_SINCE_OPENED,
    RELEASE_OF_ANOTHER_GAME,
    EntryAddForm,
    EntryEditForm,
    EntryEndForm,
    EntryResumeForm,
)
from games.models import Game
from games.writes.libraryentry import KEEP
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
            **_day("library-add-acquired", datetime.date(2026, 9, 1)),
        },
        game=graph.game,
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
    form = _add(owned_library, graph, game=graph.game)

    assert form.fields["acquired"].initial == TemporalValue.parse("2026-09-29")


def test_add_on_a_game_offers_no_game_picker(owned_library, graph):
    assert "game" not in _add(owned_library, graph, game=graph.game).fields


def test_add_without_a_game_reads_the_prefixed_game_field(owned_library, graph):
    form = _add(owned_library, graph)

    widget = form.fields["release"].widget
    assert widget.params == {"game_id": {"field": "library-add-game"}}
    assert widget.create is not None


def test_add_offers_no_create_row_on_a_shared_game(owned_library):
    shared = Game.objects.create(name="Celeste")

    form = _add(owned_library, None, game=shared)

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
        data,
        entry=entry,
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
        prefix=f"copy-{entry.pk}-edit",
    )


def _edit_post(entry, **changes) -> dict[str, str]:
    prefix = f"copy-{entry.pk}-edit"
    posted = {
        f"{prefix}-release": str(entry.release_id),
        f"{prefix}-access": entry.access,
        f"{prefix}-format": entry.format,
        f"{prefix}-note": entry.note,
        f"{prefix}-end_state": "held",
        f"{prefix}-access_end_seen": (
            ""
            if entry.access_end_recorded_at is None
            else entry.access_end_recorded_at.isoformat()
        ),
        temporal_input_name(f"{prefix}-acquired", "kind"): "date",
        temporal_input_name(f"{prefix}-acquired", "start_year"): "2021",
        temporal_input_name(f"{prefix}-acquired", "start_month"): "5",
    }
    return posted | {f"{prefix}-{key}": value for key, value in changes.items()}


def test_distinct_prefixes_give_distinct_ids(owned_library, entry, graph):
    edit = _edit(owned_library, entry)
    add = _add(owned_library, graph, game=graph.game)

    assert edit["access"].id_for_label != add["access"].id_for_label


def test_held_on_a_held_copy_keeps_the_end(owned_library, entry):
    form = _edit(owned_library, entry, _edit_post(entry))

    assert form.is_valid(), form.errors
    assert form.access_end() is KEEP
    assert form.acquired() is KEEP


def test_held_on_an_ended_copy_voids_the_end(owned_library, entry):
    entry = end_entry_access(entry, ended=TemporalValue.parse("2022"))

    form = _edit(owned_library, entry, _edit_post(entry))

    assert form.is_valid(), form.errors
    assert form.access_end() is None


def test_ended_states_the_whole_end(owned_library, entry):
    posted = _edit_post(entry, end_state="ended", way="sold", end_note=" eBay ")
    posted |= _day(f"copy-{entry.pk}-edit-ended", datetime.date(2022, 3, 4))

    form = _edit(owned_library, entry, posted)

    assert form.is_valid(), form.errors
    assert form.access_end() == WayActStatement(
        TemporalValue.parse("2022-03-04"), EndWay.SOLD, "eBay"
    )


def test_ended_needs_a_way(owned_library, entry):
    form = _edit(owned_library, entry, _edit_post(entry, end_state="ended"))

    assert not form.is_valid()
    assert "way" in form.errors


def test_a_moved_acquisition_keeps_its_note(owned_library, graph):
    entry = record_entry(
        owned_library, graph.release, acquired=MAY, acquisition_note="gift"
    )
    posted = _edit_post(entry) | _day(
        f"copy-{entry.pk}-edit-acquired", datetime.date(2021, 6, 1)
    )

    form = _edit(owned_library, entry, posted)

    assert form.is_valid(), form.errors
    assert form.acquired() == ActStatement(TemporalValue.parse("2021-06-01"), "gift")


def test_edit_refuses_an_end_that_moved_since_the_page(owned_library, entry):
    posted = _edit_post(entry)
    end_entry_access(entry)

    form = _edit(owned_library, entry, posted)

    assert not form.is_valid()
    assert form.non_field_errors() == [CHANGED_SINCE_OPENED]


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
