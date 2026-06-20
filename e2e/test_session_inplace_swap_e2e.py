"""Browser test for the session-list "Finish session now" in-place row swap (issue #53).

Drives the real session list against pytest-django's ``live_server``: clicks the
finish button on a running session and asserts the row is updated in place via
htmx (the row still exists and now shows an end-time em dash separator).
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from games.models import Device, Game, Platform, Session


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_finish_session_swaps_row_in_place(authenticated_page: Page, live_server):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic", platform=platform)
    device = Device.objects.create(name="Desktop")
    session = Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    row = page.locator(f"#session-row-{session.pk}")
    expect(row).to_be_visible()

    row.locator('button[title="Finish session now"]').click()

    # htmx swaps the row in place; the row still exists and now shows an end
    # time separated by an em dash.
    expect(row).to_contain_text("—")

    session.refresh_from_db()
    assert session.timestamp_end is not None


def test_finish_session_swap_does_not_add_scrollbar(
    authenticated_page: Page, live_server
):
    """Regression for the phantom horizontal scrollbar (issues #53 / #40).

    Flowbite re-initialises popovers on every htmx swap; a popover hidden via
    Tailwind ``invisible`` (visibility:hidden) still occupies layout, so once
    Popper parks it with a transform it expands the table's overflow-x-auto
    wrapper and a spurious scrollbar appears. The popover must be removed from
    layout while hidden.
    """
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 800})
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    # A long name guarantees a truncated NameWithIcon popover in the row.
    game = Game.objects.create(name="A Very Long Game Title That Truncates")
    game.platform = platform
    game.save()
    device = Device.objects.create(name="Desktop")
    session = Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # The fix only removes the popover from layout while it is hidden; it must
    # still display on hover. Verify on the freshly-loaded page.
    trigger = page.locator(f"#session-row-{session.pk} [data-popover-target]").first
    popover_id = trigger.get_attribute("data-popover-target")
    trigger.hover()
    page.wait_for_timeout(400)
    shown_display = page.evaluate(
        """(id) => getComputedStyle(document.querySelector(`[id="${id}"]`)).display""",
        popover_id,
    )
    assert shown_display != "none", "popover stayed display:none on hover"
    page.mouse.move(0, 0)

    page.locator(f"#session-row-{session.pk}").locator(
        'button[title="Finish session now"]'
    ).click()
    expect(page.locator(f"#session-row-{session.pk}")).to_contain_text("—")
    page.wait_for_timeout(500)  # allow Flowbite afterSettle re-init + Popper

    # After the swap re-inits popovers, the table wrapper must not become
    # horizontally scrollable (the phantom-scrollbar regression).
    overflow = page.evaluate(
        """() => {
            const w = document.querySelector('.overflow-x-auto');
            return w.scrollWidth - w.clientWidth;
        }"""
    )
    assert overflow <= 0, f"table wrapper overflows by {overflow}px after swap"
