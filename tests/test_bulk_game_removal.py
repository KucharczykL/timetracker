"""Remove games from the library, in bulk and per row.

The act states the library's own fact; the catalog row is stamped only
where the library owns it, and a shared one is never touched.
"""

import html as html_module
import json
import uuid
from datetime import date, timedelta

import pytest
from django.urls import reverse
from session_rows import duration_only_row

from games.bulk_actions import BULK_ACTIONS, RowOutcome
from games.bulk_removal import GAME_GONE
from games.models import Game, Platform, PlayerGame, Purchase
from games.reads.events import batch_aggregate_ids
from games.reads.game_departures import game_departures
from games.removal import remove
from games.views.game_menu import game_row_menu
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    remove_from_library,
    restore_to_library,
    track_game,
)

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def action():
    return BULK_ACTIONS["playergame.remove"]


@pytest.fixture
def platform():
    return Platform.objects.create(name="PC")


@pytest.fixture
def owned(owned_user, owned_library, platform):
    game = Game.objects.create(
        library=owned_library,
        name="Outer Wilds",
        sort_name="Outer Wilds",
        platform=platform,
        year_released=2019,
    )
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


@pytest.fixture
def shared(owned_user):
    game = Game.objects.create(
        library=None, name="Celeste", sort_name="Celeste", year_released=2018
    )
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _run(action, actor, game, correlation_id=None):
    return action.run(
        actor,
        game,
        choice=None,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id or uuid.uuid7(),
    )


def _undo(action, actor, player_game_id):
    return action.inverse(
        actor,
        player_game_id,
        undoes=uuid.uuid7(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


def _tracked(library, game) -> PlayerGame:
    return PlayerGame.objects.get(library=library, game=game)


# ── The rows ─────────────────────────────────────────────────────────────────


def test_the_scope_is_the_lists_read_shared_games_included(
    action, owned_library, owned, shared
):
    scoped = action.scope(owned_library, "")

    assert set(scoped.values_list("pk", flat=True)) == {owned.pk, shared.pk}


def test_the_scope_narrows_by_the_statements_filter(
    action, owned_library, owned, shared
):
    scoped = action.scope(
        owned_library,
        json.dumps({"name": {"value": "Celeste", "modifier": "EQUALS"}}),
    )

    assert list(scoped.values_list("pk", flat=True)) == [shared.pk]


def test_a_key_the_library_does_not_track_comes_out_lost(
    action, owned_library, owned, django_user_model
):
    stranger = django_user_model.objects.create_user("stranger", password="p")
    theirs = Game.objects.create(library=stranger.library, name="Hades")

    resolution = action.resolve(owned_library, [owned.pk, theirs.pk])

    assert [row.pk for row in resolution.rows] == [owned.pk]
    assert [(refused.key, refused.sentence) for refused in resolution.refused] == [
        (str(theirs.pk), GAME_GONE)
    ]
    assert resolution.refused[0].lost


def test_what_leaves_counts_live_rows_of_the_library(owned_library, owned):
    """As Game detail counts them: a removed purchase has left already."""
    kept, gone = (
        Purchase.objects.create(
            library=owned_library,
            name=name,
            date_purchased=date(2026, 1, 1),
            price=10,
            price_currency="USD",
        )
        for name in ("Kept", "Gone")
    )
    kept.games.add(owned)
    gone.games.add(owned)
    remove(gone)

    departing = game_departures(owned_library, owned)

    assert departing.purchases == 1
    #: Tracking states the default run, and no session.
    assert departing.runs == 1
    assert departing.sessions == 0


# ── The act ──────────────────────────────────────────────────────────────────


def test_removing_an_owned_game_untracks_it_and_stamps_the_row(
    action, owned_user, owned_library, owned
):
    correlation_id = uuid.uuid7()

    assert _run(action, owned_user, owned, correlation_id) is RowOutcome.MOVED

    owned.refresh_from_db()
    assert owned.removed_at is not None
    tracked = _tracked(owned_library, owned)
    assert tracked.removed_at is not None
    assert batch_aggregate_ids(
        owned_library, correlation_id, action.inverse_aggregate
    ) == [tracked.pk]


def test_removing_a_shared_game_never_stamps_the_catalog_row(
    action, owned_user, owned_library, shared
):
    _run(action, owned_user, shared)

    shared.refresh_from_db()
    assert shared.removed_at is None
    assert _tracked(owned_library, shared).removed_at is not None


def test_an_untracked_game_is_refused_and_stamped_nowhere(owned_user, owned_library):
    """A stamp with no event is a row the Undo cannot see."""
    game = Game.objects.create(library=owned_library, name="Never tracked")

    with pytest.raises(CommandFailed) as failure:
        remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    assert failure.value.status_code == CONFLICT_STATUS
    game.refresh_from_db()
    assert game.removed_at is None


def test_the_per_row_route_stamps_an_untracked_game(owned_user, owned_library):
    """Only through the explicit argument."""
    game = Game.objects.create(library=owned_library, name="Halfway")

    result = remove_from_library(
        owned_user, game, correlation_id=new_correlation_id(), stamp_untracked=True
    )

    assert result is None
    game.refresh_from_db()
    assert game.removed_at is not None


# ── The Undo ─────────────────────────────────────────────────────────────────


def test_the_undo_restores_an_owned_game(action, owned_user, owned_library, owned):
    _run(action, owned_user, owned)
    tracked = _tracked(owned_library, owned)

    assert _undo(action, owned_user, tracked.pk) is RowOutcome.MOVED

    owned.refresh_from_db()
    tracked.refresh_from_db()
    assert owned.removed_at is None
    assert tracked.removed_at is None


def test_the_undo_retracks_a_shared_game_and_leaves_its_row(
    action, owned_user, owned_library, shared
):
    _run(action, owned_user, shared)
    tracked = _tracked(owned_library, shared)

    _undo(action, owned_user, tracked.pk)

    tracked.refresh_from_db()
    assert tracked.removed_at is None
    shared.refresh_from_db()
    assert shared.removed_at is None


def test_a_game_restored_since_the_batch_answers_unchanged(
    action, owned_user, owned_library, owned
):
    _run(action, owned_user, owned)
    owned.refresh_from_db()
    restore_to_library(owned_user, owned, correlation_id=new_correlation_id())

    outcome = _undo(action, owned_user, _tracked(owned_library, owned).pk)

    assert outcome is RowOutcome.UNCHANGED


def test_a_recreated_game_refuses_the_restore_and_changes_nothing(
    action, owned_user, owned_library, owned, platform
):
    """409 and a sentence, so one row cannot end the whole Undo."""
    _run(action, owned_user, owned)
    Game.objects.create(
        library=owned_library, name=owned.name, platform=platform, year_released=2019
    )
    tracked = _tracked(owned_library, owned)

    with pytest.raises(CommandFailed) as failure:
        _undo(action, owned_user, tracked.pk)

    assert failure.value.status_code == CONFLICT_STATUS
    assert "already holds another Outer Wilds on PC from 2019" in (
        failure.value.message
    )
    owned.refresh_from_db()
    tracked.refresh_from_db()
    assert owned.removed_at is not None
    assert tracked.removed_at is not None


def test_a_recreated_platformless_game_refuses_the_restore(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tetris", year_released=1984)
    track_game(owned_user, game, correlation_id=new_correlation_id())
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())
    Game.objects.create(library=owned_library, name="Tetris", year_released=1984)
    game.refresh_from_db()

    with pytest.raises(CommandFailed) as failure:
        restore_to_library(owned_user, game, correlation_id=new_correlation_id())

    assert failure.value.status_code == CONFLICT_STATUS
    assert "another Tetris from 1984" in failure.value.message


def test_a_same_name_game_on_another_platform_restores(
    owned_user, owned_library, owned
):
    remove_from_library(owned_user, owned, correlation_id=new_correlation_id())
    Game.objects.create(
        library=owned_library,
        name=owned.name,
        platform=Platform.objects.create(name="Switch"),
        year_released=2019,
    )
    owned.refresh_from_db()

    restore_to_library(owned_user, owned, correlation_id=new_correlation_id())

    owned.refresh_from_db()
    assert owned.removed_at is None


# ── Through the runner ───────────────────────────────────────────────────────


def _statement(*keys) -> str:
    return json.dumps({"mode": "some", "keys": sorted(str(key) for key in keys)})


def _hidden(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name in ("submission", "progress"):
        marker = f'name="{name}" value="'
        if marker in html:
            start = html.index(marker) + len(marker)
            fields[name] = html_module.unescape(html[start : html.index('"', start)])
    return fields


def test_the_confirmation_states_what_leaves_with_each_game(logged_in, owned, shared):
    url = reverse("games:run_bulk_action", args=["playergame.remove"])

    html = logged_in.post(
        url, {"selection": _statement(owned.pk, shared.pk)}
    ).content.decode()

    for heading in ("Game", "Sessions", "Purchases", "Playthroughs"):
        assert heading in html
    assert "Remove 2 games" in html
    assert html.count("data-bulk-sample-row") == 2
    #: `sort_name` order.
    assert html.index("Celeste") < html.index("Outer Wilds")


def test_the_act_removes_both_kinds_of_row(logged_in, owned_library, owned, shared):
    url = reverse("games:run_bulk_action", args=["playergame.remove"])
    statement = _statement(owned.pk, shared.pk)
    confirmation = logged_in.post(url, {"selection": statement})

    logged_in.post(
        url, {"selection": statement, **_hidden(confirmation.content.decode())}
    )

    owned.refresh_from_db()
    shared.refresh_from_db()
    assert owned.removed_at is not None
    assert shared.removed_at is None
    assert not PlayerGame.objects.filter(
        library=owned_library, removed_at__isnull=True
    ).exists()


# ── The per-row routes ───────────────────────────────────────────────────────


def test_a_shared_game_is_removed_and_restored_per_row(
    logged_in, owned_library, shared
):
    """Before this, Remove on a shared row answered 404."""
    remove_url = reverse("games:remove_game", args=[shared.pk])

    assert logged_in.get(remove_url).status_code == 200
    logged_in.post(remove_url)

    shared.refresh_from_db()
    assert shared.removed_at is None
    assert _tracked(owned_library, shared).removed_at is not None

    logged_in.post(reverse("games:restore_game", args=[shared.pk]))

    assert _tracked(owned_library, shared).removed_at is None


def test_a_shared_game_the_library_never_tracked_is_not_found(logged_in):
    stranger = Game.objects.create(library=None, name="Untracked shared")

    assert (
        logged_in.get(reverse("games:remove_game", args=[stranger.pk])).status_code
        == 404
    )
    assert (
        logged_in.post(reverse("games:restore_game", args=[stranger.pk])).status_code
        == 404
    )


def test_a_halfway_removal_is_reachable_and_completes(
    logged_in, owned_user, owned_library, owned, monkeypatch
):
    """Untracked by the batch, unstamped by a defect: off every list."""
    import games.writes.playergame as writes

    def broken(instance):
        raise RuntimeError("the stamp met a defect")

    monkeypatch.setattr(writes, "remove", broken)
    with pytest.raises(RuntimeError):
        remove_from_library(owned_user, owned, correlation_id=new_correlation_id())
    monkeypatch.undo()
    owned.refresh_from_db()
    assert owned.removed_at is None
    assert _tracked(owned_library, owned).removed_at is not None

    remove_url = reverse("games:remove_game", args=[owned.pk])
    assert logged_in.get(remove_url).status_code == 200
    logged_in.post(remove_url)

    owned.refresh_from_db()
    assert owned.removed_at is not None


# ── The row menu ─────────────────────────────────────────────────────────────


def test_an_owned_row_offers_edit_and_remove(owned):
    html = str(game_row_menu(owned, origin=None))

    assert reverse("games:edit_game", args=[owned.pk]) in html
    assert reverse("games:remove_game", args=[owned.pk]) in html
    assert "Outer Wilds (PC) actions" in html


def test_a_shared_row_offers_no_edit(shared):
    html = str(game_row_menu(shared, origin=None))

    assert reverse("games:edit_game", args=[shared.pk]) not in html
    assert reverse("games:remove_game", args=[shared.pk]) in html
    assert "Celeste actions" in html


def test_the_list_carries_the_selection_and_no_actions_column(logged_in, owned):
    html = logged_in.get(reverse("games:list_games")).content.decode()

    assert ">Actions<" not in html
    assert "selectable-table" in html
    assert f"game-menu-{owned.pk}" in html
    assert reverse("games:run_bulk_action", args=["playergame.remove"]) in html


# ── Two libraries, one shared row ────────────────────────────────────────────


@pytest.fixture
def neighbour(django_user_model, shared):
    """A second library tracking the same shared catalog row."""
    user = django_user_model.objects.create_user("neighbour", password="p")
    track_game(user, shared, correlation_id=new_correlation_id())
    return user


def test_a_removal_leaves_the_other_librarys_row_alone(
    action, owned_user, owned_library, neighbour, shared
):
    """The act states one library's fact and no other's."""
    _run(action, owned_user, shared)

    shared.refresh_from_db()
    assert shared.removed_at is None
    assert _tracked(owned_library, shared).removed_at is not None
    assert _tracked(neighbour.library, shared).removed_at is None
    assert shared.pk in set(
        Game.objects.tracked_by(neighbour.library).values_list("pk", flat=True)
    )


def test_an_undo_puts_back_one_library_and_not_the_other(
    action, owned_user, owned_library, neighbour, shared
):
    _run(action, owned_user, shared)
    _run(action, neighbour, shared)

    _undo(action, owned_user, _tracked(owned_library, shared).pk)

    assert _tracked(owned_library, shared).removed_at is None
    assert _tracked(neighbour.library, shared).removed_at is not None


def test_what_leaves_counts_only_the_acting_librarys_rows(
    owned_library, neighbour, shared
):
    """A shared row's reverse accessors reach every library that holds it.

    Its purchases cannot: `validate_purchase_game_ownership` refuses a
    purchase naming a game another library owns, and a shared game is
    owned by nobody. The runs and their sessions are per library, so
    they are what a count could leak across one.
    """
    theirs = _tracked(neighbour.library, shared).playthroughs.get()
    duration_only_row(theirs, date(2026, 3, 1), timedelta(hours=2))

    ours = game_departures(owned_library, shared)
    assert (ours.sessions, ours.runs) == (0, 1)
    assert game_departures(neighbour.library, shared).sessions == 1


def test_the_counts_do_not_multiply_one_source_by_another(
    owned_library, owned_user, owned, platform
):
    """A join over sessions and purchases would report six of each."""
    for index in range(2):
        Purchase.objects.create(
            library=owned_library,
            name=f"Order {index}",
            date_purchased=date(2026, 1, index + 1),
            price=10,
            price_currency="USD",
        ).games.add(owned)
    run = _tracked(owned_library, owned).playthroughs.get()
    for index in range(3):
        duration_only_row(run, date(2026, 2, index + 1), timedelta(hours=1))

    departing = game_departures(owned_library, owned)

    assert (departing.sessions, departing.purchases) == (3, 2)


def test_a_shared_row_another_library_alone_tracks_is_not_found(
    logged_in, neighbour, owned_library
):
    """`removable_by` and `restorable_by` both scope their Exists."""
    theirs = Game.objects.create(
        library=None, name="Hollow Knight", sort_name="Hollow Knight"
    )
    track_game(neighbour, theirs, correlation_id=new_correlation_id())

    assert (
        logged_in.get(reverse("games:remove_game", args=[theirs.pk])).status_code == 404
    )
    assert (
        logged_in.post(reverse("games:restore_game", args=[theirs.pk])).status_code
        == 404
    )
    assert not PlayerGame.objects.filter(library=owned_library, game=theirs).exists()


# ── A removal a defect stopped ───────────────────────────────────────────────


def test_a_partly_removed_game_is_not_called_gone(
    action, owned_user, owned_library, owned, monkeypatch
):
    """It is sitting there; the tally names the remedy that reaches it."""
    import games.writes.playergame as writes

    def broken(instance):
        raise RuntimeError("the stamp met a defect")

    monkeypatch.setattr(writes, "remove", broken)
    with pytest.raises(RuntimeError):
        remove_from_library(owned_user, owned, correlation_id=new_correlation_id())
    monkeypatch.undo()

    resolution = action.resolve(owned_library, [owned.pk])

    assert resolution.rows == ()
    sentence = resolution.refused[0].sentence
    assert sentence != GAME_GONE
    assert owned.name in sentence
    assert "remove it again" in sentence
