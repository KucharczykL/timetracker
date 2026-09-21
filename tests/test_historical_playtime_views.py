"""Historical playtime acts through the routes."""

import re
import uuid
from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from historical_playtime_posts import MultiValuePost, posted_record
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
from games.commands.playergame import RemovePlayerGame, TrackGame
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
from games.writes.answers import CONFLICT_STATUS
from games.writes.historical_playtime import remove_historical_playtime
from games.writes.playergame import new_correlation_id

pytestmark = pytest.mark.django_db(transaction=True)

RUN_REMOVED_SENTENCE = (
    "That playthrough was removed from your library. Restore it before recording this."
)


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


def posted(run_ids, **changes) -> MultiValuePost:
    return posted_record(run_ids, when_year="2005", **changes)


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


def test_a_refusal_is_the_commands_sentence_on_the_form(logged_in, game, run):
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted([run.pk], hours="0"),
    )
    assert response.status_code == CONFLICT_STATUS
    assert AT_LEAST_A_SECOND in messages_of(response)
    assert not HistoricalPlaytime.objects.exists()


def test_no_playthrough_is_the_fields_error_not_the_commands(logged_in, game, run):
    response = logged_in.post(
        reverse("games:add_historical_playtime", args=[game.pk]),
        posted([], hours="100"),
    )
    assert response.status_code == 200
    assert AT_LEAST_ONE_RUN not in messages_of(response)
    assert "This field is required" in response.content.decode()
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
    assert response.status_code == CONFLICT_STATUS
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

    assert response["Location"] == game.get_absolute_url()
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


def test_a_repeated_add_submit_records_once(logged_in, game, run):
    url = reverse("games:add_historical_playtime", args=[game.pk])
    data = posted([run.pk])

    first = logged_in.post(url, data)
    second = logged_in.post(url, data)

    assert first.status_code == second.status_code == 302
    assert "Historical playtime recorded." in messages_of(second)
    assert HistoricalPlaytime.objects.count() == 1


def test_a_reused_key_with_another_statement_is_refused(logged_in, game, run):
    url = reverse("games:add_historical_playtime", args=[game.pk])
    data = posted([run.pk])
    logged_in.post(url, data)

    response = logged_in.post(url, {**data, "duration_hours": "5"})

    assert response.status_code == CONFLICT_STATUS
    assert HistoricalPlaytime.objects.count() == 1


def test_the_edit_page_states_the_record_and_saving_it_changes_nothing(
    logged_in, owned_user, game, run
):
    device = Device.objects.create(library=owned_user.library, name="Steam Deck")
    record = recorded(
        owned_user,
        [run.pk],
        duration=timedelta(hours=1, minutes=30, seconds=20),
        device_id=device.pk,
        emulated=True,
        note="Read off a launcher",
    )
    url = reverse("games:edit_historical_playtime", args=[record.pk])
    page = logged_in.get(url).content.decode()
    for rendered in (
        'value="1"',
        'value="30"',
        'value="2005"',
        "Steam Deck",
        "Read off a launcher",
    ):
        assert rendered in page, rendered
    assert re.search(rf'value="{run.pk}"[^>]*checked', page)
    events = LibraryEvent.objects.count()

    response = logged_in.post(
        url,
        posted(
            [run.pk],
            hours="1",
            minutes="30",
            device=str(device.pk),
            emulated="on",
            note="Read off a launcher",
        ),
    )

    assert response.status_code == 302
    assert LibraryEvent.objects.count() == events
    record.refresh_from_db()
    assert record.duration == timedelta(hours=1, minutes=30, seconds=20)


def test_a_refused_edit_keeps_the_record(logged_in, owned_user, game, run):
    record = recorded(owned_user, [run.pk])
    response = logged_in.post(
        reverse("games:edit_historical_playtime", args=[record.pk]),
        posted([run.pk], hours="0", minutes="0"),
    )
    assert response.status_code == CONFLICT_STATUS
    assert AT_LEAST_A_SECOND in messages_of(response)
    assert 'name="duration_hours" id="id_duration_hours" value="0"' in (
        response.content.decode()
    )
    record.refresh_from_db()
    assert record.duration == timedelta(hours=100)


def test_edit_without_an_origin_returns_to_game_detail(
    logged_in, owned_user, game, run
):
    record = recorded(owned_user, [run.pk])
    response = logged_in.post(
        reverse("games:edit_historical_playtime", args=[record.pk]), posted([run.pk])
    )
    assert response["Location"] == game.get_absolute_url()


def test_add_on_a_game_the_library_stopped_tracking_answers_404(
    logged_in, owned_user, game, run
):
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_user.library,
        idempotency_key="untrack",
    )
    url = reverse("games:add_historical_playtime", args=[game.pk])
    assert logged_in.get(url).status_code == 404


def test_edit_on_a_removed_record_answers_404(logged_in, owned_user, game, run):
    record = recorded(owned_user, [run.pk])
    remove_historical_playtime(owned_user, record, correlation_id=new_correlation_id())
    url = reverse("games:edit_historical_playtime", args=[record.pk])
    assert logged_in.get(url).status_code == 404


def test_a_shared_game_shows_each_library_its_own_records(
    client, owned_user, django_user_model
):
    shared = Game.objects.create(library=None, name="Shared")
    other = django_user_model.objects.create_user(username="someone-else")
    for user in (owned_user, other):
        dispatch(
            TrackGame(game_id=shared.pk),
            actor=user,
            library=user.library,
            idempotency_key=f"track-{user.pk}",
        )
        run = Playthrough.objects.get(player_game__game=shared, library=user.library)
        recorded(user, [run.pk], note=f"by {user.username}")

    client.force_login(owned_user)
    page = client.get(shared.get_absolute_url()).content.decode()

    mine = HistoricalPlaytime.objects.get(library=owned_user.library)
    theirs = HistoricalPlaytime.objects.get(library=other.library)
    assert f"record-row-{mine.pk}" in page
    assert f"record-row-{theirs.pk}" not in page
