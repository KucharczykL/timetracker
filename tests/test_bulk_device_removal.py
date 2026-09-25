"""Remove devices in bulk; undo the batch."""

import json
import uuid
from datetime import date, timedelta

import pytest
from bulk_posts import act_url, posted, selection
from devices import create_device, remove_device
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from games.bulk_actions import BULK_ACTIONS, RowOutcome
from games.bulk_removal import DEVICE_GONE, REMOVE_DEVICE
from games.models import Device, Game, PlayerSession
from games.reads.device_departures import naming_sessions_of
from games.reads.events import batch_aggregate_ids
from games.views.bulk import STATEMENT_FIELD, TOKEN_FIELD
from games.views.device_menu import device_row_menu

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def deck(owned_library):
    return create_device(owned_library, "Steam Deck", Device.HANDHELD)


@pytest.fixture
def tower(owned_library):
    return create_device(owned_library, "Tower", Device.PC)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _session_on(library, device, *, day=date(2026, 3, 5)) -> PlayerSession:
    game = Game.objects.create(library=library, name=f"Game {uuid.uuid7()}")
    return duration_only_row(
        tracked_run(library, game), day, timedelta(hours=1), device=device
    )


def test_the_act_is_declared():
    assert BULK_ACTIONS["device.remove"] is REMOVE_DEVICE
    assert REMOVE_DEVICE.inverse_aggregate == "device"


# ── The rows ─────────────────────────────────────────────────────────────────


def test_the_scope_is_the_lists_live_read(owned_library, deck, tower):
    remove_device(tower)

    assert list(REMOVE_DEVICE.scope(owned_library, "")) == [deck]


def test_the_scope_narrows_by_the_statements_filter(owned_library, deck, tower):
    narrowed = REMOVE_DEVICE.scope(
        owned_library,
        json.dumps({"name": {"value": "Tower", "modifier": "EQUALS"}}),
    )

    assert list(narrowed) == [tower]


def test_a_key_the_library_does_not_hold_comes_out_lost(
    owned_library, django_user_model, deck
):
    elsewhere = create_device(
        django_user_model.objects.create_user("stranger").library, "Theirs"
    )

    resolution = REMOVE_DEVICE.resolve(owned_library, [deck.pk, elsewhere.pk])

    assert [row.pk for row in resolution.rows] == [deck.pk]
    assert [
        (entry.key, entry.lost, entry.sentence) for entry in resolution.refused
    ] == [(str(elsewhere.pk), True, DEVICE_GONE)]


def test_the_count_is_the_live_sessions_naming_each_device(owned_library, deck, tower):
    _session_on(owned_library, deck)
    _session_on(owned_library, deck, day=date(2026, 3, 6))
    gone = _session_on(owned_library, deck, day=date(2026, 3, 7))
    PlayerSession.objects.filter(pk=gone.pk).update(removed_at=timezone.now())

    rows = REMOVE_DEVICE.resolve(owned_library, [deck.pk, tower.pk]).rows

    #: Name order.
    assert [(row.name, naming_sessions_of(row)) for row in rows] == [
        ("Steam Deck", 2),
        ("Tower", 0),
    ]


# ── Run and undo ─────────────────────────────────────────────────────────────


def test_the_act_removes_and_its_undo_restores(owned_user, deck):
    assert (
        REMOVE_DEVICE.run(
            owned_user,
            deck,
            choice=None,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )
        is RowOutcome.MOVED
    )
    deck.refresh_from_db()
    assert deck.removed_at is not None

    assert (
        REMOVE_DEVICE.inverse(
            owned_user,
            deck.pk,
            undoes=uuid.uuid7(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )
        is RowOutcome.MOVED
    )
    deck.refresh_from_db()
    assert deck.removed_at is None


def test_a_device_restored_since_the_batch_answers_unchanged(owned_user, deck):
    assert (
        REMOVE_DEVICE.inverse(
            owned_user,
            deck.pk,
            undoes=uuid.uuid7(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )
        is RowOutcome.UNCHANGED
    )


def test_a_batch_removes_and_its_undo_puts_every_row_back(
    logged_in, owned_library, deck, tower
):
    url = act_url(REMOVE_DEVICE)
    confirmation = logged_in.post(url, {STATEMENT_FIELD: selection(deck, tower)})
    html = confirmation.content.decode()
    for heading in ("Device", "Type", "Sessions", "Remove these devices"):
        assert heading in html
    submitted = posted(confirmation)

    logged_in.post(url, submitted)
    #: The same token again acts once.
    logged_in.post(url, submitted)

    assert not Device.objects.for_library(owned_library).exists()
    batch = uuid.UUID(submitted[TOKEN_FIELD])
    assert set(batch_aggregate_ids(owned_library, batch, "device")) == {
        deck.pk,
        tower.pk,
    }
    assert (
        Device.objects.filter(pk__in=[deck.pk, tower.pk])
        .exclude(removed_at=None)
        .count()
        == 2
    )

    logged_in.post(reverse("games:undo_bulk_action", args=[batch]))

    assert Device.objects.for_library(owned_library).count() == 2


# ── The row menu and the list ────────────────────────────────────────────────


def test_a_row_offers_edit_and_remove(deck):
    html = str(device_row_menu(deck, origin=None))

    assert reverse("games:edit_device", args=[deck.pk]) in html
    assert reverse("games:remove_device", args=[deck.pk]) in html
    assert "Steam Deck (Handheld) actions" in html


def test_the_list_carries_the_selection_and_no_actions_column(logged_in, deck):
    html = logged_in.get(reverse("games:list_devices")).content.decode()

    assert ">Actions<" not in html
    assert "selectable-table" in html
    assert f"device-menu-{deck.pk}" in html
    assert act_url(REMOVE_DEVICE) in html
