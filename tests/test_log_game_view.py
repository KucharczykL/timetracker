"""Log a game page: render, write, refuse."""

import re
import uuid

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from graphs import default_graph
from stated_runs import state_run
from tracked_games import create_tracked_game

from games.models import Game, LibraryEntry, PlayerGameStatus
from games.views import log_game as log_game_view
from games.writes.answers import CommandFailed
from games.writes.log_game import LogRefused

pytestmark = pytest.mark.django_db(transaction=True)

SUBMISSION = str(uuid.UUID("01928e5e-4f6b-7c3a-8e9d-000000000002"))
DAY = "2026-09-01"


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return create_tracked_game(owned_library, "Tunic")


def _page(client, game: Game | None = None, *, prefill: Game | None = None) -> str:
    url = reverse("games:log_game")
    if game is not None:
        url = f"{url}?game={game.pk}"
    if prefill is not None:
        url = f"{url}?prefill_game={prefill.pk}"
    return client.get(url).content.decode()


def _title(html: str) -> str:
    found = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert found
    return found.group(1).strip().removeprefix("Timetracker - ")


def _press(game: Game, **fields: object) -> dict[str, object]:
    """Press stating only `fields`."""
    posted: dict[str, object] = {
        "submission": SUBMISSION,
        "game": str(game.pk),
        "status": "unplayed",
        "status_seen": "unplayed",
        "platform_seen": "",
        "started_seen": "",
        "completed_seen": "",
        "note_seen": "",
        "mastered_seen": "False",
        "attempt": "0",
        "playtime_kind": "session",
        "duration_hours": "",
        "duration_minutes": "",
        "device": "",
        "day": DAY,
    }
    return posted | fields


def _post(client, game: Game, data: dict[str, object]):
    return client.post(f"{reverse('games:log_game')}?game={game.pk}", data)


def test_the_page_renders_under_its_plain_title(logged_in):
    response = logged_in.get(reverse("games:log_game"))

    assert response.status_code == 200
    assert _title(response.content.decode()) == "Log a game"


def test_a_fixed_game_titles_the_page_with_its_name(logged_in, game):
    html = _page(logged_in, game)

    assert _title(html) == "Log Tunic"


def test_a_prefilled_game_titles_the_page_and_stays_editable(logged_in, game):
    html = _page(logged_in, prefill=game)

    assert _title(html) == "Log Tunic"
    assert f'value="{game.pk}"' in html
    assert "Save" in html


def test_a_tracked_game_prefills_its_status_mastery_and_note(
    logged_in, owned_user, owned_library
):
    game = create_tracked_game(
        owned_library, "Hades", status=PlayerGameStatus.COMPLETED, mastered=True
    )
    state_run(owned_user, game, note="Second pass")

    html = _page(logged_in, game)

    assert 'name="status_seen" value="completed"' in html
    assert 'name="mastered_seen" value="True"' in html
    assert 'name="note_seen" value="Second pass"' in html
    assert "Second pass" in html


def test_an_untracked_game_is_logged_by_create_log(logged_in):
    html = _page(logged_in)

    assert ">Create log<" in html


def test_a_tracked_game_is_saved(logged_in, game):
    html = _page(logged_in, game)

    assert ">Save<" in html


def test_the_inline_fields_and_the_two_openers_render(logged_in, game):
    html = _page(logged_in, game)

    assert 'name="status"' in html
    assert 'name="platform"' in html
    assert 'data-log-section-edit="playtime"' in html
    assert 'data-log-section-edit="more"' in html
    assert "Add playtime…" in html
    assert "Mastered and note…" in html


def test_each_nested_section_renders_in_its_own_dialog(logged_in):
    html = _page(logged_in)

    for section in ("playtime", "more"):
        assert f'data-log-section="{section}"' in html


def test_a_fresh_page_opens_no_section(logged_in):
    assert 'open-section=""' in _page(logged_in)


def test_the_element_names_the_route_and_no_origin(logged_in):
    html = _page(logged_in)

    assert f'route="{reverse("games:log_game")}"' in html
    assert 'origin=""' in html


def test_a_valid_press_redirects_to_game_detail_with_a_toast(
    logged_in, owned_library, game
):
    response = _post(logged_in, game, _press(game))

    assert response.url == reverse("games:view_game", args=[game.pk, game.url_slug])
    texts = [message.message for message in get_messages(response.wsgi_request)]
    assert "Logged Tunic." in texts


def test_a_changed_platform_records_a_copy(logged_in, owned_library, game, owned_user):
    from games.models import Platform

    pc = Platform.objects.create(library=owned_library, name="PC")
    default_graph(game, owned_library, platform=pc)

    response = _post(logged_in, game, _press(game, platform=str(pc.pk)))

    assert response.status_code == 302
    entry = LibraryEntry.objects.get(library=owned_library)
    assert (entry.access, entry.format) == ("unknown", "unknown")


def test_a_refused_later_step_keeps_what_was_written(
    logged_in, owned_library, game, monkeypatch
):
    refusal = LogRefused(
        "dates",
        CommandFailed("That playthrough has ended.", 409),
        frozenset({"copy"}),
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    response = _post(logged_in, game, _press(game))

    assert response.status_code == 409
    html = response.content.decode()
    assert "That playthrough has ended." in html


def test_a_refused_step_names_its_field(logged_in, game, monkeypatch):
    refusal = LogRefused(
        "track", CommandFailed("Restore it instead.", 409), frozenset()
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    response = _post(logged_in, game, _press(game))

    assert response.status_code == 409
    assert "Restore it instead." in response.content.decode()


def test_a_written_playtime_is_dropped_and_its_attempt_raised(
    logged_in, game, monkeypatch
):
    refusal = LogRefused(
        "more",
        CommandFailed("That run is removed.", 409),
        frozenset({"playtime"}),
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    response = _post(
        logged_in,
        game,
        _press(game, duration_hours="2", duration_minutes="0", attempt="1"),
    )

    html = response.content.decode()
    assert 'name="attempt" value="2"' in html
    assert 'name="duration_hours" value="2"' not in html


def test_a_zero_duration_refusal_opens_its_section(logged_in, game):
    response = _post(
        logged_in,
        game,
        _press(game, duration_hours="0", duration_minutes="0"),
    )

    assert response.status_code == 200
    assert 'open-section="playtime"' in response.content.decode()


def test_a_removed_game_is_refused_on_the_page(logged_in, owned_library, game):
    from games.models import PlayerGame

    PlayerGame.objects.filter(library=owned_library, game=game).update(
        removed_at="2026-09-01T00:00:00+00:00"
    )

    response = _post(logged_in, game, _press(game))

    assert response.status_code == 200
    assert "Restore it instead." in response.content.decode()


def test_the_fresh_page_is_not_a_refused_one(logged_in, game):
    html = _page(logged_in, game)

    assert "Restore it instead." not in html
    assert "aria-invalid" not in html
