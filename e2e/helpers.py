"""Shared waits and steps for e2e tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from django.urls import reverse
from playwright.sync_api import Locator, Page, expect


class Credentials(NamedTuple):
    """One user's login form values."""

    username: str
    password: str


E2E_LOGIN = Credentials("tester", "secret123")


def log_in(page: Page, live_server, credentials: Credentials = E2E_LOGIN) -> None:
    """Sign in through the form; land on ``/tracker``.

    Enter, not a click: a click parks the virtual mouse on the
    button, and the next page opens whatever hovers under it.
    """
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', credentials.username)
    page.fill('input[name="password"]', credentials.password)
    page.press('input[name="password"]', "Enter")
    page.wait_for_url(f"{live_server.url}/tracker**")


TABLES_SETTLED = """
() => [...document.querySelectorAll('responsive-table')].every(
    (table) => typeof table.isSettled !== 'function' || table.isSettled()
)
"""


def settle_layout(page: Page) -> None:
    """Wait until fonts are loaded and every <responsive-table> has refitted.

    A viewport resize updates the region's width immediately, but the
    element's column-drop decision is coalesced into a later frame — so a
    measurement taken right after ``set_viewport_size`` reads the previous
    decision and sees the table overflow its wrapper. Awaiting
    ``document.fonts.ready`` buys no frames at all once the fonts are cached,
    and counting frames only approximates the wait; the element reports its
    own settled state, which a resize invalidates synchronously.

    Elements that never upgraded have no ``isSettled`` and are skipped.
    """
    page.evaluate("() => document.fonts.ready")
    page.wait_for_function(TABLES_SETTLED)


def open_row_menu(page: Page, menu_id: str) -> None:
    """Open a row's menu, once its element can answer.

    Every item starts in a panel that is `hidden`, and a press landing on a
    `<drop-down>` the module has not upgraded is swallowed: the timeout that
    follows names the item rather than the cause.
    """
    page.wait_for_function("() => !!customElements.get('drop-down')")
    page.locator(f"#{menu_id}Link").click()


def open_facet(page: Page, field: str) -> None:
    """Open a quick facet, from the row or ⋯."""
    trigger = page.locator(f"#quick-{field}-dropdownLink")
    if not trigger.is_visible():
        page.locator("[data-quick-overflow] [data-toggle]").first.click()
    trigger.click()


@contextmanager
def picker_opened(picker: Locator) -> Iterator[None]:
    """Open a picker; on a clean exit, its sheet has closed.

    Below sm, the face opens a sheet; a leaving
    sheet still holds the page inert.
    """
    host = picker.locator("xpath=ancestor::drop-down[1]")
    face = host.locator(
        ":scope > [data-search-select-face] [data-search-select-face-open]"
    )
    if not face.is_visible():
        picker.locator("[data-search-select-search]").click()
        yield
        return
    # The widget leaves its host; pin the dialog.
    sheet = picker.page.locator(
        f"#{_stamped_id(host.locator(':scope > dialog[data-dropdown-sheet]'))}"
    )
    face.click()
    yield
    # A page the pick reloads has none.
    expect(sheet.and_(picker.page.locator("dialog[open]"))).to_have_count(0)


def _stamped_id(element: Locator) -> str:
    """The element's id; stamps one, kept for the page."""
    return element.evaluate(
        "dialog => dialog.id || (dialog.id = `picker-sheet-${crypto.randomUUID()}`)"
    )


def pick_choice(scope: Page | Locator, name: str, value: str) -> None:
    """Pick a picker's row by value; empty picks none."""
    picker = scope.locator(f'search-select[name="{name}"]')
    with picker_opened(picker):
        row = (
            picker.locator("[data-search-select-none-option]")
            if value == ""
            else picker.locator(f'[data-search-select-option][data-value="{value}"]')
        )
        row.click()


def held_choice(scope: Page | Locator, name: str) -> Locator:
    """The hidden input a picker holds."""
    return scope.locator(
        f'search-select[name="{name}"] [data-search-select-pills] input[type="hidden"]'
    )


def offered_choices(scope: Page | Locator, name: str) -> list[str]:
    """Every row value a picker offers."""
    return scope.locator(
        f'search-select[name="{name}"] [data-search-select-option]'
    ).evaluate_all("rows => rows.map(row => row.getAttribute('data-value'))")
