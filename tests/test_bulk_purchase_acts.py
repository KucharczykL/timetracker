"""Bulk purchase edit and removal, and Undo."""

import datetime
import html as html_module
import json
import logging
import re
import uuid
from decimal import Decimal
from typing import cast

import pytest
from bulk_posts import act_url, posted, press, selection
from django.http import Http404, QueryDict
from django.urls import reverse
from entries import record_entry, remove_entry
from graphs import default_graph
from purchases import record_purchase, refund_purchase, remove_purchase

from common.components.unset_field import unset_input_name
from common.criteria import FilterError
from games.bulk_actions import BULK_ACTIONS
from games.bulk_parts import Control, EventRows, RowOutcome
from games.bulk_purchase_edit import (
    EDIT_CHOICE,
    NOT_EDITED_BY_THIS_BATCH,
    PURCHASE_EDIT,
    PurchaseEditStatement,
    _form,
)
from games.bulk_purchase_edit import NOTHING_STATED as EDIT_NOTHING_STATED
from games.bulk_purchase_edit import PURCHASE_REMOVED as EDIT_PURCHASE_REMOVED
from games.bulk_purchases import PURCHASE_GONE
from games.bulk_removal import REMOVE_PURCHASE
from games.commands.endpoint import ActStatement
from games.commands.purchase import (
    ENTRY_REMOVED,
    KIND_UNDER_A_REFUND,
    UNKNOWN_PRICE,
    StatedPrice,
)
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.purchase import PURCHASE_CREATED, PURCHASE_PRICE_CHANGED
from games.forms import ChoiceSearchSelectWidget, TemporalWidget, UnsetWidget
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    Platform,
    Purchase,
    PurchaseKind,
)
from games.price_fields import AMOUNT_REQUIRED
from games.reads.events import batch_aggregate_ids
from games.reads.fact_change import FactChange, _value
from games.reads.purchase_facts import _PRICE, purchase_fact_changes
from games.views.bulk import CHOICE_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.writes import revaluation
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.purchase import restate_purchase
from timetracker.settings_commands import change_user_setting
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library):
    return default_graph(
        Game(name="Tunic", library=owned_library),
        owned_library,
        platform=Platform.objects.create(name="PS5", group="Sony"),
    )


@pytest.fixture
def copy(owned_library, graph) -> LibraryEntry:
    return record_entry(owned_library, graph.release)


@pytest.fixture
def first(copy) -> Purchase:
    return record_purchase(copy, purchased=TemporalValue.parse("2021-03-01"))


@pytest.fixture
def second(copy) -> Purchase:
    return record_purchase(copy, kind="season_pass", amount=None)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


# ── The declarations ────────────────────────────────────────────────────────


def test_remove_is_declared():
    assert BULK_ACTIONS["purchase.remove"] is REMOVE_PURCHASE
    assert REMOVE_PURCHASE.undo_rows == EventRows(Purchase)
    assert REMOVE_PURCHASE.title.many.format(count=3) == "Remove 3 purchases"
    assert REMOVE_PURCHASE.title.one == "Remove this purchase"


# ── Scope and rows ──────────────────────────────────────────────────────────


def test_the_scope_narrows_by_the_statements_filter(owned_library, first, second):
    narrowed = REMOVE_PURCHASE.scope(
        owned_library,
        json.dumps({"kind": {"value": ["season_pass"], "modifier": "INCLUDES"}}),
    )

    assert list(narrowed) == [second]


def test_an_unreadable_filter_refuses_the_act(owned_library, first):
    with pytest.raises(FilterError):
        REMOVE_PURCHASE.scope(owned_library, json.dumps({"nonsense": {}}))


def test_another_librarys_purchase_comes_out_lost(
    owned_library, first, django_user_model
):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = record_purchase(
        record_entry(
            stranger,
            default_graph(Game(name="Hades", library=stranger), stranger).release,
        )
    )

    resolution = REMOVE_PURCHASE.resolve(owned_library, [first.pk, theirs.pk])

    assert [row.pk for row in resolution.rows] == [first.pk]
    assert [(refused.key, refused.sentence) for refused in resolution.refused] == [
        (str(theirs.pk), PURCHASE_GONE)
    ]


def test_the_preview_names_game_purchase_price_and_day(owned_library, first, second):
    rows = REMOVE_PURCHASE.resolve(owned_library, [first.pk, second.pk]).rows
    cells = [
        [str(column.cell(row, None)) for column in REMOVE_PURCHASE.preview[:3]]
        for row in rows
    ]

    assert [column.heading for column in REMOVE_PURCHASE.preview] == [
        "Game",
        "Purchase",
        "Price",
        "Purchased",
    ]
    assert cells == [
        ["Tunic", "Bought", "19.99 EUR"],
        ["Tunic", "Season pass", "Unknown price"],
    ]


# ── Remove and its Undo ─────────────────────────────────────────────────────


def test_remove_takes_two_purchases_and_undo_puts_them_back(logged_in, first, second):
    fields = posted(
        logged_in.post(
            act_url(REMOVE_PURCHASE), {STATEMENT_FIELD: selection(first, second)}
        )
    )
    logged_in.post(act_url(REMOVE_PURCHASE), fields)

    assert not Purchase.objects.filter(removed_at__isnull=True).exists()

    _undo(logged_in, fields[TOKEN_FIELD])

    assert Purchase.objects.filter(removed_at__isnull=True).count() == 2


def test_the_undo_requests_a_revaluation(logged_in, first, monkeypatch):
    fields = posted(
        logged_in.post(act_url(REMOVE_PURCHASE), {STATEMENT_FIELD: selection(first)})
    )
    logged_in.post(act_url(REMOVE_PURCHASE), fields)
    requested = []
    monkeypatch.setattr(
        revaluation, "request_revaluation", lambda library: requested.append(library)
    )

    _undo(logged_in, fields[TOKEN_FIELD])

    assert requested == [first.library]


def test_a_purchase_removed_since_the_confirmation_is_left_alone(logged_in, first):
    remove_purchase(first)

    press(logged_in, REMOVE_PURCHASE, first)

    first.refresh_from_db()
    assert first.removed_at is not None


def test_an_undo_of_another_librarys_purchase_is_absent(owned_user, django_user_model):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = remove_purchase(
        record_purchase(
            record_entry(
                stranger,
                default_graph(Game(name="Hades", library=stranger), stranger).release,
            )
        )
    )

    with pytest.raises(Http404):
        REMOVE_PURCHASE.inverse(
            owned_user,
            theirs.pk,
            undoes=uuid.uuid7(),
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


# ── Edit: the question ──────────────────────────────────────────────────────


def _control(**answers: str) -> dict[str, str]:
    """`unset_x` is x's ⊘; `purchased` a day."""
    fields: dict[str, str] = {}
    for key, value in answers.items():
        if key == "purchased":
            day = datetime.date.fromisoformat(value)
            name = f"{CHOICE_FIELD}-purchased"
            fields[temporal_input_name(name, "kind")] = "date"
            fields[temporal_input_name(name, "start_year")] = str(day.year)
            fields[temporal_input_name(name, "start_month")] = str(day.month)
            fields[temporal_input_name(name, "start_day")] = str(day.day)
        elif key.startswith("unset_"):
            fields[unset_input_name(f"{CHOICE_FIELD}-{key.removeprefix('unset_')}")] = (
                value
            )
        else:
            fields[f"{CHOICE_FIELD}-{key}"] = value
    fields.setdefault(f"{CHOICE_FIELD}-price", "keep")
    return fields


def _settle(owned_library, **answers: str) -> PurchaseEditStatement:
    post = QueryDict(mutable=True)
    post.update(_control(**answers))
    return PurchaseEditStatement.decode(EDIT_CHOICE.settle(owned_library, post))


def _edit(client, *purchases, **answers: str) -> str:
    url = act_url(PURCHASE_EDIT)
    fields = posted(client.post(url, {STATEMENT_FIELD: selection(*purchases)}))
    fields.update(_control(**answers))
    fields.pop(CHOICE_FIELD, None)
    client.post(url, fields)
    return fields[TOKEN_FIELD]


def _facts(purchase) -> tuple[str, Decimal | None, str, str | None, str]:
    purchase.refresh_from_db()
    return (
        purchase.kind,
        purchase.amount,
        purchase.currency,
        purchase.purchased.canonical if purchase.purchased else None,
        purchase.note,
    )


def test_edit_is_declared():
    assert BULK_ACTIONS["purchase.edit"] is PURCHASE_EDIT
    assert PURCHASE_EDIT.undo_rows == EventRows(Purchase)
    assert PURCHASE_EDIT.title.many.format(count=2) == "Edit 2 purchases"


def test_the_control_keeps_what_the_rows_hold(owned_library, first, second):
    rows = PURCHASE_EDIT.resolve(owned_library, [first.pk, second.pk]).rows

    offered = PURCHASE_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert isinstance(offered, Control)
    markup = str(offered.node)
    assert "Keep: mixed" in markup
    assert 'value="keep"' in markup


def test_the_control_names_one_price_the_rows_share(owned_library, first):
    rows = PURCHASE_EDIT.resolve(owned_library, [first.pk]).rows

    offered = PURCHASE_EDIT.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert isinstance(offered, Control)
    assert "Keep: 19.99 EUR" in str(offered.node)


def test_settling_refuses_a_form_that_states_nothing(owned_library):
    with pytest.raises(CommandRejected) as refused:
        _settle(owned_library, kind="")

    assert refused.value.sentence == EDIT_NOTHING_STATED


def test_paid_needs_an_amount(owned_library):
    with pytest.raises(CommandRejected) as refused:
        _settle(owned_library, price="paid", amount="", currency="EUR")

    assert AMOUNT_REQUIRED in str(refused.value.sentence)


def test_settling_reads_each_price(owned_library):
    paid = _settle(owned_library, price="paid", amount="12.5", currency="eur")
    free = _settle(owned_library, price="free", currency="CZK")
    unknown = _settle(owned_library, price="unknown")

    assert paid.price == StatedPrice(Decimal("12.5"), "EUR")
    assert free.price == StatedPrice(Decimal(0), "CZK")
    assert unknown.price == UNKNOWN_PRICE


def test_settling_states_a_cleared_note_and_a_day(owned_library):
    settled = _settle(owned_library, unset_note="1", purchased="2020-05-04")

    assert settled == PurchaseEditStatement(
        None, None, TemporalValue.parse("2020-05-04"), ""
    )


def test_settling_states_an_unknown_day_through_the_toggle(owned_library):
    settled = _settle(owned_library, unset_purchased="1")

    assert settled == PurchaseEditStatement(None, None, TemporalValue.unknown(), None)


def test_the_toggle_clears_each_rows_day(logged_in, first):
    _edit(logged_in, first, unset_purchased="1")

    assert _facts(first)[3] is None


def test_an_unknown_day_and_price_round_trip():
    statement = PurchaseEditStatement(
        None, UNKNOWN_PRICE, TemporalValue.unknown(), None
    )

    assert PurchaseEditStatement.decode(statement.encode()) == statement


def test_a_carried_price_reads_one_spelling():
    carried = '{"price": {"amount": "1.5", "currency": "eur"}}'

    assert PurchaseEditStatement.decode(carried).price == StatedPrice(
        Decimal("1.5"), "EUR"
    )


def test_the_day_field_reads_the_users_date_locale(owned_library):
    change_user_setting(owned_library.user, "DATE_FORMAT_LOCALE", "cs")

    form = _form(owned_library, None, CHOICE_FIELD)

    day = cast(UnsetWidget, form.fields["purchased"].widget).widget
    assert cast(TemporalWidget, day).presentation.locale == "cs"


def test_kind_and_note_keep_as_placeholders(owned_library, first, second):
    rows = PURCHASE_EDIT.resolve(owned_library, [first.pk, second.pk]).rows

    form = _form(owned_library, None, CHOICE_FIELD, rows)

    kind = cast(ChoiceSearchSelectWidget, form.fields["kind"].widget)
    note = cast(UnsetWidget, form.fields["note"].widget).widget
    assert kind.placeholder == "Keep: mixed"
    assert note.attrs["placeholder"] == "Keep: no note"


def test_a_chunk_posted_twice_edits_once(logged_in, owned_user, first):
    url = act_url(PURCHASE_EDIT)
    fields = posted(logged_in.post(url, {STATEMENT_FIELD: selection(first)}))
    fields.update(_control(price="paid", amount="5", currency="EUR"))
    fields.pop(CHOICE_FIELD, None)
    logged_in.post(url, fields)
    first.refresh_from_db()
    restate_purchase(owned_user, first, note="later", correlation_id=uuid.uuid7())
    events = LibraryEvent.objects.count()

    logged_in.post(url, fields)

    assert LibraryEvent.objects.count() == events
    assert _facts(first)[4] == "later"


def test_a_chunk_posted_twice_removes_once(logged_in, owned_library, first):
    url = act_url(REMOVE_PURCHASE)
    fields = posted(logged_in.post(url, {STATEMENT_FIELD: selection(first)}))
    logged_in.post(url, fields)
    events = LibraryEvent.objects.count()

    logged_in.post(url, fields)

    assert LibraryEvent.objects.count() == events
    assert set(
        batch_aggregate_ids(owned_library, uuid.UUID(fields[TOKEN_FIELD]), "purchase")
    ) == {first.pk}


def test_an_undo_puts_an_unknown_price_back(logged_in, owned_library, second):
    token = _edit(logged_in, second, price="paid", amount="5", currency="EUR")

    changes = purchase_fact_changes(owned_library, second.pk, uuid.UUID(token))
    _undo(logged_in, token)

    assert changes.price == FactChange(
        UNKNOWN_PRICE, StatedPrice(Decimal("5.00"), "EUR")
    )
    assert _facts(second)[1:3] == (None, "")


def test_an_undo_under_a_removed_copy_is_a_sentence(logged_in, graph, first, copy):
    other = record_purchase(
        record_entry(copy.library, graph.release), purchased=first.purchased
    )
    fields = posted(
        logged_in.post(
            act_url(REMOVE_PURCHASE), {STATEMENT_FIELD: selection(first, other)}
        )
    )
    logged_in.post(act_url(REMOVE_PURCHASE), fields)
    remove_entry(copy)

    response = logged_in.post(
        reverse("games:undo_bulk_action", args=[fields[TOKEN_FIELD]]), follow=True
    )

    first.refresh_from_db()
    other.refresh_from_db()
    assert first.removed_at is not None
    assert other.removed_at is None
    assert html_module.escape(ENTRY_REMOVED) in response.text


def test_a_missing_price_key_is_unreadable(owned_library):
    event = LibraryEvent(
        pk=1,
        library_id=owned_library.pk,
        sequence=7,
        event_type=PURCHASE_PRICE_CHANGED.event_type,
        payload={},
    )

    with pytest.raises(RowUnreadable):
        _value(_PRICE, event)


def test_a_statement_round_trips():
    statement = PurchaseEditStatement(
        PurchaseKind.UPGRADE,
        UNKNOWN_PRICE,
        TemporalValue.parse("2020-05-04"),
        "boxed",
    )

    assert PurchaseEditStatement.decode(statement.encode()) == statement


@pytest.mark.parametrize(
    "carried",
    [
        '{"kind": "dlc"}',
        '{"note": 3}',
        "{}",
        '{"status": "x"}',
        '{"price": {"amount": "x", "currency": "EUR"}}',
        '{"price": {"amount": 3, "currency": "EUR"}}',
        '{"price": {"amount": "1.234", "currency": "EUR"}}',
        '{"price": {"amount": "1", "currency": ""}}',
        '{"purchased": "someday"}',
        '{"purchased": 5}',
    ],
)
def test_an_unreadable_statement_is_refused(carried):
    with pytest.raises(CommandRejected):
        PurchaseEditStatement.decode(carried)


# ── Edit and its Undo ───────────────────────────────────────────────────────


def test_edit_states_the_facts_and_keeps_empty_fields(logged_in, first, second):
    _edit(logged_in, first, second, price="free", currency="EUR")

    assert _facts(first) == ("game", Decimal("0.00"), "EUR", "2021-03-01", "")
    assert _facts(second) == ("season_pass", Decimal("0.00"), "EUR", None, "")


def test_edit_states_kind_day_and_note_together(logged_in, first):
    _edit(logged_in, first, kind="upgrade", purchased="2020-05-04", note="boxed")

    assert _facts(first) == ("upgrade", Decimal("19.99"), "EUR", "2020-05-04", "boxed")


def test_a_day_keeps_the_rows_own_note(logged_in, copy):
    purchase = record_purchase(
        copy, purchased=TemporalValue.parse("2021-03-01"), purchase_note="receipt"
    )

    _edit(logged_in, purchase, purchased="2020-05-04")

    purchase.refresh_from_db()
    assert purchase.purchased == TemporalValue.parse("2020-05-04")
    assert purchase.purchase_note == "receipt"


def test_a_row_already_so_is_unchanged(owned_user, first):
    outcome = PURCHASE_EDIT.run(
        owned_user,
        first,
        choice=PurchaseEditStatement(None, None, first.purchased, None).encode(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )

    assert outcome is RowOutcome.UNCHANGED


def test_undo_states_every_fact_before_the_batch(logged_in, first, second):
    token = _edit(
        logged_in,
        first,
        second,
        kind="upgrade",
        price="unknown",
        purchased="2020-05-04",
        unset_note="1",
    )

    _undo(logged_in, token)

    assert _facts(first) == ("game", Decimal("19.99"), "EUR", "2021-03-01", "")
    assert _facts(second) == ("season_pass", None, "", None, "")


def _edit_back(owned_user, purchase, token):
    return PURCHASE_EDIT.inverse(
        owned_user,
        purchase.pk,
        undoes=uuid.UUID(token),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


def test_an_undo_finds_the_facts_already_back(logged_in, owned_user, first):
    token = _edit(logged_in, first, kind="upgrade")
    _undo(logged_in, token)

    assert _edit_back(owned_user, first, token) is RowOutcome.UNCHANGED


def test_an_undo_writes_over_a_later_change(
    logged_in, owned_user, first, capture_games_logger
):
    token = _edit(logged_in, first, note="boxed")
    restate_purchase(owned_user, first, note="later", correlation_id=uuid.uuid7())

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        _undo(logged_in, token)

    assert _facts(first)[4] == ""
    assert any("over later" in record.getMessage() for record in captured.records)


def test_an_undo_of_a_batch_that_changed_nothing_is_refused(owned_user, first):
    with pytest.raises(CommandFailed, match=NOT_EDITED_BY_THIS_BATCH):
        _edit_back(owned_user, first, str(uuid.uuid7()))


def test_an_undo_refuses_a_purchase_removed_since(logged_in, owned_user, first):
    token = _edit(logged_in, first, kind="upgrade")
    remove_purchase(first)

    with pytest.raises(CommandFailed, match=EDIT_PURCHASE_REMOVED):
        _edit_back(owned_user, first, token)
    assert _facts(first)[0] == "upgrade"


def test_an_undo_meets_a_refund_since_and_the_batch_goes_on(logged_in, first, second):
    token = _edit(logged_in, first, second, kind="upgrade")
    refund_purchase(first, TemporalValue.parse("2021-04-01"))

    _undo(logged_in, token)

    assert _facts(first)[0] == "upgrade"
    assert _facts(second)[0] == "season_pass"


def test_a_price_edit_and_its_undo_request_revaluations(logged_in, first, monkeypatch):
    requested = []
    monkeypatch.setattr(
        revaluation, "request_revaluation", lambda library: requested.append(library)
    )

    token = _edit(logged_in, first, price="paid", amount="5", currency="EUR")
    _undo(logged_in, token)

    assert requested == [first.library, first.library]


def test_an_undo_puts_the_days_note_back(logged_in, owned_user, copy):
    purchase = record_purchase(
        copy, purchased=TemporalValue.parse("2021-03-01"), purchase_note="receipt"
    )
    token = _edit(logged_in, purchase, purchased="2020-05-04")
    purchase.refresh_from_db()
    restate_purchase(
        owned_user,
        purchase,
        purchased=ActStatement(purchase.purchased, "later"),
        correlation_id=uuid.uuid7(),
    )

    _undo(logged_in, token)

    purchase.refresh_from_db()
    assert purchase.purchased == TemporalValue.parse("2021-03-01")
    assert purchase.purchase_note == "receipt"


def test_an_undo_restores_an_undated_day(logged_in, second):
    token = _edit(logged_in, second, purchased="2020-05-04")

    _undo(logged_in, token)

    assert _facts(second)[3] is None


def test_an_unreadable_fact_names_keys_not_text(owned_library):
    event = LibraryEvent(
        pk=1,
        library_id=owned_library.pk,
        sequence=7,
        event_type=PURCHASE_CREATED.event_type,
        payload={"price": "free", "note": "private words"},
    )

    with pytest.raises(RowUnreadable) as unreadable:
        _value(_PRICE, event)

    assert "price" in str(unreadable.value)
    assert "private words" not in str(unreadable.value)


def test_the_api_refuses_a_kind_change_under_a_refund(logged_in, first):
    refund_purchase(first, TemporalValue.parse("2021-04-01"))

    response = logged_in.patch(
        f"/api/purchases/{first.pk}",
        data={"kind": "upgrade"},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert KIND_UNDER_A_REFUND in response.text


def test_a_refunded_purchase_keeps_its_kind_and_the_batch_goes_on(
    logged_in, first, second
):
    refund_purchase(first, TemporalValue.parse("2021-04-01"))

    _edit(logged_in, first, second, kind="upgrade")

    assert _facts(first)[0] == "game"
    assert _facts(second)[0] == "upgrade"


# ── The reader ──────────────────────────────────────────────────────────────


def test_the_reader_reads_the_creation_for_each_fact(owned_user, owned_library, copy):
    purchase = record_purchase(
        copy,
        purchased=TemporalValue.parse("2021-03-01"),
        purchase_note="receipt",
        note="first",
    )
    batch = new_correlation_id()
    restate_purchase(
        owned_user,
        purchase,
        kind="upgrade",
        price=UNKNOWN_PRICE,
        note="second",
        purchased=ActStatement(TemporalValue.parse("2020-05-04"), "receipt"),
        correlation_id=batch,
    )

    changes = purchase_fact_changes(owned_library, purchase.pk, batch)

    assert changes.kind == FactChange(PurchaseKind.GAME, PurchaseKind.UPGRADE)
    assert changes.price == FactChange(
        StatedPrice(Decimal("19.99"), "EUR"), UNKNOWN_PRICE
    )
    assert changes.purchased == FactChange(
        ActStatement(TemporalValue.parse("2021-03-01"), "receipt"),
        ActStatement(TemporalValue.parse("2020-05-04"), "receipt"),
    )
    assert changes.note == FactChange("first", "second")


# ── The lists ───────────────────────────────────────────────────────────────


def test_the_purchases_list_carries_the_selection(logged_in, first):
    html = logged_in.get(reverse("games:list_purchases")).content.decode()

    assert "selectable-table" in html
    assert f'id="purchase-row-{first.pk}"' in html
    assert act_url(PURCHASE_EDIT) in html
    assert act_url(REMOVE_PURCHASE) in html


def _purchases_cell(client, copy) -> str:
    html = client.get(reverse("games:list_library")).content.decode()
    (row,) = re.findall(
        rf'<tr[^>]*data-selection-key="{copy.pk}".*?</tr>', html, re.DOTALL
    )
    return row


def test_the_library_tab_lists_each_purchase_price(logged_in, copy, first):
    record_purchase(copy, kind="season_pass", amount=Decimal("9.99"))
    record_purchase(copy, name="Deluxe", amount=None)
    refunded = record_purchase(copy, amount=Decimal(0))
    refund_purchase(refunded, TemporalValue.parse("2021-04-01"))

    row = _purchases_cell(logged_in, copy)

    #: Unvalued: EUR against the seeded CZK target.
    assert row.count("No CZK valuation") == 2
    assert ">19.99 EUR<" in row
    assert "Season pass · <pop-over" in row
    assert ">9.99 EUR<" in row
    assert "Deluxe · <span>Unknown price</span>" in row
    #: Refunded too: Access ended says so.
    assert "<span>Free</span>" in row


def test_a_copy_without_purchases_has_an_empty_cell(logged_in, copy):
    row = _purchases_cell(logged_in, copy)

    assert "EUR" not in row
