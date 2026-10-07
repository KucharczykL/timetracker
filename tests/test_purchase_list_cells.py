"""The Purchases list's Name and Amount cells."""

from decimal import Decimal

import pytest
from entries import record_entry
from purchases import record_purchase, request_run

from common.components import PurchaseAmount, PurchaseName
from games import tasks
from games.models import ExchangeRate, Game, Purchase
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _listed(purchase) -> Purchase:
    return Purchase.objects.annotated_for_filtering(purchase.library).get(
        pk=purchase.pk
    )


def test_a_game_purchase_names_the_game(entry):
    assert ">Tunic<" in str(PurchaseName(record_purchase(entry)))


def test_a_named_product_leads(entry):
    purchase = record_purchase(entry, kind="season_pass", name="Pass")

    assert "Pass · Tunic" in str(PurchaseName(purchase))


@pytest.mark.parametrize(("amount", "words"), [(None, "Unknown"), (Decimal(0), "Free")])
def test_an_unknown_or_free_amount_says_so(entry, amount, words):
    assert words in str(PurchaseAmount(_listed(record_purchase(entry, amount=amount))))


def _visible(cell: str) -> str:
    """The trigger, which renders before the panel."""
    return cell.split("data-pop-over-panel")[0]


def _panel(cell: str) -> str:
    """The popover panel."""
    return cell.split("data-pop-over-panel")[1]


def test_a_valuation_in_the_same_currency_is_the_amount_alone(entry, owned_library):
    purchase = record_purchase(entry, amount=Decimal("12.50"), currency="EUR")
    tasks.convert_library_prices(
        str(owned_library.pk), request_run(owned_library, "EUR")
    )

    cell = str(PurchaseAmount(_listed(purchase)))

    assert "12.50 EUR" in cell
    assert cell.count("EUR") == 1
    assert "<pop-over" not in cell


def test_a_display_currency_purchase_not_valued_yet_is_the_amount_alone(entry):
    cell = str(
        PurchaseAmount(
            _listed(record_purchase(entry, amount=Decimal(5), currency="CZK"))
        )
    )

    assert "5.00 CZK" in cell
    assert "<pop-over" not in cell


@pytest.fixture
def foreign(entry):
    ExchangeRate.objects.update_or_create(
        currency_from="USD",
        currency_to="EUR",
        year=2021,
        defaults={"rate": Decimal("0.5")},
    )
    return record_purchase(
        entry,
        amount=Decimal(10),
        currency="USD",
        purchased=TemporalValue.parse("2021-03-01"),
    )


def _value_in_eur(library) -> None:
    tasks.convert_library_prices(str(library.pk), request_run(library, "EUR"))


def test_a_foreign_purchase_shows_its_valuation(foreign, owned_library):
    _value_in_eur(owned_library)

    cell = str(PurchaseAmount(_listed(foreign)))

    assert "5.00 EUR" in _visible(cell)
    assert "USD" not in _visible(cell)
    assert "Price" in _panel(cell)
    assert "10.00 USD" in _panel(cell)
    assert f'id="purchase-amount-{foreign.pk}"' in cell


def test_a_purchase_without_a_valuation_says_so(foreign):
    cell = str(PurchaseAmount(_listed(foreign)))

    assert "10.00 USD" in _visible(cell)
    #: The seeded target is the display currency.
    assert "No CZK valuation" in _panel(cell)
    assert f'id="purchase-amount-{foreign.pk}"' in cell
    assert "decoration-dotted" not in cell


def test_a_purchase_without_a_rate_says_so_after_a_run(
    entry, owned_library, monkeypatch
):
    monkeypatch.setattr(tasks, "exchange_rate", lambda *_: None)
    purchase = record_purchase(
        entry,
        amount=Decimal(3),
        currency="EUO",
        purchased=TemporalValue.parse("2021-03-01"),
    )
    _value_in_eur(owned_library)

    cell = str(PurchaseAmount(_listed(purchase)))

    assert "3.00 EUO" in _visible(cell)
    assert "No EUR valuation" in _panel(cell)


def test_a_changed_amount_drops_the_old_valuation(foreign, owned_library):
    _value_in_eur(owned_library)
    Purchase.objects.filter(pk=foreign.pk).update(amount=Decimal(11))

    cell = str(PurchaseAmount(_listed(foreign)))

    assert "11.00 USD" in _visible(cell)
    assert "5.00 EUR" not in cell
    assert "No EUR valuation" in _panel(cell)


def test_a_requested_currency_shows_the_published_one_until_it_runs(
    foreign, entry, owned_library
):
    _value_in_eur(owned_library)
    euros = record_purchase(entry, amount=Decimal(7), currency="EUR")
    request_run(owned_library, "CZK")

    assert "5.00 EUR" in _visible(str(PurchaseAmount(_listed(foreign))))
    assert "<pop-over" not in str(PurchaseAmount(_listed(euros)))


def test_an_amount_without_its_valuation_is_refused(entry):
    purchase = record_purchase(entry, amount=Decimal(5), currency="EUR")

    with pytest.raises(ValueError, match="annotated_for_filtering"):
        PurchaseAmount(Purchase.objects.get(pk=purchase.pk))


def test_a_row_without_its_list_annotations_is_refused(entry):
    from games.views.purchase import _purchase_cells

    purchase = record_purchase(entry)

    with pytest.raises(ValueError, match="purchase_list_rows"):
        _purchase_cells(purchase, presentation=None)


# ── The list ────────────────────────────────────────────────────────────────


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


def _headers(body: str) -> list[str]:
    import re

    [head] = re.findall(r"<thead.*?</thead>", body, re.DOTALL)
    head = re.sub(r"<form .*?</form>", "", head, flags=re.DOTALL)
    return [
        re.sub(r"<[^>]+>", "", cell).strip()
        for cell in re.findall(r"<th.*?</th>", head, re.DOTALL)
    ]


def test_the_list_has_no_actions_column(logged_client, entry):
    from django.urls import reverse

    record_purchase(entry)

    headers = _headers(
        logged_client.get(reverse("games:list_purchases")).content.decode()
    )

    assert "Actions" not in headers
    #: A sorted header carries its rank.
    assert [header.rstrip("0123456789") for header in headers[:4]] == [
        "Name",
        "Kind",
        "Amount",
        "Purchased",
    ]


def test_a_stored_choice_naming_a_gone_column_reads_as_the_default(
    logged_client, owned_user, entry
):
    from django.urls import reverse

    from games.models import ListColumnChoice

    record_purchase(entry)
    ListColumnChoice.objects.create(
        user=owned_user, mode="purchases", shown={"price": True, "infinite": True}
    )

    response = logged_client.get(reverse("games:list_purchases"))

    assert response.status_code == 200
    headers = _headers(response.content.decode())
    assert "Price" not in headers
    assert "Infinite" not in headers
    assert "Amount" in headers
