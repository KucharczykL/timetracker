"""Real-browser proof of the selectable table.

The page is synthetic, as the set-filter suite's is: a stripped ROOT_URLCONF
with its own template, so the test needs no auth and no list view. The
element modules are listed by hand, because render_page does not serve this.
"""

import pytest
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import path
from playwright.sync_api import Page, expect

from common import components
from common.components.custom_elements import Dropdown, DropdownMenuPanel

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/dist/elements/responsive-table.js" type="module"></script>
    <script src="/static/js/dist/elements/selectable-table.js" type="module"></script>
    <script src="/static/js/dist/elements/drop-down.js" type="module"></script>
    <script src="/static/js/dist/elements/pop-over.js" type="module"></script>
</head>
<body>
    <div style="height: 40px">a page above the table</div>
    {body}
</body>
</html>"""

ROW_COUNT = 25
PAGE_SIZE = 10
MATCHING_COUNT = 120

LINE_BOTTOM = """
() => {
    const line = document.querySelector('[data-selection-line]');
    return line.getBoundingClientRect().bottom;
}
"""

ROW_GEOMETRY = """
() => [...document.querySelectorAll('tbody tr')].map((row) => {
    const name = row.querySelector('th').getBoundingClientRect();
    return [Math.round(row.getBoundingClientRect().height), Math.round(name.left)];
})
"""

SETTLED = """
() => [...document.querySelectorAll('responsive-table')].every(
    (table) => typeof table.isSettled !== 'function' || table.isSettled()
)
"""

PUBLISHED_HEIGHT = """
() => parseFloat(
    getComputedStyle(document.documentElement)
        .getPropertyValue('--selection-line')
) || 0
"""

LINE_HEIGHT = """
() => document.querySelector('[data-selection-line]')
    .getBoundingClientRect().height
"""

STATEMENT_LOG = """
() => {
    window.statements = [];
    document.addEventListener('selectable-table:change', (event) => {
        window.statements.push(event.detail);
    });
}
"""


def _menu(index: int):
    return Dropdown(
        # The dropdown contract stamps the trigger's id.
        trigger_element=components.Button()[f"Act {index}"],
        target_element=DropdownMenuPanel(
            items=[components.Li(role="presentation")["Nothing"]]
        ),
        id=f"row-menu-{index}",
    )


def _table(paginated: bool):
    rows = [
        components.make_row(
            f"Game {index:02d}",
            components.Popover(
                popover_content="The year it came out",
                wrapped_content=str(2000 + index),
                id=f"year-{index}",
            ),
            _menu(index),
            key=str(index),
            summary=f"{index} hours, PC",
        )
        for index in range(ROW_COUNT)
    ]
    paginator = Paginator(list(range(MATCHING_COUNT)), PAGE_SIZE)
    return components.StyledTable(
        columns=[
            components.Column("Name", shrinkable=True),
            components.Column("Year"),
            components.Column("Actions", align="right", priority=4),
        ],
        rows=rows,
        data_table=True,
        caption="Games",
        selection={"filter": '{"year": 2025}'},
        page_obj=paginator.page(1) if paginated else None,
        elided_page_range=list(paginator.get_elided_page_range(1))
        if paginated
        else None,
        request=None,
    )


def paginated_view(request):
    return HttpResponse(
        _PAGE_TEMPLATE.format(body=str(_table(True)), title="Selectable table")
    )


def whole_list_view(request):
    return HttpResponse(
        _PAGE_TEMPLATE.format(body=str(_table(False)), title="Selectable table")
    )


urlpatterns = [
    path("test-selectable-table/", paginated_view),
    path("test-selectable-table-whole/", whole_list_view),
]

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def synthetic_urls(settings):
    """Serve the two pages above, not the site's routes."""
    settings.ROOT_URLCONF = "e2e.test_selectable_table_e2e"


def _open(page: Page, live_server, url: str = "/test-selectable-table/") -> None:
    page.goto(live_server.url + url)
    page.wait_for_function("() => customElements.get('selectable-table')")


def _checkboxes(page: Page):
    return page.locator("tbody [data-selection-checkbox]")


def _line(page: Page):
    return page.locator("[data-selection-line]")


def _header_check_all(page: Page):
    return page.locator("thead [data-selection-check-all]")


def _line_check_all(page: Page):
    return page.locator("[data-selection-line] [data-selection-check-all]")


def _select_first(page: Page) -> None:
    """One row marked, so the line shows."""
    _checkboxes(page).nth(0).click()
    expect(_line(page)).to_be_visible()


def test_every_row_shows_its_checkbox_and_the_line_follows_the_count(
    page: Page, live_server
):
    _open(page, live_server)
    expect(_checkboxes(page)).to_have_count(ROW_COUNT)
    for index in range(ROW_COUNT):
        expect(_checkboxes(page).nth(index)).to_be_visible()
    expect(_line(page)).to_be_hidden()
    _checkboxes(page).nth(0).click()
    expect(_line(page)).to_be_visible()
    _checkboxes(page).nth(0).click()
    expect(_line(page)).to_be_hidden()


def test_a_selection_moves_no_row(page: Page, live_server):
    """The line comes after the rows."""
    _open(page, live_server)
    at_rest = page.evaluate(ROW_GEOMETRY)
    _select_first(page)
    assert page.evaluate(ROW_GEOMETRY) == at_rest


BOX_LEFTS = """
() => [
    'thead [data-selection-check-all]',
    'tbody [data-selection-checkbox]',
    '[data-selection-line] [data-selection-check-all]',
].map((selector) => document.querySelector(selector).getBoundingClientRect().left)
"""


@pytest.mark.parametrize("width", [1280, 390])
def test_the_three_boxes_share_one_column(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, live_server)
    page.wait_for_function(SETTLED)
    _select_first(page)
    header, row, line = page.evaluate(BOX_LEFTS)
    assert abs(header - row) <= 1, f"header {header}, row {row}"
    assert abs(line - row) <= 1, f"line {line}, row {row}"


def test_both_check_alls_move_together(page: Page, live_server):
    _open(page, live_server)
    _header_check_all(page).click()
    expect(_line(page)).to_be_visible()
    expect(_line_check_all(page)).to_be_checked()
    expect(_checkboxes(page).nth(ROW_COUNT - 1)).to_be_checked()
    _line_check_all(page).click()
    expect(_header_check_all(page)).not_to_be_checked()
    expect(_line(page)).to_be_hidden()


def test_a_tabbed_box_is_not_under_the_line(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_first(page)
    _checkboxes(page).nth(0).focus()
    target = "12"
    for _ in range(80):
        page.keyboard.press("Tab")
        focused = page.evaluate(
            "() => document.activeElement.matches('[data-selection-checkbox]')"
            " ? document.activeElement.closest('tr').dataset.selectionKey : null"
        )
        if focused == target:
            break
    assert focused == target
    box_bottom, line_top = page.evaluate(
        """() => [
            document.activeElement.getBoundingClientRect().bottom,
            document.querySelector('[data-selection-line]').getBoundingClientRect().top,
        ]"""
    )
    assert box_bottom <= line_top + 1, f"box {box_bottom}, line {line_top}"


def test_tabbing_into_the_line_does_not_scroll_the_page(page: Page, live_server):
    """The sticky line is in view already."""
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_first(page)
    page.evaluate("() => window.scrollTo(0, 400)")
    page.wait_for_timeout(100)
    before = page.evaluate("() => window.scrollY")
    page.locator("[data-selection-clear]").focus()
    page.wait_for_timeout(100)
    assert page.evaluate("() => window.scrollY") == before


def test_clear_hands_focus_to_the_header_without_scrolling(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_first(page)
    page.evaluate("() => window.scrollTo(0, 400)")
    page.wait_for_timeout(100)
    before = page.evaluate("() => window.scrollY")
    page.locator("[data-selection-clear]").click()
    expect(_line(page)).to_be_hidden()
    assert page.evaluate(
        "() => document.activeElement === "
        "document.querySelector('thead [data-selection-check-all]')"
    )
    assert page.evaluate("() => window.scrollY") == before


def test_no_scripting_shows_no_checkbox_and_no_line(browser, live_server):
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.goto(live_server.url + "/test-selectable-table/")
        expect(_header_check_all(page)).to_be_hidden()
        expect(_checkboxes(page)).to_have_count(0)
        expect(_line(page)).to_be_hidden()
    finally:
        context.close()


def test_the_checkbox_leads_the_name_it_marks(page: Page, live_server):
    """First in the row the name states, and centred on it.

    The cell holds the summary under the name, so a checkbox placed in
    the cell would centre on both lines and sit below the name.
    """
    _open(page, live_server)
    placed = page.evaluate(
        """() => {
            const identity = document.querySelector('tbody th [data-row-identity]');
            const box = identity.firstElementChild;
            // The name is a text node here, so a range measures it.
            const text = [...identity.childNodes].find(
                (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()
            );
            const range = document.createRange();
            range.selectNodeContents(text);
            const middle = (shape) => shape.top + shape.height / 2;
            return {
                tag: box.tagName,
                outsideTheSummary: !document
                    .querySelector('tbody th [data-row-summary]')
                    ?.contains(box),
                offBy: Math.abs(
                    middle(box.getBoundingClientRect())
                    - middle(range.getBoundingClientRect())
                ),
            };
        }"""
    )
    assert placed["tag"] == "INPUT"
    assert placed["outsideTheSummary"]
    #: One line's rounding, not the four the cell's own middle costs.
    assert placed["offBy"] < 1
    label = _checkboxes(page).first.get_attribute("aria-label")
    assert label is not None and label.startswith("Game 00")


def test_shift_click_takes_the_range(page: Page, live_server):
    _open(page, live_server)
    page.evaluate(STATEMENT_LOG)
    _checkboxes(page).nth(1).click()
    _checkboxes(page).nth(4).click(modifiers=["Shift"])
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {"mode": "some", "keys": ["1", "2", "3", "4"]}


def test_shift_space_takes_the_same_range_and_marks_the_anchor_once(
    page: Page, live_server
):
    """The space must not toggle the anchor twice."""
    _open(page, live_server)
    page.evaluate(STATEMENT_LOG)
    _checkboxes(page).nth(1).click()
    _checkboxes(page).nth(4).focus()
    page.keyboard.press("Shift+Space")
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {"mode": "some", "keys": ["1", "2", "3", "4"]}
    assert _checkboxes(page).nth(1).is_checked()


def test_check_all_reads_indeterminate_with_one_row_unchecked(page: Page, live_server):
    _open(page, live_server)
    _header_check_all(page).click()
    _checkboxes(page).nth(3).click()
    assert page.evaluate(
        "() => [...document.querySelectorAll('[data-selection-check-all]')]"
        ".every((checkAll) => checkAll.indeterminate)"
    )


def test_all_matching_keeps_the_scope_and_records_the_exclusion(
    page: Page, live_server
):
    _open(page, live_server)
    _select_first(page)
    page.evaluate(STATEMENT_LOG)
    page.locator("[data-selection-all-matching]").click()
    _checkboxes(page).nth(2).click()
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {
        "mode": "all",
        "filter": '{"year": 2025}',
        "count": MATCHING_COUNT,
        "except": ["2"],
    }
    assert "119 selected" in page.locator("[data-selection-count]").inner_text()


def test_a_whole_list_offers_no_wider_scope(page: Page, live_server):
    _open(page, live_server, "/test-selectable-table-whole/")
    _select_first(page)
    assert page.locator("[data-selection-all-matching]").count() == 0
    expect(_header_check_all(page)).to_be_visible()
    expect(_line_check_all(page)).to_be_visible()


def test_the_region_speaks_at_a_change_of_scope_and_not_at_a_tick(
    page: Page, live_server
):
    _open(page, live_server)
    region = page.locator("[data-selection-announcement]")
    assert region.get_attribute("role") == "status"
    appearing = "1 selected. Selection actions follow the table."
    _checkboxes(page).nth(0).click()
    assert region.text_content() == appearing
    _checkboxes(page).nth(1).click()
    assert region.text_content() == appearing
    page.locator("[data-selection-all-matching]").click()
    assert "every row matching the filter" in (region.text_content() or "")
    page.locator("[data-selection-clear]").click()
    assert region.text_content() == "Selection cleared."


def test_a_selection_survives_the_next_page(page: Page, live_server):
    """The statement waits in the tab for the list's other pages."""
    _open(page, live_server)
    _checkboxes(page).nth(0).click()
    _checkboxes(page).nth(2).click()

    page.get_by_role("link", name="Next").click()
    page.wait_for_function("() => customElements.get('selectable-table')")

    expect(_line(page)).to_be_visible()
    assert "2 selected" in page.locator("[data-selection-count]").inner_text()


def test_clearing_forgets_a_selection_for_the_next_page(page: Page, live_server):
    _open(page, live_server)
    _checkboxes(page).nth(0).click()
    page.locator("[data-selection-clear]").click()

    page.get_by_role("link", name="Next").click()
    page.wait_for_function("() => customElements.get('selectable-table')")

    expect(_line(page)).to_be_hidden()


def test_the_line_sticks_to_the_foot_of_the_window(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_first(page)
    # Mid-table, with the table still below the window.
    page.evaluate("() => window.scrollTo(0, 300)")
    page.wait_for_timeout(100)
    bottom = page.evaluate(LINE_BOTTOM)
    height = page.evaluate("() => window.innerHeight")
    assert abs(bottom - height) <= 1, f"line bottom {bottom}, window {height}"


def test_the_line_stops_at_the_end_of_its_own_table(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_first(page)
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(100)
    bottom = page.evaluate(LINE_BOTTOM)
    window_height = page.evaluate("() => window.innerHeight")
    nav_top = page.evaluate(
        "() => document.querySelector('nav').getBoundingClientRect().top"
    )
    # At the end the line takes its place back.
    assert bottom < window_height
    assert bottom <= nav_top + 1


def test_the_line_publishes_its_height(page: Page, live_server):
    _open(page, live_server)
    _select_first(page)
    published = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--selection-line')"
    )
    assert published.endswith("px")
    assert int(published.removesuffix("px")) > 0


def test_a_row_menu_opens_over_the_line_and_owns_escape(page: Page, live_server):
    _open(page, live_server)
    _checkboxes(page).nth(0).click()
    page.get_by_role("button", name="Act 0").click()
    panel = page.locator("[role='menu']").first
    panel.wait_for(state="visible")
    page.keyboard.press("Escape")
    # The menu answered it; the selection stands.
    expect(panel).to_be_hidden()
    expect(_checkboxes(page).nth(0)).to_be_checked()
    page.keyboard.press("Escape")
    expect(_checkboxes(page).nth(0)).not_to_be_checked()


def test_the_name_keeps_its_floor_at_a_phone_width(page: Page, live_server):
    """The fit budgets the checkbox beside the name."""
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, live_server)
    page.wait_for_function(SETTLED)
    name_width = page.evaluate(
        "() => document.querySelector('tbody th').getBoundingClientRect().width"
        " - document.querySelector('tbody [data-selection-checkbox]')"
        ".getBoundingClientRect().width"
    )
    assert name_width >= 150, f"name squeezed to {name_width}px"


def test_a_hidden_line_publishes_nothing(page: Page, live_server):
    """No stale height pads the page or lifts the toasts."""
    _open(page, live_server)
    _select_first(page)
    assert page.evaluate(PUBLISHED_HEIGHT) > 0
    page.locator("[data-selection-clear]").click()
    expect(_line(page)).to_be_hidden()
    published = page.evaluate(
        "() => document.documentElement.style.getPropertyValue('--selection-line')"
    )
    assert published == ""


def test_the_published_height_follows_a_line_that_wraps(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page, live_server)
    _select_first(page)
    published = page.evaluate(PUBLISHED_HEIGHT)
    measured = page.evaluate(LINE_HEIGHT)
    assert abs(published - measured) <= 1, f"{published} against {measured}"


def test_a_tooltip_answers_escape_before_the_selection(page: Page, live_server):
    """Every closer marks the press spent, not the menus alone."""
    _open(page, live_server)
    _checkboxes(page).nth(0).click()
    page.locator("pop-over button").first.click()
    page.locator("[data-pop-over-panel]:not([hidden])").first.wait_for()
    page.keyboard.press("Escape")
    expect(page.locator("[data-pop-over-panel]:not([hidden])")).to_have_count(0)
    expect(_checkboxes(page).nth(0)).to_be_checked()


def test_the_stacked_identity_cell_at_a_phone_width(page: Page, live_server):
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, live_server)
    summary = page.locator("tbody th [data-row-summary]").first
    assert summary.is_visible()
    box = summary.bounding_box()
    name_box = page.locator("tbody th").first.bounding_box()
    assert box is not None and name_box is not None
    # A second line, not a second column.
    assert box["y"] > name_box["y"]
