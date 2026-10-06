"""Shared waits and steps for e2e tests."""

from playwright.sync_api import Locator, Page

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


def pick_choice(page: Page, name: str, value: str) -> None:
    """Pick a picker's row by value; empty picks none."""
    picker = page.locator(f'search-select[name="{name}"]')
    picker.locator("[data-search-select-search]").click()
    row = (
        picker.locator("[data-search-select-none-option]")
        if value == ""
        else picker.locator(f'[data-search-select-option][data-value="{value}"]')
    )
    row.click()


def held_choice(page: Page, name: str) -> Locator:
    """The hidden input a picker holds."""
    return page.locator(
        f'search-select[name="{name}"] [data-search-select-pills] input[type="hidden"]'
    )
