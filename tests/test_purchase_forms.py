"""The forms a purchase is stated with."""

import datetime
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from entries import record_entry
from purchases import record_purchase, refund_purchase

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.endpoint import ActStatement
from games.commands.purchase import UNKNOWN_PRICE, StatedPrice
from games.entry_forms import EntryAddForm
from games.models import Game, Purchase, UserPreferences
from games.price_fields import (
    AMOUNT_REQUIRED,
    AMOUNT_ROW,
    CURRENCY_REQUIRED,
    CURRENCY_ROW,
    NOT_AN_AMOUNT,
    PRICE_GROUP,
)
from games.purchase_forms import (
    REFUND_CHANGED_SINCE_OPENED,
    REFUND_GROUP,
    REFUNDED_ROW,
    PurchaseAddForm,
    PurchaseEditForm,
    refund_seen,
)
from games.writes.endpoint import KEEP
from games.writes.purchase import restate_purchase
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
TODAY = datetime.date(2026, 9, 29)
JUNE = TemporalValue.parse("2021-06-03")
JULY = TemporalValue.parse("2021-07-01")
SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


def _unknown_day(name: str) -> dict[str, str]:
    return {temporal_input_name(name, "kind"): "unknown"}


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


def _add(owned_library, **data) -> PurchaseAddForm:
    return PurchaseAddForm(
        {
            "kind": "game",
            "submission": SUBMISSION,
            **_day("purchased", datetime.date(2026, 9, 1)),
            **data,
        },
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
    )


@pytest.mark.parametrize(
    ("data", "price"),
    [
        (
            {"price": "paid", "amount": " 19.99 ", "currency": "eur"},
            StatedPrice(Decimal("19.99"), "EUR"),
        ),
        ({"price": "free", "currency": "CZK"}, StatedPrice(Decimal(0), "CZK")),
        ({"price": "unknown"}, UNKNOWN_PRICE),
    ],
    ids=["paid", "free", "unknown"],
)
def test_each_choice_states_its_price(owned_library, entry, data, price):
    form = _add(owned_library, **data)

    assert form.is_valid(), form.errors
    draft = form.draft(entry.pk)
    assert draft.price == price
    assert draft.copy == entry.pk
    assert draft.purchased == ActStatement(TemporalValue.parse("2026-09-01"), "")
    assert form.submission_key() == f"purchase-add-{SUBMISSION}"


@pytest.mark.parametrize(
    "data",
    [
        {"price": "free", "amount": "not a number", "currency": "EUR"},
        {"price": "unknown", "amount": "not a number", "currency": "TOOLONG"},
    ],
    ids=["free", "unknown"],
)
def test_a_hidden_row_holds_no_error(owned_library, data):
    assert _add(owned_library, **data).is_valid()


@pytest.mark.parametrize(
    ("data", "field", "sentence"),
    [
        ({"price": "paid", "amount": "", "currency": "EUR"}, "amount", AMOUNT_REQUIRED),
        (
            {"price": "paid", "amount": "abc", "currency": "EUR"},
            "amount",
            NOT_AN_AMOUNT,
        ),
        (
            {"price": "paid", "amount": "5", "currency": ""},
            "currency",
            CURRENCY_REQUIRED,
        ),
        ({"price": "free", "currency": " "}, "currency", CURRENCY_REQUIRED),
    ],
    ids=["paid-blank", "paid-text", "paid-no-currency", "free-no-currency"],
)
def test_a_shown_row_refuses(owned_library, data, field, sentence):
    form = _add(owned_library, **data)

    assert not form.is_valid()
    assert form.errors[field] == [sentence]


def test_the_currency_defaults_to_the_users_setting(owned_library):
    UserPreferences.objects.filter(user=owned_library.user).update(
        default_purchase_currency="CZK"
    )

    form = PurchaseAddForm(
        library=owned_library, presentation=PRESENTATION, today=TODAY
    )

    assert form["currency"].value() == "CZK"
    assert form["price"].value() == "paid"
    assert form.fields["purchased"].initial == TemporalValue.from_day(TODAY)


def test_add_offers_no_no_purchase(owned_library):
    form = PurchaseAddForm(
        library=owned_library, presentation=PRESENTATION, today=TODAY
    )

    assert [value for value, _ in form.fields["price"].choices] == [
        "paid",
        "free",
        "unknown",
    ]


# --- Add to library's purchase ----------------------------------------------


def _entry_add(owned_library, graph, **data) -> EntryAddForm:
    return EntryAddForm(
        {
            "release": str(graph.release.pk),
            "access": "owned",
            "format": "digital",
            "submission": SUBMISSION,
            **_day("acquired", datetime.date(2026, 9, 1)),
            **data,
        },
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
        facts={"game": str(graph.game.pk)},
    )


def test_add_to_library_offers_paid_free_and_none(owned_library, graph):
    form = EntryAddForm(
        library=owned_library,
        presentation=PRESENTATION,
        today=TODAY,
        facts={"game": str(graph.game.pk)},
    )

    assert [value for value, _ in form.fields["price"].choices] == [
        "paid",
        "free",
        "none",
    ]
    assert form["price"].value() == "paid"


def test_add_to_library_states_the_games_purchase_on_the_acquired_day(
    owned_library, graph
):
    form = _entry_add(owned_library, graph, price="paid", amount="30", currency="EUR")

    assert form.is_valid(), form.errors
    draft = form.purchase_draft()
    assert draft is not None
    assert draft.copy == form.draft()
    assert (draft.kind, draft.price) == ("game", StatedPrice(Decimal(30), "EUR"))
    assert draft.purchased == ActStatement(TemporalValue.parse("2026-09-01"), "")


def test_no_purchase_states_none_and_ignores_the_amount(owned_library, graph):
    form = _entry_add(owned_library, graph, price="none", amount="abc")

    assert form.is_valid(), form.errors
    assert form.purchase_draft() is None


def test_a_borrowed_copy_left_on_paid_is_refused(owned_library, graph):
    form = _entry_add(owned_library, graph, access="borrowed", price="paid")

    assert not form.is_valid()
    assert form.errors["amount"] == [AMOUNT_REQUIRED]


# --- Edit purchase ------------------------------------------------------------


def _edit_data(purchase: Purchase, **data) -> dict[str, str]:
    form = PurchaseEditForm(purchase=purchase, presentation=PRESENTATION)
    initial = {
        "kind": purchase.kind,
        "name": purchase.name,
        "price": form["price"].value(),
        "amount": form["amount"].value(),
        "currency": purchase.currency,
        "note": purchase.note,
        "refund": form["refund"].value(),
        "refund_note": form["refund_note"].value(),
        "refund_seen": form["refund_seen"].value(),
        **_unknown_day("purchased"),
        **_unknown_day("refunded"),
    }
    return initial | data


def refund_purchase_correction(purchase: Purchase, when) -> Purchase:
    restate_purchase(
        purchase.library.user,
        purchase,
        refund=ActStatement(when, ""),
        correlation_id=uuid.uuid7(),
    )
    purchase.refresh_from_db()
    return purchase


def _edit(purchase: Purchase, **data) -> PurchaseEditForm:
    return PurchaseEditForm(
        _edit_data(purchase, **data), purchase=purchase, presentation=PRESENTATION
    )


def test_edit_shows_the_purchase(entry):
    purchase = refund_purchase(record_purchase(entry, amount=Decimal(0)), JUNE, "store")

    form = PurchaseEditForm(purchase=purchase, presentation=PRESENTATION)

    assert form["price"].value() == "free"
    assert form["amount"].value() == ""
    assert form["refund"].value() == "refunded"
    assert form["refund_note"].value() == "store"
    assert form["refund_seen"].value() == refund_seen(purchase)


def test_not_refunded_keeps_where_no_refund_stands(entry):
    form = _edit(record_purchase(entry))

    assert form.is_valid(), form.errors
    assert form.refund_statement() is KEEP


def test_not_refunded_voids_a_standing_refund(entry):
    form = _edit(refund_purchase(record_purchase(entry), None), refund="not_refunded")

    assert form.is_valid(), form.errors
    assert form.refund_statement() is None


def test_an_unchanged_refund_keeps(entry):
    form = _edit(refund_purchase(record_purchase(entry), None, "store"))

    assert form.is_valid(), form.errors
    assert form.refund_statement() is KEEP


def test_refunded_states_the_day_and_note(entry):
    form = _edit(
        record_purchase(entry),
        refund="refunded",
        refund_note="store",
        **_day("refunded", datetime.date(2021, 6, 3)),
    )

    assert form.is_valid(), form.errors
    assert form.refund_statement() == ActStatement(JUNE, "store")


def test_a_refund_moved_since_refuses_only_a_changed_block(entry):
    purchase = record_purchase(entry)
    stale = _edit_data(purchase)
    changed_block = _edit_data(purchase, refund="refunded")
    refund_purchase(purchase, JUNE)

    untouched = PurchaseEditForm(stale, purchase=purchase, presentation=PRESENTATION)
    touched = PurchaseEditForm(
        changed_block, purchase=purchase, presentation=PRESENTATION
    )

    assert untouched.is_valid(), untouched.errors
    assert not touched.is_valid()
    assert touched.non_field_errors() == [REFUND_CHANGED_SINCE_OPENED]


def test_an_untouched_stale_block_keeps_the_newer_refund(entry):
    purchase = record_purchase(entry)
    stale = _edit_data(purchase, name="Renamed")
    purchase = refund_purchase(purchase, JUNE)

    form = PurchaseEditForm(stale, purchase=purchase, presentation=PRESENTATION)

    assert form.is_valid(), form.errors
    assert form.refund_statement() is KEEP


def test_an_untouched_stale_block_keeps_a_newer_correction(entry):
    purchase = refund_purchase(record_purchase(entry), JUNE)
    stale = _edit_data(purchase, **_day("refunded", datetime.date(2021, 6, 3)))
    purchase = refund_purchase_correction(purchase, JULY)

    form = PurchaseEditForm(stale, purchase=purchase, presentation=PRESENTATION)

    assert form.is_valid(), form.errors
    assert form.refund_statement() is KEEP


@pytest.mark.parametrize(
    ("group", "rows"),
    [
        (PRICE_GROUP, (AMOUNT_ROW, CURRENCY_ROW)),
        (REFUND_GROUP, (REFUNDED_ROW,)),
    ],
)
def test_each_row_rule_reads_its_group(group, rows):
    name = group.removeprefix("group")
    for row in rows:
        assert f"]{name}:block" in row


def test_the_refund_statement_is_read_after_validation(entry):
    form = PurchaseEditForm(
        _edit_data(record_purchase(entry)),
        purchase=entry.purchases.get(),
        presentation=PRESENTATION,
    )

    with pytest.raises(AttributeError):
        form.refund_statement()
