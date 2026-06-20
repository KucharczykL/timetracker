"""Browser test: the device dropdown is not clipped by the table wrapper (#39).

The session list lives inside an ``overflow-x-auto`` wrapper, which forces
``overflow-y: auto`` and used to clip an absolutely-positioned dropdown menu
that extended past a short table. The menu now opens with ``position: fixed``
so it escapes the clipping ancestor and stays within the viewport.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page

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


def test_device_dropdown_not_clipped_on_short_table(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 800})
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic")
    game.platform = platform
    game.save()
    # Many devices → a tall menu; a single row → a short table that would clip
    # an absolutely-positioned menu.
    devices = [Device.objects.create(name=f"Device {i:02d}") for i in range(15)]
    session = Session.objects.create(
        game=game, device=devices[0], timestamp_start=timezone.now()
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    page.locator(f"#session-row-{session.pk} [data-toggle]").click()

    menu = page.locator("[data-menu]:not([hidden])")
    menu.wait_for(state="visible")

    geometry = page.evaluate(
        """() => {
            const menu = document.querySelector('[data-menu]:not([hidden])');
            const rect = menu.getBoundingClientRect();
            return {
                position: getComputedStyle(menu).position,
                bottom: rect.bottom,
                viewportHeight: window.innerHeight,
            };
        }"""
    )
    # Fixed positioning escapes the overflow-x-auto clip...
    assert geometry["position"] == "fixed"
    # ...and the menu stays inside the viewport (not clipped/cut off).
    assert geometry["bottom"] <= geometry["viewportHeight"] + 1, geometry

    # A device far down the (previously clipped) list is selectable.
    page.locator("[data-option]", has_text="Device 14").click()
    page.wait_for_timeout(200)
    session.refresh_from_db()
    assert session.device == devices[14]


def test_device_dropdown_flips_up_near_viewport_bottom(
    authenticated_page: Page, live_server
):
    """A dropdown whose toggle sits near the viewport bottom must open upward
    and stay fully visible — not collapse off-screen.

    Regression: the menu keeps a ``top-[105%]`` utility class; clearing inline
    ``top`` to "" in the flip-up branch let that class reassert ``top: 105%``
    on the now-``fixed`` menu, collapsing it to a 2px sliver below the viewport.
    """
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 760})
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic")
    game.platform = platform
    game.save()
    devices = [Device.objects.create(name=f"Device {i:02d}") for i in range(15)]
    sessions = [
        Session.objects.create(
            game=game, device=devices[0], timestamp_start=timezone.now()
        )
        for _ in range(10)
    ]

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    # Scroll the table so the lower rows sit near the viewport bottom, where the
    # menu cannot fit below and must flip up.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(200)

    bottom_row = sessions[-3]
    page.locator(f"#session-row-{bottom_row.pk} [data-toggle]").click()
    menu = page.locator("[data-menu]:not([hidden])")
    menu.wait_for(state="visible")

    geometry = page.evaluate(
        """() => {
            const menu = document.querySelector('[data-menu]:not([hidden])');
            const rect = menu.getBoundingClientRect();
            return {
                top: rect.top,
                bottom: rect.bottom,
                height: rect.height,
                viewportHeight: window.innerHeight,
            };
        }"""
    )
    # The flipped-up menu is a real, fully on-screen box (not a 2px sliver).
    assert geometry["height"] > 50, geometry
    assert geometry["top"] >= -1, geometry
    assert geometry["bottom"] <= geometry["viewportHeight"] + 1, geometry
