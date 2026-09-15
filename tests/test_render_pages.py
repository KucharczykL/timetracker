"""Every read-only page, rendered to a file."""

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from session_rows import timed_row, tracked_run

from common.components.custom_elements import FILTER_MODE_MODELS
from games.management.commands.render_pages import (
    HOST,
    normalise,
    render_plan,
)
from games.models import Game, Platform, Purchase
from games.views.returns import READ_ONLY

pytestmark = pytest.mark.django_db


@pytest.fixture
def furnished(owned_user):
    library = owned_user.library
    platform = Platform.objects.create(library=library, name="PC")
    first = Game.objects.create(library=library, name="Outer Wilds", platform=platform)
    second = Game.objects.create(library=library, name="Tunic", platform=platform)
    purchase = Purchase.objects.create(
        library=library,
        price_currency="EUR",
        date_purchased=datetime(2024, 5, 1, tzinfo=UTC).date(),
        platform=platform,
        num_purchases=1,
    )
    purchase.games.add(first)
    #: Projection rows: the stats years and every session read come from them.
    for game, year in ((first, 2024), (second, 2025)):
        start = datetime(year, 6, 1, 10, tzinfo=UTC)
        timed_row(
            tracked_run(library, game),
            start,
            start + timedelta(hours=1),
            day_zone="UTC",
        )
    return owned_user


def names_of(urls) -> list[str]:
    return [rendered.name for rendered in urls]


def test_every_read_only_route_is_rendered_once_or_per_row(furnished):
    plan = render_plan(furnished)

    names = names_of(plan.urls)
    #: Mounted only under DEBUG; another test may have mounted it.
    assert set(plan.unmounted) <= {"games:settings_kit_preview"}
    assert set(names) | set(plan.unmounted) == set(READ_ONLY)
    assert names.count("games:view_game") == 2
    assert names.count("games:view_purchase") == 1
    assert names.count("games:stats_by_year") == 2
    assert names.count("games:filter_builder") == len(FILTER_MODE_MODELS)
    assert names.count("games:list_games") == 1


def test_a_list_is_rendered_whole(furnished):
    urls = {rendered.name: rendered.url for rendered in render_plan(furnished).urls}

    assert urls["games:list_games"].endswith("?per_page=0")
    assert urls["games:list_sessions"].endswith("?per_page=0")


def test_file_names_are_the_url(furnished):
    (rendered,) = [
        rendered
        for rendered in render_plan(furnished).urls
        if rendered.name == "games:list_games"
    ]

    assert rendered.url == "/tracker/game/list?per_page=0"
    assert rendered.file_name == "tracker_game_list_per_page=0.html"


def test_the_csrf_token_and_the_version_footer_are_normalised(furnished):
    client = Client(SERVER_NAME=HOST)
    client.force_login(furnished)

    first = client.get("/tracker/game/list").content.decode()
    second = client.get("/tracker/game/list").content.decode()

    assert first != second
    assert "csrfmiddlewaretoken" in first
    assert normalise(first) == normalise(second)
    assert 'value="CSRF"' in normalise(first)
    assert ">VERSION</span>" in normalise(first)


def test_the_command_writes_one_file_per_url_with_its_status_first(furnished, tmp_path):
    out = tmp_path / "pages"
    stdout = StringIO()

    call_command("render_pages", user=furnished.username, out=str(out), stdout=stdout)

    plan = render_plan(furnished)
    file_by_name = {rendered.name: out / rendered.file_name for rendered in plan.urls}
    files = sorted(out.iterdir())
    assert len(files) == len(plan.urls)
    admin = file_by_name["games:admin_settings"]
    assert admin.read_text().splitlines()[0] == "403"
    games = file_by_name["games:list_games"]
    assert games.read_text().splitlines()[0] == "200"
    assert "Outer Wilds" in games.read_text()
    assert f"Rendered {len(files)} page(s)" in stdout.getvalue()
    #: The index redirects; the two admin routes refuse a plain user.
    assert "3 answered other than 200" in stdout.getvalue()
    assert "  403 /tracker/admin-settings\n" in stdout.getvalue()
    assert "  302 /tracker/\n" in stdout.getvalue()
    for name in plan.unmounted:
        assert f"{name} is not mounted" in stdout.getvalue()


def test_the_command_refuses_a_non_empty_directory(furnished, tmp_path):
    (tmp_path / "stale.html").write_text("")

    with pytest.raises(CommandError, match="not empty"):
        call_command("render_pages", user=furnished.username, out=str(tmp_path))


def test_the_command_refuses_an_unknown_user(tmp_path):
    with pytest.raises(CommandError, match="No user"):
        call_command("render_pages", user="nobody", out=str(tmp_path / "x"))
