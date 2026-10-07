"""The Set times played page and its Undo."""

import json
import re
import uuid

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus
from games.reads.playthrough_runs import completed_run_count
from games.views.returns import ORIGIN_AWARE
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: Tracked by command: the Undo reads events.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def untracked(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def game(owned_user, untracked) -> Game:
    track_game(owned_user, untracked, correlation_id=new_correlation_id())
    return untracked


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _page(game) -> str:
    return reverse("games:state_times_played", args=[game.pk])


def _post(logged_in, game, count, *, submission=None, page=None):
    return logged_in.post(
        page or _page(game),
        {"count": count, "submission": str(submission or uuid.uuid7())},
    )


def _count_input(body: str) -> str:
    match = re.search(r'<input[^>]*name="count"[^>]*>', body)
    assert match is not None, "the count field changed shape"
    return match.group(0)


def _submission(body: str) -> str:
    match = re.search(r'name="submission"[^>]*value="([^"]+)"', body) or re.search(
        r'value="([^"]+)"[^>]*name="submission"', body
    )
    assert match is not None, "the submission field changed shape"
    return match.group(1)


def _undo_url(response) -> str:
    return json.loads(_toasts(response)[0].extra_tags)["action"]["url"]


def _total(owned_library, game) -> int:
    return completed_run_count(owned_library, PlayerGame.objects.get(game=game))


def _toasts(response) -> list:
    return list(get_messages(response.wsgi_request))


def test_the_page_seeds_the_current_total(logged_in, owned_library, game):
    _post(logged_in, game, 2)

    body = logged_in.get(_page(game)).content.decode()

    assert 'value="2"' in _count_input(body)
    assert "Times played through" in body


def test_a_save_returns_to_the_game_with_an_undo(logged_in, owned_library, game):
    response = _post(logged_in, game, 3)

    assert response.status_code == 302
    assert response["Location"] == game.get_absolute_url()
    toasts = _toasts(response)
    assert [str(toast) for toast in toasts] == ["Played 3 times."]
    action = json.loads(toasts[0].extra_tags)["action"]
    assert action["label"] == "Undo"
    assert _total(owned_library, game) == 3


def test_undo_restores_the_total(logged_in, owned_library, game):
    undone = logged_in.post(_undo_url(_post(logged_in, game, 3)))

    assert str(_toasts(undone)[-1]) == "Times played undone."
    assert _total(owned_library, game) == 0


def test_the_same_total_says_so_without_undo(logged_in, game):
    response = _post(logged_in, game, 0)

    toasts = _toasts(response)
    assert [str(toast) for toast in toasts] == ["Already played 0 times."]
    assert toasts[0].extra_tags == ""


def test_a_refusal_renders_on_the_field_under_a_fresh_key(logged_in, game):
    submission = uuid.uuid7()
    response = _post(logged_in, game, 101, submission=submission)

    body = response.content.decode()
    assert response.status_code == 409
    assert "100 times or fewer" in body
    assert 'aria-invalid="true"' in _count_input(body)
    assert _submission(body) != str(submission)


def test_a_repeated_save_says_it_was_already_saved(logged_in, owned_library, game):
    submission = uuid.uuid7()
    _post(logged_in, game, 2, submission=submission)

    again = _post(logged_in, game, 2, submission=submission)

    assert str(_toasts(again)[-1]) == "That was already saved."
    assert _total(owned_library, game) == 2


def test_a_save_returns_to_its_origin(logged_in, game):
    origin = reverse("games:list_playthroughs")
    response = _post(logged_in, game, 1, page=f"{_page(game)}?origin={origin}")

    assert response["Location"] == origin


def test_a_refused_undo_is_an_error_toast(logged_in, game):
    undo_url = _undo_url(_post(logged_in, game, 2))
    _post(logged_in, game, 3)

    undone = logged_in.post(undo_url)

    assert undone.status_code == 302
    assert "changed since" in str(_toasts(undone)[-1])


def test_undo_says_when_a_later_status_stood(logged_in, owned_user, game):
    undo_url = _undo_url(_post(logged_in, game, 1))
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.SHELVED,
        correlation_id=new_correlation_id(),
    )

    undone = logged_in.post(undo_url)

    assert str(_toasts(undone)[-1]) == (
        "Times played undone. The status you set since was kept."
    )


def test_undo_under_a_removed_game_names_the_remedy(logged_in, game):
    undo_url = _undo_url(_post(logged_in, game, 2))
    PlayerGame.objects.filter(game=game).update(removed_at=timezone.now())

    undone = logged_in.post(undo_url)

    assert undone.status_code == 302
    assert "Restore it" in str(_toasts(undone)[-1])


def test_a_forged_undo_is_absent(logged_in, game):
    url = reverse("games:undo_times_played", args=[game.pk, uuid.uuid7(), 0])

    assert logged_in.post(url).status_code == 404


def test_undo_answers_get_with_405(logged_in, game):
    url = reverse("games:undo_times_played", args=[game.pk, uuid.uuid7(), 0])

    assert logged_in.get(url).status_code == 405


def test_the_menu_offers_the_item_for_a_tracked_game(logged_in, game):
    body = logged_in.get(game.get_absolute_url()).content.decode()

    assert "Set times played" in body
    assert _page(game) in body


def test_an_untracked_game_has_no_page(logged_in, untracked):
    assert logged_in.get(_page(untracked)).status_code == 404


def test_both_routes_are_origin_aware():
    assert {"games:state_times_played", "games:undo_times_played"} <= ORIGIN_AWARE
