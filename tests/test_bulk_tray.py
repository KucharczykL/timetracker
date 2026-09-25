"""What the line is told to offer."""

import json

import pytest
from django.urls import reverse

from games.bulk_tray import tray_actions
from games.views.bulk import STATEMENT_FIELD

ORIGIN = "/session/list"


def test_an_act_is_offered_with_its_label_and_its_route():
    offered = tray_actions("session.remove", origin=ORIGIN)

    assert len(offered) == 1
    assert offered[0]["label"] == "Remove"
    assert "/bulk/session.remove/" in offered[0]["url"]


def test_the_url_carries_the_page_the_person_stands_on():
    offered = tray_actions("session.reclassify", origin=ORIGIN)

    assert "origin=%2Fsession%2Flist" in offered[0]["url"]


def test_every_named_act_is_offered_in_the_order_it_was_named():
    offered = tray_actions(
        "session.reclassify", "session.move", "session.remove", origin=ORIGIN
    )

    assert [action["label"] for action in offered] == [
        "Record as historical playtime",
        "Move to playthrough…",
        "Remove",
    ]


def test_a_name_no_act_declares_is_refused():
    """The view stated it, so a quiet omission would hide the typo."""
    with pytest.raises(ValueError, match="no declared act"):
        tray_actions("session.remoove", origin=ORIGIN)


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_field_the_line_renders_is_the_field_the_route_reads(
    client_in, owned_user, owned_library, game
):
    """Posted under the name the page states, not a name a test knows.

    Comparing the two constants proves nothing: one is assigned from
    the other.
    """
    session = _a_session(owned_user, owned_library, game)
    html = client_in.get(reverse("games:list_sessions")).content.decode()
    form = html.split("data-selection-actions-form")[1].split("</form>")[0]
    field = form.split("data-selection-statement")[1]
    marker = 'name="'
    start = field.index(marker) + len(marker)
    rendered = field[start : field.index('"', start)]

    confirmation = client_in.post(
        reverse("games:run_bulk_action", args=["session.remove"]),
        {rendered: json.dumps({"mode": "some", "keys": [str(session.pk)]})},
    )

    assert rendered == STATEMENT_FIELD
    #: One row, so the heading says so. The tray could always select one.
    assert "Remove this session" in confirmation.content.decode()


# ── The pages that offer them ────────────────────────────────────────────────


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    from games.models import Game

    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _a_session(owned_user, owned_library, game):
    """One written-down session, and the record made beside it."""
    from datetime import date, timedelta

    from session_rows import duration_only_row, tracked_run

    return duration_only_row(
        tracked_run(owned_library, game), date(2026, 3, 5), timedelta(hours=2)
    )


def _a_record(owned_user, owned_library, game):
    import uuid
    from datetime import timedelta

    from session_rows import tracked_run

    from games.commands.historical_playtime import HistoricalPlaytimeStatement
    from games.models import HistoricalPlaytime, HistoricalPlaytimeProvenance
    from games.writes.historical_playtime import record_historical_playtime

    run = tracked_run(owned_library, game)
    record_id = record_historical_playtime(
        owned_user,
        HistoricalPlaytimeStatement(
            duration=timedelta(hours=100),
            when="2005",
            provenance=HistoricalPlaytimeProvenance.ESTIMATED,
            playthrough_ids=(run.pk,),
            device_id=None,
            emulated=False,
            note="",
        ),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )
    return HistoricalPlaytime.objects.get(pk=record_id)


#: The session list's acts, in the order the tray lays them out.
SESSION_ACTS = (
    "session.finish",
    "session.move",
    "session.edit",
    "session.reclassify",
    "session.remove",
)


def _tray(html: str) -> str:
    """The selection line's own acts, without the rows' menus."""
    start = html.index('data-selection-actions=""')
    return html[start : html.index("</selection-actions>", start)]


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_session_list_names_its_rows_and_offers_five_acts(
    client_in, owned_user, owned_library, game
):
    session = _a_session(owned_user, owned_library, game)

    html = client_in.get(reverse("games:list_sessions")).content.decode()

    assert f'data-selection-key="{session.pk}"' in html
    assert "data-selection-actions-form" in html
    for name in SESSION_ACTS:
        assert f"/bulk/{name}/" in _tray(html)


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_session_lists_acts_are_offered_in_one_order(
    client_in, owned_user, owned_library, game
):
    """The line reads in the row menu's order, and the removal trails.

    Read out of the tray alone. A row's own menu hands one row to the same
    act, so the page states the move's route once a row besides.
    """
    _a_session(owned_user, owned_library, game)

    tray = _tray(client_in.get(reverse("games:list_sessions")).content.decode())

    assert [tray.index(f"/bulk/{name}/") for name in SESSION_ACTS] == sorted(
        tray.index(f"/bulk/{name}/") for name in SESSION_ACTS
    )


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_historical_list_names_its_rows_and_offers_remove(
    client_in, owned_user, owned_library, game
):
    record = _a_record(owned_user, owned_library, game)

    html = client_in.get(reverse("games:list_historical_playtime")).content.decode()

    assert f'data-selection-key="{record.pk}"' in html
    assert "/bulk/historicalplaytime.remove/" in html


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_playthrough_list_names_its_rows_and_offers_remove(
    client_in, owned_user, owned_library, game
):
    from games.writes.playergame import new_correlation_id, track_game

    track_game(owned_user, game, correlation_id=new_correlation_id())
    from games.models import Playthrough

    run = Playthrough.objects.get(player_game__game=game)

    html = client_in.get(reverse("games:list_playthroughs")).content.decode()

    assert f'data-selection-key="{run.pk}"' in html
    assert "/bulk/playthrough.remove/" in html


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_game_detail_offers_both_acts_and_scopes_its_stored_selection(
    client_in, owned_user, owned_library, game
):
    """Two tables, and a scope that names the library holding them."""
    record = _a_record(owned_user, owned_library, game)
    from games.models import Playthrough

    run = Playthrough.objects.get(player_game__game=game)

    html = client_in.get(game.get_absolute_url()).content.decode()

    assert f'data-selection-key="{record.pk}"' in html
    assert f'data-selection-key="{run.pk}"' in html
    assert "/bulk/historicalplaytime.remove/" in html
    assert "/bulk/playthrough.remove/" in html
    #: Never an empty library segment: the next person at this
    #: browser would inherit the selection.
    assert f'scope="{owned_library.pk}:' in html


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_game_detail_can_state_no_wider_selection(
    client_in, owned_user, owned_library, game
):
    """Its acts scope the library, so the page must name its rows.

    Both sections declare an empty filter, which narrows nothing: an
    "all" statement from either would name every run and every record
    the library holds. No paginator is what keeps that statement
    unreachable, and this says so.
    """
    _a_record(owned_user, owned_library, game)

    html = client_in.get(game.get_absolute_url()).content.decode()

    assert "data-selection-all-matching" not in html
    assert 'count="0"' in html


#: The two colours the line keeps, and the one every other act takes.
def test_the_line_keeps_green_and_red_and_greys_the_rest():
    """Blue is the page's primary colour, and a line of four primaries
    names none of them. Only the act that adds and the act that takes
    away keep a colour; the rest read as ordinary."""
    from games.bulk_finish import FINISH_SESSION
    from games.bulk_move import MOVE
    from games.bulk_reclassification import RECLASSIFY
    from games.bulk_removal import REMOVE_SESSION
    from games.bulk_tray import tray_actions

    offered = tray_actions(
        FINISH_SESSION.name,
        MOVE.name,
        RECLASSIFY.name,
        REMOVE_SESSION.name,
        origin=None,
    )

    assert [act["color"] for act in offered] == ["green", "gray", "gray", "red"]


def test_an_act_keeps_its_own_colour_on_its_confirmation():
    """One page, one primary press: the act's blue belongs there."""
    from games.bulk_move import MOVE

    assert MOVE.color == "blue"
