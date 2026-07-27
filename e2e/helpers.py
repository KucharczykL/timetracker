"""Shared waits for e2e tests that measure rendered layout."""

from playwright.sync_api import Page

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

    Elements that never upgraded (the no-JS pages) have no ``isSettled`` and
    are skipped.
    """
    page.evaluate("() => document.fonts.ready")
    page.wait_for_function(TABLES_SETTLED)
