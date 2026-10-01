"""The purchase pages, one-click refund and Undo."""

import datetime
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from calendar_days import displace_calendar
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry
from purchases import record_purchase, refund_purchase, remove_purchase

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.purchase import REFUND_OVERTAKEN
from games.end_ways import EndWay
from games.models import Game, LibraryEvent, Purchase, UserPreferences
from games.purchase_forms import PurchaseAddForm, PurchaseEditForm
from games.reads.calendar import calendar_today
from games.views.purchase import ALREADY_REFUNDED
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"
OTHER_SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000002"
PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
JUNE = TemporalValue.parse("2021-06-03")


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


@pytest.fixture
def purchase(entry):
    return record_purchase(entry, purchased=TemporalValue.parse("2021-05-01"))


def _types(aggregate_id) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=aggregate_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def _page(client, response) -> str:
    return client.get(response["Location"]).content.decode()


# --- Add purchase -------------------------------------------------------------


def _add_post(**changes) -> dict[str, str]:
    return {
        "kind": "season_pass",
        "name": "Year one",
        "price": "paid",
        "amount": "9.99",
        "currency": "EUR",
        "note": "",
        "submission": SUBMISSION,
        **_day("purchased", datetime.date(2021, 6, 3)),
    } | changes


def test_add_states_a_purchase_of_the_copy_once(logged_in, entry, graph):
    url = reverse("games:add_purchase", args=[entry.pk])

    for _ in range(2):
        response = logged_in.post(url, _add_post())

    assert response.status_code == 302
    assert response["Location"] == graph.game.get_absolute_url()
    purchase = Purchase.objects.get(entry=entry)
    assert (purchase.kind, purchase.name, purchase.amount, purchase.currency) == (
        "season_pass",
        "Year one",
        Decimal("9.99"),
        "EUR",
    )
    assert purchase.purchased == JUNE


def test_add_offers_today_on_the_library_calendar(owned_library, entry):
    displace_calendar(owned_library)

    form = PurchaseAddForm(
        library=owned_library,
        presentation=PRESENTATION,
        today=calendar_today(owned_library),
    )

    assert form.fields["purchased"].initial == TemporalValue.from_day(
        calendar_today(owned_library)
    )


def test_add_answers_a_command_refusal_on_the_page(logged_in, entry):
    response = logged_in.post(
        reverse("games:add_purchase", args=[entry.pk]), _add_post(amount="-1")
    )

    assert response.status_code == 409
    assert not Purchase.objects.exists()


# --- Edit purchase ------------------------------------------------------------


def _edit_post(purchase: Purchase, **changes) -> dict[str, str]:
    form = PurchaseEditForm(purchase=purchase, presentation=PRESENTATION)
    return {
        "kind": purchase.kind,
        "name": purchase.name,
        "price": form["price"].value(),
        "amount": form["amount"].value(),
        "currency": purchase.currency,
        "note": purchase.note,
        "refund": form["refund"].value(),
        "refund_note": form["refund_note"].value(),
        "refund_seen": form["refund_seen"].value(),
        **_day("purchased", datetime.date(2021, 5, 1)),
        temporal_input_name("refunded", "kind"): "unknown",
    } | changes


def test_edit_states_each_changed_fact(logged_in, purchase):
    response = logged_in.post(
        reverse("games:edit_purchase", args=[purchase.pk]),
        _edit_post(purchase, name="Deluxe", price="free", note="gift"),
    )

    assert response.status_code == 302
    purchase.refresh_from_db()
    assert (purchase.name, purchase.amount, purchase.note) == (
        "Deluxe",
        Decimal(0),
        "gift",
    )
    assert "library.purchase.corrected" not in _types(purchase.pk)


def test_edit_states_a_refund_and_not_refunded_voids_it(logged_in, purchase):
    url = reverse("games:edit_purchase", args=[purchase.pk])
    logged_in.post(
        url,
        _edit_post(
            purchase, refund="refunded", **_day("refunded", datetime.date(2021, 6, 3))
        ),
    )
    purchase.refresh_from_db()
    assert purchase.refunded == JUNE

    logged_in.post(url, _edit_post(purchase, refund="not_refunded"))

    purchase.refresh_from_db()
    assert purchase.refund_recorded_at is None


def test_edit_refuses_a_refund_changed_since_the_page_opened(logged_in, purchase):
    stale = _edit_post(purchase, refund="refunded")
    refund_purchase(purchase, JUNE, "store")

    response = logged_in.post(reverse("games:edit_purchase", args=[purchase.pk]), stale)

    assert response.status_code == 200
    assert "changed since you opened this page" in response.content.decode()
    purchase.refresh_from_db()
    assert purchase.refund_note == "store"


# --- Remove, restore ----------------------------------------------------------


def test_remove_confirms_names_the_purchase_and_offers_undo(logged_in, purchase):
    url = reverse("games:remove_purchase", args=[purchase.pk])

    page = logged_in.get(url).content.decode()
    response = logged_in.post(url)

    assert "Bought · " in page
    purchase.refresh_from_db()
    assert purchase.removed_at is not None
    restore = reverse("games:restore_purchase", args=[purchase.pk])
    assert restore in _page(logged_in, response)

    logged_in.post(restore)

    purchase.refresh_from_db()
    assert purchase.removed_at is None


# --- Refund now, Undo -------------------------------------------------------


def _refund_now(client, purchase, token=SUBMISSION):
    return client.post(
        reverse("games:refund_purchase_now", args=[purchase.pk])
        + "?origin=/tracker/game/library",
        {"submission": token},
    )


def _offered_undo(client, response) -> str:
    match = re.search(
        r"/tracker/purchase/[0-9a-f-]+/refund/undo/\d+", _page(client, response)
    )
    assert match is not None
    return match.group(0)


def test_refund_now_states_today_and_ends_the_copy(logged_in, owned_library, purchase):
    displace_calendar(owned_library)

    for _ in range(2):
        response = _refund_now(logged_in, purchase)

    assert response.status_code == 302
    purchase.refresh_from_db()
    assert purchase.refunded == TemporalValue.from_day(calendar_today(owned_library))
    assert purchase.entry.access_end_way == "refunded"
    assert _types(purchase.pk).count("library.purchase.refunded") == 1


def test_the_refund_s_undo_voids_it_and_takes_the_end_back(logged_in, purchase):
    undo = _offered_undo(logged_in, _refund_now(logged_in, purchase))

    logged_in.post(undo)

    purchase.refresh_from_db()
    assert purchase.refund_recorded_at is None
    assert purchase.entry.access_end_recorded_at is None


def test_an_overtaken_undo_changes_nothing(logged_in, purchase):
    undo = _offered_undo(logged_in, _refund_now(logged_in, purchase))
    purchase.refresh_from_db()
    logged_in.post(
        reverse("games:edit_purchase", args=[purchase.pk]),
        _edit_post(
            purchase, refund="refunded", **_day("refunded", datetime.date(2021, 6, 3))
        ),
    )
    events = _types(purchase.pk)

    response = logged_in.post(undo)

    assert _types(purchase.pk) == events
    assert REFUND_OVERTAKEN in _page(logged_in, response)


def test_a_refunded_purchase_refuses_another_press(logged_in, purchase):
    refund_purchase(purchase, JUNE)

    response = _refund_now(logged_in, purchase)

    assert "/refund/undo/" not in _page(logged_in, response)
    purchase.refresh_from_db()
    assert purchase.refunded == JUNE


def test_a_press_without_its_key_is_malformed(logged_in, purchase):
    response = logged_in.post(reverse("games:refund_purchase_now", args=[purchase.pk]))

    assert response.status_code == 400
    assert "library.purchase.refunded" not in _types(purchase.pk)


# --- Scope -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "args"),
    [
        ("games:edit_purchase", ()),
        ("games:remove_purchase", ()),
        ("games:restore_purchase", ()),
        ("games:refund_purchase_now", ()),
        ("games:undo_purchase_refund", (1,)),
    ],
)
def test_another_librarys_purchase_is_absent(
    client, django_user_model, purchase, route, args
):
    client.force_login(django_user_model.objects.create_user(username="stranger"))
    before = _types(purchase.pk)

    response = client.post(
        reverse(route, args=[purchase.pk, *args]), {"submission": SUBMISSION}
    )

    assert response.status_code == 404
    assert _types(purchase.pk) == before


def test_a_removed_purchase_has_no_edit_page(logged_in, purchase):
    remove_purchase(purchase)

    assert (
        logged_in.get(reverse("games:edit_purchase", args=[purchase.pk])).status_code
        == 404
    )


# --- Menus --------------------------------------------------------------------


def test_the_purchases_list_rows_carry_their_menu(logged_in, purchase, entry):
    refunded = refund_purchase(
        record_purchase(entry, kind="upgrade", name="Deluxe"), JUNE
    )

    html = logged_in.get(reverse("games:list_purchases")).content.decode()

    assert f'id="purchase-menu-{purchase.pk}"' in html
    assert f"{reverse('games:edit_purchase', args=[purchase.pk])}?" in html
    assert reverse("games:refund_purchase_now", args=[purchase.pk]) in html
    assert f'id="purchase-menu-{refunded.pk}"' in html
    assert reverse("games:refund_purchase_now", args=[refunded.pk]) not in html


def test_the_library_tab_names_each_copys_purchase(logged_in, purchase, entry):
    html = logged_in.get(reverse("games:list_library")).content.decode()

    assert f'id="entry-menu-{entry.pk}-purchase-{purchase.pk}"' in html
    assert f"{reverse('games:add_purchase', args=[entry.pk])}?" in html


# --- Review follow-ups ----------------------------------------------------------


def test_a_stale_edit_keeps_a_refund_made_meanwhile(logged_in, purchase, entry):
    stale = _edit_post(purchase, name="Renamed")
    _refund_now(logged_in, purchase)

    response = logged_in.post(reverse("games:edit_purchase", args=[purchase.pk]), stale)

    assert response.status_code == 302
    purchase.refresh_from_db()
    entry.refresh_from_db()
    assert purchase.name == "Renamed"
    assert purchase.refund_recorded_at is not None
    assert entry.access_end_way == "refunded"
    assert "library.purchase.refund_voided" not in _types(purchase.pk)


def test_the_refund_toast_names_the_copys_end(logged_in, purchase):
    page = _page(logged_in, _refund_now(logged_in, purchase))

    assert "Refunded; the copy is marked as no longer yours." in page


def test_a_second_undo_changes_nothing(logged_in, purchase):
    undo = _offered_undo(logged_in, _refund_now(logged_in, purchase))
    logged_in.post(undo)
    events = _types(purchase.pk)

    response = logged_in.post(undo)

    assert _types(purchase.pk) == events
    assert REFUND_OVERTAKEN in _page(logged_in, response)


def test_a_season_pass_refund_leaves_the_copy(logged_in, entry):
    pass_purchase = record_purchase(entry, kind="season_pass", name="Pass")

    undo = _offered_undo(logged_in, _refund_now(logged_in, pass_purchase))
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None
    logged_in.post(undo)

    pass_purchase.refresh_from_db()
    assert pass_purchase.refund_recorded_at is None


def test_undo_on_an_ended_copy_leaves_its_end(logged_in, purchase, entry):
    end_entry_access(entry, way=EndWay.SOLD)

    undo = _offered_undo(logged_in, _refund_now(logged_in, purchase))
    logged_in.post(undo)

    entry.refresh_from_db()
    purchase.refresh_from_db()
    assert purchase.refund_recorded_at is None
    assert entry.access_end_way == "sold"


def test_an_identical_refund_press_says_already_refunded(
    logged_in, owned_library, purchase
):
    refund_purchase(purchase, TemporalValue.from_day(calendar_today(owned_library)))

    response = _refund_now(logged_in, purchase, token=OTHER_SUBMISSION)

    assert ALREADY_REFUNDED in _page(logged_in, response)


def test_add_purchase_on_a_foreign_or_removed_copy_is_absent(
    logged_in, django_user_model, stated_graph, entry
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    graph = stated_graph(Game(name="Hades", library=stranger), stranger)
    foreign = record_entry(stranger, graph.release)
    removed = remove_entry(record_entry(entry.library, entry.release))
    before = LibraryEvent.objects.count()

    for copy in (foreign, removed):
        url = reverse("games:add_purchase", args=[copy.pk])
        assert logged_in.get(url).status_code == 404
        assert logged_in.post(url, _add_post()).status_code == 404

    assert LibraryEvent.objects.count() == before


def test_add_purchase_refuses_no_purchase(logged_in, entry):
    response = logged_in.post(
        reverse("games:add_purchase", args=[entry.pk]), _add_post(price="none")
    )

    assert response.status_code == 200
    assert not Purchase.objects.exists()


def test_edit_shows_the_stored_currency_not_the_default(owned_library, entry):
    UserPreferences.objects.filter(user=owned_library.user).update(
        default_purchase_currency="CZK"
    )
    paid = record_purchase(entry, amount=Decimal("19.99"), currency="EUR")
    unknown = record_purchase(entry, amount=None)

    assert (
        PurchaseEditForm(purchase=paid, presentation=PRESENTATION)["currency"].value()
        == "EUR"
    )
    assert (
        PurchaseEditForm(purchase=unknown, presentation=PRESENTATION)[
            "currency"
        ].value()
        == "CZK"
    )


def test_an_unchanged_edit_appends_nothing(logged_in, purchase):
    events = _types(purchase.pk)

    logged_in.post(
        reverse("games:edit_purchase", args=[purchase.pk]), _edit_post(purchase)
    )

    assert _types(purchase.pk) == events


def test_paid_to_unknown_clears_amount_and_currency(logged_in, purchase):
    response = logged_in.post(
        reverse("games:edit_purchase", args=[purchase.pk]),
        _edit_post(purchase, price="unknown"),
    )

    assert response.status_code == 302
    purchase.refresh_from_db()
    assert (purchase.amount, purchase.currency) == (None, "")


def test_edit_answers_a_command_refusal_on_the_page(logged_in, purchase):
    events = _types(purchase.pk)

    response = logged_in.post(
        reverse("games:edit_purchase", args=[purchase.pk]),
        _edit_post(
            purchase, refund="refunded", **_day("refunded", datetime.date(2020, 1, 1))
        ),
    )

    assert response.status_code == 409
    assert _types(purchase.pk) == events


def test_a_copy_removed_alone_and_undone_brings_its_purchase(
    logged_in, purchase, entry
):
    logged_in.post(reverse("games:remove_library_entry", args=[entry.pk]))
    purchase.refresh_from_db()
    assert purchase.removed_at is not None

    logged_in.post(reverse("games:restore_library_entry", args=[entry.pk]))

    purchase.refresh_from_db()
    assert purchase.removed_at is None


def test_the_library_tab_omits_refunded_purchases(logged_in, entry):
    refunded = refund_purchase(
        record_purchase(entry, kind="upgrade", name="Deluxe"), JUNE
    )

    html = logged_in.get(reverse("games:list_library")).content.decode()

    assert f"purchase-{refunded.pk}" not in html
