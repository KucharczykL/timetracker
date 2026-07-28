"""End-to-end Playwright tests for the DatePicker element (issue #485):
add/edit Purchase and PlayEvent date fields under different account display
profiles, the calendar popup, live DATETIME_FORMAT changes, and the
JS-disabled native `<input type="date">` fallback.
"""

import json

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import expect

from common.components import DatePicker
from common.components.primitives import CsrfInput
from common.date_time_presentation import date_time_presentation_for_request
from games.models import Game, Platform, Purchase, UserPreferences

# ── Real-app tests: add/edit Purchase and PlayEvent ─────────────────────────


@pytest.fixture
def authenticated_page(live_server, page, django_user_model):
    user = django_user_model.objects.create_user(
        username="tester", password="secret123"
    )
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page, user


def _select_first_game(page):
    games = page.locator('search-select[name="games"], search-select[name="game"]')
    games.locator("[data-search-select-search]").click()
    games.locator("[data-search-select-option]").first.click()


def _fill_segments(page, container: str, values: dict) -> None:
    for part, value in values.items():
        page.locator(f'{container} input[data-date-part="{part}"]').click()
        page.keyboard.type(value)


def test_add_purchase_date_field_iso_order_and_persists(
    authenticated_page, live_server
):
    """Default (ISO) account: segments render year → month → day, and the
    persisted date matches what was typed."""
    page, _user = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name="Alpha Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    field = 'date-picker:has(input[name="date_purchased"]) [data-date-picker-field]'
    parts = page.locator(f"{field} input[data-date-part]")
    expect(parts).to_have_count(3)
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["year", "month", "day"]

    _select_first_game(page)
    _fill_segments(page, field, {"year": "2026", "month": "03", "day": "15"})

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    purchase = Purchase.objects.get()
    assert str(purchase.date_purchased) == "2026-03-15"


def test_add_purchase_date_field_mdy_order_persists_same_iso_date(
    authenticated_page, live_server
):
    """An mdy_12h account: segments render month → day → year, but the
    persisted date is the same canonical ISO value regardless of display
    order (issue #485 acceptance criterion)."""
    page, user = authenticated_page
    UserPreferences.objects.create(user=user, datetime_format="mdy_12h")
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name="Alpha Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    field = 'date-picker:has(input[name="date_purchased"]) [data-date-picker-field]'
    parts = page.locator(f"{field} input[data-date-part]")
    part_names = parts.evaluate_all("(els) => els.map(e => e.dataset.datePart)")
    assert part_names == ["month", "day", "year"]

    _select_first_game(page)
    _fill_segments(page, field, {"month": "03", "day": "15", "year": "2026"})

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    purchase = Purchase.objects.get()
    assert str(purchase.date_purchased) == "2026-03-15"


def test_edit_purchase_date_field_prefills_from_instance(
    authenticated_page, live_server
):
    page, _user = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Alpha Game", platform=platform)
    purchase = Purchase.objects.create(
        price=10,
        price_currency="USD",
        date_purchased="2025-06-01",
        platform=platform,
        ownership_type=Purchase.DIGITAL,
        type=Purchase.GAME,
    )
    purchase.games.add(game)

    page.goto(f"{live_server.url}{reverse('games:edit_purchase', args=[purchase.id])}")
    field = 'date-picker:has(input[name="date_purchased"]) [data-date-picker-field]'
    hidden = page.locator('input[name="date_purchased"][data-date-picker-hidden]')
    expect(hidden).to_have_value("2025-06-01")
    expect(page.locator(f'{field} input[data-date-part="year"]')).to_have_value("2025")
    expect(page.locator(f'{field} input[data-date-part="month"]')).to_have_value("06")
    expect(page.locator(f'{field} input[data-date-part="day"]')).to_have_value("01")


def test_changing_datetime_format_updates_add_purchase_segment_order(
    authenticated_page, live_server
):
    """Changing DATETIME_FORMAT and reloading the add-purchase form updates
    the date field's segment order (issue #485 acceptance criterion)."""
    page, user = authenticated_page
    field = 'date-picker:has(input[name="date_purchased"]) [data-date-picker-field]'

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    initial_order = page.locator(f"{field} input[data-date-part]").evaluate_all(
        "(els) => els.map(e => e.dataset.datePart)"
    )
    assert initial_order == ["year", "month", "day"]

    UserPreferences.objects.create(user=user, datetime_format="mdy_12h")
    page.reload()
    updated_order = page.locator(f"{field} input[data-date-part]").evaluate_all(
        "(els) => els.map(e => e.dataset.datePart)"
    )
    assert updated_order == ["month", "day", "year"]


def test_add_playevent_date_fields_follow_iso_profile_and_persist(
    authenticated_page, live_server
):
    from games.models import PlayEvent

    page, _user = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Alpha Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_playevent')}")
    started_field = 'date-picker:has(input[name="started"]) [data-date-picker-field]'
    ended_field = 'date-picker:has(input[name="ended"]) [data-date-picker-field]'

    _select_first_game(page)
    _fill_segments(page, started_field, {"year": "2026", "month": "01", "day": "10"})
    _fill_segments(page, ended_field, {"year": "2026", "month": "01", "day": "20"})

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    event = PlayEvent.objects.get(game=game)
    assert str(event.started) == "2026-01-10"
    assert str(event.ended) == "2026-01-20"


def test_calendar_pick_commits_value_and_closes(authenticated_page, live_server):
    page, _user = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name="Alpha Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    picker = 'date-picker:has(input[name="date_purchased"])'
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

    hidden = page.locator('input[name="date_purchased"][data-date-picker-hidden]')
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
        # A stored value, so the no-JS case can assert the field still shows
        # the date rather than rendering blank.
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
def test_js_disabled_leaves_the_field_visible_but_inert(live_server, browser):
    """With scripting off the element never upgrades, so `inert` is never
    removed: the field still shows its stored date, but cannot be focused or
    typed into.

    That is the intended degraded state now that the `<noscript>` native input
    is gone (#539). Showing the date read-only beats both alternatives — a
    blank field (what the old `:not(:defined)` rule would leave behind), and a
    field that looks editable while silently discarding input, since the
    segments carry no `name` and are never submitted.
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
