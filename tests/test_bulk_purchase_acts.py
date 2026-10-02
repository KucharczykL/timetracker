"""Purchases edited and removed in bulk, and the Undo of each."""

import json
import uuid

import pytest
from bulk_posts import act_url, posted, press, selection
from django.http import Http404
from django.urls import reverse
from entries import record_entry
from purchases import record_purchase, remove_purchase

from common.criteria import FilterError
from games.bulk_actions import BULK_ACTIONS
from games.bulk_parts import EventRows
from games.bulk_purchases import PURCHASE_GONE
from games.bulk_removal import REMOVE_PURCHASE
from games.models import Game, LibraryEntry, Platform, Purchase
from games.views.bulk import STATEMENT_FIELD, TOKEN_FIELD
from games.writes import revaluation
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(
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
    owned_library, first, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = record_purchase(
        record_entry(
            stranger,
            stated_graph(Game(name="Hades", library=stranger), stranger).release,
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


def test_an_undo_of_another_librarys_purchase_is_absent(
    owned_user, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = remove_purchase(
        record_purchase(
            record_entry(
                stranger,
                stated_graph(Game(name="Hades", library=stranger), stranger).release,
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
