"""Shared waits and steps for e2e tests."""

from playwright.sync_api import Locator, Page, expect

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


def open_picker(picker: Locator) -> Locator | None:
    """Below sm, tap the face; else the box.

    Answers the sheet a face opened.
    """
    host = picker.locator("xpath=..")
    face = host.locator(
        ":scope > [data-search-select-face] [data-search-select-face-open]"
    )
    if not face.is_visible():
        picker.locator("[data-search-select-search]").click()
        return None
    sheet = host.locator(":scope > dialog[data-dropdown-sheet]")
    #: The widget leaves its host; pin the dialog.
    sheet = sheet.page.locator(f"#{_stamped_id(sheet)}")
    face.click()
    return sheet


def _stamped_id(element: Locator) -> str:
    return element.evaluate(
        "dialog => dialog.id || (dialog.id = `picker-sheet-${crypto.randomUUID()}`)"
    )


def wait_for_sheet_to_close(sheet: Locator | None) -> None:
    """A leaving sheet still holds the page inert."""
    if sheet is not None:
        #: A page the pick reloads has none.
        expect(sheet.and_(sheet.page.locator("dialog[open]"))).to_have_count(0)


def pick_choice(scope: Page | Locator, name: str, value: str) -> None:
    """Pick a picker's row by value; empty picks none."""
    picker = scope.locator(f'search-select[name="{name}"]')
    sheet = open_picker(picker)
    row = (
        picker.locator("[data-search-select-none-option]")
        if value == ""
        else picker.locator(f'[data-search-select-option][data-value="{value}"]')
    )
    row.click()
    wait_for_sheet_to_close(sheet)


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
