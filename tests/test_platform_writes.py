"""A platform removed, edited and restored, by a batch or by hand."""

import uuid
from unittest import mock

import pytest
from django.contrib.messages import get_messages
from django.db import IntegrityError
from django.urls import reverse

from games.batch_ledger import row_changes
from games.models import BatchChange, ExternalReference, Platform
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.platform import (
    PLATFORM_REMOVED,
    edit_platform_in_batch,
    group_taken_sentence,
    remove_platform_in_batch,
    restore_platform_by_hand,
    taken_sentence,
    undo_platform_batch,
)

pytestmark = pytest.mark.django_db

REMOVE = "platform.remove"
EDIT = "platform.edit"


@pytest.fixture
def amiga(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Amiga", group="Commodore", icon="unspecified"
    )


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="other", password="p").library


def _reread(platform: Platform) -> Platform:
    return Platform.objects.get(pk=platform.pk)


def _removed(platform: Platform) -> uuid.UUID:
    batch = uuid.uuid7()
    remove_platform_in_batch(platform, batch=batch, act=REMOVE)
    return batch


def _undo(platform: Platform, batch: uuid.UUID, act: str = REMOVE) -> bool:
    return undo_platform_batch(platform, undoes=batch, batch=uuid.uuid7(), act=act)


def _edited(platform: Platform, **stated) -> uuid.UUID:
    batch = uuid.uuid7()
    stated.setdefault("group", None)
    stated.setdefault("icon", None)
    edit_platform_in_batch(platform, batch=batch, act=EDIT, **stated)
    return batch


# ── Remove, in a batch ───────────────────────────────────────────────────────


def test_a_live_row_is_removed_and_recorded(owned_library, amiga):
    batch = _removed(amiga)

    row = _reread(amiga)
    assert row.removed_at is not None
    change = row_changes(owned_library, batch, row)["removed_at"]
    assert (change.before, change.stated) == (None, row.removed_at)


def test_a_removed_row_is_left_alone(amiga):
    remove(amiga)

    assert remove_platform_in_batch(amiga, batch=uuid.uuid7(), act=REMOVE) is False


def test_a_row_restored_since_the_batch_stays_live(amiga):
    """A chunk posted again after a restore by hand."""
    batch = _removed(amiga)
    restore(amiga)

    assert remove_platform_in_batch(amiga, batch=batch, act=REMOVE) is False
    assert _reread(amiga).removed_at is None


# ── Edit, in a batch ─────────────────────────────────────────────────────────


def test_an_edit_states_group_and_icon_and_records_both(owned_library, amiga):
    batch = _edited(amiga, group="Home", icon="physical")

    row = _reread(amiga)
    assert (row.group, row.icon) == ("Home", "physical")
    changes = row_changes(owned_library, batch, row)
    assert (changes["group"].before, changes["group"].stated) == ("Commodore", "Home")
    assert (changes["icon"].before, changes["icon"].stated) == (
        "unspecified",
        "physical",
    )


def test_none_keeps_and_empty_states_no_group(amiga):
    _edited(amiga, group="")

    row = _reread(amiga)
    assert (row.group, row.icon) == ("", "unspecified")


def test_a_row_that_holds_the_statement_is_unchanged(amiga):
    assert (
        edit_platform_in_batch(
            amiga, group="Commodore", icon=None, batch=uuid.uuid7(), act=EDIT
        )
        is False
    )


def test_a_field_this_batch_wrote_is_not_written_again(amiga):
    """A chunk posted again after an edit by hand."""
    batch = _edited(amiga, group="Home")
    Platform.objects.filter(pk=amiga.pk).update(group="Mine")

    assert (
        edit_platform_in_batch(amiga, group="Home", icon=None, batch=batch, act=EDIT)
        is False
    )
    assert _reread(amiga).group == "Mine"


def test_a_group_whose_name_is_taken_refuses(owned_library, amiga):
    Platform.objects.create(library=owned_library, name="amiga", group="home")

    with pytest.raises(CommandFailed) as refusal:
        _edited(amiga, group="Home")

    assert refusal.value.message == group_taken_sentence(amiga, "Home")
    assert _reread(amiga).group == "Commodore"


def test_an_unlisted_icon_is_a_defect_not_a_write(amiga):
    with pytest.raises(ValueError):
        _edited(amiga, icon="ps1")

    assert _reread(amiga).icon == "unspecified"


def test_an_undo_writing_an_unlisted_icon_is_a_defect(owned_library, amiga):
    batch = _edited(amiga, icon="physical")
    BatchChange.objects.filter(batch=batch, field="icon").update(earlier="ps1")

    with pytest.raises(ValueError):
        _undo(amiga, batch, EDIT)

    assert _reread(amiga).icon == "physical"


# ── Undo ─────────────────────────────────────────────────────────────────────


def test_the_undo_of_a_removal_restores(amiga):
    batch = _removed(amiga)

    assert _undo(amiga, batch) is True
    assert _reread(amiga).removed_at is None


def test_the_undo_restores_over_a_later_removal(amiga):
    batch = _removed(amiga)
    restore(amiga)
    remove(amiga)

    assert _undo(amiga, batch) is True
    assert _reread(amiga).removed_at is None


def test_the_undo_of_a_live_row_changes_nothing(amiga):
    batch = _removed(amiga)
    restore(amiga)

    assert _undo(amiga, batch) is False


def test_the_undo_of_an_edit_writes_the_earlier_values_back(amiga):
    batch = _edited(amiga, group="Home", icon="physical")

    assert _undo(amiga, batch, EDIT) is True
    row = _reread(amiga)
    assert (row.group, row.icon) == ("Commodore", "unspecified")


def test_the_undo_restates_over_a_later_edit(amiga):
    batch = _edited(amiga, group="Home")
    Platform.objects.filter(pk=amiga.pk).update(group="Mine")

    assert _undo(amiga, batch, EDIT) is True
    assert _reread(amiga).group == "Commodore"


def test_an_undo_chunk_posted_again_writes_nothing(amiga):
    batch = _edited(amiga, group="Home")
    undo = uuid.uuid7()
    undo_platform_batch(amiga, undoes=batch, batch=undo, act=EDIT)
    Platform.objects.filter(pk=amiga.pk).update(group="Mine")

    assert undo_platform_batch(amiga, undoes=batch, batch=undo, act=EDIT) is False
    assert _reread(amiga).group == "Mine"


def test_the_undo_of_an_edit_refuses_a_removed_platform(amiga):
    batch = _edited(amiga, group="Home")
    remove(amiga)

    with pytest.raises(CommandFailed) as refusal:
        _undo(amiga, batch, EDIT)

    assert refusal.value.message == PLATFORM_REMOVED
    assert _reread(amiga).group == "Home"


def test_the_references_come_back_with_the_row(amiga):
    reference = ExternalReference.objects.create(
        provider="wikidata", entity_kind="platform", provider_key="Q100", platform=amiga
    )
    batch = _removed(amiga)

    _undo(amiga, batch)

    reference.refresh_from_db()
    assert reference.removed_at is None


# ── A taken name ─────────────────────────────────────────────────────────────


def test_a_private_platform_holding_the_name_refuses(owned_library, amiga):
    batch = _removed(amiga)
    Platform.objects.create(library=owned_library, name=" amiga ", group="COMMODORE")

    with pytest.raises(CommandFailed) as refusal:
        _undo(amiga, batch)

    assert refusal.value.status_code == CONFLICT_STATUS
    assert refusal.value.message == taken_sentence(amiga)
    assert _reread(amiga).removed_at is not None


def test_a_shared_platform_holding_the_name_refuses(amiga):
    batch = _removed(amiga)
    Platform.objects.create(name="Amiga", group="Commodore")

    with pytest.raises(CommandFailed):
        _undo(amiga, batch)


def test_another_librarys_platform_takes_no_name(amiga, other_library):
    batch = _removed(amiga)
    Platform.objects.create(library=other_library, name="Amiga", group="Commodore")

    assert _undo(amiga, batch) is True


def _collision(constraint: str) -> IntegrityError:
    """What the driver raises, as Django wraps it."""
    cause = Exception(constraint)
    cause.diag = mock.Mock(constraint_name=constraint)  # type: ignore[attr-defined]
    collision = IntegrityError(constraint)
    collision.__cause__ = cause
    return collision


def test_a_concurrent_insert_is_refused_not_a_defect(amiga):
    batch = _removed(amiga)
    racing = _collision("unique_private_platform_normalized_name_group")

    with (
        mock.patch("games.writes.platform.restore", side_effect=racing),
        pytest.raises(CommandFailed) as refusal,
    ):
        _undo(amiga, batch)

    assert refusal.value.status_code == CONFLICT_STATUS


def test_another_constraint_rises_as_itself(amiga):
    batch = _removed(amiga)
    defect = _collision("some_other_constraint")

    with (
        mock.patch("games.writes.platform.restore", side_effect=defect),
        pytest.raises(IntegrityError),
    ):
        _undo(amiga, batch)


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


# ── Refusals write and record nothing ────────────────────────────────────────


def test_a_refused_edit_writes_and_records_nothing(owned_library, amiga):
    Platform.objects.create(library=owned_library, name="Amiga", group="Home")
    batch = uuid.uuid7()

    with pytest.raises(CommandFailed):
        edit_platform_in_batch(
            amiga, group="Home", icon="physical", batch=batch, act=EDIT
        )

    assert (_reread(amiga).group, _reread(amiga).icon) == ("Commodore", "unspecified")
    assert not BatchChange.objects.filter(batch=batch).exists()


def test_an_edit_of_a_platform_removed_since_is_refused(amiga):
    remove(amiga)

    with pytest.raises(CommandFailed) as refusal:
        _edited(amiga, group="Home")

    assert refusal.value.message == PLATFORM_REMOVED


def test_the_undo_of_an_edit_refuses_an_earlier_group_now_taken(owned_library, amiga):
    batch = _edited(amiga, group="Home", icon="physical")
    Platform.objects.create(library=owned_library, name="Amiga", group="Commodore")
    undo = uuid.uuid7()

    with pytest.raises(CommandFailed) as refusal:
        undo_platform_batch(amiga, undoes=batch, batch=undo, act=EDIT)

    assert refusal.value.message == group_taken_sentence(_reread(amiga), "Commodore")
    assert (_reread(amiga).group, _reread(amiga).icon) == ("Home", "physical")
    assert not BatchChange.objects.filter(batch=undo).exists()
