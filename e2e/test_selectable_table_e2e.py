"""Real-browser proof of the selectable table.

The page is synthetic, as the set-filter suite's is: a stripped ROOT_URLCONF
with its own template, so the test needs no auth and no list view. The
element modules are listed by hand, because render_page does not serve this.
"""

import pytest
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import path
from playwright.sync_api import Page

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
            str(2000 + index),
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


def _select_mode(page: Page) -> None:
    page.locator("[data-selection-toggle]").click()


def _checkboxes(page: Page):
    return page.locator("tbody [data-selection-checkbox]")


def test_the_mode_builds_and_takes_back_the_checkboxes(page: Page, live_server):
    _open(page, live_server)
    assert _checkboxes(page).count() == 0
    _select_mode(page)
    assert _checkboxes(page).count() == ROW_COUNT
    _select_mode(page)
    assert _checkboxes(page).count() == 0


def test_the_checkbox_is_the_first_child_of_the_identity_cell(page: Page, live_server):
    _open(page, live_server)
    _select_mode(page)
    first_child = page.evaluate(
        "() => document.querySelector('tbody th').firstElementChild.tagName"
    )
    assert first_child == "INPUT"
    label = _checkboxes(page).first.get_attribute("aria-label")
    assert label is not None and label.startswith("Game 00")


def test_shift_click_takes_the_range(page: Page, live_server):
    _open(page, live_server)
    _select_mode(page)
    page.evaluate(STATEMENT_LOG)
    _checkboxes(page).nth(1).click()
    _checkboxes(page).nth(4).click(modifiers=["Shift"])
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {"keys": ["1", "2", "3", "4"]}


def test_shift_space_takes_the_same_range_and_marks_the_anchor_once(
    page: Page, live_server
):
    """The space must not toggle the anchor twice."""
    _open(page, live_server)
    _select_mode(page)
    page.evaluate(STATEMENT_LOG)
    _checkboxes(page).nth(1).click()
    _checkboxes(page).nth(4).focus()
    page.keyboard.press("Shift+Space")
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {"keys": ["1", "2", "3", "4"]}
    assert _checkboxes(page).nth(1).is_checked()


def test_check_all_reads_indeterminate_with_one_row_unchecked(page: Page, live_server):
    _open(page, live_server)
    _select_mode(page)
    page.locator("[data-selection-check-all]").click()
    _checkboxes(page).nth(3).click()
    assert page.evaluate(
        "() => document.querySelector('[data-selection-check-all]').indeterminate"
    )


def test_all_matching_keeps_the_scope_and_records_the_exclusion(
    page: Page, live_server
):
    _open(page, live_server)
    _select_mode(page)
    page.evaluate(STATEMENT_LOG)
    page.locator("[data-selection-all-matching]").click()
    _checkboxes(page).nth(2).click()
    statement = page.evaluate("() => window.statements.at(-1)")
    assert statement == {
        "all": True,
        "filter": '{"year": 2025}',
        "count": MATCHING_COUNT,
        "except": ["2"],
    }
    assert "119 selected" in page.locator("[data-selection-count]").inner_text()


def test_a_whole_list_offers_no_wider_scope(page: Page, live_server):
    _open(page, live_server, "/test-selectable-table-whole/")
    _select_mode(page)
    assert page.locator("[data-selection-all-matching]").count() == 0
    assert page.locator("[data-selection-check-all]").is_visible()


def test_the_region_speaks_at_a_change_of_scope_and_not_at_a_tick(
    page: Page, live_server
):
    _open(page, live_server)
    region = page.locator("[data-selection-announcement]")
    assert region.get_attribute("role") == "status"
    _select_mode(page)
    assert region.inner_text() == "Selecting rows."
    _checkboxes(page).nth(0).click()
    assert region.inner_text() == "Selecting rows."
    page.locator("[data-selection-all-matching]").click()
    assert "every row matching the filter" in region.inner_text()
    page.locator("[data-selection-clear]").click()
    assert region.inner_text() == "Selection cleared."


def test_the_line_sticks_to_the_foot_of_the_window(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_mode(page)
    # Mid-table, with the table still below the window.
    page.evaluate("() => window.scrollTo(0, 300)")
    page.wait_for_timeout(100)
    bottom = page.evaluate(LINE_BOTTOM)
    height = page.evaluate("() => window.innerHeight")
    assert abs(bottom - height) <= 1, f"line bottom {bottom}, window {height}"


def test_the_line_stops_at_the_end_of_its_own_table(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server)
    _select_mode(page)
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
    _select_mode(page)
    published = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--selection-line')"
    )
    assert published.endswith("px")
    assert int(published.removesuffix("px")) > 0


def test_a_row_menu_opens_over_the_line_and_owns_escape(page: Page, live_server):
    _open(page, live_server)
    _select_mode(page)
    _checkboxes(page).nth(0).click()
    page.get_by_role("button", name="Act 0").click()
    panel = page.locator("[role='menu']").first
    panel.wait_for(state="visible")
    page.keyboard.press("Escape")
    # The menu answered it; the selection stands.
    assert _checkboxes(page).nth(0).is_checked()
    page.keyboard.press("Escape")
    assert not _checkboxes(page).nth(0).is_checked()


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
