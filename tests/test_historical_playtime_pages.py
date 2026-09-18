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
from statistic_cards import statistic_card

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


def trigger(html: str, element_id: str) -> str:
    """One whole stat: its visible value, and any line beneath it.

    ``Popover`` carries the id on its hidden panel, which follows the
    trigger, and a header stat states its second line after the popover
    rather than inside it, so the stat ends where the next one starts.
    """
    panel = html.index(f'id="{element_id}"')
    start = html.rindex("<pop-over", 0, panel)
    following = html.find("<pop-over", panel)
    return html[start : following if following != -1 else len(html)]


def figure(html: str, element_id: str) -> str:
    """One table cell's whole figure.

    A split states its second line as a sibling of the popover rather than
    inside it, so that a figure with no historical part renders exactly what
    it rendered before. Reading both lines therefore means reading the cell.
    """
    panel = html.index(f'id="{element_id}"')
    return html[html.rindex("<pop-over", 0, panel) : html.index("</td>", panel)]


@pytest.mark.django_db
def test_game_detail_hours_add_the_record_alone(client, owned_user):
    game = Game.objects.create(library=owned_user.library, name="Tunic")
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(game, started_at=start, ended_at=start + HOUR)
    record_row([tracked_run(owned_user.library, game)], duration=2 * HOUR)
    client.force_login(owned_user)

    html = client.get(game.get_absolute_url()).content.decode()
    hours = trigger(html, "popover-hours")

    #: The visible line states the viewer's profile, decimal hours by default.
    assert "3.0 h" in hours
    #: The word follows the value's own spans, so it is not contiguous with it.
    assert "1.0 h" in hours
    assert "</span> tracked" in hours
    assert "2.0 h" in hours
    assert "</span> historical" in hours


@pytest.mark.django_db
def test_game_detail_states_no_split_without_a_record(client, owned_user):
    """The headline of a game nothing recorded reads as it did."""
    game = Game.objects.create(library=owned_user.library, name="Tunic")
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(game, started_at=start, ended_at=start + HOUR)
    client.force_login(owned_user)

    html = client.get(game.get_absolute_url()).content.decode()
    hours = trigger(html, "popover-hours")

    assert "1.0 h" in hours
    assert "tracked" not in hours
    assert "historical" not in hours


@pytest.mark.django_db
def test_the_stats_page_states_the_split_on_every_playtime_row(client, owned_user):
    """Hours, the month rows and the platform rows all name both sources."""
    library = owned_user.library
    platform = Platform.objects.create(name="PC", icon="pc")
    played = Game.objects.create(library=library, name="Played")
    recorded = Game.objects.create(library=library, name="Recorded", platform=platform)
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(played, started_at=start, ended_at=start + HOUR)
    record_row([tracked_run(library, recorded)], duration=3 * HOUR, when="2022-06")
    client.force_login(owned_user)

    html = client.get(reverse("games:stats_by_year", args=[2022])).content.decode()

    hours = figure(html, "duration-stats-total-hours")
    assert "4.0 h" in hours
    assert "1.0 h" in hours
    assert "</span> tracked" in hours
    assert "3.0 h" in hours
    assert "</span> historical" in hours

    month = figure(html, "duration-stats-month-6")
    assert "</span> historical" in month
    #: The row keeps the filter link this issue leaves to #1105.
    assert "href=" in month

    platform_row = figure(html, f"duration-stats-platform-{platform.pk}")
    assert "</span> historical" in platform_row
    assert "href=" in platform_row


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


@pytest.mark.django_db
def test_the_navbar_states_the_split_and_carries_no_link(owned_user):
    """The session list cannot show a record, so the figure links nowhere."""
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

    counts = model_counts(request)
    today = str(counts["today_played"])

    assert "</span> tracked" in today
    assert "</span> historical" in today
    assert "href=" not in today


@pytest.mark.django_db
def test_the_library_playtime_card_states_the_split_and_no_link(client, owned_user):
    """The card states playtime, not a count of two populations."""
    game = Game.objects.create(library=owned_user.library, name="Tunic")
    start = datetime(2022, 3, 1, 10, tzinfo=UTC)
    session_row(game, started_at=start, ended_at=start + HOUR)
    record_row([tracked_run(owned_user.library, game)], duration=2 * HOUR)
    client.force_login(owned_user)

    body = client.get(reverse("games:library")).content.decode()
    card = statistic_card(body, "Playtime")

    assert 'title="Tracked sessions and historical records"' in card
    assert "3.0 h" in card
    assert "</span> tracked" in card
    assert "</span> historical" in card
    #: The session list shows only one of the two populations the figure
    #: sums, so the card states it and links nowhere.
    assert "<a " not in card
