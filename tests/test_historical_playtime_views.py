"""Historical playtime acts through the routes."""

import uuid
from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from stated_runs import another_run

from common.returns import action_url
from games.commands.historical_playtime import (
    AT_LEAST_A_SECOND,
    AT_LEAST_ONE_RUN,
    INTO_THE_BUCKET_HISTORICAL,
    ONE_GAME,
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playthrough import RemovePlaythrough
from games.events.dispatch import dispatch
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryEvent,
    Playthrough,
    PlaythroughKind,
)
from games.removal import remove
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

RUN_REMOVED_SENTENCE = (
    "That playthrough was removed from your library. Restore it before recording this."
)

type PostedData = dict[str, str | list[str]]


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


def posted(run_ids, *, hours="100", minutes="0", **overrides) -> PostedData:
    data: PostedData = {
        "playthroughs": [str(run_id) for run_id in run_ids],
        "duration_hours": hours,
        "duration_minutes": minutes,
        temporal_input_name("when", "kind"): "date",
        temporal_input_name("when", "start_year"): "2005",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED.value,
        "device": "",
        "note": "",
    }
    data.update(overrides)
    return data


def recorded(user, run_ids, **changes) -> HistoricalPlaytime:
    statement = HistoricalPlaytimeStatement(
        duration=timedelta(hours=100),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=tuple(run_ids),
        device_id=None,
        emulated=False,
        note="",
    )._replace(**changes)
    dispatch(
        RecordHistoricalPlaytime(statement=statement),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.latest("created_at")


def messages_of(response) -> list[str]:
    return [message.message for message in get_messages(response.wsgi_request)]


def run_ids(record: HistoricalPlaytime) -> set[uuid.UUID]:
    return set(
        HistoricalPlaytimeRun.objects.filter(record=record).values_list(
            "playthrough_id", flat=True
        )
    )


def test_a_record_is_recorded_restated_removed_and_restored(
    logged_in, owned_user, game, run
):
    second = another_run(owned_user, game)
    origin = game.get_absolute_url()

    response = logged_in.post(
        action_url("games:add_historical_playtime", game.pk, origin=origin),
        posted([run.pk, second.pk]),
    )
    assert response.status_code == 302
    assert response["Location"] == origin
    record = HistoricalPlaytime.objects.get()
    assert run_ids(record) == {run.pk, second.pk}
    assert record.duration == timedelta(hours=100)
    assert record.when.canonical == "2005"
    kept_join = HistoricalPlaytimeRun.objects.get(record=record, playthrough=run)

    response = logged_in.post(
        action_url("games:edit_historical_playtime", record.pk, origin=origin),
        posted([run.pk]),
    )
    assert response["Location"] == origin
    assert run_ids(record) == {run.pk}
    assert HistoricalPlaytimeRun.objects.get(record=record).pk == kept_join.pk

    response = logged_in.post(
        action_url("games:remove_historical_playtime", record.pk, origin=origin)
    )
    assert response["Location"] == origin
    record.refresh_from_db()
    assert record.removed_at is not None
    undo = [
        message
        for message in get_messages(response.wsgi_request)
        if message.message == "Historical playtime removed."
    ]
    assert len(undo) == 1
    assert reverse("games:restore_historical_playtime", args=[record.pk]) in str(
        undo[0].extra_tags
    )

    response = logged_in.post(
        action_url("games:restore_historical_playtime", record.pk, origin=origin)
    )
    assert response["Location"] == origin
    record.refresh_from_db()
    assert record.removed_at is None


def test_without_an_origin_add_returns_to_game_detail(logged_in, game, run):
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]), posted([run.pk])
    )
    assert response["Location"] == game.get_absolute_url()
    assert "Historical playtime recorded." in messages_of(response)


def test_an_unchanged_edit_says_saved_and_states_nothing(
    logged_in, owned_user, game, run
):
    record = recorded(owned_user, [run.pk], note="one\ntwo")
    events = LibraryEvent.objects.count()

    response = logged_in.post(
        reverse("games:edit_historical_playtime", args=[record.pk]),
        posted([run.pk], note="one\r\ntwo"),
    )

    assert response.status_code == 302
    assert "Historical playtime saved." in messages_of(response)
    assert LibraryEvent.objects.count() == events


def test_an_edit_keeps_a_held_removed_device(logged_in, owned_user, game, run):
    device = Device.objects.create(library=owned_user.library, name="Old PC")
    record = recorded(owned_user, [run.pk], device_id=device.pk)
    remove(device)
    events = LibraryEvent.objects.count()

    page = logged_in.get(reverse("games:edit_historical_playtime", args=[record.pk]))
    assert "Old PC" in page.content.decode()
    response = logged_in.post(
        reverse("games:edit_historical_playtime", args=[record.pk]),
        posted([run.pk], device=str(device.pk)),
    )

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.device_id == device.pk
    assert LibraryEvent.objects.count() == events


@pytest.mark.parametrize(
    ("hours", "sentence"), [("0", AT_LEAST_A_SECOND), ("100", AT_LEAST_ONE_RUN)]
)
def test_a_refusal_is_the_commands_sentence_on_the_form(
    logged_in, game, run, hours, sentence
):
    runs = [] if sentence == AT_LEAST_ONE_RUN else [run.pk]
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted(runs, hours=hours),
    )
    assert response.status_code == 200
    assert sentence in messages_of(response)
    assert not HistoricalPlaytime.objects.exists()


def test_a_removed_run_is_refused_in_the_commands_words(
    logged_in, owned_user, game, run
):
    second = another_run(owned_user, game)
    dispatch(
        RemovePlaythrough(playthrough_id=second.pk),
        actor=owned_user,
        library=owned_user.library,
        idempotency_key="remove-second",
    )
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted([second.pk]),
    )
    assert response.status_code == 200
    assert RUN_REMOVED_SENTENCE in messages_of(response)


def test_the_bucket_is_refused_in_the_commands_words(logged_in, game, run):
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=run.created_at,
    )
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted([bucket.pk]),
    )
    assert INTO_THE_BUCKET_HISTORICAL in messages_of(response)


def test_runs_of_two_games_are_refused_in_the_commands_words(
    logged_in, owned_library, game, run
):
    other = Game.objects.create(library=owned_library, name="Tunic")
    other_run = Playthrough.objects.get(player_game__game=other)
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted([run.pk, other_run.pk]),
    )
    assert ONE_GAME in messages_of(response)


def test_a_second_remove_returns_and_states_nothing(logged_in, owned_user, game, run):
    record = recorded(owned_user, [run.pk])
    url = reverse("games:remove_historical_playtime", args=[record.pk])
    logged_in.post(url)
    events = LibraryEvent.objects.count()

    response = logged_in.post(url)

    assert response.status_code == 302
    assert LibraryEvent.objects.count() == events


def test_get_on_remove_confirms_and_changes_nothing(logged_in, owned_user, game, run):
    record = recorded(owned_user, [run.pk])
    response = logged_in.get(
        reverse("games:remove_historical_playtime", args=[record.pk])
    )
    assert response.status_code == 200
    assert "Remove this historical playtime record of Outer Wilds?" in (
        response.content.decode()
    )
    record.refresh_from_db()
    assert record.removed_at is None


def test_another_librarys_record_and_game_answer_404(
    logged_in, owned_user, game, run, django_user_model
):
    other_user = django_user_model.objects.create_user(username="someone-else")
    other_game = Game.objects.create(library=other_user.library, name="Theirs")
    other_run = Playthrough.objects.get(player_game__game=other_game)
    record = recorded(other_user, [other_run.pk])

    assert (
        logged_in.get(
            reverse("games:add_historical_playtime", args=[other_game.pk])
        ).status_code
        == 404
    )
    for route in ("games:edit_historical_playtime", "games:remove_historical_playtime"):
        url = reverse(route, args=[record.pk])
        assert logged_in.get(url).status_code == 404
        assert logged_in.post(url).status_code == 404
    assert (
        logged_in.post(
            reverse("games:restore_historical_playtime", args=[record.pk])
        ).status_code
        == 404
    )
    record.refresh_from_db()
    assert record.removed_at is None
