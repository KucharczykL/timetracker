"""Undo posts to a restore route; the route puts the row back and returns."""

from datetime import UTC, date, datetime

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from historical_playtime_rows import record_row
from session_rows import session_row
from stated_runs import another_run

from common.returns import action_url
from games.models import (
    Device,
    FilterPreset,
    Game,
    HistoricalPlaytime,
    Platform,
    PlayerGame,
    PlayerSession,
    Playthrough,
    Purchase,
)
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import library_sessions
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.historical_playtime import remove_historical_playtime
from games.writes.playergame import new_correlation_id
from games.writes.playersession import remove_session
from games.writes.playthrough import remove_run

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="other", password="p").library


@pytest.fixture
def game(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Removable",
        platform=Platform.objects.create(name="PC"),
    )
    session_row(game, started_at=datetime(2024, 6, 1, 12, tzinfo=UTC))
    return game


def _removed_session(user, game):
    row = library_sessions(user.library).get(playthrough__player_game__game=game)
    remove_session(user, row, correlation_id=new_correlation_id())
    return row


def _removed_run(user, game):
    run = another_run(user, game)
    remove_run(user, run, correlation_id=new_correlation_id())
    return run


def _removed_purchase(user, game):
    purchase = Purchase.objects.create(
        library=user.library,
        price_currency="CZK",
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
    )
    purchase.games.set([game])
    remove(purchase)
    return purchase


def _removed_platform(user, game):
    platform = Platform.objects.create(library=user.library, name="Doomed")
    remove(platform)
    return platform


def _removed_device(user, game):
    device = Device.objects.create(library=user.library, name="Doomed")
    remove(device)
    return device


def _removed_preset(user, game):
    preset = FilterPreset.objects.create(
        library=user.library, name="Mine", mode="games"
    )
    remove(preset)
    return preset


def _removed_record(user, game):
    record = record_row([Playthrough.objects.get(player_game__game=game)])
    remove_historical_playtime(user, record, correlation_id=new_correlation_id())
    return record


def _visible(library, instance) -> bool:
    if isinstance(instance, HistoricalPlaytime):
        return library_records(library).filter(pk=instance.pk).exists()
    if isinstance(instance, PlayerSession):
        return library_sessions(library).filter(pk=instance.pk).exists()
    if isinstance(instance, Playthrough):
        return Playthrough.objects.filter(pk=instance.pk, removed_at=None).exists()
    return type(instance).objects.for_library(library).filter(pk=instance.pk).exists()


ROUTES = [
    ("games:restore_session", _removed_session, "games:list_sessions"),
    ("games:restore_playthrough", _removed_run, None),
    ("games:restore_purchase", _removed_purchase, "games:list_purchases"),
    ("games:restore_platform", _removed_platform, "games:list_platforms"),
    ("games:restore_device", _removed_device, "games:list_devices"),
    ("games:restore_preset", _removed_preset, "games:list_games"),
    ("games:restore_historical_playtime", _removed_record, None),
]


def _messages_of(response) -> list[tuple[str, str]]:
    return [(m.level_tag, m.message) for m in get_messages(response.wsgi_request)]


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
def test_post_puts_the_row_back_and_returns_to_the_origin(
    logged_in, owned_user, game, route, removed, fallback
):
    row = removed(owned_user, game)
    assert not _visible(owned_user.library, row)
    origin = f"{reverse('games:list_games')}?page=2"

    response = logged_in.post(action_url(route, row.pk, origin=origin))

    assert response["Location"] == origin
    assert _visible(owned_user.library, row)
    assert ("success", "restored") in [
        (tag, "restored" if "restored" in text else text)
        for tag, text in _messages_of(response)
    ]


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
def test_without_an_origin_the_fallback_is_the_page(
    logged_in, owned_user, game, route, removed, fallback
):
    row = removed(owned_user, game)

    response = logged_in.post(reverse(route, args=[row.pk]))

    expected = game.get_absolute_url() if fallback is None else reverse(fallback)
    assert response["Location"] == expected


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
@pytest.mark.parametrize(
    "origin",
    ["https://evil.example/tracker/game/list", "/tracker/session/x/remove"],
)
def test_an_origin_that_is_no_read_only_page_is_refused(
    logged_in, owned_user, game, route, removed, fallback, origin
):
    row = removed(owned_user, game)

    response = logged_in.post(action_url(route, row.pk, origin=origin))

    expected = game.get_absolute_url() if fallback is None else reverse(fallback)
    assert response["Location"] == expected


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
def test_get_answers_405(logged_in, owned_user, game, route, removed, fallback):
    row = removed(owned_user, game)

    assert logged_in.get(reverse(route, args=[row.pk])).status_code == 405
    assert not _visible(owned_user.library, row)


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
def test_another_librarys_row_answers_404(
    logged_in, owned_user, second_library, game, route, removed, fallback
):
    row = removed(owned_user, game)
    Game.objects.filter(pk=game.pk).update(library=second_library)
    type(row).objects.filter(pk=row.pk).update(library=second_library)

    assert logged_in.post(reverse(route, args=[row.pk])).status_code == 404


@pytest.mark.parametrize(("route", "removed", "fallback"), ROUTES)
def test_a_second_post_still_says_restored(
    logged_in, owned_user, game, route, removed, fallback
):
    row = removed(owned_user, game)
    url = reverse(route, args=[row.pk])
    logged_in.post(url)

    response = logged_in.post(url)

    assert response.status_code == 302
    assert _visible(owned_user.library, row)
    assert any("restored" in text for _, text in _messages_of(response))


def test_a_session_under_a_removed_run_lands_an_error_on_the_origin(
    logged_in, owned_user, game
):
    row = _removed_session(owned_user, game)
    another_run(owned_user, game)
    remove_run(owned_user, row.playthrough, correlation_id=new_correlation_id())
    origin = reverse("games:list_sessions")

    response = logged_in.post(
        action_url("games:restore_session", row.pk, origin=origin)
    )

    assert response["Location"] == origin
    sentence = (
        "That playthrough was removed from your library. "
        "Restore it before changing its sessions."
    )
    assert _messages_of(response) == [("error", sentence)]
    assert not _visible(owned_user.library, row)


class TestRestoreGame:
    def _removed(self, logged_in, game):
        logged_in.post(reverse("games:remove_game", args=[game.pk]))
        game.refresh_from_db()
        assert game.removed_at is not None
        assert PlayerGame.objects.get(game=game).removed_at is not None

    def test_post_clears_both_marks(self, logged_in, game):
        self._removed(logged_in, game)
        origin = f"{reverse('games:list_games')}?page=2"

        response = logged_in.post(
            action_url("games:restore_game", game.pk, origin=origin)
        )

        assert response["Location"] == origin
        game.refresh_from_db()
        assert game.removed_at is None
        assert PlayerGame.objects.get(game=game).removed_at is None
        #: The removal's own notice is still queued: no page drew it.
        assert _messages_of(response)[-1] == (
            "success",
            "Removable restored to your library.",
        )

    def test_get_answers_405(self, logged_in, game):
        self._removed(logged_in, game)

        assert (
            logged_in.get(reverse("games:restore_game", args=[game.pk])).status_code
            == 405
        )

    def test_a_failed_command_after_the_stamp_completes_on_the_second_press(
        self, logged_in, game, monkeypatch
    ):
        """The stamp clears first; a refused command leaves the removal's
        own halfway, and pressing Undo again finishes it."""
        import games.views.playergame_writes as writes

        self._removed(logged_in, game)
        real = writes.retrack_game
        calls = {"count": 0}

        def refuse_once(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise CommandFailed("refused once", 409)
            return real(*args, **kwargs)

        monkeypatch.setattr(writes, "retrack_game", refuse_once)
        url = reverse("games:restore_game", args=[game.pk])

        first = logged_in.post(url)
        game.refresh_from_db()
        assert game.removed_at is None
        assert PlayerGame.objects.get(game=game).removed_at is not None
        assert _messages_of(first)[-1] == (
            "error",
            "Removable is back in the catalog but not tracked yet. Try again.",
        )
        from common.notices import toast_payloads

        assert toast_payloads(first.wsgi_request)[-1]["action"] == {
            "label": "Try again",
            "url": url,
        }

        second = logged_in.post(url)
        game.refresh_from_db()
        assert game.removed_at is None
        assert PlayerGame.objects.get(game=game).removed_at is None
        #: The first press's message is still queued: no page drew it.
        assert _messages_of(second)[-1] == (
            "success",
            "Removable restored to your library.",
        )

    def test_another_librarys_game_answers_404(self, logged_in, second_library, game):
        self._removed(logged_in, game)
        Game.objects.filter(pk=game.pk).update(library=second_library)

        assert (
            logged_in.post(reverse("games:restore_game", args=[game.pk])).status_code
            == 404
        )
