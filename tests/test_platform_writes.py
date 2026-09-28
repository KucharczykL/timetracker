"""A platform taken out and put back, by a batch or by hand."""

import uuid
from unittest import mock

import pytest
from django.contrib.messages import get_messages
from django.db import IntegrityError
from django.urls import reverse

from games.models import ExternalReference, Platform
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.platform import (
    remove_platform_in_batch,
    removed_again_sentence,
    restore_platform_by_hand,
    restore_platform_from_batch,
    taken_sentence,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def amiga(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Amiga", group="Commodore"
    )


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="other", password="p").library


def _reread(platform: Platform) -> Platform:
    return Platform.objects.get(pk=platform.pk)


# ── Remove, in a batch ───────────────────────────────────────────────────────


def test_a_live_row_is_removed_naming_the_batch(amiga):
    batch = uuid.uuid7()

    assert remove_platform_in_batch(amiga, batch=batch) is True

    row = _reread(amiga)
    assert row.removed_at is not None
    assert row.removed_in_batch == batch


def test_a_removed_row_is_left_alone(amiga):
    remove(amiga)

    assert remove_platform_in_batch(amiga, batch=uuid.uuid7()) is False
    assert _reread(amiga).removed_in_batch is None


def test_a_row_restored_since_the_batch_stays_live(amiga):
    """A chunk posted again after a restore by hand."""
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    restore(amiga)

    assert remove_platform_in_batch(amiga, batch=batch) is False
    assert _reread(amiga).removed_at is None


# ── Restore, from a batch ────────────────────────────────────────────────────


def test_a_row_of_the_batch_comes_back(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)

    assert restore_platform_from_batch(amiga, batch=batch) is True
    assert _reread(amiga).removed_at is None


def test_a_live_row_is_already_back(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    restore(amiga)

    assert restore_platform_from_batch(amiga, batch=batch) is False


def test_a_row_another_act_removed_since_is_refused(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    restore(amiga)
    remove(amiga)

    with pytest.raises(CommandFailed) as refusal:
        restore_platform_from_batch(amiga, batch=batch)

    assert refusal.value.message == removed_again_sentence(amiga)
    assert _reread(amiga).removed_at is not None


def test_the_references_come_back_with_the_row(amiga):
    reference = ExternalReference.objects.create(
        provider="wikidata", entity_kind="platform", provider_key="Q100", platform=amiga
    )
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)

    restore_platform_from_batch(amiga, batch=batch)

    reference.refresh_from_db()
    assert reference.removed_at is None


# ── A taken name ─────────────────────────────────────────────────────────────


def test_a_private_platform_holding_the_name_refuses(owned_library, amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    Platform.objects.create(library=owned_library, name=" amiga ", group="COMMODORE")

    with pytest.raises(CommandFailed) as refusal:
        restore_platform_from_batch(amiga, batch=batch)

    assert refusal.value.status_code == CONFLICT_STATUS
    assert refusal.value.message == taken_sentence(amiga)
    assert _reread(amiga).removed_at is not None


def test_a_shared_platform_holding_the_name_refuses(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    Platform.objects.create(name="Amiga", group="Commodore")

    with pytest.raises(CommandFailed):
        restore_platform_from_batch(amiga, batch=batch)


def test_another_librarys_platform_takes_no_name(amiga, other_library):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    Platform.objects.create(library=other_library, name="Amiga", group="Commodore")

    assert restore_platform_from_batch(amiga, batch=batch) is True


def _collision(constraint: str) -> IntegrityError:
    """What the driver raises, as Django wraps it."""
    cause = Exception(constraint)
    cause.diag = mock.Mock(constraint_name=constraint)  # type: ignore[attr-defined]
    collision = IntegrityError(constraint)
    collision.__cause__ = cause
    return collision


def test_a_concurrent_insert_is_refused_not_a_defect(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    racing = _collision("unique_private_platform_normalized_name_group")

    with (
        mock.patch("games.writes.platform.restore", side_effect=racing),
        pytest.raises(CommandFailed) as refusal,
    ):
        restore_platform_from_batch(amiga, batch=batch)

    assert refusal.value.status_code == CONFLICT_STATUS


def test_another_constraint_rises_as_itself(amiga):
    batch = uuid.uuid7()
    remove_platform_in_batch(amiga, batch=batch)
    defect = _collision("some_other_constraint")

    with (
        mock.patch("games.writes.platform.restore", side_effect=defect),
        pytest.raises(IntegrityError),
    ):
        restore_platform_from_batch(amiga, batch=batch)


def test_by_hand_a_live_row_is_left_alone(amiga):
    restore_platform_by_hand(amiga)

    assert _reread(amiga).removed_at is None


# ── The per-row route ────────────────────────────────────────────────────────


def test_the_route_answers_a_taken_name_on_the_page(client, owned_user, amiga):
    client.force_login(owned_user)
    remove(amiga)
    Platform.objects.create(library=amiga.library, name="Amiga", group="Commodore")

    response = client.post(reverse("games:restore_platform", args=[amiga.pk]))

    assert response.status_code == 302
    assert taken_sentence(amiga) in [
        message.message for message in get_messages(response.wsgi_request)
    ]
    assert _reread(amiga).removed_at is not None
