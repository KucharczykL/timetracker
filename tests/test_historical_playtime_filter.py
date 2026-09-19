"""The historical playtime filter and its scope."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import tracked_run

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    FieldComparisonCriterion,
    IntCriterion,
    Modifier,
    RelationMatch,
    StringCriterion,
    UUIDMultiCriterion,
    field_metadata,
    filter_to_json,
)
from common.filter_execution import execute_filter
from games.filters import (
    DeviceFilter,
    GameFilter,
    HistoricalPlaytimeFilter,
    filter_for_model,
    filter_query_context_for_library,
    filter_queryset_for_library,
    parse_historical_playtime_filter,
)
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Platform,
    PlayerGame,
    Playthrough,
)
from games.reads.historical_playtime_records import library_records
from games.removal import remove

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


def game_run(library, name: str, **game_fields) -> Playthrough:
    game = Game.objects.create(library=library, name=name, **game_fields)
    return tracked_run(library, game)


def matched(library, filter_object) -> set[str]:
    """The notes of the records this filter answers."""
    queryset = execute_filter(
        filter_object,
        library_records(library),
        filter_query_context_for_library(library),
    )
    return set(queryset.values_list("note", flat=True))


# ── Scope ──────────────────────────────────────────────────────────────────


def test_the_scope_holds_live_records_of_this_library(owned_library, django_user_model):
    run = game_run(owned_library, "Outer Wilds")
    live = record_row([run], note="live")
    removed = record_row([run], note="removed")
    HistoricalPlaytime.objects.filter(pk=removed.pk).update(removed_at=timezone.now())

    untracked_run = game_run(owned_library, "Untracked")
    record_row([untracked_run], note="untracked")
    PlayerGame.objects.filter(pk=untracked_run.player_game_id).update(
        removed_at=timezone.now()
    )

    catalog_run = game_run(owned_library, "Removed from the catalog")
    record_row([catalog_run], note="catalog")
    remove(catalog_run.player_game.game)

    other = django_user_model.objects.create_user(username="other").library
    record_row([game_run(other, "Elsewhere")], note="elsewhere")
    borrowed = record_row([game_run(other, "Borrowed")], note="borrowed")
    HistoricalPlaytime.objects.filter(pk=borrowed.pk).update(library=owned_library)

    assert list(library_records(owned_library)) == [live]


def test_the_filter_scopes_answer_the_record_scope(owned_library):
    run = game_run(owned_library, "Outer Wilds")
    record = record_row([run])

    assert filter_for_model("historicalplaytime") is HistoricalPlaytimeFilter
    assert list(filter_queryset_for_library("historicalplaytime", owned_library)) == [
        record
    ]
    context = filter_query_context_for_library(owned_library)
    assert list(context.queryset_for(HistoricalPlaytime)) == [record]


# ── Leaves ─────────────────────────────────────────────────────────────────


@pytest.fixture
def varied(owned_library):
    """Records that differ in one fact each."""
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    deck = Device.objects.create(library=owned_library, name="Steam Deck")
    zelda = game_run(owned_library, "Zelda", platform=platform)
    doom = game_run(owned_library, "Doom")
    record_row(
        [zelda],
        note="zelda",
        duration=timedelta(hours=40),
        provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
        device=deck,
        emulated=True,
        when="2020/2022",
    )
    record_row([doom], note="doom", duration=timedelta(hours=2), when="2019")
    record_row([doom], note="unknown", duration=timedelta(hours=5))
    return {"zelda": zelda, "doom": doom, "deck": deck}


def test_game(owned_library, varied):
    zelda = varied["zelda"].player_game.game_id
    included = HistoricalPlaytimeFilter(game=UUIDMultiCriterion(value=[zelda]))
    excluded = HistoricalPlaytimeFilter(
        game=UUIDMultiCriterion(value=[zelda], modifier=Modifier.EXCLUDES)
    )
    assert matched(owned_library, included) == {"zelda"}
    assert matched(owned_library, excluded) == {"doom", "unknown"}


def test_device(owned_library, varied):
    deck = HistoricalPlaytimeFilter(
        device=UUIDMultiCriterion(value=[varied["deck"].pk])
    )
    none = HistoricalPlaytimeFilter(
        device=UUIDMultiCriterion(value=[], modifier=Modifier.IS_NULL)
    )
    assert matched(owned_library, deck) == {"zelda"}
    assert matched(owned_library, none) == {"doom", "unknown"}


def test_provenance(owned_library, varied):
    measured = HistoricalPlaytimeFilter(
        provenance=ChoiceCriterion(value=["externally_measured"])
    )
    not_measured = HistoricalPlaytimeFilter(
        provenance=ChoiceCriterion(
            value=["externally_measured"], modifier=Modifier.EXCLUDES
        )
    )
    assert matched(owned_library, measured) == {"zelda"}
    assert matched(owned_library, not_measured) == {"doom", "unknown"}


def test_emulated_and_note(owned_library, varied):
    emulated = HistoricalPlaytimeFilter(emulated=BoolCriterion(value=True))
    note = HistoricalPlaytimeFilter(
        note=StringCriterion(value="unk", modifier=Modifier.INCLUDES)
    )
    assert matched(owned_library, emulated) == {"zelda"}
    assert matched(owned_library, note) == {"unknown"}


def test_duration_hours(owned_library, varied):
    longer = HistoricalPlaytimeFilter(
        duration_hours=IntCriterion(value=4, modifier=Modifier.GREATER_THAN)
    )
    between = HistoricalPlaytimeFilter(
        duration_hours=IntCriterion(value=1, value2=10, modifier=Modifier.BETWEEN)
    )
    assert matched(owned_library, longer) == {"zelda", "unknown"}
    assert matched(owned_library, between) == {"doom", "unknown"}


@pytest.mark.parametrize(
    ("criterion", "expected"),
    [
        (DateCriterion(value="2021-05-05"), {"zelda"}),
        (DateCriterion(value="2019-07-01"), {"doom"}),
        (
            DateCriterion(
                value="2022-01-01",
                value2="2022-12-31",
                modifier=Modifier.BETWEEN,
            ),
            {"zelda"},
        ),
        (
            DateCriterion(value="2020-01-01", modifier=Modifier.LESS_THAN),
            {"doom"},
        ),
        (DateCriterion(modifier=Modifier.IS_NULL), {"unknown"}),
        (DateCriterion(modifier=Modifier.NOT_NULL), {"zelda", "doom"}),
    ],
)
def test_when_reads_the_interval(owned_library, varied, criterion, expected):
    assert matched(owned_library, HistoricalPlaytimeFilter(when=criterion)) == expected


def test_when_admits_an_open_range(owned_library):
    run = game_run(owned_library, "Open")
    record_row([run], note="open", when="2020-01-01/")
    later = HistoricalPlaytimeFilter(
        when=DateCriterion(value="2030-01-01", modifier=Modifier.GREATER_THAN)
    )
    before = HistoricalPlaytimeFilter(
        when=DateCriterion(value="2019-01-01", modifier=Modifier.LESS_THAN)
    )
    assert matched(owned_library, later) == set()
    assert matched(
        owned_library,
        HistoricalPlaytimeFilter(when=DateCriterion(value="2030-01-01")),
    ) == {"open"}
    assert matched(owned_library, before) == set()


def test_created_at(owned_library, varied):
    today = HistoricalPlaytimeFilter(
        created_at=DateCriterion(value=timezone.localdate().isoformat())
    )
    assert matched(owned_library, today) == {"zelda", "doom", "unknown"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("zel", {"zelda"}),
        ("amiga", {"zelda"}),
        ("deck", {"zelda"}),
        ("unkn", {"unknown"}),
    ],
)
def test_search(owned_library, varied, text, expected):
    search = HistoricalPlaytimeFilter(
        search=StringCriterion(value=text, modifier=Modifier.INCLUDES)
    )
    assert matched(owned_library, search) == expected


def test_relations(owned_library, varied):
    by_game = HistoricalPlaytimeFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Doom", modifier=Modifier.EQUALS)
        )
    )
    by_device = HistoricalPlaytimeFilter(
        device_filter=DeviceFilter(
            name=StringCriterion(value="Steam Deck", modifier=Modifier.EQUALS)
        )
    )
    assert matched(owned_library, by_game) == {"doom", "unknown"}
    assert matched(owned_library, by_device) == {"zelda"}


def test_a_multivalued_comparison_reads_the_context_scope(owned_library, varied):
    comparison = HistoricalPlaytimeFilter(
        field_comparisons=[
            FieldComparisonCriterion(
                left="player_game__game__purchases__created_at",
                right="created_at",
                modifier=Modifier.GREATER_THAN,
                quantifier=RelationMatch.ANY,
            )
        ]
    )
    assert matched(owned_library, comparison) == set()


def test_the_metadata_states_choices_and_kinds():
    metadata = {meta["name"]: meta for meta in field_metadata(HistoricalPlaytimeFilter)}
    assert {choice["value"] for choice in metadata["provenance"]["choices"]} == set(
        HistoricalPlaytimeProvenance.values
    )
    assert metadata["when"]["kind"] == "date"
    assert metadata["duration_hours"]["kind"] == "number"


def test_the_filter_round_trips_through_json():
    source = HistoricalPlaytimeFilter(
        provenance=ChoiceCriterion(value=["estimated"]),
        game=UUIDMultiCriterion(value=[uuid.uuid7()]),
    )
    assert parse_historical_playtime_filter(filter_to_json(source)) == source


def test_an_unknown_key_is_refused():
    from common.criteria import FilterError

    with pytest.raises(FilterError):
        parse_historical_playtime_filter('{"run": {"value": []}}')


@pytest.fixture
def shaped_records(owned_library):
    """One record per `when` shape, noted."""
    run = game_run(owned_library, "Shaped")
    for note, when in {
        "month": "2024-03",
        "year": "2024",
        "straddling": "2023-12/2024-01",
        "open start": "/2024-06",
        "unknown": None,
    }.items():
        record_row([run], when=when, note=note)


def test_within_reads_containment(owned_library, shaped_records):
    """Whole interval inside the bounds counts."""
    assert matched(
        owned_library,
        HistoricalPlaytimeFilter.where(when__within=("2024-01-01", "2024-12-31")),
    ) == {"month", "year"}


def test_between_reads_overlap(owned_library, shaped_records):
    assert matched(
        owned_library,
        HistoricalPlaytimeFilter.where(when__between=("2024-01-01", "2024-12-31")),
    ) == {"month", "year", "straddling", "open start"}


def test_within_is_offered_on_an_interval_field_alone():
    from games.filters import PurchaseFilter

    when = next(
        entry
        for entry in field_metadata(HistoricalPlaytimeFilter)
        if entry["name"] == "when"
    )
    purchased = next(
        entry
        for entry in field_metadata(PurchaseFilter)
        if entry["name"] == "date_purchased"
    )
    assert Modifier.WITHIN.value in when["modifiers"]
    assert Modifier.WITHIN.value not in purchased["modifiers"]


def test_within_on_a_scalar_date_is_between():
    bounds = {"value": "2024-01-01", "value2": "2024-12-31"}
    assert str(DateCriterion(modifier=Modifier.WITHIN, **bounds).to_q("day")) == str(
        DateCriterion(modifier=Modifier.BETWEEN, **bounds).to_q("day")
    )


def test_within_wants_two_bounds():
    from common.criteria import FilterError

    with pytest.raises(FilterError, match="WITHIN"):
        HistoricalPlaytimeFilter(
            when=DateCriterion(value="2024-01-01", modifier=Modifier.WITHIN)
        ).to_q()
