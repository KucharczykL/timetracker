"""End-to-end Playwright tests for the DatePicker element (issue #485):
add/edit Playthrough date fields under different account display
profiles, the calendar popup, live DATETIME_FORMAT changes, and the
JS-disabled native `<input type="date">` fallback.
"""

import json

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import expect
from stated_runs import state_run
from tracked_games import create_tracked_game

from common.components import DatePicker
from common.components.primitives import CsrfInput
from common.date_time_presentation import date_time_presentation_for_request
from games.commands.endpoint import ActStatement
from games.models import Game, Platform, UserPreferences
from timetracker.temporal import TemporalValue

# ── Real-app tests: add/edit Playthrough ────────────────────────────────────


@pytest.fixture
def authenticated_page(live_server, page, e2e_user):
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page, e2e_user


def _select_first_game(page):
    games = page.locator('search-select[name="games"], search-select[name="game"]')
    games.locator("[data-search-select-search]").click()
    games.locator("[data-search-select-option]").first.click()


def _fill_segments(page, container: str, values: dict) -> None:
    for part, value in values.items():
        page.locator(f'{container} input[data-date-part="{part}"]').click()
        page.keyboard.type(value)


STARTED = 'date-picker:has(input[name="started"]) [data-date-picker-field]'


def _part_names(page, field: str) -> list[str]:
    return page.locator(f"{field} input[data-date-part]").evaluate_all(
        "(els) => els.map(e => e.dataset.datePart)"
    )


def test_an_mdy_account_types_month_first_and_persists_the_same_day(
    authenticated_page, live_server
):
    """Display order moves; the day stays."""
    from games.models import Playthrough

    page, user = authenticated_page
    preferences = UserPreferences.objects.get(user=user)
    preferences.datetime_format = "mdy_12h"
    preferences.save(update_fields=["datetime_format"])
    game = Game.objects.create(library=user.library, name="Alpha Game")

    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    assert _part_names(page, STARTED) == ["month", "day", "year"]

    _select_first_game(page)
    _fill_segments(page, STARTED, {"month": "03", "day": "15", "year": "2026"})
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    run = Playthrough.objects.get(player_game__game=game)
    assert str(run.started_lower) == "2026-03-15"


def test_edit_playthrough_date_field_prefills_from_the_run(
    authenticated_page, live_server
):
    page, user = authenticated_page
    run = state_run(
        user,
        create_tracked_game(user.library, "Alpha Game"),
        started=ActStatement(TemporalValue.parse("2025-06-01"), ""),
    )

    page.goto(f"{live_server.url}{reverse('games:edit_playthrough', args=[run.pk])}")
    hidden = page.locator('input[name="started"][data-date-picker-hidden]')
    expect(hidden).to_have_value("2025-06-01")
    expect(page.locator(f'{STARTED} input[data-date-part="year"]')).to_have_value(
        "2025"
    )
    expect(page.locator(f'{STARTED} input[data-date-part="month"]')).to_have_value("06")
    expect(page.locator(f'{STARTED} input[data-date-part="day"]')).to_have_value("01")


def test_changing_datetime_format_updates_the_segment_order(
    authenticated_page, live_server
):
    """A format change reorders the segments."""
    page, user = authenticated_page

    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    assert _part_names(page, STARTED) == ["year", "month", "day"]

    preferences = UserPreferences.objects.get(user=user)
    preferences.datetime_format = "mdy_12h"
    preferences.save(update_fields=["datetime_format"])
    page.reload()
    assert _part_names(page, STARTED) == ["month", "day", "year"]


def test_add_playthrough_date_fields_follow_iso_profile_and_persist(
    authenticated_page, live_server
):
    from games.models import Playthrough

    page, user = authenticated_page
    platform = Platform.objects.create(
        library=user.library, name="PC", icon="steam", group="PC"
    )
    game = Game.objects.create(
        library=user.library, name="Alpha Game", platform=platform
    )

    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    started_field = 'date-picker:has(input[name="started"]) [data-date-picker-field]'
    ended_field = 'date-picker:has(input[name="ended"]) [data-date-picker-field]'

    _select_first_game(page)
    _fill_segments(page, started_field, {"year": "2026", "month": "01", "day": "10"})
    _fill_segments(page, ended_field, {"year": "2026", "month": "01", "day": "20"})

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    #: #687 states the submit as a run,
    #: so the days land on the projection.
    run = Playthrough.objects.get(player_game__game=game)
    assert str(run.started_lower) == "2026-01-10"
    assert str(run.completed_lower) == "2026-01-20"


def test_calendar_pick_commits_value_and_closes(authenticated_page, live_server):
    page, user = authenticated_page
    platform = Platform.objects.create(
        library=user.library, name="PC", icon="steam", group="PC"
    )
    Game.objects.create(library=user.library, name="Alpha Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    picker = 'date-picker:has(input[name="started"])'
    popup = f"{picker} [data-date-range-calendar]"

    page.locator(f"{picker} [data-date-picker-calendar-toggle]").click()
    expect(page.locator(popup)).to_be_visible()
    # No preset column on the single-date calendar.
    expect(page.locator(f"{picker} [data-date-range-presets]")).to_have_count(0)

    day_button = page.locator(
        f"{picker} [data-date-range-grid] button[data-date]"
    ).first
    picked_iso = day_button.get_attribute("data-date")
    day_button.click()

    hidden = page.locator('input[name="started"][data-date-picker-hidden]')
    expect(hidden).to_have_value(picked_iso)
    expect(page.locator(popup)).to_be_hidden()


# ── Synthetic page: the pre-upgrade (inert) state ───────────────────────────


def date_picker_page_view(request):
    presentation = date_time_presentation_for_request(request)
    contract = json.dumps(presentation.to_client_config())
    field = DatePicker(
        presentation=presentation,
        label="Purchased",
        name="date_purchased",
        # A stored value the pre-upgrade field still shows.
        value="2024-03-15",
    )
    html = f"""<!DOCTYPE html>
<html data-date-time-presentation='{contract}'>
<head>
    <title>DatePicker E2E</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/dist/elements/drop-down.js" type="module"></script>
    <script src="/static/js/dist/elements/date-picker.js" type="module"></script>
</head>
<body>
    <form method="post" action="{request.path}">
        {CsrfInput(request)}
        {field}
        <button type="submit">Submit</button>
    </form>
</body>
</html>"""
    if request.method == "POST":
        return HttpResponse(f"submitted:{request.POST.get('date_purchased', '')}")
    return HttpResponse(html)


urlpatterns = [
    path("test-date-picker/", date_picker_page_view),
]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_picker_e2e")
def test_before_upgrade_the_field_is_visible_but_inert(live_server, browser):
    """Before upgrade the field shows its date, inert.

    Disabling scripts holds the page in that state.
    """

    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(f"{live_server.url}/test-date-picker/")

    field = page.locator("[data-date-picker-field]")
    expect(field).to_be_visible()
    assert page.locator('input[type="date"][name="date_purchased"]').count() == 0

    year = page.locator('input[data-date-part="year"]')
    expect(year).to_have_value("2024")
    # inert removes the subtree from focus order entirely.
    year.focus()
    assert page.evaluate("document.activeElement.tagName.toLowerCase()") == "body"
    context.close()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_picker_e2e")
def test_js_enabled_frees_the_field(live_server, page):
    """Upgrading removes `inert`, so the segments become reachable."""
    page.goto(f"{live_server.url}/test-date-picker/")
    expect(page.locator("[data-date-picker-field]")).to_be_visible()
    assert page.locator("[data-date-picker-field][inert]").count() == 0
    assert page.locator('input[type="date"][name="date_purchased"]').count() == 0

    year = page.locator('input[data-date-part="year"]')
    year.focus()
    assert (
        page.evaluate("document.activeElement.getAttribute('data-date-part')") == "year"
    )
