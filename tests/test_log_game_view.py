"""The Log a game page: what it renders, writes and says when a step refuses."""

import datetime
import re
import uuid

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from graphs import default_graph
from tracked_games import create_tracked_game

from games.models import Game, LibraryEntry
from games.views import log_game as log_game_view
from games.writes.answers import CommandFailed
from games.writes.log_game import LogRefused
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

SUBMISSION = str(uuid.UUID("01928e5e-4f6b-7c3a-8e9d-000000000002"))
DAY = datetime.date(2026, 9, 1)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return create_tracked_game(owned_library, "Tunic")


def _page(client, game: Game | None = None) -> str:
    url = reverse("games:log_game")
    if game is not None:
        url = f"{url}?game={game.pk}"
    return client.get(url).content.decode()


def _title(html: str) -> str:
    found = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert found
    return found.group(1).strip().removeprefix("Timetracker - ")


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


def _copy_post(release) -> dict[str, object]:
    posted: dict[str, object] = {
        "submission": SUBMISSION,
        "sections": ["copy"],
        "release": str(release.pk),
        "access": "owned",
        "format": "digital",
        "price": "none",
    }
    return posted | _day("acquired", DAY)


def test_the_page_renders_under_its_plain_title(logged_in):
    response = logged_in.get(reverse("games:log_game"))

    assert response.status_code == 200
    assert _title(response.content.decode()) == "Log a game"


def test_a_fixed_game_titles_the_page_with_its_name(logged_in, game):
    html = _page(logged_in, game)

    assert _title(html) == "Log Tunic"


def test_a_held_game_states_its_status_and_playtime(logged_in, game):
    html = _page(logged_in, game)

    assert "Leave as is: Unplayed" in html
    assert "No playtime yet" in html
    assert "Not mastered" in html


def test_a_held_copy_is_summarised_with_another_copy_label(
    logged_in, owned_library, game
):
    release = default_graph(game, owned_library).release
    response = logged_in.post(
        f"{reverse('games:log_game')}?game={game.pk}",
        _copy_post(release),
    )

    assert response.status_code == 302
    assert LibraryEntry.objects.filter(library=owned_library).count() == 1
    html = _page(logged_in, game)
    assert "Another copy" in html


def test_a_valid_press_redirects_to_game_detail_with_a_toast(
    logged_in, owned_library, game
):
    release = default_graph(game, owned_library).release
    response = logged_in.post(
        f"{reverse('games:log_game')}?game={game.pk}",
        _copy_post(release),
    )

    assert response.url == reverse("games:view_game", args=[game.pk, game.url_slug])
    texts = [message.message for message in get_messages(response.wsgi_request)]
    assert "Logged Tunic." in texts


def test_a_refused_later_step_keeps_what_was_written(
    logged_in, owned_library, game, monkeypatch
):
    release = default_graph(game, owned_library).release
    refusal = LogRefused(
        "dates",
        CommandFailed("That playthrough has ended.", 409),
        frozenset({"copy"}),
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)
    data = _copy_post(release) | {"sections": ["copy", "dates"]}

    response = logged_in.post(f"{reverse('games:log_game')}?game={game.pk}", data)

    assert response.status_code == 409
    html = response.content.decode()
    assert "Saved: Copy and price" in html
    assert "That playthrough has ended." in html
    assert not re.search(r'<input[^>]*value="copy"[^>]*type="checkbox"', html)
    assert "Leave as is" in html


def test_a_refused_game_step_names_the_game_field(
    logged_in, owned_library, game, monkeypatch
):
    refusal = LogRefused(
        "game",
        CommandFailed("Restore it instead.", 409),
        frozenset(),
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)
    response = logged_in.post(
        f"{reverse('games:log_game')}?game={game.pk}",
        {"submission": SUBMISSION, "sections": ["more"], "mastered": "on"},
    )

    assert response.status_code == 409
    assert "Restore it instead." in response.content.decode()
