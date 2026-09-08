"""#687: the screens state runs, not rows."""

import json
import uuid
from datetime import UTC, date, datetime

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from playthrough_conversion import convert_and_take_runs

from games.backfill.playthrough import convert_library
from games.models import (
    Game,
    LibraryEvent,
    PlayEvent,
    Playthrough,
    PlaythroughKind,
    Session,
)
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import remove_run
from timetracker.temporal import TemporalValue


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_adding_a_playthrough_writes_no_legacy_row(client, user, game):
    client.force_login(user)

    client.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "12h",
        },
    )

    assert PlayEvent.objects.count() == 0
    run = Playthrough.objects.get(player_game__game=game)
    assert run.note == "12h"
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_marking_finished_states_the_status_under_one_correlation_id(
    client, user, game
):
    client.force_login(user)

    client.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    correlations = set(
        LibraryEvent.objects.filter(library=user.library)
        .exclude(event_type__startswith="library.playergame.tracked")
        .values_list("correlation_id", flat=True)
    )
    assert len(correlations) == 1


@pytest.mark.django_db(transaction=True)
def test_editing_a_converted_row_states_the_difference(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    [run] = convert_and_take_runs(user.library, game)
    client.force_login(user)

    client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "read"},
    )

    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == ""


@pytest.mark.django_db(transaction=True)
def test_a_second_edit_does_not_revert_the_first(client, user, game):
    """The form is seeded off the run, never the row.

    Nothing writes the legacy row any more, so seeding the
    second edit from it would post the frozen day back over
    what the first edit stated.
    """
    PlayEvent.objects.create(game=game, started=date(2026, 1, 2), ended=None, note="")
    [run] = convert_and_take_runs(user.library, game)
    client.force_login(user)

    client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(game.pk), "started": "2026-03-04", "ended": "", "note": ""},
    )
    response = client.get(reverse("games:edit_playthrough", args=[run.pk]))

    assert response.status_code == 200
    assert b"2026-03-04" in response.content
    assert b"2026-01-02" not in response.content


@pytest.mark.django_db(transaction=True)
def test_a_run_stating_more_than_a_day_leaves_the_edit_page(client, user, game):
    """#1015 owns the screen that states a month."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    [run] = convert_and_take_runs(user.library, game)
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_month(2026, 3)
    )
    client.force_login(user)

    response = client.get(reverse("games:edit_playthrough", args=[run.pk]))

    assert response.status_code == 302
    assert any(
        "cannot hold" in str(message) for message in get_messages(response.wsgi_request)
    )


@pytest.mark.django_db(transaction=True)
def test_removing_the_only_run_is_refused_on_the_confirmation(client, user, game):
    #: Tracking states a run of its own, so the conversion
    #: leaves two. That one goes first, and the converted
    #: row is then the only run the game has left.
    PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    [converted] = convert_and_take_runs(user.library, game)
    remove_run(
        user,
        Playthrough.objects.exclude(pk=converted.pk).get(player_game__game=game),
        correlation_id=new_correlation_id(),
    )
    client.force_login(user)

    response = client.post(reverse("games:remove_playthrough", args=[converted.pk]))

    assert response.status_code == 409
    assert b"only playthrough of that game" in response.content
    converted.refresh_from_db()
    assert converted.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_removing_one_of_two_runs_stamps_the_projection_only(client, user, game):
    PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    second = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    other, run = convert_and_take_runs(user.library, game)
    client.force_login(user)

    response = client.post(reverse("games:remove_playthrough", args=[run.pk]))

    assert response.status_code == 302
    run.refresh_from_db()
    assert run.removed_at is not None
    second.refresh_from_db()
    assert second.removed_at is None
    #: The other run stays, so one remains.
    other.refresh_from_db()
    assert other.removed_at is None


def _second_run(run: Playthrough) -> Playthrough:
    """Another run at the tracked game."""
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


@pytest.mark.django_db
def test_the_page_numbers_a_run_as_game_detail_does(client, user, game):
    """The number counts the game's every run."""
    _second_run(Playthrough.objects.get(player_game__game=game))
    client.force_login(user)

    listed = client.get(
        reverse("games:list_playthroughs") + "?sort=-created"
    ).content.decode()
    detail = client.get(game.get_absolute_url()).content.decode()

    assert "Playthrough 2" in listed
    assert "Playthrough 2" in detail


@pytest.mark.django_db
def test_the_page_names_the_run_in_its_actions(client, user, game):
    """The list page names runs in actions."""
    run = Playthrough.objects.get(player_game__game=game)
    client.force_login(user)

    body = client.get(reverse("games:list_playthroughs")).content.decode()

    assert reverse("games:edit_playthrough", args=[run.pk]) in body
    assert reverse("games:remove_playthrough", args=[run.pk]) in body


@pytest.mark.django_db(transaction=True)
def test_the_page_renders_no_row_a_conversion_left_behind(client, user, game):
    """An unconverted legacy row reaches nothing."""
    other = Game.objects.create(library=user.library, name="Tunic")
    PlayEvent.objects.create(game=other, started=None, ended=None, note="")
    Playthrough.objects.filter(player_game__game=other).update(
        removed_at=timezone.now()
    )
    client.force_login(user)

    response = client.get(reverse("games:list_playthroughs"))

    assert response.status_code == 200
    body = response.content.decode()
    assert game.name in body
    assert other.name not in body


@pytest.mark.django_db(transaction=True)
def test_a_legacy_row_id_reaches_no_page(client, user, game):
    """#1012 moved the routes onto the run."""
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library)
    client.force_login(user)

    response = client.get(reverse("games:edit_playthrough", args=[row.pk]))

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_reaches_no_page(client, user, game):
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())
    client.force_login(user)

    assert (
        client.get(reverse("games:edit_playthrough", args=[run.pk])).status_code == 404
    )
    assert (
        client.get(reverse("games:remove_playthrough", args=[run.pk])).status_code
        == 404
    )


@pytest.mark.django_db(transaction=True)
def test_a_run_naming_another_librarys_tracked_game_reaches_no_page(
    client, user, game, django_user_model
):
    """Drift must not render another library's game."""
    stranger = django_user_model.objects.create_user(
        username="drift-stranger", password="p"
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(library=stranger.library)
    client.force_login(stranger)

    response = client.get(reverse("games:edit_playthrough", args=[run.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_prefill_seeds_from_the_greatest_stated_completion(
    client, user, owned_library, game
):
    """The day after the last run finished."""
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 5, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 5, 1, 12, tzinfo=UTC),
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(date(2026, 1, 10)),
    )
    client.force_login(user)

    body = client.get(
        reverse("games:add_playthrough_for_game", args=[game.pk])
    ).content.decode()

    assert "2026-01-11" in body


@pytest.mark.django_db
def test_the_prefill_seeds_nothing_from_a_completion_with_no_day(client, user, game):
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 5, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(2026, 5, 1, 12, tzinfo=UTC),
    )
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(
        completion_recorded_at=timezone.now(), completed=None
    )
    client.force_login(user)

    body = client.get(
        reverse("games:add_playthrough_for_game", args=[game.pk])
    ).content.decode()

    #: No finish day, so the earliest session.
    assert "2026-05-01" in body


@pytest.mark.django_db
def test_a_bookmarked_ended_filter_keeps_the_quick_bar(client, user, game):
    """The old word reaches the bar as the new one."""
    client.force_login(user)
    legacy = json.dumps({"ended": {"value": "2020-01-01", "modifier": "GREATER_THAN"}})

    body = client.get(
        reverse("games:list_playthroughs"), {"filter": legacy}
    ).content.decode()

    assert "Advanced filter active" not in body
