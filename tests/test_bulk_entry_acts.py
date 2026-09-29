"""Copies edited and removed in bulk, and the Undo of each."""

import json
import uuid

import pytest
from bulk_posts import act_url, posted, press, selection
from django.http import QueryDict
from django.urls import reverse
from entries import record_entry, remove_entry

from common.components.unset_field import unset_input_name
from common.criteria import FilterError
from games.bulk_actions import BULK_ACTIONS, Control, EventRows
from games.bulk_entries import ENTRY_GONE
from games.bulk_entry_edit import (
    EDIT_CHOICE,
    ENTRY_EDIT,
    NOTHING_STATED,
    EntryEditStatement,
)
from games.bulk_removal import REMOVE_ENTRY
from games.events.dispatch import CommandRejected
from games.models import EntryAccess, EntryFormat, Game, LibraryEntry, Platform
from games.reads.entry_facts import entry_fact_changes
from games.reads.fact_change import FactChange
from games.views.bulk import CHOICE_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.writes.libraryentry import describe_entry
from games.writes.playergame import new_correlation_id

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(
        Game(name="Tunic", library=owned_library),
        owned_library,
        platform=Platform.objects.create(name="PS5", group="Sony"),
    )


@pytest.fixture
def first(owned_library, graph):
    return record_entry(owned_library, graph.release, note="shelf")


@pytest.fixture
def second(owned_library, graph):
    return record_entry(owned_library, graph.release, access="borrowed")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _control(**answers: str) -> dict[str, str]:
    """`unset_x` is x's ⊘."""
    return {
        (
            unset_input_name(f"{CHOICE_FIELD}-{key.removeprefix('unset_')}")
            if key.startswith("unset_")
            else f"{CHOICE_FIELD}-{key}"
        ): value
        for key, value in answers.items()
    }


def _edit(client, *entries, **answers: str) -> str:
    url = act_url(ENTRY_EDIT)
    fields = posted(client.post(url, {STATEMENT_FIELD: selection(*entries)}))
    fields.update(_control(**answers))
    fields.pop(CHOICE_FIELD, None)
    client.post(url, fields)
    return fields[TOKEN_FIELD]


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def _facts(entry) -> tuple[str, str, str]:
    entry.refresh_from_db()
    return entry.access, entry.format, entry.note


# ── The declarations ────────────────────────────────────────────────────────


def test_both_acts_are_declared():
    assert BULK_ACTIONS["entry.edit"] is ENTRY_EDIT
    assert BULK_ACTIONS["entry.remove"] is REMOVE_ENTRY
    assert ENTRY_EDIT.undo_rows == EventRows(LibraryEntry)
    assert REMOVE_ENTRY.undo_rows == EventRows(LibraryEntry)


def test_the_titles_count_copies():
    assert ENTRY_EDIT.title.many.format(count=3) == "Edit 3 copies"
    assert REMOVE_ENTRY.title.one == "Remove this copy"


# ── Scope and rows ──────────────────────────────────────────────────────────


def test_the_scope_narrows_by_the_statements_filter(owned_library, first, second):
    narrowed = ENTRY_EDIT.scope(
        owned_library,
        json.dumps({"access": {"value": ["borrowed"], "modifier": "INCLUDES"}}),
    )

    assert list(narrowed) == [second]


def test_an_unreadable_filter_refuses_the_act(owned_library, first):
    with pytest.raises(FilterError):
        ENTRY_EDIT.scope(owned_library, json.dumps({"nonsense": {}}))


def test_another_librarys_copy_comes_out_lost(
    owned_library, first, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = record_entry(
        stranger,
        stated_graph(Game(name="Hades", library=stranger), stranger).release,
    )

    resolution = REMOVE_ENTRY.resolve(owned_library, [first.pk, theirs.pk])

    assert [row.pk for row in resolution.rows] == [first.pk]
    assert [(refused.key, refused.sentence) for refused in resolution.refused] == [
        (str(theirs.pk), ENTRY_GONE)
    ]


def test_the_preview_names_game_platform_access_and_format(owned_library, first):
    (row,) = ENTRY_EDIT.resolve(owned_library, [first.pk]).rows

    assert [str(column.cell(row, None)) for column in ENTRY_EDIT.preview] == [
        "Tunic",
        "PS5",
        "Owned",
        "Digital",
    ]


# ── The question ────────────────────────────────────────────────────────────


def test_the_control_keeps_what_the_rows_hold(owned_library, first, second):
    rows = ENTRY_EDIT.resolve(owned_library, [first.pk, second.pk]).rows

    offered = ENTRY_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert isinstance(offered, Control)
    markup = str(offered.node)
    assert "Keep: mixed" in markup
    assert "Keep: Digital" in markup


def _settle(owned_library, **answers: str) -> str:
    post = QueryDict(mutable=True)
    post.update(_control(**answers))
    return EDIT_CHOICE.settle(owned_library, post)


def test_settling_refuses_a_form_that_states_nothing(owned_library):
    with pytest.raises(CommandRejected) as refused:
        _settle(owned_library, access="")

    assert refused.value.sentence == NOTHING_STATED


def test_settling_states_a_cleared_note(owned_library):
    settled = _settle(owned_library, unset_note="1")

    assert EntryEditStatement.decode(settled) == EntryEditStatement(None, None, "")


@pytest.mark.parametrize(
    "carried", ['{"access": "lent"}', '{"note": 3}', "{}", '{"status": "x"}']
)
def test_an_unreadable_statement_is_refused(carried):
    with pytest.raises(CommandRejected):
        EntryEditStatement.decode(carried)


# ── Edit and its Undo ───────────────────────────────────────────────────────


def test_edit_states_the_facts_and_keeps_empty_fields(logged_in, first, second):
    _edit(logged_in, first, second, format="physical")

    assert _facts(first) == ("owned", "physical", "shelf")
    assert _facts(second) == ("borrowed", "physical", "")


def test_edit_clears_a_note(logged_in, first):
    _edit(logged_in, first, unset_note="1")

    assert _facts(first) == ("owned", "digital", "")


def test_undo_states_every_fact_before_the_batch(logged_in, first, second):
    token = _edit(logged_in, first, second, access="rented", unset_note="1")

    _undo(logged_in, token)

    assert _facts(first) == ("owned", "digital", "shelf")
    assert _facts(second) == ("borrowed", "digital", "")


# ── The reader ──────────────────────────────────────────────────────────────


def test_the_reader_reads_the_creation_for_a_copys_first_change(
    owned_user, owned_library, first
):
    batch = new_correlation_id()
    describe_entry(owned_user, first, access="rented", correlation_id=batch)

    changes = entry_fact_changes(owned_library, first.pk, batch)

    assert changes.access == FactChange(EntryAccess.OWNED, EntryAccess.RENTED)
    assert changes.format is None
    assert changes.note is None


def test_the_reader_reads_a_later_change(owned_user, owned_library, first):
    describe_entry(
        owned_user, first, format="physical", correlation_id=new_correlation_id()
    )
    first.refresh_from_db()
    batch = new_correlation_id()
    describe_entry(owned_user, first, format="unknown", correlation_id=batch)

    changes = entry_fact_changes(owned_library, first.pk, batch)

    assert changes.format == FactChange(EntryFormat.PHYSICAL, EntryFormat.UNKNOWN)


# ── Remove and its Undo ─────────────────────────────────────────────────────


def test_remove_takes_two_copies_and_undo_puts_them_back(logged_in, first, second):
    confirmation = logged_in.post(
        act_url(REMOVE_ENTRY), {STATEMENT_FIELD: selection(first, second)}
    )
    fields = posted(confirmation)
    logged_in.post(act_url(REMOVE_ENTRY), fields)

    assert not LibraryEntry.objects.filter(removed_at__isnull=True).exists()

    _undo(logged_in, fields[TOKEN_FIELD])

    assert LibraryEntry.objects.filter(removed_at__isnull=True).count() == 2


def test_a_copy_removed_since_the_confirmation_is_left_alone(logged_in, first):
    remove_entry(first)

    press(logged_in, REMOVE_ENTRY, first)

    first.refresh_from_db()
    assert first.removed_at is not None


def test_an_undo_of_another_librarys_copy_is_absent(owned_user, first):
    with pytest.raises(Exception, match="No such copy"):
        REMOVE_ENTRY.inverse(
            owned_user,
            uuid.uuid7(),
            undoes=uuid.uuid7(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )
