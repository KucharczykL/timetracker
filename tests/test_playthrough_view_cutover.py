"""#687: the lifecycle screens state runs, and write no legacy row."""

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from games.backfill.playthrough import convert_library
from games.models import Game, LibraryEvent, PlayEvent, Playthrough
from games.reads.playthrough_provenance import run_for_row


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
        reverse("games:add_playevent"),
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
        reverse("games:add_playevent"),
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
    convert_library(user.library)
    client.force_login(user)

    client.post(
        reverse("games:edit_playevent", args=[row.pk]),
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "read"},
    )

    run = run_for_row(user.library, row.pk)
    assert run is not None
    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == ""


@pytest.mark.django_db(transaction=True)
def test_a_row_with_no_run_is_refused_on_the_edit_page(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    client.force_login(user)

    response = client.get(reverse("games:edit_playevent", args=[row.pk]))

    assert response.status_code == 302
    sentences = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("was never converted" in sentence for sentence in sentences)
