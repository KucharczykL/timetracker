"""The historical playtime records over the API."""

import json
import logging
import uuid
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import tracked_run

from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.removal import remove

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

LIST_URL = "/api/historical-playtime/"


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner", password="p")


@pytest.fixture
def client_for(owner):
    client = Client()
    client.force_login(owner)
    return client


def a_run(library, name: str = "Zelda") -> Playthrough:
    return tracked_run(library, Game.objects.create(library=library, name=name))


def test_anonymous_is_refused():
    assert Client().get(LIST_URL).status_code == 401


def test_the_list_states_every_field(client_for, owner):
    library = owner.library
    deck = Device.objects.create(library=library, name="Steam Deck")
    run = a_run(library)
    other = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    record = record_row(
        [other, run],
        duration=timedelta(hours=40, seconds=5),
        when="2020/2022",
        provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
        device=deck,
        emulated=True,
        note="read off a launcher",
    )

    body = client_for.get(LIST_URL).json()

    assert body["count"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["num_pages"] == 1
    (item,) = body["items"]
    assert item["id"] == str(record.pk)
    assert item["player_game_id"] == str(run.player_game_id)
    assert item["game"]["name"] == "Zelda"
    assert item["playthrough_ids"] == sorted([str(run.pk), str(other.pk)])
    assert item["duration_seconds"] == 40 * 3600 + 5
    assert item["when"] == "2020/2022"
    assert item["when_lower"] == "2020-01-01"
    assert item["when_upper"] == "2022-12-31"
    assert item["provenance"] == "externally_measured"
    assert item["device"]["name"] == "Steam Deck"
    assert item["emulated"] is True
    assert item["note"] == "read off a launcher"


def test_an_unknown_when_is_null(client_for, owner):
    record_row([a_run(owner.library)])

    (item,) = client_for.get(LIST_URL).json()["items"]

    assert item["when"] is None
    assert item["when_lower"] is None
    assert item["device"] is None


def test_the_list_filters_and_sorts(client_for, owner):
    run = a_run(owner.library)
    short = record_row([run], duration=timedelta(hours=1))
    long = record_row([run], duration=timedelta(hours=9))
    record_row([run], provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED)
    estimated = json.dumps(
        {"provenance": {"modifier": "INCLUDES", "value": ["estimated"]}}
    )

    body = client_for.get(LIST_URL, {"filter": estimated, "sort": "-duration"}).json()

    assert [item["id"] for item in body["items"]] == [str(long.pk), str(short.pk)]


def test_a_bad_filter_is_refused_and_logged(client_for, capture_games_logger):
    with capture_games_logger() as caplog:
        response = client_for.get(LIST_URL, {"filter": '{"run": {}}'})

    assert response.status_code == 400
    assert any(
        record.levelno == logging.WARNING
        and "entity=historical playtime" in record.getMessage()
        for record in caplog.records
    )


def test_an_unknown_sort_is_refused(client_for):
    assert client_for.get(LIST_URL, {"sort": "nope"}).status_code == 400


def test_the_detail_answers_a_live_record(client_for, owner):
    record = record_row([a_run(owner.library)])

    response = client_for.get(f"{LIST_URL}{record.pk}")

    assert response.status_code == 200
    assert response.json()["id"] == str(record.pk)


def test_the_detail_hides_what_the_list_hides(client_for, owner, django_user_model):
    library = owner.library
    removed = record_row([a_run(library, "Removed")])
    HistoricalPlaytime.objects.filter(pk=removed.pk).update(removed_at=timezone.now())
    untracked_run = a_run(library, "Untracked")
    untracked = record_row([untracked_run])
    PlayerGame.objects.filter(pk=untracked_run.player_game_id).update(
        removed_at=timezone.now()
    )
    catalog_run = a_run(library, "Catalog")
    catalog = record_row([catalog_run])
    remove(catalog_run.player_game.game)
    other_library = django_user_model.objects.create_user(username="other").library
    foreign = record_row([a_run(other_library, "Elsewhere")])
    foreign_game = record_row([a_run(other_library, "Borrowed")])
    HistoricalPlaytime.objects.filter(pk=foreign_game.pk).update(library=library)

    for record in (removed, untracked, catalog, foreign, foreign_game):
        assert client_for.get(f"{LIST_URL}{record.pk}").status_code == 404
    assert client_for.get(LIST_URL).json()["count"] == 0


def test_the_list_pages(client_for, owner):
    run = a_run(owner.library)
    for _ in range(11):
        record_row([run])

    body = client_for.get(LIST_URL, {"page": 2}).json()

    assert body["count"] == 11
    assert body["page"] == 2
    assert body["num_pages"] == 2
    assert len(body["items"]) == 1


def test_another_librarys_join_row_is_not_listed(client_for, owner, django_user_model):
    run = a_run(owner.library)
    record = record_row([run])
    other_library = django_user_model.objects.create_user(username="other").library
    foreign_run = a_run(other_library, "Elsewhere")
    HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=other_library, record=record, playthrough=foreign_run
    )

    (item,) = client_for.get(LIST_URL).json()["items"]

    assert item["playthrough_ids"] == [str(run.pk)]
