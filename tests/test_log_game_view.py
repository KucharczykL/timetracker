"""Log a game page: render, write, refuse."""

import logging
import re
import uuid
from html.parser import HTMLParser

import pytest
from django.contrib.messages import get_messages
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from graphs import default_graph
from stated_runs import state_run
from tracked_games import create_tracked_game

from common.components.modal import MODAL_ATTRIBUTES
from games.log_forms import STALE_FORM, STALE_GAME
from games.models import (
    Game,
    LibraryEntry,
    Platform,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
)
from games.views import log_game as log_game_view
from games.writes import log_game as writes_log_game
from games.writes.answers import CommandFailed
from games.writes.log_game import PICKED_RUN_GONE, LogRefused

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
        "seen_game": str(game.pk),
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


class _HiddenInputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("type") == "hidden":
            name = attributes.get("name")
            if name:
                self.values[name] = attributes.get("value") or ""


def _hidden_inputs(html: str) -> dict[str, str]:
    """What a re-rendered page posts back unchanged."""
    parser = _HiddenInputs()
    parser.feed(html)
    return parser.values


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
    sections = [
        dialog.split("</dialog>", 1)[0]
        for dialog in html.split("<dialog")[1:]
        if "data-log-section=" in dialog.split(">", 1)[0]
    ]
    assert len(sections) == 2
    for body in sections:
        assert f'{MODAL_ATTRIBUTES["panel"]}=""' in body
        assert f'{MODAL_ATTRIBUTES["header"]}=""' in body


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
        "note",
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


def test_a_game_the_page_never_showed_writes_nothing_and_shows_its_own(
    logged_in, owned_library, game
):
    hades = create_tracked_game(
        owned_library, "Hades", status=PlayerGameStatus.COMPLETED
    )

    response = _post(
        logged_in,
        hades,
        _press(hades, seen_game=str(game.pk), status="shelved"),
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert STALE_GAME in html
    assert 'name="status_seen" value="completed"' in html
    assert 'name="seen_game" value="' + str(hades.pk) + '"' in html
    assert PlayerGame.objects.get(library=owned_library, game=hades).status == (
        PlayerGameStatus.COMPLETED
    )


def test_a_refusal_after_a_write_keeps_it_says_so_and_a_second_press_adds_nothing(
    logged_in, owned_library, game, monkeypatch
):
    pc = Platform.objects.create(library=owned_library, name="PC")
    default_graph(game, owned_library, platform=pc)
    real_record_facts = writes_log_game.record_facts
    refused_once: list[bool] = []

    def refuse_the_first_status(actor, game_, **kwargs):
        if "status" in kwargs and not refused_once:
            refused_once.append(True)
            raise CommandFailed("That game is removed.", 409)
        return real_record_facts(actor, game_, **kwargs)

    monkeypatch.setattr(writes_log_game, "record_facts", refuse_the_first_status)

    first = _post(
        logged_in,
        game,
        _press(
            game,
            platform=str(pc.pk),
            status="completed",
            duration_hours="2",
            duration_minutes="0",
        ),
    )

    html = first.content.decode()
    assert first.status_code == 409
    assert (
        "Saved: the copy and the playtime. Fix the field below and save again." in html
    )
    assert 'name="attempt" value="1"' in html
    assert 'name="duration_hours" value="2"' not in html
    assert LibraryEntry.objects.filter(library=owned_library).count() == 1
    assert PlayerSession.objects.filter(library=owned_library).count() == 1

    second = _post(
        logged_in,
        game,
        _press(
            game,
            platform=str(pc.pk),
            platform_seen=str(pc.pk),
            status="completed",
            attempt="1",
        ),
    )

    assert second.status_code == 302
    assert LibraryEntry.objects.filter(library=owned_library).count() == 1
    assert PlayerSession.objects.filter(library=owned_library).count() == 1
    assert Playthrough.objects.filter(library=owned_library).count() == 1
    assert PlayerGame.objects.get(library=owned_library, game=game).status == (
        PlayerGameStatus.COMPLETED
    )


def test_a_refused_note_opens_the_more_section(logged_in, game, monkeypatch):
    refusal = LogRefused(
        "note", CommandFailed("That run is removed.", 409), frozenset()
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    response = _post(logged_in, game, _press(game, note="Kept"))

    html = response.content.decode()
    assert 'open-section="more"' in html
    assert "That run is removed." in html


def test_a_refused_mastered_opens_the_more_section(logged_in, game, monkeypatch):
    refusal = LogRefused(
        "mastered", CommandFailed("That game is removed.", 409), frozenset()
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    response = _post(logged_in, game, _press(game, mastered="True"))

    assert 'open-section="more"' in response.content.decode()


def test_a_refused_track_marks_the_game_field(logged_in, owned_library, monkeypatch):
    untracked = Game.objects.create(library=owned_library, name="Celeste")
    refusal = LogRefused(
        "track", CommandFailed("Restore it instead.", 409), frozenset()
    )

    def refuse(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(log_game_view, "log_game", refuse)

    html = _post(logged_in, untracked, _press(untracked)).content.decode()

    sentence = html.index("Restore it instead.")
    assert html.index('name="game"') < sentence < html.index('name="status"')


@pytest.mark.untracked_games
def test_a_new_tracked_game_says_so_on_the_redirect(logged_in, owned_library):
    untracked = Game.objects.create(library=owned_library, name="Celeste")

    response = _post(logged_in, untracked, _press(untracked))

    texts = [message.message for message in get_messages(response.wsgi_request)]
    assert "Celeste is now tracked in your library." in texts


def test_a_malformed_prefill_game_is_logged(logged_in, capture_games_logger):
    with capture_games_logger() as captured:
        logged_in.get(f"{reverse('games:log_game')}?prefill_game=not-a-key")

    assert any(
        record.name == "games.opener_facts"
        and record.levelno == logging.WARNING
        and "prefill_game" in record.getMessage()
        for record in captured.records
    )


def test_a_refused_status_keeps_mastery_and_the_unticked_resubmit_clears_it(
    logged_in, owned_library, game, monkeypatch
):
    real_record_facts = writes_log_game.record_facts
    refused: list[bool] = []

    def refuse_the_first_status(actor, game_, **kwargs):
        if "status" in kwargs and not refused:
            refused.append(True)
            raise CommandFailed("That game is removed.", 409)
        return real_record_facts(actor, game_, **kwargs)

    monkeypatch.setattr(writes_log_game, "record_facts", refuse_the_first_status)

    first = _post(
        logged_in,
        game,
        _press(game, mastered="on", mastered_seen="False", status="completed"),
    )
    assert first.status_code == 409
    assert PlayerGame.objects.get(library=owned_library, game=game).mastered is True

    resubmit = _hidden_inputs(first.content.decode()) | {
        "game": str(game.pk),
        "status": "completed",
        "playtime_kind": "session",
    }
    second = _post(logged_in, game, resubmit)

    assert second.status_code == 302
    assert PlayerGame.objects.get(library=owned_library, game=game).mastered is False


def test_a_removed_run_names_the_page_not_a_hidden_field(
    logged_in, owned_library, game
):
    run = state_run(owned_library.user, game, note="Gone")
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    response = _post(logged_in, game, _press(game, run=str(run.pk)))

    assert response.status_code == 200
    assert PICKED_RUN_GONE in response.content.decode()


def test_a_malformed_attempt_names_the_page(logged_in, game):
    response = _post(logged_in, game, _press(game, attempt="x"))

    assert response.status_code == 200
    assert STALE_FORM in response.content.decode()


def test_a_row_gone_after_the_copy_says_what_was_kept(
    logged_in, owned_library, game, monkeypatch
):
    pc = Platform.objects.create(library=owned_library, name="PC")
    default_graph(game, owned_library, platform=pc)

    def vanish(*args, **kwargs):
        raise Http404("No such game.")

    monkeypatch.setattr(writes_log_game, "record_facts", vanish)

    response = _post(
        logged_in,
        game,
        _press(game, platform=str(pc.pk), status="completed"),
    )

    assert response.status_code == 409
    html = response.content.decode()
    assert "Saved: the copy. Fix the field below and save again." in html
    assert "Something in this log is gone." in html


def test_a_created_release_and_run_are_named_as_saved(
    logged_in, owned_library, game, monkeypatch
):
    pc = Platform.objects.create(library=owned_library, name="PC")
    Playthrough.objects.filter(library=owned_library, player_game__game=game).update(
        removed_at=timezone.now()
    )
    real_record_facts = writes_log_game.record_facts
    refused: list[bool] = []

    def refuse_the_first_status(actor, game_, **kwargs):
        if "status" in kwargs and not refused:
            refused.append(True)
            raise CommandFailed("That game is removed.", 409)
        return real_record_facts(actor, game_, **kwargs)

    monkeypatch.setattr(writes_log_game, "record_facts", refuse_the_first_status)

    response = _post(
        logged_in,
        game,
        _press(
            game,
            platform=str(pc.pk),
            status="completed",
            duration_hours="2",
            duration_minutes="0",
        ),
    )

    html = response.content.decode()
    assert response.status_code == 409
    assert (
        "Saved: a release on that platform, the copy, a playthrough and the playtime."
        in html
    )
