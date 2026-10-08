"""Copies edited and removed in bulk, and the Undo of each."""

import json
import logging
import uuid

import pytest
from bulk_posts import act_url, newest_batch, posted, press, selection
from django.http import Http404, QueryDict
from django.urls import reverse
from entries import record_entry, remove_entry
from graphs import default_graph
from purchases import record_purchase, remove_purchase

from common.components.unset_field import unset_input_name
from common.criteria import FilterError
from games.bulk_actions import BULK_ACTIONS
from games.bulk_entries import ENTRY_GONE
from games.bulk_entry_edit import (
    EDIT_CHOICE,
    ENTRY_EDIT,
    ENTRY_REMOVED,
    NO_RELEASE_ON_PLATFORM,
    NOT_EDITED_BY_THIS_BATCH,
    NOTHING_STATED,
    PLATFORM_REMOVED,
    SEVERAL_RELEASES_ON_PLATFORM,
    EntryEditStatement,
    StatedPlatform,
)
from games.bulk_parts import Control, EventRows, RowOutcome
from games.bulk_removal import REMOVE_ENTRY
from games.catalog_form import PLATFORM_GONE
from games.events.dispatch import CommandRejected
from games.models import (
    EntryAccess,
    EntryFormat,
    Game,
    LibraryEntry,
    Platform,
    Purchase,
    Release,
)
from games.reads.entry_facts import entry_fact_changes
from games.reads.fact_change import FactChange
from games.removal import remove
from games.views.bulk import CHOICE_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.writes.answers import CommandFailed
from games.writes.libraryentry import describe_entry
from games.writes.playergame import new_correlation_id

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library):
    return default_graph(
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


def test_another_librarys_copy_comes_out_lost(owned_library, first, django_user_model):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = record_entry(
        stranger,
        default_graph(Game(name="Hades", library=stranger), stranger).release,
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

    assert EntryEditStatement.decode(settled) == EntryEditStatement(
        access=None, format=None, note="", platform=None
    )


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


def test_remove_takes_purchases_and_undo_brings_back_only_those(logged_in, first):
    taken = record_purchase(first)
    alone = remove_purchase(record_purchase(first, name="Soundtrack"))

    fields = posted(
        logged_in.post(act_url(REMOVE_ENTRY), {STATEMENT_FIELD: selection(first)})
    )
    logged_in.post(act_url(REMOVE_ENTRY), fields)
    assert not Purchase.objects.filter(removed_at__isnull=True).exists()
    _undo(logged_in, fields[TOKEN_FIELD])

    taken.refresh_from_db()
    alone.refresh_from_db()
    assert taken.removed_at is None
    assert alone.removed_at is not None


def test_the_removal_preview_counts_unremoved_purchases(owned_library, first):
    record_purchase(first)
    remove_purchase(record_purchase(first, name="Soundtrack"))

    (row,) = REMOVE_ENTRY.resolve(owned_library, [first.pk]).rows

    assert [column.heading for column in REMOVE_ENTRY.preview][-1] == "Purchases"
    assert REMOVE_ENTRY.preview[-1].cell(row, None) == "1"


def test_a_copy_removed_since_the_confirmation_is_left_alone(logged_in, first):
    remove_entry(first)

    press(logged_in, REMOVE_ENTRY, first)

    first.refresh_from_db()
    assert first.removed_at is not None


def test_an_undo_of_another_librarys_copy_is_absent(owned_user, django_user_model):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = default_graph(Game(name="Hades", library=stranger), stranger)
    their_copy = remove_entry(record_entry(stranger, theirs.release))

    with pytest.raises(Http404):
        REMOVE_ENTRY.inverse(
            owned_user,
            their_copy.pk,
            undoes=uuid.uuid7(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def _edit_back(owned_user, entry, token):
    return ENTRY_EDIT.inverse(
        owned_user,
        entry.pk,
        undoes=uuid.UUID(token),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


def test_edit_normalises_a_notes_line_breaks(logged_in, first):
    _edit(logged_in, first, note="boxed\r\nwith manual")

    assert _facts(first)[2] == "boxed\nwith manual"


def test_an_undo_finds_the_facts_already_back(logged_in, owned_user, first):
    token = _edit(logged_in, first, access="rented")
    _undo(logged_in, token)

    assert _edit_back(owned_user, first, token) is RowOutcome.UNCHANGED


def test_an_undo_refuses_a_copy_removed_since(logged_in, owned_user, first):
    token = _edit(logged_in, first, access="rented")
    remove_entry(first)

    with pytest.raises(CommandFailed, match=ENTRY_REMOVED):
        _edit_back(owned_user, first, token)
    assert _facts(first)[0] == "rented"


# ── The platform ────────────────────────────────────────────────────────────


@pytest.fixture
def switch():
    return Platform.objects.create(name="Switch", group="Nintendo")


@pytest.fixture
def on_switch(graph, switch):
    return Release.objects.create(edition=graph.edition, platform=switch)


def _platform_alone(platform_id) -> EntryEditStatement:
    return EntryEditStatement(
        access=None, format=None, note=None, platform=StatedPlatform(platform_id)
    )


def _release(entry) -> Release:
    entry.refresh_from_db()
    return entry.release


def _move(owned_user, entry, release) -> None:
    describe_entry(
        owned_user, entry, release_id=release.pk, correlation_id=new_correlation_id()
    )


def test_the_platform_leads_the_control(owned_library, first):
    rows = ENTRY_EDIT.resolve(owned_library, [first.pk]).rows

    markup = str(ENTRY_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD).node)

    assert markup.index(f"{CHOICE_FIELD}-platform") < markup.index(
        f"{CHOICE_FIELD}-access"
    )
    assert "Keep: PS5" in markup


def test_the_platform_keeps_mixed_across_platforms(
    owned_library, first, second, on_switch, owned_user
):
    _move(owned_user, second, on_switch)
    rows = ENTRY_EDIT.resolve(owned_library, [first.pk, second.pk]).rows

    markup = str(ENTRY_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD).node)

    assert "Keep: mixed" in markup


def test_settling_states_a_platform_alone(owned_library, switch):
    settled = _settle(owned_library, platform=str(switch.pk))

    assert EntryEditStatement.decode(settled) == _platform_alone(switch.pk)


def test_settling_states_unspecified(owned_library):
    settled = _settle(owned_library, unset_platform="1")

    assert EntryEditStatement.decode(settled).platform == StatedPlatform(None)


def test_a_statement_without_a_platform_still_decodes():
    assert EntryEditStatement.decode('{"access": "rented"}').platform is None


@pytest.mark.parametrize("carried", ['{"platform": 3}', '{"platform": "ps5"}'])
def test_an_unreadable_platform_is_refused(carried):
    with pytest.raises(CommandRejected):
        EntryEditStatement.decode(carried)


def test_edit_moves_copies_onto_the_platform(logged_in, first, second, on_switch):
    _edit(logged_in, first, second, platform=str(on_switch.platform_id))

    assert _release(first) == on_switch
    assert _release(second) == on_switch


def test_edit_states_platform_and_access_in_one_dispatch(
    logged_in, owned_library, first, graph, on_switch
):
    token = _edit(
        logged_in, first, platform=str(on_switch.platform_id), access="rented"
    )

    assert _release(first) == on_switch
    assert _facts(first)[0] == "rented"
    changes = entry_fact_changes(owned_library, first.pk, uuid.UUID(token))
    assert changes.release == FactChange(graph.release.pk, on_switch.pk)


def test_a_copy_already_on_the_platform_counts_unchanged(
    logged_in, owned_library, first, graph
):
    _edit(logged_in, first, platform=str(graph.release.platform_id))

    batch = newest_batch(owned_library)
    assert (batch.done, batch.unchanged, batch.refused) == (0, 1, 0)


def test_a_game_with_no_release_there_is_refused(
    logged_in, owned_library, first, switch
):
    hades = default_graph(
        Game(name="Hades", library=owned_library), owned_library, platform=switch
    )
    theirs = record_entry(owned_library, hades.release)

    _edit(logged_in, first, theirs, platform=str(switch.pk))

    batch = newest_batch(owned_library)
    assert (batch.done, batch.unchanged, batch.refused) == (0, 1, 1)
    assert batch.reasons == [NO_RELEASE_ON_PLATFORM]


def test_two_refused_copies_give_one_reason(
    logged_in, owned_library, first, second, switch
):
    _edit(logged_in, first, second, platform=str(switch.pk))

    batch = newest_batch(owned_library)
    assert batch.refused == 2
    assert batch.reasons == [NO_RELEASE_ON_PLATFORM]
    assert _release(first) == _release(second)


def test_two_releases_there_are_refused(logged_in, owned_library, first, graph, switch):
    Release.objects.create(edition=graph.edition, platform=switch)
    Release.objects.create(edition=graph.edition, platform=switch)

    _edit(logged_in, first, platform=str(switch.pk))

    assert newest_batch(owned_library).reasons == [SEVERAL_RELEASES_ON_PLATFORM]
    assert _release(first) == graph.release


def test_a_platform_removed_after_the_press_is_refused(
    owned_user, owned_library, first, on_switch, switch
):
    remove(switch)

    with pytest.raises(CommandFailed, match=PLATFORM_REMOVED):
        ENTRY_EDIT.run(
            owned_user,
            first,
            choice=_platform_alone(switch.pk).encode(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def test_a_row_run_again_under_its_key_is_done(owned_user, first, on_switch):
    run = _runs_under_one_key(owned_user, first, on_switch.platform_id)

    assert run() is RowOutcome.MOVED
    assert run() is RowOutcome.MOVED


def _runs_under_one_key(owned_user, entry, platform_id):
    """Each call runs the freshly resolved row."""
    choice = _platform_alone(platform_id).encode()
    key, batch = str(uuid.uuid7()), uuid.uuid7()

    def run() -> RowOutcome:
        return ENTRY_EDIT.run(
            owned_user,
            ENTRY_EDIT.resolve(entry.library, [entry.pk]).rows[0],
            choice=choice,
            idempotency_key=key,
            correlation_id=batch,
        )

    return run


def test_undo_puts_the_earlier_release_back(logged_in, first, graph, on_switch):
    token = _edit(logged_in, first, platform=str(on_switch.platform_id))

    _undo(logged_in, token)

    assert _release(first) == graph.release


def test_an_undo_refuses_a_release_removed_since(
    logged_in, owned_user, first, graph, on_switch
):
    token = _edit(logged_in, first, platform=str(on_switch.platform_id))
    remove(graph.release)

    with pytest.raises(CommandFailed):
        _edit_back(owned_user, first, token)
    assert _release(first) == on_switch


def test_a_platform_removed_between_runs_keeps_the_moved_row_done(
    owned_user, first, on_switch, switch
):
    run = _runs_under_one_key(owned_user, first, switch.pk)

    assert run() is RowOutcome.MOVED
    remove(switch)
    assert run() is RowOutcome.MOVED


def test_edit_moves_a_copy_to_unspecified(logged_in, first, graph):
    unspecified = Release.objects.create(edition=graph.edition, platform=None)

    _edit(logged_in, first, unset_platform="1")

    assert _release(first) == unspecified


def test_a_copy_already_unspecified_counts_unchanged(
    logged_in, owned_user, owned_library, first, graph
):
    unspecified = Release.objects.create(edition=graph.edition, platform=None)
    _move(owned_user, first, unspecified)

    _edit(logged_in, first, unset_platform="1")

    batch = newest_batch(owned_library)
    assert (batch.done, batch.unchanged) == (0, 1)


def test_the_placeholder_keeps_unspecified(owned_user, owned_library, first, graph):
    unspecified = Release.objects.create(edition=graph.edition, platform=None)
    _move(owned_user, first, unspecified)
    rows = ENTRY_EDIT.resolve(owned_library, [first.pk]).rows

    markup = str(ENTRY_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD).node)

    assert "Keep: Unspecified" in markup


def test_an_undo_of_a_row_left_on_its_platform_is_not_this_batchs(
    logged_in, owned_user, first, graph
):
    token = _edit(logged_in, first, platform=str(graph.release.platform_id))

    with pytest.raises(CommandFailed, match=NOT_EDITED_BY_THIS_BATCH):
        _edit_back(owned_user, first, token)


def test_an_undo_overwrites_a_later_move(
    logged_in, owned_user, first, graph, on_switch, capture_games_logger
):
    token = _edit(logged_in, first, platform=str(on_switch.platform_id))
    later = Release.objects.create(edition=graph.edition, platform=None)
    _move(owned_user, first, later)

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        _undo(logged_in, token)

    assert _release(first) == graph.release
    assert any(
        f"states release {graph.release.pk} over {later.pk}" in record.getMessage()
        for record in captured.records
    )


def test_settling_refuses_another_librarys_platform(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = Platform.objects.create(name="Theirs", group="X", library=stranger)

    with pytest.raises(CommandRejected) as refused:
        _settle(owned_library, platform=str(theirs.pk))

    assert PLATFORM_GONE in (refused.value.sentence or "")


def test_settling_refuses_a_removed_platform(owned_library, switch):
    remove(switch)

    with pytest.raises(CommandRejected) as refused:
        _settle(owned_library, platform=str(switch.pk))

    assert PLATFORM_GONE in (refused.value.sentence or "")


def test_a_carried_statement_refuses_a_platform_not_offered(
    owned_library, django_user_model
):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = Platform.objects.create(name="Theirs", group="X", library=stranger)
    post = QueryDict(mutable=True)
    post[CHOICE_FIELD] = _platform_alone(theirs.pk).encode()

    with pytest.raises(CommandRejected) as refused:
        EDIT_CHOICE.settle(owned_library, post)

    assert refused.value.sentence == PLATFORM_GONE
