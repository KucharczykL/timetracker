"""Access to many copies ended, and the Undo."""

import re
import uuid
from datetime import date

import pytest
from bulk_posts import act_url, posted, said, selection
from django.db import transaction
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry
from purchases import record_purchase, refund_purchase

from games.bulk_actions import BULK_ACTIONS
from games.bulk_entry_end import (
    ENDED_MANY,
    ENDED_ONE,
    ENTRY_END,
    already_ended,
)
from games.bulk_parts import EventRows
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    END_BEFORE_ACQUISITION,
    ENTRY_REMOVED,
    ENTRY_UNDO,
    CorrectEntryAccessEnd,
    EndEntryAccess,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.events.dispatch import Command, append_command
from games.events.libraryentry import (
    LIBRARYENTRY_ACCESS_END_VOIDED,
    LIBRARYENTRY_ACCESS_ENDED,
)
from games.models import Game, LibraryEntry, LibraryEvent, Platform, UserLibrary
from games.reads.calendar import calendar_today
from games.reads.endpoints import stated
from games.views.bulk import CHOICE_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.writes.answers import CommandFailed
from games.writes.libraryentry import undo_entry_access_end
from games.writes.playergame import new_correlation_id
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

SOLD_DAY = date(2024, 5, 1)
RESUMED = ActStatement(TemporalValue.from_day(date(2024, 6, 1)), "")


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(
        Game(name="Tunic", library=owned_library),
        owned_library,
        platform=Platform.objects.create(name="PS5", group="Sony"),
    )


@pytest.fixture
def first(owned_library, graph):
    return record_entry(owned_library, graph.release)


@pytest.fixture
def second(owned_library, graph):
    return record_entry(owned_library, graph.release, access="borrowed")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _answers(way: str, day: date | None, note: str = "") -> dict[str, str]:
    name = f"{CHOICE_FIELD}-ended"
    fields = {f"{CHOICE_FIELD}-way": way, f"{CHOICE_FIELD}-note": note}
    if day is not None:
        fields[temporal_input_name(name, "kind")] = "date"
        fields[temporal_input_name(name, "start_year")] = str(day.year)
        fields[temporal_input_name(name, "start_month")] = str(day.month)
        fields[temporal_input_name(name, "start_day")] = str(day.day)
    return fields


def _confirm(client, *entries):
    return client.post(act_url(ENTRY_END), {STATEMENT_FIELD: selection(*entries)})


def _press_fields(client, *entries, way="sold", day=SOLD_DAY, note=""):
    """Confirm and answer; the fields Save posts."""
    fields = posted(_confirm(client, *entries))
    fields.update(_answers(way, day, note))
    fields.pop(CHOICE_FIELD, None)
    return fields


def _end(client, *entries, way="sold", day=SOLD_DAY, note=""):
    """Confirm, answer, press; the token and the answer."""
    fields = _press_fields(client, *entries, way=way, day=day, note=note)
    return fields[TOKEN_FIELD], client.post(act_url(ENTRY_END), fields)


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def _state(library: UserLibrary, command: Command) -> None:
    with transaction.atomic():
        append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def _end_of(entry: LibraryEntry):
    entry.refresh_from_db()
    return stated(entry, ENTRY_ACCESS_END)


# ── The declaration ─────────────────────────────────────────────────────────


def test_the_act_is_declared():
    assert BULK_ACTIONS["entry.end"] is ENTRY_END
    assert ENTRY_END.undo_rows == EventRows(LibraryEntry)
    assert ENTRY_END.title.many.format(count=3) == "I no longer have these 3 copies"


def test_the_caution_counts_ended_copies(owned_library, first, second):
    assert already_ended([first, second]) is None
    end_entry_access(first)
    assert already_ended([first, second]) == ENDED_ONE
    end_entry_access(second, ended=None)
    assert already_ended([first, second]) == ENDED_MANY.format(count=2)


# ── The confirmation ────────────────────────────────────────────────────────


def test_the_confirmation_asks_way_day_and_note(logged_in, owned_library, first):
    html = _confirm(logged_in, first).content.decode()

    assert f'name="{CHOICE_FIELD}-way"' in html
    assert f'name="{CHOICE_FIELD}-note"' in html
    assert re.search(r'<option value="unstated"[^>]*selected[^>]*>Not said<', html)
    today = calendar_today(owned_library)
    year = temporal_input_name(f"{CHOICE_FIELD}-ended", "start_year")
    assert re.search(rf'name="{year}"[^>]*value="{today.year}"', html) or re.search(
        rf'value="{today.year}"[^>]*name="{year}"', html
    )


def _preview_row(html: str, game: str) -> str:
    """One preview row's markup, by its game."""
    rows = re.findall(r"<tr\b.*?</tr>", html, re.DOTALL)
    return next(row for row in rows if f">{game}<" in row)


def test_the_confirmation_names_already_ended_copies(
    logged_in, owned_library, stated_graph, first
):
    other = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    nameless = record_entry(owned_library, other.release)
    end_entry_access(first, ended=TemporalValue.from_day(SOLD_DAY))
    end_entry_access(nameless, ended=None)
    held = record_entry(
        owned_library,
        stated_graph(
            Game(name="Celeste", library=owned_library), owned_library
        ).release,
    )

    html = _confirm(logged_in, first, nameless, held).content.decode()

    assert ENDED_MANY.format(count=2) in html
    assert ">Ended<" in html
    assert "2024" in _preview_row(html, "Tunic")
    assert "Unknown" in _preview_row(html, "Hades")
    assert "–" in _preview_row(html, "Celeste")


# ── Forward ─────────────────────────────────────────────────────────────────


def test_the_press_ends_every_copy(logged_in, first, second):
    _end(logged_in, first, second, way="sold", note="to a friend")

    for entry in (first, second):
        end = _end_of(entry)
        assert end is not None
        assert end.way == EndWay.SOLD
        assert end.when == TemporalValue.from_day(SOLD_DAY)
        assert end.note == "to a friend"
    event = LibraryEvent.objects.get(
        aggregate_id=first.pk, event_type=LIBRARYENTRY_ACCESS_ENDED.event_type
    )
    assert event.source_metadata == {"bulk": {"action": "entry.end"}}


def test_the_default_answers_state_not_said_and_today(logged_in, owned_library, first):
    _end(logged_in, first, way="unstated", day=calendar_today(owned_library))

    end = _end_of(first)
    assert end is not None
    assert end.way == EndWay.UNSTATED
    assert end.when == TemporalValue.from_day(calendar_today(owned_library))


def test_an_end_on_no_day_is_stated(logged_in, first):
    _end(logged_in, first, day=None)

    end = _end_of(first)
    assert end is not None
    assert end.when is None


def test_an_ended_copy_is_left_alone(logged_in, first, second):
    end_entry_access(first, way=EndWay.LOST)

    _, answer = _end(logged_in, first, second)

    assert _end_of(first).way == EndWay.LOST
    assert _end_of(second).way == EndWay.SOLD
    assert any("already has an end recorded" in sentence for sentence in said(answer))


def test_an_end_before_the_acquisition_is_refused(owned_library, logged_in, graph):
    late = record_entry(
        owned_library, graph.release, acquired=TemporalValue.from_day(date(2025, 1, 1))
    )

    _, answer = _end(logged_in, late, day=SOLD_DAY)

    assert _end_of(late) is None
    assert END_BEFORE_ACQUISITION in said(answer)


def test_a_token_posted_twice_acts_once(logged_in, first):
    fields = _press_fields(logged_in, first)
    logged_in.post(act_url(ENTRY_END), fields)
    logged_in.post(act_url(ENTRY_END), fields)

    assert (
        LibraryEvent.objects.filter(
            aggregate_id=first.pk, event_type=LIBRARYENTRY_ACCESS_ENDED.event_type
        ).count()
        == 1
    )


# ── Backward ────────────────────────────────────────────────────────────────


def test_the_undo_voids_every_end(logged_in, first, second):
    token, _ = _end(logged_in, first, second)

    _undo(logged_in, token)

    assert _end_of(first) is None
    assert _end_of(second) is None


def test_an_undo_pressed_twice_is_already_so(logged_in, first):
    token, _ = _end(logged_in, first)
    _undo(logged_in, token)

    again = _undo(logged_in, token)

    assert _end_of(first) is None
    assert any("already" in sentence for sentence in said(again))


def test_a_copy_voided_by_hand_is_already_so(logged_in, owned_library, first):
    token, _ = _end(logged_in, first)
    _state(owned_library, VoidEntryAccessEnd(entry_id=first.pk))

    undone = _undo(logged_in, token)

    assert _end_of(first) is None
    assert any("already" in sentence for sentence in said(undone))


def test_a_copy_resumed_since_is_already_so(logged_in, owned_library, first):
    token, _ = _end(logged_in, first)
    _state(owned_library, ResumeEntryAccess(entry_id=first.pk, statement=RESUMED))

    undone = _undo(logged_in, token)

    assert _end_of(first) is None
    assert any("already" in sentence for sentence in said(undone))
    assert not LibraryEvent.objects.filter(
        aggregate_id=first.pk, event_type=LIBRARYENTRY_ACCESS_END_VOIDED.event_type
    ).exists()


def test_a_copy_corrected_since_keeps_its_end(logged_in, owned_library, first):
    token, _ = _end(logged_in, first)
    corrected = WayActStatement(TemporalValue.from_day(SOLD_DAY), EndWay.LOST, "")
    _state(owned_library, CorrectEntryAccessEnd(entry_id=first.pk, statement=corrected))

    undone = _undo(logged_in, token)

    assert _end_of(first).way == EndWay.LOST
    assert ENTRY_UNDO.changed_since in said(undone)


def test_a_copy_ended_again_since_keeps_its_end(logged_in, owned_library, first):
    token, _ = _end(logged_in, first)
    _state(owned_library, ResumeEntryAccess(entry_id=first.pk, statement=RESUMED))
    again = WayActStatement(TemporalValue.from_day(date(2024, 7, 1)), EndWay.LOST, "")
    _state(owned_library, EndEntryAccess(entry_id=first.pk, statement=again))

    undone = _undo(logged_in, token)

    assert _end_of(first).way == EndWay.LOST
    assert ENTRY_UNDO.changed_since in said(undone)


def test_a_removed_copy_keeps_its_end_and_the_rest_are_voided(logged_in, first, second):
    token, _ = _end(logged_in, first, second)
    remove_entry(first)

    undone = _undo(logged_in, token)

    assert _end_of(first) is not None
    assert _end_of(second) is None
    assert ENTRY_REMOVED in said(undone)


def test_an_undo_after_a_refund_leaves_the_copy_held(logged_in, first):
    """The refund wrote no end: one stood."""
    purchase = record_purchase(first)
    token, _ = _end(logged_in, first)
    refund_purchase(purchase, TemporalValue.from_day(date(2024, 6, 1)))

    _undo(logged_in, token)

    assert _end_of(first) is None


def test_a_carried_way_that_is_no_text_is_asked_again(logged_in, first):
    fields = posted(_confirm(logged_in, first))
    fields[CHOICE_FIELD] = '{"when": null, "way": ["sold"], "note": ""}'

    answer = logged_in.post(act_url(ENTRY_END), fields)

    #: Drawn again, not a 500.
    assert answer.status_code == 400
    assert "Choose it again." in answer.content.decode()
    assert _end_of(first) is None


def test_the_undo_of_a_copy_no_batch_ended_is_refused(owned_user, first):
    with pytest.raises(CommandFailed) as refused:
        undo_entry_access_end(
            owned_user,
            first,
            batch_id=uuid.uuid7(),
            correlation_id=new_correlation_id(),
        )

    assert refused.value.message == ENTRY_UNDO.not_stated
