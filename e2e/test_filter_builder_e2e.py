"""End-to-end tests for the advanced filter-builder page shell (#196).

Covers the full browser lifecycle of the builder page:
  1. All four custom elements load and initialize (filter-group, filter-summary,
     filter-count, filter-builder).
  2. A prefilled ?filter= seeds the filter-group tree so the summary reflects
     the criterion field (even though the DOM widget is blank — the tree structure
     is seeded, the DOM widget value is read live on Apply).
  3. Clicking Apply navigates to the game list.
  4. Navigating to the game list with ?filter= narrows results via the Django
     backend (tests the round-trip: JSON → GameFilter.to_q() → queryset).

Prefill behavior note:
  The filter-group element deserializes the ?filter= JSON into its internal tree
  on connectedCallback, so ``filter-group.serialize()`` returns the original
  filter.  However ``serializeForQuery()`` — which Apply and filter-count both
  call — reads values from the live DOM widgets.  Because widget templates are
  cloned blank (no value is back-propagated from the deserialized tree into the
  DOM), serializeForQuery() returns {} for a prefilled filter whose widgets have
  not been touched.  The count badge therefore shows all games (empty query) and
  Apply navigates to the plain game-list URL without ?filter=.

  What IS tested end-to-end:
    - the JS loads and upgrades all four custom elements
    - the filter-group dispatches filter-tree-change on connect, triggering the
      summary to render "Games where Status …" (criterion field is known)
    - the count badge reaches a settled non-"Counting…" state
    - the Apply button triggers a navigation to /tracker/game/list
    - navigating directly to /tracker/game/list?filter=<JSON> narrows results
      on the Django side (round-trip GameFilter JSON test)

Known limitation — tracked in #263:
  Prefill seeds the filter-group tree structure but does NOT yet hydrate the
  leaf value widgets.  Therefore ``serializeForQuery()`` reads blank widgets and
  Apply navigates to the list WITHOUT ``?filter=`` — the prefilled filter is
  dropped.  The full prefill→Apply→filtered-list round-trip is tested below as a
  strict xfail (``test_prefill_apply_roundtrip_carries_filter``); when #263 lands
  and that test unexpectedly passes, the suite will fail — forcing removal of the
  marker and confirming the fix.
"""

import json
import urllib.parse

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import FilterPreset, Game, Platform


# ── auth helpers (no shared authenticated_page fixture exists in conftest.py) ──


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    _login(page, live_server)
    return page


# ── filter JSON helpers ────────────────────────────────────────────────────────


def _encode_filter(filter_dict: dict) -> str:
    """URL-encode a filter dict for use in a ?filter= query parameter."""
    return urllib.parse.quote(json.dumps(filter_dict))


# ── tests ──────────────────────────────────────────────────────────────────────


def test_builder_page_elements_load_and_initialize(
    authenticated_page: Page, live_server
) -> None:
    """The builder page loads all four custom elements and the JavaScript
    initializes: the filter-group seeds its tree from the prefilled ?filter=
    and fires filter-tree-change, the summary updates to show "Games where
    Status", and the count badge settles from "Counting…"."""
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    Game.objects.create(name="DoneGame", platform=platform, status="f")
    Game.objects.create(name="PlayGame", platform=platform, status="p")

    # The filter JSON seeds the filter-group tree: status INCLUDES finished ("f").
    # filter-group.serialize() will reflect this field, even though the DOM widget
    # is blank (serializeForQuery() reads from widgets, not the stored tree).
    filter_json = {"status": {"modifier": "INCLUDES", "value": ["f"]}}
    filter_param = _encode_filter(filter_json)

    builder_url = (
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={filter_param}"
    )
    page.goto(builder_url)

    # All four custom elements are present in the DOM.
    expect(page.locator("filter-group")).to_be_attached()
    expect(page.locator("filter-summary")).to_be_attached()
    expect(page.locator("filter-count")).to_be_attached()
    expect(page.locator("filter-builder")).to_be_attached()

    # The filter-group fires filter-tree-change on connect (with the seeded tree).
    # The summary element receives the event and renders "Games where Status …"
    # because the tree has a criterion node with field="status" (but no live widget
    # value yet — summary renders the field label with "…" as a placeholder).
    expect(page.locator("filter-summary")).to_contain_text("Games where")

    # The count badge fetches from the API and settles (stops showing "Counting…").
    # It uses serializeForQuery() which returns {} for a blank-widget tree, so
    # the count reflects all seeded games (both finished and playing).
    count_badge = page.locator("filter-count")
    expect(count_badge).not_to_contain_text("Counting…")
    # The count must be numeric — just not still loading. We don't assert the exact
    # number since serializeForQuery() returns {} (all games match).
    expect(count_badge).to_contain_text("≈")


def test_apply_navigates_to_game_list(authenticated_page: Page, live_server) -> None:
    """Clicking Apply on the builder page triggers navigation to the game list.

    Because serializeForQuery() reads from blank DOM widgets when the filter is
    seeded only via ?filter=, it returns {} (empty filter) and Apply navigates
    to the plain game-list URL without ?filter=. This still validates that the
    Apply button is present, enabled, and wired up correctly."""
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    Game.objects.create(name="DoneGame", platform=platform, status="f")
    Game.objects.create(name="PlayGame", platform=platform, status="p")

    filter_json = {"status": {"modifier": "INCLUDES", "value": ["f"]}}
    filter_param = _encode_filter(filter_json)

    builder_url = (
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={filter_param}"
    )
    page.goto(builder_url)

    # Wait for the JS to initialize: count badge must have settled.
    expect(page.locator("filter-count")).not_to_contain_text("Counting…")

    # Click the Apply button inside the <filter-builder> toolbar.
    with page.expect_navigation():
        page.locator("filter-builder [data-apply]").click()

    # Apply navigates to the game list (with or without ?filter=, depending on
    # widget state). The path must contain /tracker/game/list.
    current_url = page.url
    assert "/tracker/game/list" in current_url, (
        f"Expected URL to contain '/tracker/game/list', got: {current_url}"
    )


def test_game_list_filter_narrows_results(
    authenticated_page: Page, live_server
) -> None:
    """The game list URL with ?filter=<JSON> narrows results end-to-end.

    The JSON {"status": {"modifier": "INCLUDES", "value": ["f"]}} is a valid
    GameFilter JSON whose to_q() produces Q(status__in=["f"]), matching only
    games with status="f" (Finished).  This round-trip proves the Django backend
    correctly filters the queryset from the URL parameter."""
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    Game.objects.create(name="DoneGame", platform=platform, status="f")
    Game.objects.create(name="PlayGame", platform=platform, status="p")

    # Navigate directly to the game list with the status=Finished filter.
    # This is the same JSON the builder's Apply would send if the widget were set.
    filter_json = {"status": {"modifier": "INCLUDES", "value": ["f"]}}
    filter_param = _encode_filter(filter_json)

    game_list_url = (
        f"{live_server.url}{reverse('games:list_games')}?filter={filter_param}"
    )
    page.goto(game_list_url)

    # DoneGame (status=f) must appear; PlayGame (status=p) must not.
    expect(page.get_by_text("DoneGame")).to_be_visible()
    expect(page.get_by_text("PlayGame")).not_to_be_visible()


@pytest.mark.xfail(
    reason="prefill value-widget hydration not implemented yet — #263",
    strict=True,
)
def test_prefill_apply_roundtrip_carries_filter(
    authenticated_page: Page, live_server
) -> None:
    """The full prefill → Apply → filtered-list round-trip is NOT yet working.

    When #263 lands (leaf value widgets are hydrated from the deserialized tree),
    serializeForQuery() will read the hydrated values and Apply will carry the
    ?filter= through to the game list, narrowing results.  Until then this test
    is expected to fail (strict xfail): if it unexpectedly passes the suite
    reports XPASS and fails, forcing removal of the marker."""
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    Game.objects.create(name="DoneGame", platform=platform, status="f")
    Game.objects.create(name="PlayGame", platform=platform, status="p")

    # Same filter JSON used by the other tests in this file: status INCLUDES "f".
    filter_json = {"status": {"modifier": "INCLUDES", "value": ["f"]}}
    filter_param = _encode_filter(filter_json)

    builder_url = (
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={filter_param}"
    )
    page.goto(builder_url)

    # Wait for the JS to initialize: count badge must have settled.
    expect(page.locator("filter-count")).not_to_contain_text("Counting…")

    # Click Apply and wait for navigation.
    with page.expect_navigation():
        page.locator("filter-builder [data-apply]").click()

    # The round-trip assertion: Apply must carry ?filter= into the game list URL
    # so the Django backend can narrow results.
    current_url = page.url
    assert "?filter=" in current_url, (
        f"Expected Apply to carry ?filter= but got: {current_url}"
    )

    # With the prefilled filter active, only the finished game should appear.
    expect(page.get_by_text("DoneGame")).to_be_visible()
    expect(page.get_by_text("PlayGame")).not_to_be_visible()


def test_load_set_field_preset_reflects_field_without_crash(
    authenticated_page: Page, live_server, django_user_model
) -> None:
    """Loading a preset whose filter contains a set-field criterion (session's
    ``game`` field) must not throw and must reflect the field in the picker.

    Before Fix-C (commit 3b18252) ``loadFilter`` called ``showFieldSelection``
    during the detached build phase, before the cloned ``<search-select>``
    elements were upgraded.  ``setSelected`` did not exist on the detached
    element, which threw a TypeError and triggered the "Preset is not a valid
    filter." error toast.  Fix-C defers field reflection to
    ``reflectFieldSelections()``, called after ``replaceChildren()`` so every
    ``<search-select>`` is live.  This test guards that fix at the browser level.

    Asserted boundary: the field picker shows "Game" selected (a pill with the
    label "Game" appears in the field-picker's pills area) after the preset
    loads.  Value/modifier hydration is deferred to issue #263 and is NOT
    asserted here.
    """
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="SpyGame", platform=platform, status="p")

    # Obtain the user created by the authenticated_page fixture (username="tester").
    user = django_user_model.objects.get(username="tester")

    # A session preset whose object_filter contains a set-field criterion for
    # the session's ``game`` field.  This is the exact shape that triggered the
    # Fix-C crash: a ``set`` kind field with an id/label value list.
    FilterPreset.objects.create(
        user=user,
        mode="sessions",
        name="setpreset",
        object_filter={
            "AND": [
                {
                    "game": {
                        "value": [{"id": str(game.pk), "label": game.name}],
                        "excludes": [],
                        "modifier": "INCLUDES",
                    }
                }
            ]
        },
    )

    # Collect console messages BEFORE navigating so nothing is missed.
    console_messages: list[str] = []
    page.on("console", lambda message: console_messages.append(message.text))

    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['session'])}")

    # Wait for the builder page to finish initializing (count badge settles).
    expect(page.locator("filter-count")).not_to_contain_text(
        "Counting…", timeout=10_000
    )

    # Open the Load-preset dropdown.
    page.locator("filter-builder [data-load-presets]").click()

    # Wait for the dropdown to populate with the preset anchor.
    preset_anchor = page.locator("[data-preset-dropdown] a").filter(
        has_text="setpreset"
    )
    expect(preset_anchor).to_be_visible(timeout=5_000)

    # Click the preset anchor to load it into the filter group.
    preset_anchor.click()

    # Wait for the filter group to re-render (the criterion row must appear).
    criterion_row = page.locator("[data-node-kind='criterion']")
    expect(criterion_row).to_be_attached(timeout=5_000)

    # -- Assertion 1: no crash --
    # The Fix-C crash was logged as a ``console.error`` by the catch block in
    # ``onPresetPicked``: "filter-builder: preset load failed".  Assert that
    # exact string is absent.  (A generic "TypeError: Failed to fetch" from
    # filter-bar's auto-load on connect is unrelated and ignored here.)
    # The builder page has no <filter-bar> and <filter-builder> does not
    # auto-fetch on connect (only on Load-preset click).  This check simply
    # guards that loading the preset produced no error/crash.
    crash_messages = [text for text in console_messages if "preset load failed" in text]
    assert not crash_messages, (
        f"Unexpected crash in console after preset load: {crash_messages}"
    )

    # -- Assertion 2: no error toast --
    # A crash triggers window.toast("Preset is not a valid filter.", "error").
    # The toast renders via Alpine.js (x-text="toast.message") as a <p> element.
    # Assert the error message is NOT visible anywhere on the page.
    expect(page.get_by_text("Preset is not a valid filter.")).not_to_be_visible()

    # -- Assertion 3: field picker reflects "Game" --
    # After Fix-C, reflectFieldSelections() calls search-select.setSelected("game",
    # "Game") once the cloned element is live.  The field picker uses single-select
    # mode (multi_select=False): setSelected sets search.value = label rather than
    # inserting a pill.  Assert the search input inside the field picker shows "Game".
    field_search_input = criterion_row.locator(
        "[data-field-picker] [data-search-select-search]"
    )
    expect(field_search_input).to_have_value("Game", timeout=5_000)
