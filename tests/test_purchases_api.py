"""The `/api/purchases/` routes."""

import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from entries import record_entry
from purchases import record_purchase, remove_purchase

from games.commands.purchase import (
    ENTRY_OF_ANOTHER_GAME,
    TOO_LARGE_AMOUNT,
    TOO_PRECISE_AMOUNT,
)
from games.models import Game, Purchase
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def library(user):
    return user.library


@pytest.fixture
def graph(library, stated_graph):
    return stated_graph(Game(name="Tunic", library=library), library)


@pytest.fixture
def entry(library, graph):
    return record_entry(library, graph.release)


def _post(client: Client, body: dict, **headers):
    return client.post(
        "/api/purchases/", json.dumps(body), content_type="application/json", **headers
    )


def _patch(client: Client, purchase_id, body: dict):
    return client.patch(
        f"/api/purchases/{purchase_id}",
        json.dumps(body),
        content_type="application/json",
    )


def _body(held, **changes) -> dict:
    return {
        "entry_id": str(held.pk),
        "kind": "game",
        "amount": "12.5",
        "currency": "eur",
    } | changes


def test_post_records_and_answers_the_row(auth_client, entry):
    response = _post(
        auth_client, _body(entry, purchased="2021-05", purchase_note="sale")
    )

    assert response.status_code == 201, response.content
    row = response.json()
    assert (row["amount"], row["currency"]) == ("12.50", "EUR")
    assert (row["game"], row["entry_id"]) == ("Tunic", str(entry.pk))
    assert (row["purchased"], row["purchase_note"]) == ("2021-05", "sale")
    assert Purchase.objects.get(pk=row["id"]).amount == Decimal("12.50")


def test_post_with_a_new_copy_tracks_the_game(auth_client, graph):
    body = {
        "entry": {
            "release_id": str(graph.release.pk),
            "access": "owned",
            "format": "digital",
        },
        "kind": "game",
        "amount": 0,
        "currency": "USD",
    }

    response = _post(auth_client, body)

    assert response.status_code == 201, response.content
    assert response.json()["amount"] == "0.00"


@pytest.mark.parametrize(
    "changes",
    (
        {"colour": "black"},
        {"kind": "loot_box"},
        {"amount": "NaN"},
        {"entry": {"release_id": "x"}},
        {"entry_id": None},
    ),
)
def test_post_refuses_a_malformed_body(auth_client, entry, changes):
    assert _post(auth_client, _body(entry, **changes)).status_code == 422


def test_post_answers_the_price_rule_at_409(auth_client, entry):
    response = _post(auth_client, _body(entry, amount="12.345"))

    assert response.status_code == 409
    assert TOO_PRECISE_AMOUNT in response.content.decode()


def test_post_naming_another_librarys_copy_is_404(
    auth_client, django_user_model, stated_graph
):
    other = django_user_model.objects.create_user(username="other").library
    theirs = stated_graph(Game(name="Hades", library=other), other)
    their_entry = record_entry(other, theirs.release)

    assert _post(auth_client, _body(their_entry)).status_code == 404


def test_a_repeated_key_records_once(auth_client, entry):
    first = _post(auth_client, _body(entry), HTTP_IDEMPOTENCY_KEY="k1")
    again = _post(auth_client, _body(entry), HTTP_IDEMPOTENCY_KEY="k1")

    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert Purchase.objects.count() == 1


def test_get_lists_and_reads_one(auth_client, entry):
    purchase = record_purchase(entry)

    listed = auth_client.get("/api/purchases/").json()
    one = auth_client.get(f"/api/purchases/{purchase.pk}")

    assert [row["id"] for row in listed] == [str(purchase.pk)]
    assert one.json()["amount"] == "19.99"


def test_another_librarys_purchase_is_404(auth_client, django_user_model, stated_graph):
    other = django_user_model.objects.create_user(username="other").library
    theirs = stated_graph(Game(name="Hades", library=other), other)
    purchase = record_purchase(record_entry(other, theirs.release))

    assert auth_client.get(f"/api/purchases/{purchase.pk}").status_code == 404
    assert _patch(auth_client, purchase.pk, {"name": "x"}).status_code == 404
    assert auth_client.get("/api/purchases/").json() == []


def test_patch_refuses_a_half_stated_day(auth_client, entry):
    purchase = record_purchase(entry)

    response = _patch(auth_client, purchase.pk, {"purchased": "2022"})

    assert response.status_code == 422


def test_patch_states_each_named_key(auth_client, entry):
    purchase = record_purchase(entry)

    response = _patch(
        auth_client,
        purchase.pk,
        {
            "name": "Deluxe",
            "amount": None,
            "currency": "",
            "purchased": "2022",
            "purchase_note": "",
        },
    )

    assert response.status_code == 200, response.content
    row = response.json()
    assert (row["name"], row["amount"], row["currency"]) == ("Deluxe", None, "")
    assert row["purchased"] == "2022"


def test_patch_states_an_unknown_day(auth_client, entry):
    purchase = record_purchase(entry, purchased=TemporalValue.parse("2021"))

    response = _patch(
        auth_client, purchase.pk, {"purchased": None, "purchase_note": "no receipt"}
    )

    assert response.status_code == 200, response.content
    assert (response.json()["purchased"], response.json()["purchase_note"]) == (
        None,
        "no receipt",
    )


def test_patch_moves_to_a_sibling_copy(auth_client, library, graph, entry):
    purchase = record_purchase(entry)
    sibling = record_entry(library, graph.release, format="physical")

    response = _patch(auth_client, purchase.pk, {"entry_id": str(sibling.pk)})

    assert response.status_code == 200, response.content
    assert response.json()["entry_id"] == str(sibling.pk)


def test_patch_onto_another_games_copy_is_409(
    auth_client, library, stated_graph, entry
):
    purchase = record_purchase(entry)
    elsewhere = stated_graph(Game(name="Hades", library=library), library)
    other = record_entry(library, elsewhere.release)

    response = _patch(auth_client, purchase.pk, {"entry_id": str(other.pk)})

    assert response.status_code == 409
    assert ENTRY_OF_ANOTHER_GAME in response.content.decode()


def test_patch_onto_another_librarys_copy_is_404(
    auth_client, django_user_model, stated_graph, entry
):
    purchase = record_purchase(entry)
    other = django_user_model.objects.create_user(username="other").library
    theirs = record_entry(
        other, stated_graph(Game(name="Hades", library=other), other).release
    )

    assert (
        _patch(auth_client, purchase.pk, {"entry_id": str(theirs.pk)}).status_code
        == 404
    )


def test_patch_on_a_removed_purchase_is_404(auth_client, entry):
    purchase = remove_purchase(record_purchase(entry))

    assert _patch(auth_client, purchase.pk, {"name": "x"}).status_code == 404


def test_a_huge_amount_is_409(auth_client, entry):
    response = _post(auth_client, _body(entry, amount="1e30"))

    assert response.status_code == 409
    assert TOO_LARGE_AMOUNT in response.content.decode()


def test_the_list_pages_in_recorded_order(auth_client, entry):
    purchases = [record_purchase(entry) for _ in range(3)]
    ids = [str(purchase.pk) for purchase in purchases]

    def listed(query: str) -> list[str]:
        return [row["id"] for row in auth_client.get(f"/api/purchases/{query}").json()]

    assert listed("?limit=2") == ids[:2]
    assert listed("?offset=2") == ids[2:]
    assert listed("?limit=0") == ids


def test_the_message_names_a_tracked_game(auth_client, library, graph, stated_graph):
    held = _post(auth_client, _body(record_entry(library, graph.release)))
    elsewhere = stated_graph(Game(name="Hades", library=library), library)
    tracking = _post(
        auth_client,
        {
            "entry": {
                "release_id": str(elsewhere.release.pk),
                "access": "owned",
                "format": "digital",
            },
            "kind": "game",
        },
    )

    assert "game added" not in held.headers.get("X-Events", "")
    assert "game added to your library" in tracking.headers.get("X-Events", "")


@pytest.mark.parametrize(
    "body",
    ({"amount": "1.00"}, {"currency": "EUR"}, {"purchase_note": "x"}, {"name": None}),
)
def test_patch_refuses_a_half_or_null_statement(auth_client, entry, body):
    purchase = record_purchase(entry)

    assert _patch(auth_client, purchase.pk, body).status_code == 422
