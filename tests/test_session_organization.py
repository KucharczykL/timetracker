"""The two counts the organizer starts from."""

import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone
from entries import prerelease_release, record_entry
from session_rows import duration_only_row, tracked_run

from games.filters import filter_url, parse_session_filter
from games.models import Game, PlayerGame, Playthrough, PlaythroughKind
from games.reads.session_organization import (
    OrganizationCounts,
    before_start_filter,
    bucket_sessions_filter,
    organization_counts,
)
from timetracker.temporal import TemporalValue

AN_HOUR = timedelta(hours=1)
A_STATED_START = date(2022, 2, 1)
A_STATED_COMPLETION = date(2022, 4, 1)


def _dated_run(library, name):
    """One game's run, stating both endpoints."""
    game = Game.objects.create(library=library, name=name)
    run = tracked_run(library, game)
    run.started = TemporalValue.from_day(A_STATED_START)
    run.start_recorded_at = timezone.now()
    run.completed = TemporalValue.from_day(A_STATED_COMPLETION)
    run.completion_recorded_at = timezone.now()
    run.save()
    return run


def _bucket_run(library, name):
    game = Game.objects.create(library=library, name=name)
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=PlayerGame.objects.get(library=library, game=game),
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )


@pytest.fixture
def population(owned_library):
    """Before start, after completion, inside, bucketed."""
    run = _dated_run(owned_library, "Dated")
    duration_only_row(run, date(2021, 12, 30), AN_HOUR)
    duration_only_row(run, date(2024, 7, 1), AN_HOUR)
    duration_only_row(run, date(2022, 3, 2), AN_HOUR)
    duration_only_row(_bucket_run(owned_library, "Imported"), date(2022, 3, 2), AN_HOUR)
    return owned_library


@pytest.mark.django_db
def test_each_count_answers_its_own_filter(population):
    assert organization_counts(population) == OrganizationCounts(
        bucket=1, before_start=1
    )


@pytest.mark.django_db
def test_a_library_sees_none_of_another_librarys_rows(population, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger").library
    assert organization_counts(stranger) == OrganizationCounts(bucket=0, before_start=0)


@pytest.mark.django_db
def test_a_library_with_nothing_to_organize_counts_none(owned_library):
    assert organization_counts(owned_library) == OrganizationCounts(
        bucket=0, before_start=0
    )


@pytest.mark.django_db
@pytest.mark.parametrize("builder", [bucket_sessions_filter, before_start_filter])
def test_the_link_opens_the_session_list_on_the_same_filter(builder):
    parsed = urlparse(filter_url(builder()))
    assert parsed.path == reverse("games:list_sessions")
    stated = parse_qs(parsed.query)["filter"][0]
    assert parse_session_filter(stated) == builder()


@pytest.mark.django_db
def test_hiding_prerelease_play_moves_no_before_start_count(
    owned_library, stated_graph, set_user_setting
):
    """Demo play is out either way."""
    graph = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    record_entry(owned_library, graph.release)
    demo = prerelease_release(owned_library, graph.release)
    run = Playthrough.objects.get(player_game__game=graph.game)
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_day(A_STATED_START),
        start_recorded_at=timezone.now(),
    )
    duration_only_row(run, date(2021, 6, 1), AN_HOUR, release=demo)
    duration_only_row(run, date(2021, 6, 2), AN_HOUR, release=graph.release)

    counted = []
    for shown in ("show", "hide"):
        set_user_setting(owned_library.user, "SHOW_PRERELEASE_PLAY", shown)
        counted.append(organization_counts(owned_library).before_start)

    assert counted == [1, 1]
