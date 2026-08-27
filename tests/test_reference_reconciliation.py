"""Whether recorded references still name rows."""

import uuid
from io import StringIO
from typing import ClassVar, TypedDict

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext, isolate_apps
from pydantic import ConfigDict, with_config
from test_projection_rebuild import (
    create_tables,
    relation_exists,
    seed_shelf,
    shadow_of,
)
from test_projection_targets import SHELF_TABLE, declare_projection_models

from games.events.append import lock_stream
from games.events.envelope import RecordedEvent
from games.events.projection import (
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.reconcile import (
    GAP_SAMPLE_LIMIT,
    MESSAGE_GAP_LIMIT,
    NO_SNAPSHOT_RECORDED,
    UnresolvedReferences,
    reconcile_references,
)
from games.events.references import (
    Reference,
    ReferenceKind,
    ReferenceKindRegistry,
    Resolution,
    UnknownReferenceKind,
    capture_reference,
)
from games.events.replay import replay
from games.events.vocabulary import EventSpec, EventTypeRegistry
from games.events.wiring import EventWiring
from games.models import Device, Game, LibraryEvent, LibraryEventReference, Platform
from games.retention import (
    UnresolvableReference,
    purging_library,
    resolve_reference,
    tombstone_or_delete,
    unresolved_among,
)

pytestmark = pytest.mark.django_db

STRICT_CONFIG = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT_CONFIG)
class DevicePayload(TypedDict):
    device: Reference
    note: str


@with_config(STRICT_CONFIG)
class EveryArityPayload(TypedDict):
    game: Reference
    device: Reference | None
    platforms: list[Reference]


@with_config(STRICT_CONFIG)
class EvidencePayload(TypedDict):
    platform: Reference


def _capture_device(device: Device) -> Reference:
    return Reference(
        kind="device", id=str(device.pk), label=device.name, detail=device.type
    )


def _capture_game(game: Game) -> Reference:
    return Reference(
        kind="catalog.game",
        id=str(game.pk),
        label=game.name,
        detail=str(game.year_released),
    )


def _capture_platform(platform: Platform) -> Reference:
    return Reference(
        kind="catalog.platform",
        id=str(platform.pk),
        label=platform.name,
        detail=platform.group,
    )


#: This module's own kinds, never production's.
KINDS = ReferenceKindRegistry()
KINDS.register(
    ReferenceKind(
        name="device",
        model=Device,
        capture=_capture_device,
        resolution=Resolution.REQUIRED,
    )
)
KINDS.register(
    ReferenceKind(
        name="catalog.game",
        model=Game,
        capture=_capture_game,
        resolution=Resolution.REQUIRED,
    )
)
#: EVIDENCE_ONLY here, so a skip is testable.
KINDS.register(
    ReferenceKind(
        name="catalog.platform",
        model=Platform,
        capture=_capture_platform,
        resolution=Resolution.EVIDENCE_ONLY,
    )
)

DEVICE_RECORDED = EventSpec(
    "library.device.recorded", aggregate_type="probe", payload=DevicePayload
)
EVERYTHING_RECORDED = EventSpec(
    "library.everything.recorded", aggregate_type="probe", payload=EveryArityPayload
)
PLATFORM_RECORDED = EventSpec(
    "library.platform.recorded", aggregate_type="probe", payload=EvidencePayload
)

EVENT_TYPES = EventTypeRegistry(reference_kinds=KINDS)
for registered_spec in (DEVICE_RECORDED, EVERYTHING_RECORDED, PLATFORM_RECORDED):
    EVENT_TYPES.register(registered_spec)

#: Which events a replay reached.
REPLAYED: list[int] = []

REGISTRY = ProjectorRegistry()
WIRING = EventWiring(event_types=EVENT_TYPES, projectors=REGISTRY)


class Recorder(Projector, registry=REGISTRY):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        REPLAYED.append(event.sequence)

    handles: ClassVar[HandlerMap] = {
        DEVICE_RECORDED: _recorded,
        EVERYTHING_RECORDED: _recorded,
        PLATFORM_RECORDED: _recorded,
    }


@pytest.fixture(autouse=True)
def forget_replayed_events():
    REPLAYED.clear()
    yield
    REPLAYED.clear()


@pytest.fixture
def device(owned_library):
    return Device.objects.create(
        library=owned_library, name="Steam Deck", type=Device.HANDHELD
    )


@pytest.fixture
def game(owned_library):
    return Game.objects.create(
        library=owned_library, name="Baldur's Gate 3", year_released=2023
    )


@pytest.fixture
def platform(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Steam", group="PC storefronts"
    )


def append(library, events, *, key="reconcile-key"):
    with transaction.atomic():
        return lock_stream(library).append(
            events,
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
            wiring=WIRING,
        )


def device_event(device, note="moved"):
    return DEVICE_RECORDED.new(
        aggregate_id=uuid.uuid7(),
        payload=DevicePayload(device=capture_reference(device, kinds=KINDS), note=note),
    )


def everything_event(game, device, platforms):
    return EVERYTHING_RECORDED.new(
        aggregate_id=uuid.uuid7(),
        payload=EveryArityPayload(
            game=capture_reference(game, kinds=KINDS),
            device=None if device is None else capture_reference(device, kinds=KINDS),
            platforms=[capture_reference(one, kinds=KINDS) for one in platforms],
        ),
    )


def platform_event(platform):
    return PLATFORM_RECORDED.new(
        aggregate_id=uuid.uuid7(),
        payload=EvidencePayload(platform=capture_reference(platform, kinds=KINDS)),
    )


def strand(instance) -> None:
    """The one way a row can leave."""
    with purging_library():
        instance.delete()


def reconcile(library):
    return reconcile_references(library, kinds=KINDS)


# --- what still resolves ----------------------------------------------------


def test_a_live_row_resolves(owned_library, device):
    append(owned_library, [device_event(device)])

    reconciliation = reconcile(owned_library)

    assert reconciliation.resolves
    assert reconciliation.unresolved == 0
    assert reconciliation.gaps == ()
    assert reconciliation.library_id == owned_library.pk
    assert reconciliation.kinds_checked == ("device",)


def test_a_tombstoned_row_resolves(owned_library, device):
    """The retention policy's whole point, read back."""
    append(owned_library, [device_event(device)])

    tombstone_or_delete(device)

    #: Gone from the library, still stored.
    assert not Device.objects.for_library(owned_library).filter(pk=device.pk).exists()
    assert reconcile(owned_library).resolves


def test_another_library_row_resolves(owned_library, django_user_model, device):
    """Pinned today, so #909 finds it named."""
    other_library = django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library
    other_device = Device.objects.create(
        library=other_library, name="Their Deck", type=Device.HANDHELD
    )
    append(owned_library, [device_event(other_device)])

    assert reconcile(owned_library).resolves


def test_a_strand_in_one_library_says_nothing_about_another(
    owned_library, django_user_model, device
):
    other_library = django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library
    other_device = Device.objects.create(
        library=other_library, name="Their Deck", type=Device.HANDHELD
    )
    append(owned_library, [device_event(device)])
    append(other_library, [device_event(other_device)], key="other-key")

    strand(other_device)

    assert reconcile(owned_library).resolves
    assert not reconcile(other_library).resolves


# --- what a gap says --------------------------------------------------------


def test_a_stranded_row_is_one_gap(owned_library, device):
    result = append(owned_library, [device_event(device)])
    stranded_id = device.pk

    strand(device)

    reconciliation = reconcile(owned_library)
    assert not reconciliation.resolves
    assert reconciliation.unresolved == 1
    gap = reconciliation.gaps[0]
    assert gap.kind == "device"
    assert gap.referenced_id == stranded_id
    assert gap.label == "Steam Deck"
    assert gap.detail == Device.HANDHELD
    assert gap.payload_key == "device"
    assert gap.first_sequence == result.events[0].sequence
    assert gap.event_count == 1


def test_many_events_naming_one_stranded_row_are_one_gap(owned_library, device):
    for number in range(4):
        append(owned_library, [device_event(device)], key=f"key-{number}")

    strand(device)

    (gap,) = reconcile(owned_library).gaps
    assert gap.event_count == 4
    assert gap.first_sequence == 1


def test_one_event_naming_a_row_twice_is_one_event(owned_library, game, platform):
    """The count is events, not index rows."""
    kinds = ReferenceKindRegistry()
    kinds.register(
        ReferenceKind(
            name="catalog.game",
            model=Game,
            capture=_capture_game,
            resolution=Resolution.REQUIRED,
        )
    )
    kinds.register(
        ReferenceKind(
            name="catalog.platform",
            model=Platform,
            capture=_capture_platform,
            resolution=Resolution.REQUIRED,
        )
    )
    append(owned_library, [everything_event(game, None, [platform, platform])])

    strand(platform)

    (gap,) = reconcile_references(owned_library, kinds=kinds).gaps
    assert LibraryEventReference.objects.filter(kind="catalog.platform").count() == 2
    assert gap.event_count == 1


def test_a_sequence_field_names_its_key_and_its_entry(
    owned_library, game, device, platform
):
    second_platform = Platform.objects.create(
        library=owned_library, name="GOG", group="PC storefronts"
    )
    append(owned_library, [everything_event(game, device, [platform, second_platform])])

    #: Platforms are evidence only here.
    strand(game)
    with purging_library():
        second_platform.delete()

    (gap,) = reconcile(owned_library).gaps
    assert gap.kind == "catalog.game"
    assert gap.payload_key == "game"
    assert gap.label == "Baldur's Gate 3"
    assert gap.detail == "2023"


def test_a_list_entry_is_the_one_the_gap_names(owned_library, game, platform):
    """The matching entry, not the first."""
    second_platform = Platform.objects.create(
        library=owned_library, name="GOG", group="PC storefronts"
    )
    kinds = ReferenceKindRegistry()
    kinds.register(
        ReferenceKind(
            name="catalog.game",
            model=Game,
            capture=_capture_game,
            resolution=Resolution.REQUIRED,
        )
    )
    kinds.register(
        ReferenceKind(
            name="catalog.platform",
            model=Platform,
            capture=_capture_platform,
            resolution=Resolution.REQUIRED,
        )
    )
    append(owned_library, [everything_event(game, None, [platform, second_platform])])

    with purging_library():
        second_platform.delete()

    (gap,) = reconcile_references(owned_library, kinds=kinds).gaps
    assert gap.kind == "catalog.platform"
    assert gap.payload_key == "platforms"
    assert gap.label == "GOG"


def test_a_payload_that_does_not_hold_the_row_says_so(owned_library, device):
    """A disagreement is legible, not blank."""
    append(owned_library, [device_event(device)])
    LibraryEvent.objects.update(
        payload={"device": _capture_device(device) | {"id": str(uuid.uuid7())}}
    )

    strand(device)

    (gap,) = reconcile(owned_library).gaps
    assert gap.label == NO_SNAPSHOT_RECORDED
    assert gap.detail == ""


# --- which kinds are checked ------------------------------------------------


def test_an_evidence_only_kind_is_skipped(owned_library, platform):
    append(owned_library, [platform_event(platform)])

    assert reconcile(owned_library).kinds_checked == ()

    strand(platform)

    reconciliation = reconcile(owned_library)
    assert reconciliation.resolves
    assert reconciliation.gaps == ()


def test_an_unregistered_kind_refuses(owned_library, device):
    result = append(owned_library, [device_event(device)])
    LibraryEventReference.objects.create(
        library=owned_library,
        event=result.events[0],
        kind="catalog.retired",
        referenced_id=uuid.uuid7(),
        payload_key="device",
    )

    with pytest.raises(UnknownReferenceKind):
        reconcile(owned_library)


def test_the_set_rule_agrees_with_the_single_row_rule(
    owned_library, device, game, platform
):
    """One rule, two callers."""
    append(owned_library, [everything_event(game, device, [platform])])
    tombstone_or_delete(game)
    strand(platform)

    index = LibraryEventReference.objects.for_library(owned_library)
    for kind_name in ("device", "catalog.game", "catalog.platform"):
        kind = KINDS.kind_for(kind_name)
        unresolved = set(
            unresolved_among(kind, index.filter(kind=kind_name)).values_list(
                "referenced_id", flat=True
            )
        )
        for row in index.filter(kind=kind_name):
            reference = Reference(
                kind=kind_name, id=str(row.referenced_id), label="", detail=""
            )
            try:
                resolve_reference(reference, kinds=KINDS)
            except UnresolvableReference:
                assert row.referenced_id in unresolved
            else:
                assert row.referenced_id not in unresolved


# --- the bound --------------------------------------------------------------


def stranded_many(library, count: int) -> None:
    """Name `count` devices, then strand them."""
    devices = [
        Device.objects.create(library=library, name=f"Deck {number}", type=Device.PC)
        for number in range(count)
    ]
    append(library, [device_event(one) for one in devices])
    for one in devices:
        strand(one)


def test_the_report_is_bounded_and_the_count_is_not(owned_library):
    stranded_many(owned_library, GAP_SAMPLE_LIMIT + 5)

    reconciliation = reconcile(owned_library)

    assert reconciliation.unresolved == GAP_SAMPLE_LIMIT + 5
    assert len(reconciliation.gaps) == GAP_SAMPLE_LIMIT
    assert reconciliation.gaps == reconcile(owned_library).gaps


def test_the_report_is_ordered_by_kind_and_row(owned_library):
    stranded_many(owned_library, 5)

    gaps = reconcile(owned_library).gaps

    assert [(gap.kind, gap.referenced_id) for gap in gaps] == sorted(
        (gap.kind, gap.referenced_id) for gap in gaps
    )


def test_the_bound_is_applied_before_the_detail_is_read(owned_library):
    """Twenty payloads, whatever the accident's size."""
    stranded_many(owned_library, 50)

    with CaptureQueriesContext(connection) as captured:
        reconcile(owned_library)

    described = [
        query["sql"]
        for query in captured.captured_queries
        if "DISTINCT ON" in query["sql"]
    ]
    assert len(described) == 1
    assert described[0].count('referenced_id" = ') == GAP_SAMPLE_LIMIT


# --- what it costs ----------------------------------------------------------


@pytest.mark.parametrize("events", (1, 20))
def test_a_reconciliation_costs_one_query_per_kind(
    owned_library, device, game, platform, events, django_assert_num_queries
):
    append(
        owned_library,
        [everything_event(game, device, [platform]) for _ in range(events)],
    )

    #: The kinds, then one anti-join each.
    with django_assert_num_queries(3):
        assert reconcile(owned_library).resolves


@pytest.mark.parametrize("events", (1, 20))
def test_describing_a_gap_costs_two_more(
    owned_library, device, game, platform, events, django_assert_num_queries
):
    append(
        owned_library,
        [everything_event(game, device, [platform]) for _ in range(events)],
    )
    strand(device)

    with django_assert_num_queries(5):
        assert not reconcile(owned_library).resolves


# --- what a replay does with it ---------------------------------------------


def test_a_replay_refuses_before_it_touches_anything(owned_library, device):
    append(owned_library, [device_event(device), device_event(device)], key="two")
    strand(device)
    REPLAYED.clear()

    with pytest.raises(UnresolvedReferences):
        replay(owned_library, wiring=WIRING)

    assert REPLAYED == []


def test_the_refusal_carries_every_gap(owned_library):
    stranded_many(owned_library, 3)
    REPLAYED.clear()

    with pytest.raises(UnresolvedReferences) as raised:
        replay(owned_library, wiring=WIRING)

    reconciliation = raised.value.reconciliation
    assert reconciliation.unresolved == 3
    assert len(reconciliation.gaps) == 3


def test_the_refusal_names_the_remedy_and_the_rest(owned_library):
    stranded_many(owned_library, MESSAGE_GAP_LIMIT + 2)

    with pytest.raises(UnresolvedReferences) as raised:
        replay(owned_library, wiring=WIRING)

    message = str(raised.value)
    assert "Restore each one under the same id" in message
    assert "and 2 more" in message
    assert message.count("first named by event #") == MESSAGE_GAP_LIMIT


def test_a_library_whose_references_resolve_replays_as_before(owned_library, device):
    append(owned_library, [device_event(device), device_event(device)], key="two")
    REPLAYED.clear()

    result = replay(owned_library, wiring=WIRING)

    assert result.replayed_through == 2
    assert REPLAYED == [1, 2]


def test_a_library_with_no_head_never_reconciles(
    owned_library, django_assert_num_queries
):
    """No stream, no references, one query."""
    with django_assert_num_queries(1):
        result = replay(owned_library, wiring=WIRING)

    assert result.stream_id is None
    assert result.replayed_through == 0


def test_another_library_strand_does_not_refuse_this_replay(
    owned_library, django_user_model, device
):
    other_library = django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library
    other_device = Device.objects.create(
        library=other_library, name="Their Deck", type=Device.HANDHELD
    )
    append(owned_library, [device_event(device)])
    append(other_library, [device_event(other_device)], key="other-key")
    strand(other_device)
    REPLAYED.clear()

    assert replay(owned_library, wiring=WIRING).replayed_through == 1
    with pytest.raises(UnresolvedReferences):
        replay(other_library, wiring=WIRING)


# --- what a rebuild does with it --------------------------------------------


def shelf_holding_one_row(library):
    """A live row a swap would remove."""
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, library)
    return shelf


@pytest.mark.parametrize("mode", (RebuildMode.REBUILD, RebuildMode.CHECK))
@isolate_apps("games")
def test_a_rebuild_refuses_and_leaves_the_live_table_as_it_was(
    owned_library, device, mode
):
    shelf = shelf_holding_one_row(owned_library)
    append(owned_library, [device_event(device)])
    strand(device)

    with pytest.raises(UnresolvedReferences):
        rebuild_projections(
            owned_library, mode=mode, wiring=WIRING, apps=shelf._meta.apps
        )

    assert shelf.objects.count() == 1
    #: The shadow block drops its tables.
    assert not relation_exists(shadow_of(SHELF_TABLE))


def test_a_broken_library_does_not_stop_another_rebuild(
    owned_library, django_user_model, device
):
    other_library = django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library
    other_device = Device.objects.create(
        library=other_library, name="Their Deck", type=Device.HANDHELD
    )
    append(owned_library, [device_event(device)])
    append(other_library, [device_event(other_device)], key="other-key")
    strand(other_device)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD, wiring=WIRING)

    assert report.swapped is True
    with pytest.raises(UnresolvedReferences):
        rebuild_projections(other_library, mode=RebuildMode.REBUILD, wiring=WIRING)


# --- what the operator reads ------------------------------------------------


def run_command(*arguments) -> tuple[str, str]:
    """Both streams, whether it failed or not."""
    stdout, stderr = StringIO(), StringIO()
    call_command("rebuild_projections", *arguments, stdout=stdout, stderr=stderr)
    return stdout.getvalue(), stderr.getvalue()


@pytest.mark.parametrize("arguments", ((), ("--check",)))
def test_the_command_fails_and_names_the_stranded_row(owned_library, device, arguments):
    """Both modes refuse."""
    stranded_id = device.pk
    result = append(owned_library, [device_event(device)])
    strand(device)
    stderr = StringIO()

    with pytest.raises(CommandError, match="nothing was replayed"):
        call_command(
            "rebuild_projections",
            str(owned_library.pk),
            *arguments,
            stdout=StringIO(),
            stderr=stderr,
        )

    printed = stderr.getvalue()
    assert f"device {stranded_id}" in printed
    assert "'Steam Deck'" in printed
    assert f"first named by event #{result.events[0].sequence}" in printed
    assert "at payload key 'device'" in printed
    assert "Restore each one under the same id" in printed


def test_the_printed_report_counts_what_it_did_not_name(owned_library):
    stranded_many(owned_library, GAP_SAMPLE_LIMIT + 2)
    stderr = StringIO()

    with pytest.raises(CommandError):
        call_command(
            "rebuild_projections",
            str(owned_library.pk),
            stdout=StringIO(),
            stderr=stderr,
        )

    printed = stderr.getvalue()
    assert f"name {GAP_SAMPLE_LIMIT + 2} row(s) that no longer exist" in printed
    assert printed.count("first named by event #") == GAP_SAMPLE_LIMIT
    assert "and 2 more." in printed


def test_a_swap_says_the_references_resolved(owned_library):
    """Nothing counts them outward."""
    stdout, _ = run_command(str(owned_library.pk))

    assert "Swapped" in stdout
    assert "References: all resolved." in stdout
