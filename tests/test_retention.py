"""What a delete does to referenced rows.

The load-bearing claim is not "the row stays". It is that
everything else the delete would do still happens.
"""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from typing import TypedDict

import pytest
from django.core.management import call_command
from django.db import transaction
from django.db.models.deletion import RestrictedError
from pydantic import ConfigDict, with_config

from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    Reference,
    ReferenceKindRegistry,
    Resolution,
    capture_reference,
)
from games.events.vocabulary import EventSpec, EventTypeRegistry
from games.events.wiring import EventWiring
from games.models import (
    Device,
    Edition,
    Game,
    LibraryEvent,
    LibraryEventReference,
    Platform,
    PlayerGame,
    PlayEvent,
    Purchase,
    Release,
    Session,
    UserLibraryPreferences,
)
from games.retention import (
    ReferencedRowDeletion,
    Retirement,
    UnresolvableReference,
    must_be_retained,
    purging_library,
    reference_count,
    resolve_reference,
    tombstone_or_delete,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


@with_config(ConfigDict(extra="forbid", strict=True))
class RowNamedPayload(TypedDict):
    row: Reference


ROW_NAMED = EventSpec(
    "library.row.named", aggregate_type="probe", payload=RowNamedPayload
)

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(ROW_NAMED)
WIRING = EventWiring(event_types=EVENT_TYPES)


def name_in_an_event(library, instance, *, key=None):
    """Record one event naming `instance`."""
    reference = capture_reference(instance)
    with transaction.atomic():
        lock_stream(library).append(
            [ROW_NAMED.new(aggregate_id=uuid.uuid7(), payload={"row": reference})],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key=key or f"names-{reference['id']}",
            wiring=WIRING,
        )
    return reference


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


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


@pytest.fixture
def device(owned_library):
    return Device.objects.create(
        library=owned_library, name="Steam Deck", type=Device.HANDHELD
    )


# --- an unreferenced row is still really deleted -----------------------------


def test_an_unreferenced_game_is_deleted(game):
    assert tombstone_or_delete(game) is Retirement.DELETED

    assert not Game.objects.filter(pk=game.pk).exists()


def test_an_unreferenced_platform_is_deleted(platform):
    assert tombstone_or_delete(platform) is Retirement.DELETED

    assert not Platform.objects.filter(pk=platform.pk).exists()


def test_an_unreferenced_device_is_deleted(device):
    assert tombstone_or_delete(device) is Retirement.DELETED

    assert not Device.objects.filter(pk=device.pk).exists()


# --- a referenced row is retained --------------------------------------------


def test_a_referenced_game_is_tombstoned(owned_library, game):
    name_in_an_event(owned_library, game)

    assert tombstone_or_delete(game) is Retirement.TOMBSTONED

    retained = Game.objects.get(pk=game.pk)
    assert retained.tombstoned_at is not None
    assert not Game.objects.for_library(owned_library).exists()


def test_a_tracked_game_is_tombstoned_and_keeps_its_projection_row(
    owned_user, owned_library
):
    """A tombstone must not delete a projection row."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    assert tombstone_or_delete(game) is Retirement.TOMBSTONED

    assert Game.objects.get(pk=game.pk).tombstoned_at is not None
    assert PlayerGame.objects.filter(game=game).count() == 1


def test_a_tracked_game_refuses_a_hard_delete(owned_user, owned_library):
    #: The policy answers, not the foreign key.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    with pytest.raises(ReferencedRowDeletion, match="tombstone_or_delete"):
        game.delete()

    assert Game.objects.filter(pk=game.pk).exists()


def test_a_bulk_delete_of_a_tracked_game_still_answers_restricted(
    owned_user, owned_library
):
    """A queryset never reaches `Model.delete()`.

    The limit of the override, written down rather than found. Every path a
    person takes deletes one row, so the message they read is the policy's.
    """
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    with pytest.raises(RestrictedError):
        Game.objects.filter(pk=game.pk).delete()

    assert Game.objects.filter(pk=game.pk).exists()


def test_a_referenced_platform_is_tombstoned(owned_library, platform):
    name_in_an_event(owned_library, platform)

    assert tombstone_or_delete(platform) is Retirement.TOMBSTONED

    assert Platform.objects.get(pk=platform.pk).tombstoned_at is not None


def test_a_referenced_device_is_tombstoned(owned_library, device):
    name_in_an_event(owned_library, device)

    assert tombstone_or_delete(device) is Retirement.TOMBSTONED

    assert Device.objects.get(pk=device.pk).tombstoned_at is not None


def test_a_shared_platform_one_library_referenced_is_retained_for_everyone(
    owned_library,
):
    """Retention is not library-scoped."""
    shared = Platform.objects.create(name="Steam", group="PC storefronts")
    name_in_an_event(owned_library, shared)

    assert must_be_retained(shared)
    assert tombstone_or_delete(shared) is Retirement.TOMBSTONED


def test_reference_count_counts_events_not_rows(owned_library, device):
    name_in_an_event(owned_library, device, key="first")
    name_in_an_event(owned_library, device, key="second")

    assert reference_count(device) == 2


# --- retiring is deleting, minus the row -------------------------------------


class LibraryState(TypedDict):
    """What a library has left after a game goes."""

    sessions: int
    play_events: int
    purchases: int
    editions: int
    releases: int
    bundle_count: int | None
    other_game_playtime: timedelta


def populate(library):
    """One game with everything below it.

    The bystander shares a bundle purchase, so the bundle survives
    with a lower count and the single-game purchase does not.
    """
    platform = Platform.objects.create(library=library, name="Steam", group="PC")
    doomed = Game.objects.create(
        library=library, name="Doomed", year_released=2023, platform=platform
    )
    bystander = Game.objects.create(
        library=library, name="Bystander", year_released=2024, platform=platform
    )
    Session.objects.create(
        game=doomed,
        timestamp_start=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 1, 12, tzinfo=UTC),
    )
    Session.objects.create(
        game=bystander,
        timestamp_start=datetime(2026, 1, 2, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 2, 11, tzinfo=UTC),
    )
    PlayEvent.objects.create(game=doomed, started=date(2026, 1, 1))
    edition = Edition.objects.create(game=doomed, is_default=True)
    Release.objects.create(edition=edition, is_default=True, platform=platform)

    alone = Purchase.objects.create(
        library=library,
        date_purchased=date(2026, 1, 1),
        platform=platform,
        price_currency="USD",
    )
    alone.games.set([doomed])
    bundle = Purchase.objects.create(
        library=library,
        date_purchased=date(2026, 1, 2),
        platform=platform,
        price_currency="USD",
    )
    bundle.games.set([doomed, bystander])
    return doomed, bundle, bystander


def snapshot(library, bundle, bystander) -> LibraryState:
    surviving = Purchase.objects.filter(pk=bundle.pk).first()
    return LibraryState(
        sessions=Session.objects.filter(game__library=library).count(),
        play_events=PlayEvent.objects.filter(game__library=library).count(),
        purchases=Purchase.objects.filter(library=library).count(),
        editions=Edition.objects.filter(game__library=library).count(),
        releases=Release.objects.filter(edition__game__library=library).count(),
        bundle_count=None if surviving is None else surviving.num_purchases,
        other_game_playtime=Game.objects.get(pk=bystander.pk).playtime,
    )


def test_tombstoning_leaves_exactly_what_deleting_would(owned_library, other_library):
    """The tombstone did not change product behaviour.

    The same fixture in two libraries. One game is tombstoned, one is
    deleted. What the two libraries have left must match.
    """
    deleted_game, deleted_bundle, deleted_bystander = populate(owned_library)
    tombstoned_game, tombstoned_bundle, tombstoned_bystander = populate(other_library)
    name_in_an_event(other_library, tombstoned_game)

    assert tombstone_or_delete(deleted_game) is Retirement.DELETED
    assert tombstone_or_delete(tombstoned_game) is Retirement.TOMBSTONED

    after_delete = snapshot(owned_library, deleted_bundle, deleted_bystander)
    after_tombstone = snapshot(other_library, tombstoned_bundle, tombstoned_bystander)
    assert after_tombstone == after_delete
    #: Not vacuous: the fixture had things to lose.
    assert after_delete == LibraryState(
        sessions=1,
        play_events=0,
        purchases=1,
        editions=0,
        releases=0,
        bundle_count=1,
        other_game_playtime=timedelta(hours=1),
    )


def test_tombstoning_a_platform_nulls_what_deleting_would(owned_library, platform):
    game = Game.objects.create(
        library=owned_library, name="Tetris", year_released=1984, platform=platform
    )
    purchase = Purchase.objects.create(
        library=owned_library,
        date_purchased=date(2026, 1, 1),
        platform=platform,
        price_currency="USD",
    )
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(
        edition=edition, is_default=True, platform=platform
    )
    name_in_an_event(owned_library, platform)

    tombstone_or_delete(platform)

    assert Game.objects.get(pk=game.pk).platform_id is None
    assert Purchase.objects.get(pk=purchase.pk).platform_id is None
    assert Release.objects.get(pk=release.pk).platform_id is None


def test_tombstoning_a_device_nulls_what_deleting_would(owned_library, game, device):
    session = Session.objects.create(
        game=game,
        device=device,
        timestamp_start=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 1, 11, tzinfo=UTC),
    )
    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    preferences.set_default_device(device)
    name_in_an_event(owned_library, device)

    tombstone_or_delete(device)

    assert Session.objects.get(pk=session.pk).device_id is None
    preferences.refresh_from_db()
    assert preferences.default_device_id is None


# --- the reference still resolves --------------------------------------------


def test_a_tombstoned_row_still_resolves(owned_library, game):
    reference = name_in_an_event(owned_library, game)

    tombstone_or_delete(game)

    assert resolve_reference(reference) == game


def test_a_live_row_resolves(owned_library, platform):
    reference = name_in_an_event(owned_library, platform)

    assert resolve_reference(reference) == platform


def test_a_row_that_left_outside_the_policy_reports_itself(owned_library, device):
    reference = name_in_an_event(owned_library, device)
    with purging_library():
        device.delete()

    with pytest.raises(UnresolvableReference) as raised:
        resolve_reference(reference)

    assert raised.value.reference == reference


# --- the guard holds outside the views ---------------------------------------


@pytest.mark.parametrize("fixture", ["game", "platform", "device"])
def test_a_raw_delete_of_a_referenced_row_is_refused(owned_library, request, fixture):
    instance = request.getfixturevalue(fixture)
    name_in_an_event(owned_library, instance)

    with pytest.raises(ReferencedRowDeletion, match="tombstone_or_delete"):
        instance.delete()

    assert type(instance).objects.filter(pk=instance.pk).exists()


def test_a_raw_delete_of_an_unreferenced_row_is_allowed(game):
    game.delete()

    assert not Game.objects.filter(pk=game.pk).exists()


def test_a_cascade_that_would_take_a_referenced_row_is_refused(owned_library, game):
    """A cascade reaches the row, and is stopped."""
    name_in_an_event(owned_library, game)

    with pytest.raises(ReferencedRowDeletion):
        owned_library.user.delete()


# --- except during a whole-library purge -------------------------------------


def test_purging_a_library_takes_its_referenced_rows(owned_user, owned_library, game):
    name_in_an_event(owned_library, game)

    call_command(
        "delete_user_library",
        user=owned_user.username,
        confirm=owned_user.username,
        stdout=StringIO(),
    )

    assert not Game.objects.filter(pk=game.pk).exists()
    assert not LibraryEvent.objects.exists()
    assert not LibraryEventReference.objects.exists()


def test_purging_one_library_leaves_the_others_rows(
    owned_user, owned_library, other_library
):
    mine = Game.objects.create(library=owned_library, name="Mine", year_released=2023)
    theirs = Game.objects.create(
        library=other_library, name="Theirs", year_released=2023
    )
    shared = Platform.objects.create(name="Steam", group="PC storefronts")
    name_in_an_event(owned_library, mine, key="mine")
    name_in_an_event(other_library, theirs, key="theirs")
    name_in_an_event(other_library, shared, key="shared")

    call_command(
        "delete_user_library",
        user=owned_user.username,
        confirm=owned_user.username,
        stdout=StringIO(),
    )

    assert not Game.objects.filter(pk=mine.pk).exists()
    assert Game.objects.for_library(other_library).get() == theirs
    assert Platform.objects.get(pk=shared.pk) == shared
    assert LibraryEventReference.objects.for_library(other_library).count() == 2


def test_purging_a_library_takes_its_projection_rows_with_it(owned_library):
    """A CASCADE through the library clears RESTRICT."""
    user = owned_library.user
    game = Game.objects.create(library=owned_library, name="Purged")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    assert PlayerGame.objects.filter(library=owned_library).exists()

    with transaction.atomic(), purging_library():
        user.delete()

    assert not PlayerGame.objects.filter(library=owned_library).exists()
    assert not Game.objects.filter(pk=game.pk).exists()


def test_the_exemption_does_not_outlive_the_purge(owned_library, game):
    name_in_an_event(owned_library, game)
    with purging_library():
        pass

    with pytest.raises(ReferencedRowDeletion):
        game.delete()


# --- an evidence-only kind is not retained -----------------------------------


def test_an_evidence_only_kind_is_free_to_go(owned_library, device):
    """An EVIDENCE_ONLY row is free to go.

    Every registered kind is REQUIRED today. Use a local registry.
    """
    name_in_an_event(owned_library, device)
    evidence_only = ReferenceKindRegistry()
    evidence_only.register(
        replace(
            DEFAULT_REFERENCE_KINDS.kind_of(device),
            resolution=Resolution.EVIDENCE_ONLY,
        )
    )

    assert reference_count(device, kinds=evidence_only) == 1
    assert must_be_retained(device)
    assert not must_be_retained(device, kinds=evidence_only)
