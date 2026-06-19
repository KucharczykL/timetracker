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
        <!-- search_select.js is an ES module and initializes via onSwap(),
             which rides on htmx.onLoad — so htmx must be present. -->
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/search_select.js"></script>
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
        const c = document.querySelector('[data-search-select]');
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
