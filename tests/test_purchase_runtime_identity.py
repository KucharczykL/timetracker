from types import SimpleNamespace
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase

from games.models import Game, LibraryEvent

#: Transactional: a refund dispatches, and a dispatch cannot
#: nest in the transaction pytest-django rolls back.
pytestmark = pytest.mark.django_db(transaction=True)

ROUTE_UUID = UUID("018f5e66-e800-7000-8000-000000000001")
UUID4 = UUID("018f5e66-e800-4000-8000-000000000001")
SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"

#: Each route, and arguments beside the key.
PURCHASE_IDENTITY_ROUTES = [
    ("games:edit_purchase", {}),
    ("games:remove_purchase", {}),
    ("games:restore_purchase", {}),
    ("games:refund_purchase_now", {}),
    ("games:undo_purchase_refund", {"sequence": 1}),
]


@pytest.mark.parametrize(("route_name", "extra"), PURCHASE_IDENTITY_ROUTES)
def test_purchase_identity_routes_reverse_and_resolve_uuidv7(route_name, extra):
    """Changing a Purchase route back to an integer converter breaks UUID paths."""
    url = reverse(route_name, kwargs={"purchase_id": ROUTE_UUID, **extra})

    match = resolve(url)

    assert match.view_name == route_name
    assert match.kwargs == {"purchase_id": ROUTE_UUID, **extra}


@pytest.mark.parametrize(("route_name", "extra"), PURCHASE_IDENTITY_ROUTES)
@pytest.mark.parametrize(
    "invalid_id", [pytest.param(1, id="integer"), pytest.param(UUID4, id="uuid4")]
)
def test_purchase_identity_routes_reject_non_uuidv7_ids(route_name, extra, invalid_id):
    """Changing a converter to accept integers or UUIDv4 leaks non-Purchase IDs."""
    with pytest.raises(NoReverseMatch):
        reverse(route_name, kwargs={"purchase_id": invalid_id, **extra})

    valid_url = reverse(route_name, kwargs={"purchase_id": ROUTE_UUID, **extra})
    invalid_url = valid_url.replace(str(ROUTE_UUID), str(invalid_id))
    with pytest.raises(Resolver404):
        resolve(invalid_url)


def _purchase_of(library, name: str):
    graph = default_graph(Game(library=library, name=name), library)
    return record_purchase(record_entry(library, graph.release))


@pytest.fixture
def runtime_world(db):
    owner = get_user_model().objects.create_user(username="purchase-runtime-owner")
    foreign_user = get_user_model().objects.create_user(
        username="purchase-runtime-foreign"
    )
    client = Client()
    client.force_login(owner)
    own_purchase = _purchase_of(owner.library, "Owned runtime game")
    foreign_purchase = _purchase_of(foreign_user.library, "Foreign runtime game")
    return SimpleNamespace(**locals())


@pytest.mark.parametrize(
    ("method", "route_name", "expected_status"),
    [
        ("get", "games:edit_purchase", 200),
        ("get", "games:remove_purchase", 200),
        ("post", "games:refund_purchase_now", 302),
    ],
)
def test_purchase_identity_routes_accept_owned_uuidv7s(
    runtime_world, method, route_name, expected_status
):
    """Changing a route lookup or converter prevents an owner using its Purchase."""
    response = getattr(runtime_world.client, method)(
        reverse(route_name, args=[runtime_world.own_purchase.pk]),
        {"submission": SUBMISSION} if method == "post" else {},
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("method", "route_name", "extra"),
    [
        ("get", "games:edit_purchase", ()),
        ("get", "games:remove_purchase", ()),
        ("post", "games:remove_purchase", ()),
        ("post", "games:restore_purchase", ()),
        ("post", "games:refund_purchase_now", ()),
        ("post", "games:undo_purchase_refund", (1,)),
    ],
)
def test_purchase_identity_routes_hide_foreign_uuidv7s(
    runtime_world, method, route_name, extra
):
    """Removing the library-scoped Purchase lookup reveals another library's UUID."""
    foreign_purchase = runtime_world.foreign_purchase
    before = LibraryEvent.objects.count()

    response = getattr(runtime_world.client, method)(
        reverse(route_name, args=[foreign_purchase.pk, *extra]),
        {"submission": SUBMISSION} if method == "post" else {},
    )

    assert response.status_code == 404
    assert LibraryEvent.objects.count() == before
