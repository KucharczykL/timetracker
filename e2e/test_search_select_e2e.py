import pytest
from django.urls import path
from django.http import HttpResponse
from django.test import override_settings
from common.components import SearchSelect


def e2e_test_view(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SearchSelect E2E Test</title>
        <!-- search-select is a custom element; htmx must be present for filter_bar. -->
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
    </head>
    <body>
        <div style="padding: 50px;">
            {
        SearchSelect(
            name="games",
            selected=[{"value": "7", "label": "Game A", "data": {}}],
            options=[
                {"value": "7", "label": "Game A", "data": {}},
                {"value": "8", "label": "Game B", "data": {}},
            ],
            multi_select=False,
        )
    }
            <input type="text" id="next-field" />
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


urlpatterns = [
    path("test-search-select/", e2e_test_view),
]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_backspace_clears_single_select(live_server, page):
    # Enable console log forwarding
    page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))

    page.goto(live_server.url + "/test-search-select/")

    # Inject our event logger
    page.evaluate("""() => {
        const s = document.querySelector('input[data-search-select-search]');
        const c = document.querySelector('search-select');
        s.addEventListener('focus', () => console.log('JS-EVENT: focus, dirty=' + c._searchSelectDirty + ', value="' + s.value + '"'));
        s.addEventListener('blur', () => console.log('JS-EVENT: blur, dirty=' + c._searchSelectDirty + ', value="' + s.value + '"'));
        s.addEventListener('input', () => console.log('JS-EVENT: input, dirty=' + c._searchSelectDirty + ', value="' + s.value + '"'));
        s.addEventListener('keydown', (e) => console.log('JS-EVENT: keydown ' + e.key + ', dirty=' + c._searchSelectDirty + ', value="' + s.value + '"'));
    }""")

    search_input = page.locator("input[data-search-select-search]")

    assert search_input.input_value() == "Game A"

    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "7"

    # Focus the input
    print("\n--- FOCUSING INPUT ---")
    search_input.focus()
    assert search_input.input_value() == ""

    # Press Backspace using the raw keyboard API to avoid any high-level Playwright input simulation
    print("\n--- PRESSING BACKSPACE ---")
    page.keyboard.press("Backspace")

    # Explicitly blur the input
    print("\n--- BLURRING INPUT ---")
    search_input.blur()

    # Wait for blur microtasks/setTimeout to settle (120ms timeout in JS)
    page.wait_for_timeout(200)

    # After Backspace and blur, the input should remain empty (the selection is cleared)
    assert search_input.input_value() == ""
    assert hidden_input.count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_typing_replaces_single_select(live_server, page):
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator("input[data-search-select-search]")

    search_input.focus()
    assert search_input.input_value() == ""

    search_input.type("X")
    assert search_input.input_value() == "X"

    search_input.blur()
    page.wait_for_timeout(200)

    assert search_input.input_value() == "Game A"

    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "7"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_tab_does_not_enter_panel(live_server, page):
    """Regression guard for issue #119: Tab must leave the widget, not land focus
    on the overflowing options scroller (which Chrome makes keyboard-focusable)."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator("input[data-search-select-search]")
    search_input.focus()

    page.keyboard.press("Tab")

    focus_inside_panel = page.evaluate(
        """() => {
            const active = document.activeElement;
            return !!(active && active.closest('[data-search-select-options]'));
        }"""
    )
    assert focus_inside_panel is False


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_tab_closes_panel(live_server, page):
    """Issue #119 follow-up: Tabbing out of the widget must close the dropdown
    and clear any highlight (it previously stayed open over the next field)."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator("input[data-search-select-search]")
    options_panel = page.locator("[data-search-select-options]")

    search_input.focus()
    # Panel is open on focus.
    assert "hidden" not in (options_panel.get_attribute("class") or "")

    page.keyboard.press("Tab")
    page.wait_for_timeout(50)

    # Focus moved to the next field, and the panel closed with no lingering highlight.
    assert page.evaluate("() => document.activeElement.id") == "next-field"
    assert "hidden" in (options_panel.get_attribute("class") or "")
    assert page.locator("[data-search-select-highlighted]").count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_arrow_and_enter_selects(live_server, page):
    """Arrow navigation moves the highlight and Enter commits the selection."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator("input[data-search-select-search]")
    search_input.focus()
    assert search_input.input_value() == ""

    # On focus the first option (Game A) is auto-highlighted; ArrowDown moves to
    # the next visible option (Game B), and Enter commits it.
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(50)

    assert search_input.input_value() == "Game B"
    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "8"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_type_filters_and_highlights(live_server, page):
    """Typing filters out non-matching rows and auto-highlights a match."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator("input[data-search-select-search]")
    search_input.focus()
    search_input.type("B")
    page.wait_for_timeout(50)

    game_a_row = page.locator('[data-search-select-option][data-value="7"]')
    game_b_row = page.locator('[data-search-select-option][data-value="8"]')

    assert game_a_row.evaluate("node => node.style.display") == "none"
    assert game_b_row.evaluate("node => node.style.display") != "none"
    assert game_b_row.get_attribute("data-search-select-highlighted") is not None
