"""Edit many platforms' group and icon; undo the batch."""

import json
import uuid

import pytest
from bulk_posts import act_url, posted, said, selection
from django.http import QueryDict
from django.urls import reverse

from common.components.unset_field import unset_input_name
from games.bulk_actions import BULK_ACTIONS
from games.bulk_edit import STATEMENT_UNREADABLE
from games.bulk_parts import LedgerRows
from games.bulk_platform_edit import (
    EDIT_PLATFORMS,
    NOTHING_STATED,
    BulkPlatformEditForm,
    PlatformEditStatement,
)
from games.events.dispatch import CommandRejected
from games.models import BatchChange, Platform, UserLibrary
from games.removal import remove
from games.views.bulk import (
    CHOICE_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
    UNKNOWN_ACT,
    _act_of,
)
from games.writes.platform import PLATFORM_REMOVED

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def amiga(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Amiga", group="Commodore", icon="unspecified"
    )


@pytest.fixture
def dos(owned_library):
    return Platform.objects.create(
        library=owned_library, name="DOS", group="PC", icon="unspecified"
    )


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _held(platform: Platform) -> tuple[str, str]:
    row = Platform.objects.get(pk=platform.pk)
    return row.group, row.icon


def _form_post(**fields: str) -> dict[str, str]:
    return {f"{CHOICE_FIELD}-{name}": value for name, value in fields.items()}


def _press(client, *rows, **fields: str) -> uuid.UUID:
    """Confirm, fill the form, run; the batch's id."""
    url = act_url(EDIT_PLATFORMS)
    confirmation = client.post(url, {STATEMENT_FIELD: selection(*rows)})
    submitted = {**posted(confirmation), **_form_post(**fields)}
    client.post(url, submitted)
    return uuid.UUID(submitted[TOKEN_FIELD])


def _undo(client, batch: uuid.UUID):
    return client.post(reverse("games:undo_bulk_action", args=[batch]))


# ── The declaration ──────────────────────────────────────────────────────────


def test_the_act_is_declared():
    assert BULK_ACTIONS["platform.edit"] is EDIT_PLATFORMS
    assert EDIT_PLATFORMS.undo_rows == LedgerRows(Platform)


# ── The statement ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    [
        PlatformEditStatement("Home", None),
        PlatformEditStatement("", "steam"),
        PlatformEditStatement(None, "gog"),
    ],
)
def test_a_statement_reads_back(statement):
    assert PlatformEditStatement.decode(statement.encode()) == statement


@pytest.mark.parametrize(
    "raw",
    ["", "[]", '{"name": "x"}', '{"group": 1}', "{}", '{"icon": "delete"}'],
)
def test_an_unreadable_statement_is_refused(raw):
    with pytest.raises(CommandRejected) as refusal:
        PlatformEditStatement.decode(raw)

    assert refusal.value.sentence == STATEMENT_UNREADABLE


def test_a_carried_group_is_stripped_and_bounded():
    assert PlatformEditStatement.decode('{"group": "  Home "}').group == "Home"
    with pytest.raises(CommandRejected):
        PlatformEditStatement.decode(json.dumps({"group": "x" * 256}))


# ── The form ─────────────────────────────────────────────────────────────────


def _form(library: UserLibrary, rows=(), **fields: str) -> BulkPlatformEditForm:
    data = QueryDict(mutable=True)
    data.update(_form_post(**fields))
    return BulkPlatformEditForm(data, library=library, prefix=CHOICE_FIELD, rows=rows)


def test_an_empty_form_states_nothing(owned_library):
    form = _form(owned_library)

    assert not form.is_valid()
    assert NOTHING_STATED in form.non_field_errors()


def test_an_empty_group_keeps_and_an_icon_states(owned_library):
    form = _form(owned_library, icon="steam")

    assert form.is_valid(), form.errors
    assert form.statement() == PlatformEditStatement(None, "steam")


def test_the_unset_toggle_states_no_group(owned_library):
    data = QueryDict(mutable=True)
    data[unset_input_name(f"{CHOICE_FIELD}-group")] = "1"
    form = BulkPlatformEditForm(data, library=owned_library, prefix=CHOICE_FIELD)

    assert form.is_valid(), form.errors
    assert form.statement() == PlatformEditStatement("", None)


def test_the_placeholders_say_what_the_rows_hold(owned_library, amiga, dos):
    html = str(
        BulkPlatformEditForm(
            library=owned_library, prefix=CHOICE_FIELD, rows=[amiga, dos]
        )["group"]
    )

    assert "Keep: mixed" in html
    assert 'data-value="Commodore"' in html
    assert 'create="select"' in html
    assert "<datalist" not in html
    assert 'maxlength="255"' in html


# ── A batch and its Undo ─────────────────────────────────────────────────────


def test_a_batch_edits_and_its_undo_writes_the_earlier_values_back(
    logged_in, amiga, dos
):
    url = act_url(EDIT_PLATFORMS)
    confirmation = logged_in.post(url, {STATEMENT_FIELD: selection(amiga, dos)})
    html = confirmation.content.decode()
    for heading in ("Edit 2 platforms", "Platform", "Group", "Icon"):
        assert heading in html

    batch = _press(logged_in, amiga, dos, group="Home", icon="physical")

    assert _held(amiga) == _held(dos) == ("Home", "physical")
    assert _act_of(amiga.library, batch) is EDIT_PLATFORMS

    _undo(logged_in, batch)

    assert _held(amiga) == ("Commodore", "unspecified")
    assert _held(dos) == ("PC", "unspecified")


def test_the_undo_restates_over_a_later_edit(logged_in, amiga):
    batch = _press(logged_in, amiga, group="Home")
    Platform.objects.filter(pk=amiga.pk).update(group="Mine")

    _undo(logged_in, batch)

    assert _held(amiga)[0] == "Commodore"


def test_a_taken_name_refuses_that_row_only(logged_in, owned_library, amiga, dos):
    Platform.objects.create(library=owned_library, name="Amiga", group="Home")

    _press(logged_in, amiga, dos, group="Home")

    assert _held(amiga)[0] == "Commodore"
    assert _held(dos)[0] == "Home"


def test_the_undo_refuses_a_platform_removed_since(logged_in, amiga, dos):
    batch = _press(logged_in, amiga, dos, group="Home")
    remove(amiga)

    response = logged_in.post(
        reverse("games:undo_bulk_action", args=[batch]), follow=True
    )

    assert _held(amiga)[0] == "Home"
    assert _held(dos)[0] == "PC"
    assert any(PLATFORM_REMOVED in sentence for sentence in said(response))


def test_an_undo_batch_offers_no_undo(logged_in, amiga):
    batch = _press(logged_in, amiga, group="Home")
    undo_page = _undo(logged_in, batch)
    assert undo_page.status_code in (200, 302)
    undo_batch = (
        BatchChange.objects.exclude(batch=batch).values_list("batch", flat=True).first()
    )

    response = logged_in.post(reverse("games:undo_bulk_action", args=[undo_batch]))

    assert response.status_code == 400
    assert UNKNOWN_ACT in response.content.decode()
    assert _held(amiga)[0] == "Commodore"


# ── The list ─────────────────────────────────────────────────────────────────


def test_the_tray_offers_edit_before_remove(logged_in, amiga):
    html = logged_in.get(reverse("games:list_platforms")).content.decode()

    edit = html.index(act_url(EDIT_PLATFORMS))
    remove_at = html.index(reverse("games:run_bulk_action", args=["platform.remove"]))
    assert edit < remove_at
