"""Pages that show playtime count historical records."""

from datetime import UTC, datetime, time, timedelta

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import session_row, tracked_run

from games.models import Game, Platform
from games.views.general import model_counts

HOUR = timedelta(hours=1)


def element(html: str, element_id: str) -> str:
    """Markup from one id to the next."""
    start = html.index(f'id="{element_id}"')
    end = html.find(' id="', start + 1)
    return html[start:end]


@pytest.mark.django_db
def test_the_navbar_adds_todays_record_in_two_queries(owned_user):
    game = Game.objects.create(library=owned_user.library, name="Tunic")
    noon = timezone.make_aware(datetime.combine(timezone.localdate(), time(12)))
    session_row(game, started_at=noon, ended_at=noon + HOUR)
    record_row(
        [tracked_run(owned_user.library, game)],
        duration=2 * HOUR,
        when=timezone.localdate().isoformat(),
    )
    request = RequestFactory().get("/")
    request.user = owned_user

    with CaptureQueriesContext(connection) as queries:
        counts = model_counts(request)

    assert "3 h 00 m" in str(counts["today_played"])
    assert "3 h 00 m" in str(counts["last_7_played"])
    summed = [query for query in queries if "SUM(" in query["sql"]]
    assert len(summed) == 2


@pytest.mark.django_db
def test_game_detail_hours_add_the_record_alone(client, owned_user):
    game = Game.objects.create(library=owned_user.library, name="Tunic")
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(game, started_at=start, ended_at=start + HOUR)
    record_row([tracked_run(owned_user.library, game)], duration=2 * HOUR)
    client.force_login(owned_user)

    html = client.get(game.get_absolute_url()).content.decode()
    hours = html[html.index('id="popover-hours"') : html.index('id="popover-sessions"')]

    assert "3 h 00 m" in hours
    assert "1 h 00 m" not in hours


@pytest.mark.django_db
def test_the_stats_page_renders_the_composed_figures(client, owned_user):
    library = owned_user.library
    platform = Platform.objects.create(name="PC", icon="pc")
    played = Game.objects.create(library=library, name="Played")
    recorded = Game.objects.create(library=library, name="Recorded", platform=platform)
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(played, started_at=start, ended_at=start + HOUR)
    record_row([tracked_run(library, recorded)], duration=3 * HOUR, when="2022-06")
    client.force_login(owned_user)

    html = client.get(reverse("games:stats_by_year", args=[2022])).content.decode()

    assert "4 h 00 m" in element(html, "duration-stats-total-hours")
    assert "3 h 00 m" in element(html, "duration-stats-month-6")
    assert "3 h 00 m" in element(html, f"duration-stats-platform-{platform.pk}")
    assert "3 h 00 m" in element(html, f"duration-stats-game-{recorded.pk}-playtime")
