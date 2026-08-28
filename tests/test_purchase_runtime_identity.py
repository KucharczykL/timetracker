from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from games.models import Game, Purchase

#: Transactional, because a refund dispatches a command and
#: run_in_transaction refuses to open a transaction inside the rolled-back one
#: pytest-django wraps a test in.
pytestmark = pytest.mark.django_db(transaction=True)

ROUTE_UUID = UUID("018f5e66-e800-7000-8000-000000000001")
UUID4 = UUID("018f5e66-e800-4000-8000-000000000001")

PURCHASE_IDENTITY_ROUTES = [
    ("games:edit_purchase", "purchase_id"),
    ("games:delete_purchase", "purchase_id"),
    ("games:view_purchase", "purchase_id"),
    ("games:refund_purchase_confirmation", "purchase_id"),
    ("games:refund_purchase", "purchase_id"),
    ("games:split_purchase_confirmation", "purchase_id"),
    ("games:split_purchase", "purchase_id"),
]


@pytest.mark.parametrize(("route_name", "parameter"), PURCHASE_IDENTITY_ROUTES)
def test_purchase_identity_routes_reverse_and_resolve_uuidv7(route_name, parameter):
    """Changing a Purchase route back to an integer converter breaks UUID paths."""
    url = reverse(route_name, kwargs={parameter: ROUTE_UUID})

    match = resolve(url)

    assert match.view_name == route_name
    assert match.kwargs == {parameter: ROUTE_UUID}


@pytest.mark.parametrize(("route_name", "parameter"), PURCHASE_IDENTITY_ROUTES)
@pytest.mark.parametrize(
    "invalid_id", [pytest.param(1, id="integer"), pytest.param(UUID4, id="uuid4")]
)
def test_purchase_identity_routes_reject_non_uuidv7_ids(
    route_name, parameter, invalid_id
):
    """Changing a converter to accept integers or UUIDv4 leaks non-Purchase IDs."""
    with pytest.raises(NoReverseMatch):
        reverse(route_name, kwargs={parameter: invalid_id})

    valid_url = reverse(route_name, kwargs={parameter: ROUTE_UUID})
    invalid_url = valid_url.replace(str(ROUTE_UUID), str(invalid_id))
    with pytest.raises(Resolver404):
        resolve(invalid_url)


@pytest.fixture
def runtime_world(db):
    owner = get_user_model().objects.create_user(username="purchase-runtime-owner")
    foreign_user = get_user_model().objects.create_user(
        username="purchase-runtime-foreign"
    )
    client = Client()
    client.force_login(owner)

    own_game_one = Game.objects.create(
        library=owner.library, name="Owned runtime game one"
    )
    own_game_two = Game.objects.create(
        library=owner.library, name="Owned runtime game two"
    )
    foreign_game = Game.objects.create(
        library=foreign_user.library, name="Foreign runtime game"
    )
    own_purchase = Purchase.objects.create(
        library=owner.library,
        name="Owned runtime purchase",
        date_purchased=date(2026, 8, 20),
        price=10,
        price_currency="USD",
    )
    own_purchase.games.set([own_game_one, own_game_two])
    foreign_purchase = Purchase.objects.create(
        library=foreign_user.library,
        name="Foreign runtime purchase",
        date_purchased=date(2026, 8, 20),
        price=20,
        price_currency="USD",
    )
    foreign_purchase.games.add(foreign_game)
    return SimpleNamespace(**locals())


@pytest.mark.parametrize(
    ("method", "route_name", "expected_status"),
    [
        ("get", "games:edit_purchase", 200),
        ("get", "games:delete_purchase", 200),
        ("get", "games:view_purchase", 200),
        ("get", "games:refund_purchase_confirmation", 200),
        ("post", "games:refund_purchase", 200),
        ("get", "games:split_purchase_confirmation", 200),
        ("post", "games:split_purchase", 204),
    ],
)
def test_purchase_identity_routes_accept_owned_uuidv7s(
    runtime_world, method, route_name, expected_status
):
    """Changing a route lookup or converter prevents an owner using its Purchase."""
    response = getattr(runtime_world.client, method)(
        reverse(route_name, args=[runtime_world.own_purchase.pk])
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("method", "route_name"),
    [
        ("get", "games:edit_purchase"),
        ("get", "games:delete_purchase"),
        ("get", "games:view_purchase"),
        ("get", "games:refund_purchase_confirmation"),
        ("post", "games:refund_purchase"),
        ("get", "games:split_purchase_confirmation"),
        ("post", "games:split_purchase"),
    ],
)
def test_purchase_identity_routes_hide_foreign_uuidv7s(
    runtime_world, method, route_name
):
    """Removing the library-scoped Purchase lookup reveals another library's UUID."""
    foreign_purchase = runtime_world.foreign_purchase
    before_count = Purchase.objects.count()

    response = getattr(runtime_world.client, method)(
        reverse(route_name, args=[foreign_purchase.pk])
    )

    foreign_purchase.refresh_from_db()
    assert response.status_code == 404
    assert Purchase.objects.count() == before_count
    assert foreign_purchase.date_refunded is None
