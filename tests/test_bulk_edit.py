"""One device, or emulated, set on many sessions, and put back."""

import uuid
from datetime import date, timedelta

import pytest
from bulk_posts import act_url, posted, selection
from devices import create_device, remove_device
from django.http import QueryDict
from django.urls import reverse
from session_rows import tracked_run

from games.bulk_actions import AsksNothing, Control
from games.bulk_edit import (
    DEVICE_AND_NONE,
    DEVICE_GONE,
    EDIT,
    EMULATED,
    NOT_EDITED_BY_THIS_BATCH,
    NOT_EMULATED,
    NOTHING_STATED,
    STATEMENT_UNREADABLE,
    EditStatement,
    device_field,
    edit_one,
    emulated_field,
    no_device_field,
    offer_edit,
    settle_edit,
    values_before,
)
from games.commands.playersession import (
    CreateSession,
    DurationOnlyTiming,
    StatedDevice,
)
from games.events.dispatch import CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerSession
from games.views.bulk import CHOICE_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.writes.answers import CommandFailed
from games.writes.playersession import describe_session, remove_session

pytestmark = pytest.mark.django_db(transaction=True)

A_DAY = date(2026, 3, 5)
AN_HOUR = timedelta(hours=1)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def deck(owned_library):
    return create_device(owned_library, "Steam Deck")


@pytest.fixture
def desktop(owned_library):
    return create_device(owned_library, "Desktop")


def a_session(owned_user, run, day=A_DAY, device=None, emulated=False):
    """A session with the events a real one has; the Undo reads them."""
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(day=day, duration=AN_HOUR),
            device_id=None if device is None else device.pk,
            emulated=emulated,
        ),
        actor=owned_user,
        library=owned_user.library,
        idempotency_key=str(uuid.uuid7()),
    )
    return PlayerSession.objects.get(playthrough=run, stated_day=day)


def post(**fields) -> QueryDict:
    stated = QueryDict(mutable=True)
    stated.update(fields)
    return stated


def control(**answers) -> QueryDict:
    """The confirmation's own fields, as the first press posts them."""
    names = {
        "device": device_field(CHOICE_FIELD),
        "no_device": no_device_field(CHOICE_FIELD),
        "emulated": emulated_field(CHOICE_FIELD),
    }
    return post(**{names[key]: value for key, value in answers.items()})


# ── The statement ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    [
        EditStatement(StatedDevice(uuid.uuid7()), None),
        EditStatement(StatedDevice(None), None),
        EditStatement(None, True),
        EditStatement(StatedDevice(uuid.uuid7()), False),
    ],
)
def test_a_statement_round_trips(statement):
    assert EditStatement.decode(statement.encode()) == statement


def test_a_statement_stating_nothing_is_no_statement():
    with pytest.raises(ValueError):
        EditStatement(None, None)


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[]", "{}", '{"note": "x"}', '{"device": 3}', '{"emulated": 1}'],
)
def test_an_unreadable_statement_refuses(raw):
    with pytest.raises(CommandRejected) as refused:
        EditStatement.decode(raw)
    assert refused.value.sentence == STATEMENT_UNREADABLE


# ── The question ─────────────────────────────────────────────────────────────


def test_no_rows_ask_nothing(owned_library):
    assert isinstance(offer_edit(owned_library, [], CHOICE_FIELD), AsksNothing)


def test_the_control_never_posts_under_the_choice_field(
    owned_user, owned_library, game
):
    session = a_session(owned_user, tracked_run(owned_library, game))

    offered = offer_edit(owned_library, [session], CHOICE_FIELD)

    assert isinstance(offered, Control)
    markup = str(offered.node)
    assert f'name="{CHOICE_FIELD}"' not in markup
    for name in (
        device_field(CHOICE_FIELD),
        no_device_field(CHOICE_FIELD),
        emulated_field(CHOICE_FIELD),
    ):
        assert f'name="{name}"' in markup


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ({"no_device": "1"}, EditStatement(StatedDevice(None), None)),
        ({"emulated": EMULATED}, EditStatement(None, True)),
        ({"emulated": NOT_EMULATED}, EditStatement(None, False)),
    ],
)
def test_the_control_composes_a_statement(owned_library, answers, expected):
    settled = settle_edit(owned_library, control(**answers))

    assert EditStatement.decode(settled) == expected


def test_a_picked_device_settles(owned_library, deck):
    settled = settle_edit(
        owned_library, control(device=str(deck.pk), emulated=EMULATED)
    )

    assert EditStatement.decode(settled) == EditStatement(StatedDevice(deck.pk), True)


def test_settling_its_own_answer_answers_it_again(owned_library, deck):
    first = settle_edit(owned_library, control(device=str(deck.pk)))

    assert settle_edit(owned_library, post(**{CHOICE_FIELD: first})) == first


def test_a_carried_statement_outranks_the_control(owned_library, deck):
    carried = EditStatement(None, True).encode()

    settled = settle_edit(
        owned_library, post(**{CHOICE_FIELD: carried, device_field(CHOICE_FIELD): ""})
    )

    assert settled == carried


@pytest.mark.parametrize(
    ("answers", "sentence"),
    [
        ({}, NOTHING_STATED),
        ({"emulated": ""}, NOTHING_STATED),
        ({"emulated": "maybe"}, STATEMENT_UNREADABLE),
    ],
)
def test_a_control_stating_nothing_readable_refuses(owned_library, answers, sentence):
    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, control(**answers))
    assert refused.value.sentence == sentence


def test_a_device_and_no_device_refuse(owned_library, deck):
    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, control(device=str(deck.pk), no_device="1"))
    assert refused.value.sentence == DEVICE_AND_NONE


def test_a_removed_device_refuses(owned_library, deck):
    remove_device(deck)

    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, control(device=str(deck.pk)))
    assert refused.value.sentence == DEVICE_GONE


def test_another_librarys_device_refuses(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user("stranger", password="x")
    theirs = create_device(stranger.library, "Their Deck")
    carried = EditStatement(StatedDevice(theirs.pk), None).encode()

    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, post(**{CHOICE_FIELD: carried}))
    assert refused.value.sentence == DEVICE_GONE


# ── The act ──────────────────────────────────────────────────────────────────


def _edit(owned_user, session, statement, correlation_id=None):
    return edit_one(
        owned_user,
        session,
        choice=statement.encode(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id or uuid.uuid7(),
    )


def test_a_row_takes_the_device_and_keeps_its_emulated(
    owned_user, owned_library, game, deck
):
    session = a_session(owned_user, tracked_run(owned_library, game), emulated=True)

    outcome = _edit(owned_user, session, EditStatement(StatedDevice(deck.pk), None))

    session.refresh_from_db()
    assert outcome == "moved"
    assert session.device_id == deck.pk
    assert session.emulated is True


def test_a_row_already_so_is_unchanged(owned_user, owned_library, game, deck):
    session = a_session(owned_user, tracked_run(owned_library, game), device=deck)

    outcome = _edit(owned_user, session, EditStatement(StatedDevice(deck.pk), None))

    assert outcome == "unchanged"


def test_a_removed_session_is_refused(owned_user, owned_library, game, deck):
    session = a_session(owned_user, tracked_run(owned_library, game))
    remove_session(owned_user, session, correlation_id=uuid.uuid7())

    with pytest.raises(CommandFailed):
        _edit(owned_user, session, EditStatement(StatedDevice(deck.pk), None))


# ── Backward ─────────────────────────────────────────────────────────────────


def test_values_before_read_the_creation(owned_user, owned_library, game, deck):
    session = a_session(owned_user, tracked_run(owned_library, game))
    batch = uuid.uuid7()
    _edit(owned_user, session, EditStatement(StatedDevice(deck.pk), True), batch)

    assert values_before(owned_library, session.pk, batch) == EditStatement(
        StatedDevice(None), False
    )


def test_values_before_read_an_earlier_change(
    owned_user, owned_library, game, deck, desktop
):
    session = a_session(owned_user, tracked_run(owned_library, game), device=deck)
    describe_session(
        owned_user,
        session,
        device=StatedDevice(desktop.pk),
        correlation_id=uuid.uuid7(),
    )
    batch = uuid.uuid7()
    _edit(owned_user, session, EditStatement(StatedDevice(None), None), batch)

    assert values_before(owned_library, session.pk, batch) == EditStatement(
        StatedDevice(desktop.pk), None
    )


def test_values_before_name_only_the_fact_the_batch_changed(
    owned_user, owned_library, game, deck
):
    """Emulated was already so: the batch wrote a device event alone."""
    session = a_session(owned_user, tracked_run(owned_library, game), emulated=True)
    batch = uuid.uuid7()
    _edit(owned_user, session, EditStatement(StatedDevice(deck.pk), True), batch)

    assert values_before(owned_library, session.pk, batch) == EditStatement(
        StatedDevice(None), None
    )


def test_a_row_the_batch_left_alone_refuses_its_undo(owned_user, owned_library, game):
    session = a_session(owned_user, tracked_run(owned_library, game))

    with pytest.raises(CommandRejected) as refused:
        values_before(owned_library, session.pk, uuid.uuid7())
    assert refused.value.sentence == NOT_EDITED_BY_THIS_BATCH


# ── Through the runner ───────────────────────────────────────────────────────


def _token(client, *sessions) -> dict[str, str]:
    confirmation = client.post(act_url(EDIT), {STATEMENT_FIELD: selection(*sessions)})
    return posted(confirmation)


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def test_a_batch_sets_the_device_and_its_undo_puts_each_back(
    client_in, owned_user, owned_library, game, deck, desktop
):
    run = tracked_run(owned_library, game)
    bare = a_session(owned_user, run, A_DAY)
    elsewhere = a_session(owned_user, run, A_DAY + AN_HOUR * 24, device=desktop)
    fields = _token(client_in, bare, elsewhere)
    client_in.post(act_url(EDIT), {**fields, **control(device=str(deck.pk)).dict()})

    for session in (bare, elsewhere):
        session.refresh_from_db()
        assert session.device_id == deck.pk

    _undo(client_in, fields[TOKEN_FIELD])

    bare.refresh_from_db()
    elsewhere.refresh_from_db()
    assert bare.device_id is None
    assert elsewhere.device_id == desktop.pk


def test_a_second_undo_changes_nothing(
    client_in, owned_user, owned_library, game, deck
):
    session = a_session(owned_user, tracked_run(owned_library, game))
    fields = _token(client_in, session)
    client_in.post(act_url(EDIT), {**fields, **control(emulated=EMULATED).dict()})
    _undo(client_in, fields[TOKEN_FIELD])
    appended = LibraryEvent.objects.filter(aggregate_id=session.pk).count()

    _undo(client_in, fields[TOKEN_FIELD])

    session.refresh_from_db()
    assert session.emulated is False
    assert LibraryEvent.objects.filter(aggregate_id=session.pk).count() == appended


def test_an_undo_overwrites_a_value_set_since(
    client_in, owned_user, owned_library, game, deck, desktop
):
    """A restating inverse reads the row as it stands."""
    session = a_session(owned_user, tracked_run(owned_library, game))
    fields = _token(client_in, session)
    client_in.post(act_url(EDIT), {**fields, **control(device=str(deck.pk)).dict()})
    session.refresh_from_db()
    describe_session(
        owned_user,
        session,
        device=StatedDevice(desktop.pk),
        correlation_id=uuid.uuid7(),
    )

    _undo(client_in, fields[TOKEN_FIELD])

    session.refresh_from_db()
    assert session.device_id is None


def test_an_undo_to_a_device_removed_since_leaves_the_row(
    client_in, owned_user, owned_library, game, deck, desktop
):
    session = a_session(owned_user, tracked_run(owned_library, game), device=desktop)
    fields = _token(client_in, session)
    client_in.post(act_url(EDIT), {**fields, **control(device=str(deck.pk)).dict()})
    remove_device(desktop)

    _undo(client_in, fields[TOKEN_FIELD])

    session.refresh_from_db()
    assert session.device_id == deck.pk


def test_a_refused_settle_asks_again_on_the_same_token(
    client_in, owned_user, owned_library, game
):
    session = a_session(owned_user, tracked_run(owned_library, game))
    fields = _token(client_in, session)

    again = client_in.post(act_url(EDIT), {**fields, **control().dict()})

    assert again.status_code == 400
    assert posted(again)[TOKEN_FIELD] == fields[TOKEN_FIELD]
    session.refresh_from_db()
    assert session.device_id is None


def test_the_question_drops_the_labels_three_dots(
    client_in, owned_user, owned_library, game
):
    session = a_session(owned_user, tracked_run(owned_library, game))

    body = client_in.post(
        act_url(EDIT), {STATEMENT_FIELD: selection(session)}
    ).content.decode()

    assert "Edit: 1 session?" in body
    assert "Edit…:" not in body
