"""The pages that add, edit, end, resume, remove and restore a copy."""

import datetime
import re
from decimal import Decimal

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry
from purchases import record_purchase, refund_purchase, remove_purchase

from games.catalog_release import SHARED_GAME_RELEASE
from games.end_ways import EndWay
from games.entry_forms import CHANGED_SINCE_OPENED, end_seen
from games.models import (
    Edition,
    Game,
    LibraryEntry,
    LibraryEvent,
    Platform,
    PlayerGame,
    Purchase,
    Release,
)
from games.removal import remove
from games.views.library_entry import NO_RELEASE, UNDO_OVERTAKEN
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


@pytest.fixture
def graph(owned_library, stated_graph):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(
        owned_library, graph.release, acquired=TemporalValue.parse("2021-05")
    )


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _types(entry_id) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=entry_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


# --- add ------------------------------------------------------------------


def _add_post(graph, **changes) -> dict[str, str]:
    return {
        "release": str(graph.release.pk),
        "access": "owned",
        "format": "digital",
        "note": "",
        "submission": SUBMISSION,
        "price": "none",
        **_day("acquired", datetime.date(2026, 9, 1)),
    } | changes


def _add_url(game) -> str:
    return reverse("games:add_library_entry", args=[game.pk])


def test_add_records_a_copy_and_returns(logged_in, graph):
    response = logged_in.post(
        _add_url(graph.game) + f"?origin={graph.game.get_absolute_url()}",
        _add_post(graph),
    )

    assert response.status_code == 302
    assert response["Location"] == graph.game.get_absolute_url()
    entry = LibraryEntry.objects.get(release=graph.release)
    assert entry.acquired == TemporalValue.parse("2026-09-01")


def test_a_repeated_add_records_once(logged_in, graph):
    for _ in range(2):
        logged_in.post(_add_url(graph.game), _add_post(graph))

    assert LibraryEntry.objects.filter(release=graph.release).count() == 1


def test_the_add_page_seeds_digital_and_the_default_release(logged_in, graph):
    response = logged_in.get(_add_url(graph.game))

    assert response.status_code == 200
    html = response.content.decode()
    assert (
        'value="digital" class'
        in html.split('checked="true"')[0].rsplit("<input", 1)[1]
    )
    assert str(graph.release.pk) in html


def test_an_invalid_add_renders_the_page_again(logged_in, graph):
    response = logged_in.post(_add_url(graph.game), _add_post(graph, access="lent"))

    assert response.status_code == 200
    assert "Add to library - Tunic" in response.content.decode()
    assert not LibraryEntry.objects.exists()


def test_a_removed_release_is_refused_on_the_form(logged_in, graph):
    remove(graph.release)
    response = logged_in.post(_add_url(graph.game), _add_post(graph))

    assert response.status_code == 200
    assert not LibraryEntry.objects.exists()


def test_add_on_another_librarys_game_is_absent(client, graph, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    response = client.post(_add_url(graph.game), _add_post(graph))

    assert response.status_code == 404


# --- edit -----------------------------------------------------------------


def _edit_post(entry, **changes) -> dict[str, str]:
    return {
        "release": str(entry.release_id),
        "access": entry.access,
        "format": entry.format,
        "note": entry.note,
        temporal_input_name("acquired", "kind"): "date",
        temporal_input_name("acquired", "start_year"): "2021",
        temporal_input_name("acquired", "start_month"): "5",
    } | changes


def _edit_url(entry) -> str:
    return reverse("games:edit_library_entry", args=[entry.pk])


def test_the_edit_page_holds_the_copys_facts_alone(logged_in, entry):
    response = logged_in.get(_edit_url(entry))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Edit details - Tunic (PS5)" in html
    assert 'name="way"' not in html


def test_edit_restates_the_copy(logged_in, entry):
    response = logged_in.post(_edit_url(entry), _edit_post(entry, note="shelf"))

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.note == "shelf"


def test_edit_leaves_a_standing_end_alone(logged_in, entry):
    entry = end_entry_access(entry)

    logged_in.post(_edit_url(entry), _edit_post(entry, note="shelf"))

    entry.refresh_from_db()
    assert entry.access_end_recorded_at is not None
    assert entry.note == "shelf"


def test_a_refused_edit_renders_the_page_at_its_status(logged_in, entry):
    end_entry_access(entry, ended=TemporalValue.parse("2022"))
    posted = _edit_post(entry)
    posted[temporal_input_name("acquired", "start_year")] = "2025"

    response = logged_in.post(_edit_url(entry), posted)

    assert response.status_code == 409
    assert "Edit details - Tunic" in response.content.decode()


def test_edit_of_another_librarys_copy_is_absent(client, entry, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    assert client.post(_edit_url(entry), _edit_post(entry)).status_code == 404


def test_a_saved_edit_returns_to_its_origin(logged_in, entry):
    origin = reverse("games:list_games")

    response = logged_in.post(_edit_url(entry) + f"?origin={origin}", _edit_post(entry))

    assert response["Location"] == origin


# --- end, edit end, resume ----------------------------------------------------


def _end_post(**changes) -> dict[str, str]:
    return {
        "way": "sold",
        "note": "",
        "access_end_seen": "",
        "submission": SUBMISSION,
        **_day("ended", datetime.date(2026, 9, 2)),
    } | changes


def test_end_access_states_the_end_once(logged_in, entry):
    url = reverse("games:end_library_entry", args=[entry.pk])
    for _ in range(2):
        response = logged_in.post(url, _end_post())

    assert response.status_code == 302
    assert _types(entry.pk).count("library.libraryentry.access_ended") == 1


def test_end_access_on_an_ended_copy_goes_to_edit_end(logged_in, entry):
    entry = end_entry_access(entry)

    response = logged_in.get(reverse("games:end_library_entry", args=[entry.pk]))

    assert response.status_code == 302
    assert (
        reverse("games:edit_library_entry_end", args=[entry.pk]) in response["Location"]
    )


def _edit_end_post(entry, **changes) -> dict[str, str]:
    return {
        "way": "sold",
        "note": "",
        "access_end_seen": end_seen(entry),
        **_day("ended", datetime.date(2024, 3, 1)),
    } | changes


def test_edit_end_restates_the_way(logged_in, entry):
    entry = end_entry_access(entry)
    url = reverse("games:edit_library_entry_end", args=[entry.pk])

    response = logged_in.post(url, _edit_end_post(entry))

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.access_end_way == "sold"


def test_a_stale_end_marker_is_refused(logged_in, entry):
    entry = end_entry_access(entry)
    posted = _edit_end_post(entry) | {"access_end_seen": "2000-01-01T00:00:00+00:00"}

    response = logged_in.post(
        reverse("games:edit_library_entry_end", args=[entry.pk]), posted
    )

    assert response.status_code == 200
    assert CHANGED_SINCE_OPENED in response.content.decode()


def test_edit_end_on_a_held_copy_goes_to_end_access(logged_in, entry):
    response = logged_in.get(reverse("games:edit_library_entry_end", args=[entry.pk]))

    assert response.status_code == 302
    assert reverse("games:end_library_entry", args=[entry.pk]) in response["Location"]


def test_resume_states_the_resume(logged_in, entry):
    entry = end_entry_access(entry, ended=TemporalValue.parse("2022"))

    response = logged_in.post(
        reverse("games:resume_library_entry", args=[entry.pk]),
        {
            "note": "",
            "access_end_seen": end_seen(entry),
            "submission": SUBMISSION,
            **_day("resumed", datetime.date(2026, 9, 2)),
        },
    )

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


# --- remove and restore -----------------------------------------------------


def test_remove_confirms_then_removes(logged_in, entry, graph):
    url = reverse("games:remove_library_entry", args=[entry.pk])

    assert logged_in.get(url).status_code == 200
    response = logged_in.post(url + f"?origin={graph.game.get_absolute_url()}")

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.removed_at is not None


def test_remove_names_each_purchase_it_takes(logged_in, entry):
    record_purchase(entry, purchased=TemporalValue.parse("2021-06-03"))
    refund_purchase(record_purchase(entry, kind="upgrade", name="Deluxe"), None)
    remove_purchase(record_purchase(entry, name="Gone already"))

    page = logged_in.get(
        reverse("games:remove_library_entry", args=[entry.pk])
    ).content.decode()

    assert "Its purchases are removed with it:" in page
    assert "Bought · " in page and "19.99 EUR" in page
    assert "Upgrade: Deluxe · " in page and " · refunded" in page
    assert "Gone already" not in page


def test_remove_of_a_copy_without_purchases_names_none(logged_in, entry):
    page = logged_in.get(
        reverse("games:remove_library_entry", args=[entry.pk])
    ).content.decode()

    assert "Its purchases" not in page


def test_restore_puts_a_removed_copy_back(logged_in, entry):
    entry = remove_entry(entry)

    response = logged_in.post(reverse("games:restore_library_entry", args=[entry.pk]))

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.removed_at is None


# --- the Add to library page ------------------------------------------------


def test_the_add_page_renders_a_game_picker(logged_in):
    response = logged_in.get(reverse("games:add_to_library"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="game"' in html
    assert "&quot;field&quot;: &quot;game&quot;" in html.split('name="release"')[1]


def test_the_add_page_records_a_copy_on_the_picked_game(logged_in, graph):
    posted = _add_post(graph) | {"game": str(graph.game.pk)}

    response = logged_in.post(reverse("games:add_to_library"), posted)

    assert response.status_code == 302
    assert response["Location"] == graph.game.get_absolute_url()
    assert LibraryEntry.objects.filter(release=graph.release).count() == 1


@pytest.mark.parametrize(
    "price",
    [{"price": "none"}, {"price": "paid", "amount": "5"}, {"price": "free"}],
    ids=["none", "paid", "free"],
)
def test_the_add_page_tracks_an_untracked_shared_game(logged_in, owned_library, price):
    shared = Game.objects.create(name="Celeste")
    edition = Edition.objects.create(game=shared, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)
    posted = {
        "game": str(shared.pk),
        "release": str(release.pk),
        "access": "owned",
        "format": "physical",
        "submission": SUBMISSION,
        "currency": "EUR",
        **price,
    }

    response = logged_in.post(reverse("games:add_to_library"), posted)

    assert response.status_code == 302
    assert PlayerGame.objects.filter(library=owned_library, game=shared).exists()
    assert Purchase.objects.exists() is (price["price"] != "none")


@pytest.mark.parametrize(
    ("price", "amount"),
    [({"price": "paid", "amount": "30"}, Decimal(30)), ({"price": "free"}, Decimal(0))],
    ids=["paid", "free"],
)
def test_add_records_the_games_purchase_with_the_copy(logged_in, graph, price, amount):
    posted = _add_post(graph, currency="EUR", **price)

    for _ in range(2):
        response = logged_in.post(_add_url(graph.game), posted)

    assert response.status_code == 302
    entry = LibraryEntry.objects.get(release=graph.release)
    purchase = Purchase.objects.get(entry=entry)
    assert (purchase.kind, purchase.amount, purchase.currency) == (
        "game",
        amount,
        "EUR",
    )
    assert purchase.purchased == entry.acquired


def test_no_purchase_records_the_copy_alone(logged_in, graph):
    logged_in.post(_add_url(graph.game), _add_post(graph))

    assert LibraryEntry.objects.filter(release=graph.release).count() == 1
    assert not Purchase.objects.exists()


def test_the_add_page_starts_on_paid(logged_in, graph):
    html = logged_in.get(_add_url(graph.game)).content.decode()

    assert re.search(r'value="paid"[^>]*checked|checked[^>]*value="paid"', html)
    assert "group/price" in html


def test_the_library_page_offers_add_to_library(logged_in):
    html = logged_in.get(reverse("games:library")).content.decode()

    assert reverse("games:add_to_library") in html


# --- one click, then Undo ---------------------------------------------------


def _now(client, route, target, token=SUBMISSION):
    return client.post(
        reverse(route, args=[target]) + "?origin=/tracker/game/library",
        {"submission": token},
    )


def test_one_click_add_records_the_defaults_once(logged_in, graph):
    for _ in range(2):
        response = _now(logged_in, "games:add_library_entry_now", graph.game.pk)

    assert response.status_code == 302
    entry = LibraryEntry.objects.get(release=graph.release)
    assert (entry.access, entry.format) == ("owned", "digital")
    assert entry.acquired is not None


def test_one_click_end_states_not_said_today(logged_in, entry):
    response = _now(logged_in, "games:end_library_entry_now", entry.pk)

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.access_end_way == "unstated"
    assert entry.access_ended is not None


def _offered_undo(client, response) -> str:
    page = client.get(response["Location"]).content.decode()
    match = re.search(r"/tracker/library/[0-9a-f-]+/(?:end|resume)/undo/\d+", page)
    assert match is not None
    return match.group(0)


def _messages(client, response) -> str:
    return client.get(response["Location"]).content.decode()


def test_the_end_s_undo_voids_it(logged_in, entry):
    undo = _offered_undo(
        logged_in, _now(logged_in, "games:end_library_entry_now", entry.pk)
    )

    logged_in.post(undo)

    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None
    assert _types(entry.pk)[-1] == "library.libraryentry.access_end_voided"


def test_the_end_s_undo_leaves_a_later_correction_alone(logged_in, entry):
    undo = _offered_undo(
        logged_in, _now(logged_in, "games:end_library_entry_now", entry.pk)
    )
    entry.refresh_from_db()
    logged_in.post(
        reverse("games:edit_library_entry_end", args=[entry.pk]),
        _edit_end_post(entry, way="sold"),
    )

    response = logged_in.post(undo)

    entry.refresh_from_db()
    assert entry.access_end_way == "sold"
    assert UNDO_OVERTAKEN in _messages(logged_in, response)


def test_a_second_undo_of_one_end_changes_nothing(logged_in, entry):
    undo = _offered_undo(
        logged_in, _now(logged_in, "games:end_library_entry_now", entry.pk)
    )
    logged_in.post(undo)
    events = _types(entry.pk)

    response = logged_in.post(undo)

    assert _types(entry.pk) == events
    assert UNDO_OVERTAKEN in _messages(logged_in, response)


def test_the_resume_s_undo_states_the_end_it_took_back(logged_in, entry):
    entry = end_entry_access(entry, ended=TemporalValue.parse("2022"))
    undo = _offered_undo(
        logged_in, _now(logged_in, "games:resume_library_entry_now", entry.pk)
    )
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None

    logged_in.post(undo)

    entry.refresh_from_db()
    assert entry.access_end_way == "returned"
    assert entry.access_ended == TemporalValue.parse("2022")


def test_a_stale_resume_undo_never_restates_a_voided_end(logged_in, entry):
    entry = end_entry_access(entry, ended=TemporalValue.parse("2022"))
    stale = _offered_undo(
        logged_in, _now(logged_in, "games:resume_library_entry_now", entry.pk)
    )
    gone = _offered_undo(
        logged_in,
        _now(
            logged_in,
            "games:end_library_entry_now",
            entry.pk,
            token="01928e5e-4f6b-7c3a-8e9d-000000000002",
        ),
    )
    logged_in.post(gone)

    logged_in.post(stale)

    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


def test_one_click_offers_undo(logged_in, entry):
    response = _now(logged_in, "games:end_library_entry_now", entry.pk)

    assert f"/library/{entry.pk}/end/undo/" in _offered_undo(logged_in, response)


def test_a_refused_one_click_offers_no_undo(logged_in, entry):
    entry = end_entry_access(entry, way=EndWay.SOLD)

    response = _now(logged_in, "games:end_library_entry_now", entry.pk)

    assert "/end/undo/" not in _messages(logged_in, response)
    entry.refresh_from_db()
    assert entry.access_end_way == "sold"


def test_a_one_click_press_without_its_key_is_malformed(logged_in, entry):
    response = logged_in.post(
        reverse("games:end_library_entry_now", args=[entry.pk]), {}
    )

    assert response.status_code == 400
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


def test_one_click_add_on_an_own_game_without_a_version_says_so(
    logged_in, owned_library
):
    game = Game.objects.create(name="Unreleased", library=owned_library)

    response = _now(logged_in, "games:add_library_entry_now", game.pk)

    assert NO_RELEASE in _messages(logged_in, response)
    assert not LibraryEntry.objects.filter(player_game__game=game).exists()


def test_one_click_add_on_a_shared_game_without_a_version_says_so(logged_in):
    shared = Game.objects.create(name="Celeste")

    response = _now(logged_in, "games:add_library_entry_now", shared.pk)

    assert SHARED_GAME_RELEASE in _messages(logged_in, response)


@pytest.mark.parametrize(
    "route",
    [
        "games:add_library_entry_now",
    ],
)
def test_one_click_add_on_another_librarys_game_is_absent(
    client, graph, django_user_model, route
):
    client.force_login(django_user_model.objects.create_user(username="stranger"))

    assert _now(client, route, graph.game.pk).status_code == 404


@pytest.mark.parametrize(
    "route",
    [
        "games:remove_library_entry",
        "games:restore_library_entry",
        "games:undo_library_entry_end",
        "games:undo_library_entry_resume",
    ],
)
def test_another_librarys_copy_is_absent_from_every_act(
    client, entry, django_user_model, route
):
    client.force_login(django_user_model.objects.create_user(username="stranger"))
    args = [entry.pk] if "undo" not in route else [entry.pk, 1]
    before = _types(entry.pk)

    assert client.post(reverse(route, args=args)).status_code == 404
    assert _types(entry.pk) == before


def test_the_resume_page_of_a_held_copy_goes_to_end_access(logged_in, entry):
    response = logged_in.get(reverse("games:resume_library_entry", args=[entry.pk]))

    assert response.status_code == 302
    assert reverse("games:end_library_entry", args=[entry.pk]) in response["Location"]


def test_a_correction_since_the_page_opened_is_refused(logged_in, entry):
    entry = end_entry_access(entry, way=EndWay.SOLD)
    opened = _edit_end_post(entry, way="lost")
    logged_in.post(
        reverse("games:edit_library_entry_end", args=[entry.pk]),
        _edit_end_post(entry, way="stolen"),
    )

    response = logged_in.post(
        reverse("games:edit_library_entry_end", args=[entry.pk]), opened
    )

    entry.refresh_from_db()
    assert entry.access_end_way == "stolen"
    assert CHANGED_SINCE_OPENED in response.content.decode()


def test_an_empty_add_page_post_renders_its_errors(logged_in):
    response = logged_in.post(reverse("games:add_to_library"), {})

    assert response.status_code == 200
    assert f'href="{reverse("games:library")}"' in response.content.decode()


def test_one_click_on_another_librarys_copy_is_absent(client, entry, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="stranger"))

    assert _now(client, "games:end_library_entry_now", entry.pk).status_code == 404


def test_a_get_on_a_one_click_route_is_refused(logged_in, entry):
    url = reverse("games:end_library_entry_now", args=[entry.pk])

    assert logged_in.get(url).status_code == 405
