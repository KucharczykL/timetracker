import pytest
from django.urls import path
from django.http import HttpResponse
from django.test import override_settings
from playwright.sync_api import expect
from common.components import SearchSelect


def e2e_test_view(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SearchSelect E2E Test</title>
        <!-- Load the compiled CSS so tests can assert real rendered visibility
             (the .hidden utility resolves to display:none) instead of class strings. -->
        <link rel="stylesheet" href="/static/base.css">
        <!-- search-select is a custom element; htmx must be present for filter_bar. -->
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <!-- host_dropdown=True wraps each widget in <drop-down behavior=inline-combobox>,
             whose behaviors are registered by drop-down.js (#348). -->
        <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
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
            host_dropdown=True,
        )
    }
            {
        SearchSelect(
            name="tags",
            options=[
                {"value": "1", "label": "Apple", "data": {}},
                {"value": "2", "label": "Banana", "data": {}},
            ],
            multi_select=True,
            id="multi-search",
            host_dropdown=True,
        )
    }
            <input type="text" id="next-field" />
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


def anchor_test_view(request):
    options = [
        {"value": str(i), "label": f"Option {i:02d}", "data": {}} for i in range(15)
    ]
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Anchor E2E Test</title>
        <link rel="stylesheet" href="/static/base.css">
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
    </head>
    <body>
        <div style="height: 1400px"></div>
        <div style="padding: 8px;">
            {
        SearchSelect(
            name="thing",
            options=options,
            multi_select=False,
            host_dropdown=True,
        )
    }
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


def anchor_search_options_view(request):
    from django.http import JsonResponse

    items = [{"value": str(i), "label": f"Item {i:02d}", "data": {}} for i in range(6)]
    query = request.GET.get("q", "").lower()
    if query:
        items = [item for item in items if query in item["label"].lower()]
    return JsonResponse(items, safe=False)


def searchurl_committed_view(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="/static/base.css">
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
    </head>
    <body>
        <div style="padding: 50px;">
            {
        SearchSelect(
            name="item",
            search_url="/anchor-search-options/",
            prefetch=6,
            selected=[{"value": "3", "label": "Item 03", "data": {}}],
            multi_select=False,
            host_dropdown=True,
        )
    }
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


def slow_options_view(request):
    """A search_url endpoint that stalls, so a test can Tab away while a fetch is
    in flight and assert the resolved response can't reopen the panel (#451)."""
    import json
    import time

    time.sleep(0.3)
    return HttpResponse(
        json.dumps([{"value": "9", "label": "Delayed Game", "data": {}}]),
        content_type="application/json",
    )


def slow_search_view(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SearchSelect slow-fetch E2E Test</title>
        <link rel="stylesheet" href="/static/base.css">
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
    </head>
    <body>
        <div style="padding: 50px;">
            {
        SearchSelect(
            name="games",
            options=[],
            search_url="/slow-options/",
            multi_select=False,
            id="slow-search",
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
    path("test-anchor/", anchor_test_view),
    path("anchor-search-options/", anchor_search_options_view),
    path("searchurl-committed/", searchurl_committed_view),
    path("test-slow-search/", slow_search_view),
    path("slow-options/", slow_options_view),
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

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )

    assert search_input.input_value() == "Game A"

    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "7"

    # Focus the input
    print("\n--- FOCUSING INPUT ---")
    search_input.focus()
    # Focus keeps the committed label (selected), not wiped.
    assert search_input.input_value() == "Game A"

    # Press Backspace using the raw keyboard API to avoid any high-level Playwright input simulation
    print("\n--- PRESSING BACKSPACE ---")
    page.keyboard.press("Backspace")

    # Explicitly blur the input
    print("\n--- BLURRING INPUT ---")
    search_input.blur()

    # Deleting all text is an edit, and the edit itself cleared the committed
    # value — blur changes nothing.
    assert search_input.input_value() == ""
    assert hidden_input.count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_typing_replaces_label_and_keeps_text(live_server, page):
    """Typing over a committed label replaces it, and the typed text survives
    blur — a value is committed only by an explicit pick, so the first edit
    clears the old one instead of blur restoring it."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )

    search_input.focus()
    assert search_input.input_value() == "Game A"

    search_input.type("X")
    assert search_input.input_value() == "X"

    search_input.blur()

    assert search_input.input_value() == "X"

    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_tab_does_not_enter_panel(live_server, page):
    """Regression guard for issue #119: Tab must leave the widget, not land focus
    on the overflowing options scroller (which Chrome makes keyboard-focusable)."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
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

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    options_panel = page.locator(
        'search-select[name="games"] [data-search-select-options]'
    )

    search_input.focus()
    # Panel is open on focus.
    expect(options_panel).to_be_visible()

    page.keyboard.press("Tab")

    # Focus left the widget, and the panel closed with no lingering highlight.
    expect(options_panel).to_be_hidden()
    assert page.evaluate(
        "() => !document.activeElement.closest('search-select[name=\"games\"]')"
    )
    assert (
        page.locator(
            'search-select[name="games"] [data-search-select-highlighted]'
        ).count()
        == 0
    )


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_option_click_selects(live_server, page):
    """Clicking an option still selects it (the new focusout handler must not
    close the panel before the click lands — guarded by options mousedown)."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    options_panel = page.locator(
        'search-select[name="games"] [data-search-select-options]'
    )

    search_input.focus()
    page.locator('[data-search-select-option][data-value="8"]').click()

    expect(search_input).to_have_value("Game B")
    assert page.locator('input[name="games"]').first.get_attribute("value") == "8"
    expect(options_panel).to_be_hidden()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_arrow_and_enter_selects(live_server, page):
    """Arrow navigation moves the highlight and Enter commits the selection."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    search_input.focus()
    assert search_input.input_value() == "Game A"

    # On focus the first option (Game A) is auto-highlighted; ArrowDown moves to
    # the next visible option (Game B), and Enter commits it.
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")

    expect(search_input).to_have_value("Game B")
    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "8"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_type_filters_and_highlights(live_server, page):
    """Typing filters out non-matching rows and auto-highlights a match."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    search_input.focus()
    search_input.type("B")

    game_a_row = page.locator('[data-search-select-option][data-value="7"]')
    game_b_row = page.locator('[data-search-select-option][data-value="8"]')

    expect(game_a_row).to_be_hidden()
    expect(game_b_row).to_be_visible()
    assert game_b_row.get_attribute("data-search-select-highlighted") is not None


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_aria_combobox_semantics(live_server, page):
    """Issue #154: the widget exposes the full ARIA combobox pattern —
    aria-expanded tracks the panel, aria-controls points at the listbox, and
    aria-activedescendant/aria-selected follow the keyboard highlight."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    options_panel = page.locator(
        'search-select[name="games"] [data-search-select-options]'
    )

    # Static roles come from the server markup; the JS wires aria-controls to
    # the panel's generated id at init.
    assert search_input.get_attribute("role") == "combobox"
    assert options_panel.get_attribute("role") == "listbox"
    expect(search_input).to_have_attribute("aria-expanded", "false")
    panel_id = options_panel.get_attribute("id")
    assert panel_id
    assert search_input.get_attribute("aria-controls") == panel_id

    search_input.focus()

    # Panel opens; the auto-highlighted first option becomes the active
    # descendant without moving DOM focus off the input.
    expect(search_input).to_have_attribute("aria-expanded", "true")
    game_a_row = page.locator('[data-search-select-option][data-value="7"]')
    game_b_row = page.locator('[data-search-select-option][data-value="8"]')
    expect(game_a_row).to_have_attribute("aria-selected", "true")
    assert search_input.get_attribute(
        "aria-activedescendant"
    ) == game_a_row.get_attribute("id")

    page.keyboard.press("ArrowDown")
    expect(game_b_row).to_have_attribute("aria-selected", "true")
    expect(game_a_row).to_have_attribute("aria-selected", "false")
    assert search_input.get_attribute(
        "aria-activedescendant"
    ) == game_b_row.get_attribute("id")

    page.keyboard.press("Escape")
    expect(search_input).to_have_attribute("aria-expanded", "false")
    assert search_input.get_attribute("aria-activedescendant") is None


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_click_commit_clears_highlight(live_server, page):
    """PR #294 review: committing via option click must not leave the collapsed
    listbox with a stale highlighted/aria-selected row (the Enter path already
    cleared it; the click path used to skip clearHighlight)."""
    page.goto(live_server.url + "/test-search-select/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    search_input.focus()
    # Focus auto-highlights Game A; commit Game B by mouse instead.
    page.locator('[data-search-select-option][data-value="8"]').click()

    expect(search_input).to_have_attribute("aria-expanded", "false")
    assert search_input.get_attribute("aria-activedescendant") is None
    games_widget = page.locator('search-select[name="games"]')
    assert games_widget.locator("[data-search-select-highlighted]").count() == 0
    assert games_widget.locator('[aria-selected="true"]').count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_multi_select_aria_selected_tracks_membership(live_server, page):
    """PR #294 review: in the aria-multiselectable listbox, aria-selected means
    membership (a pill exists for the value), not the keyboard highlight."""
    page.goto(live_server.url + "/test-search-select/")

    multi_search = page.locator("#multi-search")
    apple_row = page.locator(
        'search-select[name="tags"] [data-search-select-option][data-value="1"]'
    )
    banana_row = page.locator(
        'search-select[name="tags"] [data-search-select-option][data-value="2"]'
    )

    multi_search.focus()
    apple_row.click()

    expect(apple_row).to_have_attribute("aria-selected", "true")
    expect(banana_row).to_have_attribute("aria-selected", "false")

    # Removing the pill revokes membership.
    page.locator('search-select[name="tags"] [data-pill-remove]').click()
    expect(apple_row).to_have_attribute("aria-selected", "false")


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_multi_select_keeps_query_on_tab_out(live_server, page):
    """The uncommitted query must persist across tab-out/refocus (matching
    single-select, which keeps its committed label). Text must not disappear
    unless the user deletes it."""
    multi_search = page.locator("#multi-search")
    banana_row = page.locator('[data-search-select-option][data-value="2"]')

    page.goto(live_server.url + "/test-search-select/")

    multi_search.focus()
    multi_search.type("App")
    # Filtering is active: the non-matching row is hidden while the panel is open.
    expect(banana_row).to_be_hidden()

    page.keyboard.press("Tab")

    # The transient query persists after tabbing out.
    expect(multi_search).to_have_value("App")
    # Re-opening keeps the query applied (list stays filtered).
    multi_search.focus()
    expect(banana_row).to_be_hidden()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_panel_stays_anchored_when_filtered(live_server, page):
    """A top-flipped combobox panel must stay anchored to its trigger as filtering
    shrinks it — not keep the taller panel's stale top and float up."""
    page.set_viewport_size({"width": 1280, "height": 520})
    page.goto(live_server.url + "/test-anchor/")

    search_input = page.locator(
        'search-select[name="thing"] input[data-search-select-search]'
    )
    panel = page.locator('search-select[name="thing"] [data-search-select-options]')

    # Field sits near the viewport bottom → the panel cannot fit below and flips up.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    search_input.focus()
    expect(panel).to_be_visible()

    def measure():
        return page.evaluate(
            """() => {
                const trigger = document.querySelector('search-select[name="thing"]');
                const panel = document.querySelector('search-select[name="thing"] [data-search-select-options]');
                const triggerRect = trigger.getBoundingClientRect();
                const panelRect = panel.getBoundingClientRect();
                return {
                    flippedUp: panelRect.top < triggerRect.top,
                    gap: Math.abs(panelRect.bottom - triggerRect.top),
                };
            }"""
        )

    before = measure()
    assert before["flippedUp"], before
    assert before["gap"] <= 2, before

    # Filter to a single row — the panel shrinks sharply.
    search_input.type("Option 01")
    page.wait_for_timeout(100)

    after = measure()
    # Still anchored: the panel's bottom edge meets the trigger's top edge.
    assert after["gap"] <= 2, after


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_click_then_type_replaces_label(live_server, page):
    """Clicking a committed field (mouse, not programmatic focus) then typing must
    REPLACE the selected label, not append to it. Guards the select()
    mouseup-collapse quirk."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    search_input.click()
    page.keyboard.type("X")
    assert search_input.input_value() == "X"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_searchurl_committed_single_select_shows_full_list_on_focus(live_server, page):
    """A committed single-select backed by a search-url must show the committed
    label in the box AND the full prefetched list on focus — not collapse to the
    single row matching the label."""
    page.goto(live_server.url + "/searchurl-committed/")
    search_input = page.locator(
        'search-select[name="item"] input[data-search-select-search]'
    )
    assert search_input.input_value() == "Item 03"
    search_input.focus()
    options = page.locator(
        'search-select[name="item"] [data-search-select-option]:visible'
    )
    expect(options).to_have_count(6)


def _games_search_input(page):
    return page.locator('search-select[name="games"] input[data-search-select-search]')


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_keeps_partial_query_on_blur(live_server, page):
    """Typing a partial query and leaving without picking keeps the text —
    typed text must never disappear unless the user deletes it. The edit
    already cleared the old committed value, so nothing submits."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)

    search_input.focus()
    search_input.type("Gam")
    page.locator("#next-field").focus()

    # Nothing deferred may rewrite the box after blur.
    page.wait_for_timeout(200)
    assert search_input.input_value() == "Gam"
    assert page.locator('input[name="games"]').count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_retained_query_filters_on_refocus(live_server, page):
    """Refocusing a box holding a retained (unpicked) query keeps the text and
    filters the list by it — not the committed-label full-list treatment."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)
    game_a_row = page.locator('[data-search-select-option][data-value="7"]')
    game_b_row = page.locator('[data-search-select-option][data-value="8"]')

    search_input.focus()
    search_input.type("B")
    page.locator("#next-field").focus()

    search_input.focus()
    assert search_input.input_value() == "B"
    expect(game_a_row).to_be_hidden()
    expect(game_b_row).to_be_visible()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_edit_clears_committed_value(live_server, page):
    """The first keystroke in a committed field clears its value immediately and
    fires exactly one empty search-select:change; later keystrokes are plain
    query edits."""
    page.goto(live_server.url + "/test-search-select/")
    page.evaluate(
        """() => {
            window.__changes = [];
            document.querySelector('search-select[name="games"]').addEventListener(
                'search-select:change',
                (event) => window.__changes.push(event.detail)
            );
        }"""
    )
    search_input = _games_search_input(page)
    hidden_input = page.locator('input[name="games"]')
    assert hidden_input.first.get_attribute("value") == "7"

    search_input.focus()
    search_input.type("X")

    assert hidden_input.count() == 0
    changes = page.evaluate("() => window.__changes")
    assert len(changes) == 1
    assert changes[0]["values"] == []
    assert changes[0]["last"] is None

    # A second keystroke edits the query without another change event.
    search_input.type("Y")
    assert page.evaluate("() => window.__changes.length") == 1


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_focus_then_blur_keeps_committed_value(live_server, page):
    """Focusing a committed field and leaving without typing is a no-op: the
    label stays in the box and the committed value still submits."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)

    search_input.focus()
    assert search_input.input_value() == "Game A"
    page.locator("#next-field").focus()

    # Nothing deferred may rewrite the box or the value after blur.
    page.wait_for_timeout(200)
    assert search_input.input_value() == "Game A"
    assert page.locator('input[name="games"]').first.get_attribute("value") == "7"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_committed_focus_shows_full_list(live_server, page):
    """Focusing a committed inline (no search-url) single-select shows the full
    option list, not just the row matching the committed label."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)

    search_input.focus()
    options = page.locator(
        'search-select[name="games"] [data-search-select-option]:visible'
    )
    expect(options).to_have_count(2)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_repick_after_edit_clear(live_server, page):
    """After an edit cleared the committed value, picking an option commits it:
    hidden value set, box shows the picked label."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)
    hidden_input = page.locator('input[name="games"]')

    search_input.focus()
    search_input.type("B")
    assert hidden_input.count() == 0

    page.locator('[data-search-select-option][data-value="8"]').click()

    expect(search_input).to_have_value("Game B")
    assert hidden_input.first.get_attribute("value") == "8"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_escape_keeps_text(live_server, page):
    """Escape only closes the panel. After an edit it keeps the typed text and
    the cleared value (no undo); on an unedited committed field it keeps the
    label and the committed value."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)
    options_panel = page.locator(
        'search-select[name="games"] [data-search-select-options]'
    )
    hidden_input = page.locator('input[name="games"]')

    search_input.focus()
    search_input.type("Gam")
    page.keyboard.press("Escape")

    expect(options_panel).to_be_hidden()
    assert search_input.input_value() == "Gam"
    assert hidden_input.count() == 0

    # Unedited committed field: Escape closes the panel and touches nothing.
    page.reload()
    search_input.focus()
    page.keyboard.press("Escape")

    expect(options_panel).to_be_hidden()
    assert search_input.input_value() == "Game A"
    assert hidden_input.first.get_attribute("value") == "7"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_single_select_exact_retype_saves_nothing(live_server, page):
    """Retyping the exact label without a pick leaves the field uncommitted: the
    box reads a valid label but nothing submits. Guards against a future
    accidental auto-commit on a text match."""
    page.goto(live_server.url + "/test-search-select/")
    search_input = _games_search_input(page)

    search_input.focus()
    search_input.type("Game A")
    page.locator("#next-field").focus()

    page.wait_for_timeout(200)
    assert search_input.input_value() == "Game A"
    assert page.locator('input[name="games"]').count() == 0


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_e2e")
def test_search_select_late_fetch_does_not_reopen_after_blur(live_server, page):
    """Issue #451: a debounced search_url fetch that resolves after the user has
    Tabbed away must not reopen the panel over the next field. focusout cancels
    the pending debounce timer and aborts the in-flight request."""
    page.goto(live_server.url + "/test-slow-search/")

    search_input = page.locator(
        'search-select[name="games"] input[data-search-select-search]'
    )
    options_panel = page.locator(
        'search-select[name="games"] [data-search-select-options]'
    )

    search_input.focus()
    search_input.type("D")
    # Let the 100ms debounce fire so the (300ms) fetch is genuinely in flight,
    # then Tab away while it is still pending.
    page.wait_for_timeout(150)
    page.keyboard.press("Tab")
    expect(options_panel).to_be_hidden()

    # Wait past the fetch's completion: the aborted response must not reopen it.
    page.wait_for_timeout(400)
    expect(options_panel).to_be_hidden()
    assert page.evaluate(
        "() => !document.activeElement.closest('search-select[name=\"games\"]')"
    )
