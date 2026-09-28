"""What a batch changed on conventional rows."""

import uuid

import pytest
from django.utils import timezone

from games.batch_ledger import batch_act, batch_rows, record, recorded, row_changes
from games.models import BatchChange, Platform

pytestmark = pytest.mark.django_db


@pytest.fixture
def amiga(owned_library):
    return Platform.objects.create(library=owned_library, name="Amiga")


@pytest.fixture
def dos(owned_library):
    return Platform.objects.create(library=owned_library, name="DOS")


def _record(library, batch, row, field="group", earlier="", stated="Home"):
    record(
        library,
        batch=batch,
        act="platform.edit",
        row=row,
        field=field,
        earlier=earlier,
        stated=stated,
    )


def test_a_repeat_records_nothing(owned_library, amiga):
    batch = uuid.uuid7()
    _record(owned_library, batch, amiga)
    _record(owned_library, batch, amiga, stated="Elsewhere")

    assert BatchChange.objects.count() == 1
    assert row_changes(owned_library, batch, amiga)["group"].stated == "Home"


def test_the_rows_come_in_the_order_the_batch_reached_them(owned_library, amiga, dos):
    batch = uuid.uuid7()
    _record(owned_library, batch, dos)
    _record(owned_library, batch, amiga)
    _record(owned_library, batch, dos, field="icon")

    assert batch_rows(owned_library, batch, Platform) == [dos.pk, amiga.pk]


def test_the_batch_names_its_act(owned_library, amiga):
    batch = uuid.uuid7()
    _record(owned_library, batch, amiga)

    assert batch_act(owned_library, batch) == "platform.edit"
    assert batch_act(owned_library, uuid.uuid7()) is None


def test_an_instant_reads_back_as_an_instant(owned_library, amiga):
    batch = uuid.uuid7()
    stamp = timezone.now()
    _record(owned_library, batch, amiga, field="removed_at", earlier=None, stated=stamp)

    change = row_changes(owned_library, batch, amiga)["removed_at"]
    assert (change.before, change.stated) == (None, stamp)


def test_a_field_without_a_decoder_is_refused(owned_library, amiga):
    with pytest.raises(ValueError, match="name"):
        _record(owned_library, uuid.uuid7(), amiga, field="name")


def test_another_library_reads_nothing(owned_library, django_user_model, amiga):
    batch = _batch = uuid.uuid7()
    _record(owned_library, _batch, amiga)
    stranger = django_user_model.objects.create_user("stranger").library

    assert batch_rows(stranger, batch, Platform) == []
    assert batch_act(stranger, batch) is None
    assert not recorded(stranger, batch=batch, row=amiga, field="group")


def test_an_unreadable_instant_is_a_defect(owned_library, amiga):
    batch = uuid.uuid7()
    _record(owned_library, batch, amiga, field="removed_at", earlier=None, stated="x")

    with pytest.raises(ValueError, match="no instant"):
        row_changes(owned_library, batch, amiga)
