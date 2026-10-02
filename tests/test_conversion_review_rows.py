"""The conversion review and its Hide preference."""

import re
from decimal import Decimal

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry
from purchases import _state, record_purchase

from games.commands.purchase import DescribePurchase, StatedPrice
from games.conversion_review import ORIGIN, REVIEW_WORDS, Category
from games.end_ways import EndWay
from games.models import Game, UserLibraryPreferences
from games.removal import remove
from games.toast_middleware import RELOAD_HEADER
from games.views import conversion_review
from games.views.conversion_review import REPURCHASED, conversion_review_rows

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

HIDDEN_URL = "/api/library/conversion-review-hidden"


def tagged(*words: Category) -> dict[str, object]:
    return {"origin": ORIGIN, "issue": 723, "review": [str(word) for word in words]}


@pytest.fixture
def release(owned_library, stated_graph):
    def made(name: str):
        graph = stated_graph(Game(name=name, library=owned_library), owned_library)
        return graph.release

    return made


@pytest.fixture
def converted(owned_library, release):
    """Unknown price, rental, and a plain copy."""
    unknown = record_purchase(
        record_entry(owned_library, release("Tunic")),
        amount=None,
        source_metadata=tagged(Category.UNKNOWN_PRICE),
    )
    rental = record_entry(
        owned_library,
        release("Hades"),
        access="rented",
        source_metadata=tagged(Category.RENTAL),
    )
    record_entry(owned_library, release("Celeste"))
    return unknown, rental


def _rows(library):
    return {row.label: row for row in conversion_review_rows(library)}


def test_each_category_counts_its_target_list(owned_library, converted):
    rows = _rows(owned_library)

    assert set(rows) == {
        REVIEW_WORDS[Category.UNKNOWN_PRICE].label,
        REVIEW_WORDS[Category.RENTAL].label,
    }
    assert rows[REVIEW_WORDS[Category.UNKNOWN_PRICE].label].count == 1
    assert rows[REVIEW_WORDS[Category.UNKNOWN_PRICE].label].url.startswith(
        reverse("games:list_purchases") + "?"
    )
    assert rows[REVIEW_WORDS[Category.RENTAL].label].count == 1


def test_a_link_opens_exactly_its_rows(client, owned_library, converted):
    client.force_login(owned_library.user)
    rows = _rows(owned_library)

    purchases = client.get(rows[REVIEW_WORDS[Category.UNKNOWN_PRICE].label].url)
    entries = client.get(rows[REVIEW_WORDS[Category.RENTAL].label].url)

    assert purchases.status_code == 200
    assert "Tunic" in purchases.text
    assert "Hades" not in purchases.text
    assert entries.status_code == 200
    assert "Hades" in entries.text
    assert "Tunic" not in entries.text
    assert "Celeste" not in entries.text


def test_a_removed_purchase_leaves_the_count(owned_library, converted):
    from purchases import remove_purchase

    unknown, _ = converted
    remove_purchase(unknown)

    assert REVIEW_WORDS[Category.UNKNOWN_PRICE].label not in _rows(owned_library)


def test_repurchased_counts_live_copies_and_opens_those_games(
    client, owned_library, release, converted
):
    twice = release("Outer Wilds")
    record_entry(owned_library, twice)
    record_entry(owned_library, twice)
    ended = release("Celeste 64")
    record_entry(owned_library, ended)
    end_entry_access(record_entry(owned_library, ended), way=EndWay.SOLD)
    removed = release("Hollow Knight")
    record_entry(owned_library, removed)
    remove_entry(record_entry(owned_library, removed))
    client.force_login(owned_library.user)

    row = _rows(owned_library)[REPURCHASED]
    listed = client.get(row.url).text

    assert row.count == 2
    assert row.url.startswith(reverse("games:list_games") + "?")
    assert "Outer Wilds" in listed
    assert "Celeste 64" in listed
    assert "Hollow Knight" not in listed


def test_an_edit_leaves_a_row_in_its_category(owned_library, converted):
    unknown, _ = converted

    _state(
        owned_library,
        DescribePurchase(purchase_id=unknown.pk, price=StatedPrice(Decimal(5), "EUR")),
    )

    assert _rows(owned_library)[REVIEW_WORDS[Category.UNKNOWN_PRICE].label].count == 1


def test_a_hidden_copy_leaves_both_count_and_link(client, owned_library, stated_graph):
    seen = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    hidden = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    for graph in (seen, hidden):
        record_entry(
            owned_library,
            graph.release,
            access="rented",
            source_metadata=tagged(Category.RENTAL),
        )
    remove(hidden.release)
    client.force_login(owned_library.user)

    row = _rows(owned_library)[REVIEW_WORDS[Category.RENTAL].label]
    listed = client.get(row.url).text

    assert row.count == 1
    assert "Hades" in listed
    assert "Tunic" not in listed


def test_a_library_never_converted_shows_no_review(client, owned_library, release):
    record_entry(owned_library, release("Tunic"))
    client.force_login(owned_library.user)

    body = client.get(reverse("games:library")).text

    assert "Conversion review" not in body
    assert "Hide this review" not in body


def test_the_page_lists_the_rows(client, owned_library, converted):
    client.force_login(owned_library.user)

    body = client.get(reverse("games:library")).text

    assert "Conversion review" in body
    assert REVIEW_WORDS[Category.RENTAL].label in body
    assert 'data-setting-key="conversion-review-hidden"' in body
    assert "data-reload-after-save" in body


def test_a_hidden_review_reads_no_row(client, owned_library, converted, monkeypatch):
    UserLibraryPreferences.objects.filter(library=owned_library).update(
        conversion_review_hidden=True
    )

    def refused(library):
        raise AssertionError("a hidden review reads no row")

    monkeypatch.setattr(conversion_review, "conversion_review_rows", refused)
    client.force_login(owned_library.user)

    body = client.get(reverse("games:library")).text

    assert REVIEW_WORDS[Category.RENTAL].label not in body
    assert "Hide this review" in body
    (control,) = re.findall(r'<input[^>]*name="hidden"[^>]*>', body)
    assert " checked" in control


@pytest.mark.parametrize("hidden", [True, False])
def test_the_route_stores_the_preference(client, owned_library, hidden):
    UserLibraryPreferences.objects.filter(library=owned_library).update(
        conversion_review_hidden=not hidden
    )
    client.force_login(owned_library.user)

    response = client.patch(
        HIDDEN_URL, data={"value": hidden}, content_type="application/json"
    )

    assert response.status_code == 200
    assert response.json() == {
        "key": "conversion-review-hidden",
        "value": hidden,
        "source": "library",
        "locked": False,
        "namespace": "library",
    }
    assert response[RELOAD_HEADER] == "true"
    owned_library.preferences.refresh_from_db()
    assert owned_library.preferences.conversion_review_hidden is hidden


@pytest.mark.parametrize(
    "body", [{"value": "yes"}, {"value": None}, {}, {"value": True, "other": 1}]
)
def test_the_route_refuses_anything_but_a_bool(client, owned_library, body):
    client.force_login(owned_library.user)

    response = client.patch(HIDDEN_URL, data=body, content_type="application/json")

    assert response.status_code == 422


def test_the_route_touches_only_the_viewers_library(
    client, owned_library, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    client.force_login(owned_library.user)

    client.patch(HIDDEN_URL, data={"value": True}, content_type="application/json")

    stranger.preferences.refresh_from_db()
    owned_library.preferences.refresh_from_db()
    assert stranger.preferences.conversion_review_hidden is False
    assert owned_library.preferences.conversion_review_hidden is True


def test_another_librarys_conversion_shows_no_review(
    client, owned_library, release, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    graph = stated_graph(Game(name="Hades", library=stranger), stranger)
    record_entry(
        stranger,
        graph.release,
        access="rented",
        source_metadata=tagged(Category.RENTAL),
    )
    client.force_login(owned_library.user)

    body = client.get(reverse("games:library")).text

    assert conversion_review_rows(owned_library) == ()
    assert "Conversion review" not in body


def test_a_converted_library_with_no_rows_shows_the_control_alone(
    client, owned_library, release
):
    record_entry(owned_library, release("Tunic"), source_metadata=tagged())
    client.force_login(owned_library.user)

    body = client.get(reverse("games:library")).text

    assert "Conversion review" in body
    assert "Hide this review" in body
    assert REVIEW_WORDS[Category.RENTAL].label not in body


def test_the_review_reads_a_bounded_number_of_queries(
    client, owned_library, converted, django_assert_num_queries
):
    client.force_login(owned_library.user)

    #: Twelve categories and Repurchased among them.
    with django_assert_num_queries(37):
        client.get(reverse("games:library"))


def test_the_route_queues_no_toast(client, owned_library):
    client.force_login(owned_library.user)

    client.patch(HIDDEN_URL, data={"value": True}, content_type="application/json")

    assert "Conversion review hidden" not in client.get(reverse("games:library")).text
