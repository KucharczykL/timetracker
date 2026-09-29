"""The `/api/entries/` routes."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from entries import record_entry, remove_entry

from games.commands.libraryentry import (
    RELEASE_OF_ANOTHER_GAME,
    RELEASE_REMOVED,
)
from games.models import Game, LibraryEntry, LibraryEvent, Platform, PlayerGame
from games.removal import remove
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
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def graph(library, stated_graph):
    platform = Platform.objects.create(library=library, name="Switch", group="")
    return stated_graph(Game(name="Tunic", library=library), library, platform=platform)


def _post(client: Client, body: dict, **headers):
    return client.post(
        "/api/entries/", json.dumps(body), content_type="application/json", **headers
    )


def _patch(client: Client, entry_id, body: dict):
    return client.patch(
        f"/api/entries/{entry_id}", json.dumps(body), content_type="application/json"
    )


def _body(graph, **changes) -> dict:
    return {
        "release_id": str(graph.release.pk),
        "access": "owned",
        "format": "digital",
    } | changes


def test_post_records_and_answers_the_row(auth_client, library, graph):
    response = _post(
        auth_client,
        _body(graph, note="gift", acquired="2021-05", acquisition_note="birthday"),
    )

    assert response.status_code == 201, response.content
    row = response.json()
    entry = LibraryEntry.objects.get(pk=row["id"])
    assert row["game"] == "Tunic"
    assert row["game_id"] == str(graph.game.pk)
    assert row["release_id"] == str(graph.release.pk)
    assert (row["access"], row["format"], row["note"]) == ("owned", "digital", "gift")
    assert (row["acquired"], row["acquired_lower"], row["acquired_upper"]) == (
        "2021-05",
        "2021-05-01",
        "2021-05-31",
    )
    assert row["acquisition_note"] == "birthday"
    assert row["platform"] == "Switch"
    assert row["acquisition_recorded_at"] is not None
    assert entry.player_game.library == library
    assert PlayerGame.objects.filter(library=library, game=graph.game).exists()


def test_a_repeat_under_one_key_answers_the_same_row(auth_client, graph):
    first = _post(auth_client, _body(graph), HTTP_IDEMPOTENCY_KEY="once")
    again = _post(auth_client, _body(graph), HTTP_IDEMPOTENCY_KEY="once")

    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json()["id"] == again.json()["id"]
    assert LibraryEntry.objects.count() == 1


def test_a_removed_release_answers_the_sentence(auth_client, graph):
    remove(graph.release)

    response = _post(auth_client, _body(graph))

    assert response.status_code == 409
    assert response.json()["detail"] == RELEASE_REMOVED


def test_another_librarys_private_release_is_absent(
    auth_client, second_library, stated_graph
):
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)

    response = _post(auth_client, {**_body(theirs)})

    assert response.status_code == 404


def test_an_unknown_key_is_refused(auth_client, graph):
    assert _post(auth_client, _body(graph, colour="black")).status_code == 422


def test_a_foreign_word_is_refused_by_the_schema(auth_client, graph):
    assert _post(auth_client, _body(graph, access="stolen")).status_code == 422
    assert _post(auth_client, _body(graph, format="tape")).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"access": None},
        {"format": None},
        {"note": None},
        {"release_id": None},
        {"acquired": "2021-06", "acquisition_note": None},
    ],
)
def test_patch_refuses_a_present_null(auth_client, library, graph, body):
    entry = record_entry(library, graph.release)

    response = _patch(auth_client, entry.pk, body)

    assert response.status_code == 422
    assert LibraryEvent.objects.filter(aggregate_id=entry.pk).count() == 1


def test_a_repeat_under_the_key_of_a_removed_entry_answers_no_row(auth_client, graph):
    first = _post(auth_client, _body(graph), HTTP_IDEMPOTENCY_KEY="gone")
    remove_entry(LibraryEntry.objects.get(pk=first.json()["id"]))

    assert (
        _post(auth_client, _body(graph), HTTP_IDEMPOTENCY_KEY="gone").status_code == 404
    )


def test_the_list_pages_and_reads_limit_zero(auth_client, library, graph):
    entries = [record_entry(library, graph.release) for _ in range(3)]

    everything = auth_client.get("/api/entries/?limit=0").json()
    page = auth_client.get("/api/entries/?limit=1&offset=1").json()

    assert [row["id"] for row in everything] == [str(entry.pk) for entry in entries]
    assert [row["id"] for row in page] == [str(entries[1].pk)]


def test_the_list_hides_a_removed_entry(auth_client, library, graph):
    kept = record_entry(library, graph.release)
    remove_entry(record_entry(library, graph.release))

    assert [row["id"] for row in auth_client.get("/api/entries/").json()] == [
        str(kept.pk)
    ]


def test_get_answers_the_row_or_404(auth_client, library, graph):
    entry = record_entry(library, graph.release)

    assert auth_client.get(f"/api/entries/{entry.pk}").json()["id"] == str(entry.pk)
    assert (
        auth_client.get("/api/entries/01890000-0000-7000-8000-000000000009").status_code
        == 404
    )


def test_patch_describes_each_named_fact(auth_client, library, graph):
    entry = record_entry(library, graph.release)

    response = _patch(
        auth_client, entry.pk, {"access": "borrowed", "format": "physical", "note": "x"}
    )

    assert response.status_code == 200, response.content
    entry.refresh_from_db()
    assert (entry.access, entry.format, entry.note) == ("borrowed", "physical", "x")


def test_patch_corrects_the_acquisition_as_one_statement(auth_client, library, graph):
    entry = record_entry(library, graph.release, acquired=None)

    response = _patch(
        auth_client,
        entry.pk,
        {"acquired": "2021-06", "acquisition_note": "receipt"},
    )

    assert response.status_code == 200, response.content
    assert (response.json()["acquired"], response.json()["acquisition_note"]) == (
        "2021-06",
        "receipt",
    )
    types = list(
        LibraryEvent.objects.filter(aggregate_id=entry.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert types[-1] == "library.libraryentry.acquisition_corrected"


def test_patch_states_an_unknown_day_with_null(auth_client, library, graph):
    entry = record_entry(
        library, graph.release, acquired=TemporalValue.parse("2021-05")
    )

    response = _patch(auth_client, entry.pk, {"acquired": None, "acquisition_note": ""})

    assert response.status_code == 200, response.content
    entry.refresh_from_db()
    assert entry.acquired is None
    assert (
        LibraryEvent.objects.filter(aggregate_id=entry.pk).latest("sequence").event_type
        == "library.libraryentry.acquisition_corrected"
    )


def test_a_refused_patch_leaves_the_day_unmoved(
    auth_client, library, graph, stated_graph
):
    entry = record_entry(
        library, graph.release, acquired=TemporalValue.parse("2021-05")
    )
    other = stated_graph(Game(name="Celeste", library=library), library)

    response = _patch(
        auth_client,
        entry.pk,
        {
            "acquired": "2021-06",
            "acquisition_note": "",
            "release_id": str(other.release.pk),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == RELEASE_OF_ANOTHER_GAME
    entry.refresh_from_db()
    assert entry.acquired == TemporalValue.parse("2021-05")
    assert LibraryEvent.objects.filter(aggregate_id=entry.pk).count() == 1


@pytest.mark.parametrize(
    "body", [{"acquired": "2021-06"}, {"acquisition_note": "receipt"}]
)
def test_patch_refuses_half_an_acquisition(auth_client, library, graph, body):
    entry = record_entry(library, graph.release)

    response = _patch(auth_client, entry.pk, body)

    assert response.status_code == 422
    assert "together" in json.dumps(response.json())


def test_patch_with_no_change_still_answers_the_row(auth_client, library, graph):
    entry = record_entry(library, graph.release)

    response = _patch(auth_client, entry.pk, {"access": "owned"})

    assert response.status_code == 200
    assert response.json()["id"] == str(entry.pk)


def test_patch_refuses_an_unknown_key(auth_client, library, graph):
    entry = record_entry(library, graph.release)

    assert _patch(auth_client, entry.pk, {"colour": "black"}).status_code == 422


def test_the_routes_require_auth():
    assert Client().get("/api/entries/").status_code == 401


# --- access end and resume --------------------------------------------------


def _resume(client: Client, entry_id, body: dict, **headers):
    return client.post(
        f"/api/entries/{entry_id}/resume",
        json.dumps(body),
        content_type="application/json",
        **headers,
    )


def test_patch_states_corrects_and_voids_the_end(auth_client, library, graph):
    entry = record_entry(library, graph.release, acquired=TemporalValue.parse("2021"))

    ended = _patch(
        auth_client,
        entry.pk,
        {"access_end": {"ended": "2022-03", "way": "returned", "note": "lent"}},
    )
    corrected = _patch(
        auth_client, entry.pk, {"access_end": {"ended": None, "way": "expired"}}
    )
    corrected_row = corrected.json()
    voided = _patch(auth_client, entry.pk, {"access_end": None})

    assert ended.status_code == 200, ended.content
    row = ended.json()
    assert (row["access_ended"], row["access_end_way"], row["access_end_note"]) == (
        "2022-03",
        "returned",
        "lent",
    )
    assert (row["access_ended_lower"], row["access_ended_upper"]) == (
        "2022-03-01",
        "2022-03-31",
    )
    assert row["access_end_recorded_at"] is not None
    assert (corrected_row["access_ended"], corrected_row["access_end_way"]) == (
        None,
        "expired",
    )
    assert voided.json()["access_end_recorded_at"] is None
    assert voided.json()["access_end_way"] == ""


def test_patch_without_the_key_keeps_the_end(auth_client, library, graph):
    entry = record_entry(library, graph.release)
    _patch(auth_client, entry.pk, {"access_end": {"ended": "2022", "way": "sold"}})

    response = _patch(auth_client, entry.pk, {"note": "kept"})

    assert response.json()["access_end_way"] == "sold"


@pytest.mark.parametrize(
    "access_end",
    [
        {"ended": "2022", "way": "melted"},
        {"ended": "2022"},
        {"ended": "2022", "way": "sold", "day": "2022"},
    ],
)
def test_patch_refuses_a_malformed_end(auth_client, library, graph, access_end):
    entry = record_entry(library, graph.release)

    response = _patch(auth_client, entry.pk, {"access_end": access_end})

    assert response.status_code == 422


def test_an_end_before_the_acquisition_answers_the_sentence(
    auth_client, library, graph
):
    entry = record_entry(library, graph.release, acquired=TemporalValue.parse("2022"))

    response = _patch(
        auth_client, entry.pk, {"access_end": {"ended": "2021", "way": "returned"}}
    )

    assert response.status_code == 409
    assert "acquired after that day" in response.json()["detail"]


def test_resume_answers_the_row_and_a_keyed_repeat_the_same(
    auth_client, library, graph
):
    entry = record_entry(library, graph.release)
    _patch(auth_client, entry.pk, {"access_end": {"ended": "2022", "way": "sold"}})

    first = _resume(
        auth_client,
        entry.pk,
        {"resumed": "2023", "note": "bought back"},
        HTTP_IDEMPOTENCY_KEY="resume-once",
    )
    repeat = _resume(
        auth_client,
        entry.pk,
        {"resumed": "2023", "note": "bought back"},
        HTTP_IDEMPOTENCY_KEY="resume-once",
    )
    unkeyed = _resume(auth_client, entry.pk, {"resumed": "2023"})

    assert first.status_code == 200, first.content
    assert first.json()["access_end_recorded_at"] is None
    assert repeat.status_code == 200
    assert unkeyed.status_code == 409
    assert (
        LibraryEvent.objects.filter(
            aggregate_id=entry.pk, event_type="library.libraryentry.access_resumed"
        ).count()
        == 1
    )


def test_resume_refuses_an_unknown_key(auth_client, library, graph):
    entry = record_entry(library, graph.release)

    response = _resume(auth_client, entry.pk, {"day": "2023"})

    assert response.status_code == 422


def test_another_librarys_entry_is_absent_to_both_acts(
    auth_client, second_library, stated_graph
):
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)
    entry = record_entry(second_library, theirs.release)

    patched = _patch(
        auth_client, entry.pk, {"access_end": {"ended": None, "way": "sold"}}
    )
    resumed = _resume(auth_client, entry.pk, {})

    assert (patched.status_code, resumed.status_code) == (404, 404)
