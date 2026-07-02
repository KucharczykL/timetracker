"""End-to-end tests for the advanced filter-builder page shell (#196).

Covers the full browser lifecycle of the builder page:
  1. All four custom elements load and initialize (filter-group, filter-summary,
     filter-count, filter-builder).
  2. A prefilled ?filter= seeds the filter-group tree AND hydrates each leaf's
     value widget (#263), so the summary reflects the criterion field and the
     count/Apply read the prefilled values from the live widgets.
  3. Clicking Apply navigates to the game list carrying the ?filter=.
  4. Navigating to the game list with ?filter= narrows results via the Django
     backend (tests the round-trip: JSON → GameFilter.to_q() → queryset).

Prefill behavior note:
  The filter-group element deserializes the ?filter= JSON into its internal tree
  on connectedCallback, so ``filter-group.serialize()`` returns the original
  filter.  ``serializeForQuery()`` — which Apply and filter-count both call —
  reads values from the live DOM widgets; since #263 each cloned widget is
  hydrated from its leaf's stored criterion (``writeLeafWidget``), so a prefilled
  filter round-trips: the count badge reflects the narrowed query and Apply
  carries the ``?filter=`` through to the list
  (``test_prefill_apply_roundtrip_carries_filter``).
"""

import json
import urllib.parse
from datetime import datetime, timezone

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import FilterPreset, Game, Platform, PlayEvent, Purchase


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

    # The filter JSON seeds the filter-group tree AND the leaf's value widget
    # (#263 hydration): status INCLUDES finished ("f").
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
    # It uses serializeForQuery(), which reads the hydrated widget (#263), so the
    # count reflects the prefilled filter: only DoneGame (status=f) matches.
    count_badge = page.locator("filter-count")
    expect(count_badge).not_to_contain_text("Counting…")
    expect(count_badge).to_contain_text("≈ 1 game")


def test_apply_navigates_to_game_list(authenticated_page: Page, live_server) -> None:
    """Clicking Apply on the builder page triggers navigation to the game list.

    Validates only that the Apply button is present, enabled, and wired to a
    navigation; the ?filter= carried by that navigation is asserted separately
    by test_prefill_apply_roundtrip_carries_filter."""
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

    # Apply navigates to the game list; the path must contain /tracker/game/list
    # (the carried ?filter= is asserted by the round-trip test below).
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


def test_prefill_apply_roundtrip_carries_filter(
    authenticated_page: Page, live_server
) -> None:
    """The full prefill → Apply → filtered-list round-trip (#263).

    The leaf value widgets are hydrated from the deserialized tree
    (writeLeafWidget), so serializeForQuery() reads the prefilled values and
    Apply carries the ?filter= through to the game list, narrowing results."""
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

    Asserted boundary: the field picker shows "Game" selected after the preset
    loads, and the value widget carries the hydrated include pill (#263).
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

    # -- Assertion 4: the value widget is hydrated (#263) --
    # writeLeafWidget clones an include pill for the preset's {id, label} value
    # into the FilterSelect's pills area, so the game's name shows as a pill.
    value_pill = criterion_row.locator(
        "[data-value-cell] [data-search-select-pills] [data-pill]"
    )
    expect(value_pill).to_be_visible(timeout=5_000)
    expect(value_pill).to_contain_text("SpyGame")


def test_nested_relation_prefill_renders_full_tree(
    authenticated_page: Page, live_server
) -> None:
    """The stats "View all" → Advanced filter URL shape: a purchase filter whose
    only key is a nested relation chain (game_filter → playevent_filter → ended
    BETWEEN) must deserialize into two relation rows with the inner date widget
    hydrated — not one "Incomplete" criterion row whose pruned query matches all
    purchases.  Regression: buildRegistry() leaked relation-kind field names into
    the registry's criterion-field set, and deserialize resolves criterion-first,
    so the relation swallowed its whole subtree as an opaque criterion payload."""
    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    done_game = Game.objects.create(name="DoneGame", platform=platform, status="f")
    other_game = Game.objects.create(name="OtherGame", platform=platform, status="p")
    PlayEvent.objects.create(
        game=done_game, ended=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    )
    matching_purchase = Purchase.objects.create(
        date_purchased=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        type=Purchase.GAME,
    )
    matching_purchase.games.set([done_game])
    non_matching_purchase = Purchase.objects.create(
        date_purchased=datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc),
        type=Purchase.GAME,
    )
    non_matching_purchase.games.set([other_game])

    filter_json = {
        "game_filter": {
            "playevent_filter": {
                "ended": {
                    "value": "2026-01-01",
                    "modifier": "BETWEEN",
                    "value2": "2026-12-31",
                }
            }
        }
    }
    page.goto(
        f"{live_server.url}{reverse('games:filter_builder', args=['purchase'])}"
        f"?filter={_encode_filter(filter_json)}"
    )

    group = page.locator("filter-group")
    expect(group).to_be_attached()

    # Two relation rows (outer game_filter, inner playevent_filter), each with its
    # field reflected in the relation picker.  The rows nest, so "first" is the
    # outer card and its own picker is the first select inside it.
    relation_rows = group.locator('[data-node-slot][data-node-kind="relation"]')
    expect(relation_rows).to_have_count(2)
    expect(relation_rows.nth(0).locator("[data-relation-field]").first).to_have_value(
        "game_filter"
    )
    expect(relation_rows.nth(1).locator("[data-relation-field]").first).to_have_value(
        "playevent_filter"
    )

    # Nothing is incomplete: the inner date criterion hydrated both bounds.
    expect(group.locator("[data-incomplete-badge]")).to_have_count(0)
    expect(group.locator("[data-range-min]").first).to_have_value("2026-01-01")
    expect(group.locator("[data-range-max]").first).to_have_value("2026-12-31")

    # The count reads the live widgets via serializeForQuery(): only the purchase
    # of the game with a 2026 PlayEvent matches — not all purchases (the bug
    # pruned the whole filter and counted everything).
    count_badge = page.locator("filter-count")
    expect(count_badge).not_to_contain_text("Counting…")
    expect(count_badge).to_contain_text("≈ 1 purchase")
