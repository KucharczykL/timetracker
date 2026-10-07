"""What Game detail's Library note counts and links."""

import json
import re
from decimal import Decimal

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry
from purchases import record_purchase, refund_purchase, remove_purchase

from games.end_ways import EndWay
from games.filters import (
    filter_url,
    parse_entry_filter,
    parse_purchase_filter,
)
from games.models import Game, Platform
from games.reads.previous_copies import (
    previous_copies_filter,
    previous_purchase_count,
    previous_purchases_filter,
)
from games.reads.purchases import copy_purchases, unrefunded
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def ps5():
    return Platform.objects.create(name="PS5", group="Sony")


@pytest.fixture
def graph(owned_library, stated_graph, ps5):
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


class History:
    """One game's copies, each kind the note reads."""

    def __init__(self, library, graph, other_graph, stranger, stranger_graph):
        self.held = record_entry(library, graph.release)
        self.kept = record_purchase(self.held)
        self.refunded_addon = refund_purchase(
            record_purchase(self.held, kind="upgrade", name="Gone back"), None
        )
        remove_purchase(record_purchase(self.held, name="Removed one"))

        self.ended = record_entry(library, graph.release)
        self.sold = record_purchase(self.ended, amount=Decimal(30))
        end_entry_access(self.ended, way=EndWay.SOLD)

        gone = record_entry(library, graph.release)
        record_purchase(gone)
        end_entry_access(gone, way=EndWay.SOLD)
        remove_entry(gone)

        elsewhere = record_entry(library, other_graph.release)
        record_purchase(elsewhere)
        end_entry_access(elsewhere, way=EndWay.SOLD)

        foreign = record_entry(stranger, stranger_graph.release)
        record_purchase(foreign)
        end_entry_access(foreign, way=EndWay.SOLD)


@pytest.fixture
def history(owned_library, graph, stated_graph, django_user_model, ps5):
    other_graph = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    stranger = django_user_model.objects.create_user("stranger").library
    stranger_graph = stated_graph(
        Game(name="Tunic", library=stranger), stranger, platform=ps5
    )
    return History(owned_library, graph, other_graph, stranger, stranger_graph)


def test_copy_purchases_reads_refunded_ones_too(owned_library, history):
    purchases = copy_purchases(owned_library, [history.held.pk])[history.held.pk]

    assert [purchase.pk for purchase in purchases] == [
        history.kept.pk,
        history.refunded_addon.pk,
    ]
    assert [purchase.pk for purchase in unrefunded(purchases)] == [history.kept.pk]


def test_copy_purchases_keeps_purchase_order(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    later = record_purchase(entry, purchased=TemporalValue.parse("2022-01-01"))
    earlier = refund_purchase(
        record_purchase(
            entry, kind="upgrade", purchased=TemporalValue.parse("2021-01-01")
        ),
        None,
    )

    purchases = copy_purchases(owned_library, [entry.pk])[entry.pk]

    assert [purchase.pk for purchase in purchases] == [earlier.pk, later.pk]


def test_the_purchase_count_takes_refunds_and_ended_copies(
    owned_library, graph, history
):
    assert previous_purchase_count(owned_library, graph.game) == 2


def _keys(html: str, prefix: str) -> set[str]:
    return set(re.findall(rf'id="{prefix}-([0-9a-f-]{{36}})"', html))


def test_the_purchase_link_lists_what_it_counts(
    client, owned_user, owned_library, graph, history
):
    client.force_login(owned_user)

    html = client.get(filter_url(previous_purchases_filter(graph.game))).content
    listed = _keys(html.decode(), "purchase-menu")

    assert listed == {str(history.refunded_addon.pk), str(history.sold.pk)}
    assert len(listed) == previous_purchase_count(owned_library, graph.game)


def test_the_copy_link_lists_the_ended_copies(client, owned_user, graph, history):
    client.force_login(owned_user)

    html = client.get(filter_url(previous_copies_filter(graph.game))).content

    assert _keys(html.decode(), "entry-menu") == {str(history.ended.pk)}


def test_both_filters_round_trip(graph):
    copies = previous_copies_filter(graph.game)
    purchases = previous_purchases_filter(graph.game)

    assert parse_entry_filter(json.dumps(copies.to_json())) == copies
    assert parse_purchase_filter(json.dumps(purchases.to_json())) == purchases


def test_the_copy_link_targets_the_library_tab(graph):
    assert filter_url(previous_copies_filter(graph.game)).startswith(
        reverse("games:list_library")
    )
