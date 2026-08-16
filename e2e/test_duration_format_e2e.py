"""Changing the duration format preference re-renders every visible duration."""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page, expect

from games.models import Game, Platform, Session
from timetracker.settings_commands import change_user_setting


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def session(e2e_library) -> Session:
    game = Game.objects.create(
        library=e2e_library,
        name="Duration Game",
        platform=Platform.objects.create(library=e2e_library, name="PC"),
    )
    return Session.objects.create(
        game=game,
        timestamp_start=dt.datetime(2024, 6, 1, 12, 0, tzinfo=dt.UTC),
        timestamp_end=dt.datetime(2024, 6, 1, 13, 12, tzinfo=dt.UTC),
    )


def _duration_cell(page: Page, session: Session):
    return page.locator(f"#session-row-{session.pk} td").nth(1)


def _center_x(locator: Locator) -> float:
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2


def test_default_profile_renders_decimal_hours(
    authenticated_page: Page, live_server, session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    expect(_duration_cell(page, session)).to_contain_text("1.2 h")


def test_changing_the_preference_rerenders_the_list(
    authenticated_page: Page, live_server, django_user_model, session
):
    page = authenticated_page
    change_user_setting(
        django_user_model.objects.get(username="tester"),
        "DURATION_FORMAT",
        "hours_minutes",
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    expect(_duration_cell(page, session)).to_contain_text("1 h 12 m")


def test_popover_lists_the_other_profiles(
    authenticated_page: Page, live_server, session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    trigger = _duration_cell(page, session).locator("[data-pop-over-control]")
    trigger.click()

    panel = page.locator(f"#duration-session-{session.pk}")
    expect(panel).to_be_visible()
    # The visible value never repeats inside its own panel.
    expect(panel).to_contain_text("1 h 12 m")
    expect(panel).to_contain_text("1 hour")
    expect(panel).not_to_contain_text("1.2 h")


def test_reveal_glyph_is_visible_without_hovering(
    authenticated_page: Page, live_server, session
):
    """A pointer device can hover the value to open the panel, but nothing
    tells it the panel exists — so the glyph stays visible there too."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    reveal = _duration_cell(page, session).locator("[data-pop-over-reveal]")
    expect(reveal).to_be_visible()
    expect(page.locator(f"#duration-session-{session.pk}")).to_be_hidden()

    reveal.click()
    expect(page.locator(f"#duration-session-{session.pk}")).to_be_visible()


def test_panel_arrow_points_at_the_reveal_glyph(
    authenticated_page: Page, live_server, session
):
    """The glyph is the control, so the arrow aims there — not at the centre of
    the value-plus-glyph group, which lands in the gap between them (or in
    empty space once the value wraps)."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    reveal = _duration_cell(page, session).locator("[data-pop-over-reveal]")
    reveal.click()
    panel = page.locator(f"#duration-session-{session.pk}")
    expect(panel).to_be_visible()

    assert (
        abs(_center_x(reveal) - _center_x(panel.locator("[data-pop-over-arrow]"))) < 1
    )


def test_hovering_the_value_still_opens_the_panel(
    authenticated_page: Page, live_server, session
):
    """The glyph is the tap target; the whole host remains the hover target."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    _duration_cell(page, session).locator("pop-over").hover()

    expect(page.locator(f"#duration-session-{session.pk}")).to_be_visible()


def test_screen_reader_text_spells_the_value_out(
    authenticated_page: Page, live_server, session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    spoken = _duration_cell(page, session).locator(".sr-only")

    expect(spoken).to_have_text("1 hour 12 minutes")
