"""What the line is told to offer."""

import pytest
from django.urls import reverse

from games.bulk_tray import tray_actions
from games.views.bulk import STATEMENT_FIELD

ORIGIN = "/session/list"


def test_an_act_is_offered_with_its_label_and_its_route():
    offered = tray_actions("session.remove", origin=ORIGIN)

    assert len(offered) == 1
    assert offered[0]["label"] == "Remove"
    assert offered[0]["cardinality"] == "many"
    assert "/bulk/session.remove/" in offered[0]["url"]


def test_the_url_carries_the_page_the_person_stands_on():
    offered = tray_actions("session.reclassify", origin=ORIGIN)

    assert "origin=%2Fsession%2Flist" in offered[0]["url"]


def test_every_named_act_is_offered_in_the_order_it_was_named():
    offered = tray_actions("session.reclassify", "session.remove", origin=ORIGIN)

    assert [action["label"] for action in offered] == [
        "Record as historical playtime",
        "Remove",
    ]


def test_a_name_no_act_declares_is_refused():
    """The view stated it, so a quiet omission would hide the typo."""
    with pytest.raises(ValueError, match="no declared act"):
        tray_actions("session.remoove", origin=ORIGIN)


def test_the_line_and_the_route_spell_the_statement_one_way():
    from common.components import SELECTION_STATEMENT_FIELD

    assert STATEMENT_FIELD == SELECTION_STATEMENT_FIELD


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


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_session_list_names_its_rows_and_offers_two_acts(
    client_in, owned_user, owned_library, game
):
    session = _a_session(owned_user, owned_library, game)

    html = client_in.get(reverse("games:list_sessions")).content.decode()

    assert f'data-selection-key="{session.pk}"' in html
    assert "data-selection-actions-form" in html
    assert "/bulk/session.remove/" in html
    assert "/bulk/session.reclassify/" in html


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
