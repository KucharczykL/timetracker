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
import re
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

    # Server-template cloning contract (#273/#274): the tree's controls carry the
    # server-owned classes. A broken template selector would fall back to a
    # CLASSLESS control (the jsdom fixture path) and everything above would still
    # pass — so assert the styling actually arrived from the server templates.
    connective_chip = page.locator(
        'filter-group button[data-action="toggle-connective"]'
    ).first
    expect(connective_chip).to_have_class(re.compile(r"rounded-base"))
    action_button = page.locator(
        'filter-group button[data-action="add-condition"]'
    ).first
    expect(action_button).not_to_have_class("")
    add_relation = page.locator('filter-group button[data-action="add-relation"]').first
    add_relation.click()
    relation_match_select = page.locator(
        "filter-group select[data-relation-match]"
    ).first
    expect(relation_match_select).to_have_class(re.compile(r"rounded"))


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
    expect(page.locator("[data-truncated-clip]", has_text="DoneGame")).to_be_visible()
    expect(
        page.locator("[data-truncated-clip]", has_text="PlayGame")
    ).not_to_be_visible()


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
    expect(page.locator("[data-truncated-clip]", has_text="DoneGame")).to_be_visible()
    expect(
        page.locator("[data-truncated-clip]", has_text="PlayGame")
    ).not_to_be_visible()


def test_empty_preset_dropdown_shows_readable_placeholder(
    authenticated_page: Page, live_server
) -> None:
    """With zero saved presets, the Load-preset dropdown must show a readable
    "No saved presets" row (issue #295).

    The row was present in the DOM but invisible: the dropdown panel used
    ``bg-body`` — a *text*-color token (gray-600 light / gray-400 dark) — as its
    background, and the placeholder row uses ``text-body``, the same token, so
    the text was painted in exactly its background color.  Playwright's
    ``to_be_visible`` cannot catch same-color-on-same-color, so this test
    compares the row's computed ``color`` against the panel's computed
    ``background-color`` directly, in both light and dark mode.
    """
    page = authenticated_page

    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['game'])}")
    expect(page.locator("filter-builder")).to_be_attached()

    # Open the combobox dialog once; the fetch-on-open returns zero presets and
    # unhides the widget's no-results row. The dark-mode toggle only flips a
    # class on <html>; the already-open panel restyles in place. The no-results
    # node is stable (refetches replace only option rows), so no detach race.
    page.locator("filter-builder [data-preset-picker] [data-toggle]").click()
    panel = page.locator("filter-builder [data-preset-picker] [data-menu]")
    placeholder = panel.locator("[data-search-select-no-results]")
    expect(placeholder).to_have_text("No saved presets", timeout=5_000)

    for dark_mode in (False, True):
        page.evaluate(
            "dark => document.documentElement.classList.toggle('dark', dark)",
            dark_mode,
        )
        colors = panel.evaluate(
            """panel => {
                const row = panel.querySelector('[data-search-select-no-results]');
                return {
                    text: getComputedStyle(row).color,
                    panel: getComputedStyle(panel).backgroundColor,
                };
            }"""
        )
        assert colors["text"] != colors["panel"], (
            f"placeholder text invisible (dark={dark_mode}): text color "
            f"{colors['text']} equals dropdown background {colors['panel']}"
        )


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

    # Open the Load-preset combobox dialog.
    page.locator("filter-builder [data-preset-picker] [data-toggle]").click()

    # Wait for the fetch-on-open to populate the preset row.
    preset_row = page.locator(
        "filter-builder [data-preset-picker] [data-search-select-option]"
    ).filter(has_text="setpreset")
    expect(preset_row).to_be_visible(timeout=5_000)

    # Click the preset row to load it into the filter group.
    preset_row.click()

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


def test_field_layout_value_widget_hosts_on_inline_combobox(
    authenticated_page: Page, live_server
) -> None:
    """A set (enum) leaf's value widget renders on
    ``<drop-down behavior="inline-combobox">`` (#354): focusing its search input
    opens the hosted panel through the shared attachMenu engine, an include click
    adds a pill, and dismissal hides the panel again.

    The filter-group clones/moves leaf rows during the detached prefill build, so
    the widget under test is already a reconnected node — and adding a second
    condition re-renders the tree, after which the first widget must still open
    and dismiss cleanly (the #354 no-double-wire reconnection guard).
    """
    page = authenticated_page

    # Prefill a game filter with a status (enum set) criterion: "p" included.
    filter_json = _encode_filter(
        {"AND": [{"status": {"value": ["p"], "modifier": "INCLUDES"}}]}
    )
    page.goto(
        f"{live_server.url}"
        f"{reverse('games:filter_builder', args=['game'])}?filter={filter_json}"
    )
    expect(page.locator("filter-count")).not_to_contain_text(
        "Counting…", timeout=10_000
    )

    # The hosted value widget is the criterion whose value cell holds a drop-down
    # (a blank leaf's value cell is empty), so this targets the status leaf even
    # after a second condition is added below. ``.first`` keeps the locator
    # single-element (strict mode) regardless of what a later condition renders.
    value_cell = (
        page.locator("[data-node-kind='criterion']")
        .filter(has=page.locator("[data-value-cell] drop-down"))
        .first.locator("[data-value-cell]")
    )

    expect(value_cell.locator("drop-down[behavior='inline-combobox']")).to_be_attached()

    search = value_cell.locator("[data-search-select-search]")
    panel = value_cell.locator("[data-search-select-options]")
    pills = value_cell.locator("[data-search-select-pills] [data-pill]")

    # attachMenu owns visibility via the `hidden` attribute: closed until focus.
    expect(panel).to_be_hidden()
    expect(pills).to_have_count(1)  # the prefilled "p" include pill

    # Focus the search input → the host opens the panel.
    search.click()
    expect(search).to_be_focused()  # guards the Escape-dismiss target below
    expect(panel).to_be_visible(timeout=5_000)

    # Include a second status (Finished) → a new include pill lands.
    panel.locator(
        "[data-search-select-option][data-value='f'] "
        "[data-search-select-action='include']"
    ).click()
    expect(pills).to_have_count(2)

    # Escape dismisses (the host's attachMenu owns dismiss when delegated).
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()

    # Reconnection: adding a condition re-renders the tree (moves the leaf); the
    # first widget's drop-down must re-bind without double-wiring — re-open and
    # dismiss once more.
    page.locator("filter-group button[data-action='add-condition']").first.click()
    search.click()
    expect(panel).to_be_visible(timeout=5_000)
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()


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

    # reflectFieldSelections must descend into owned (relation-child) groups: the
    # inner criterion's field picker shows its chosen field. Only assertable in a
    # real browser — jsdom's un-upgraded search-select makes setSelected a no-op.
    inner_field_search = group.locator(
        "[data-node-kind='criterion'] [data-field-picker] [data-search-select-search]"
    ).first
    expect(inner_field_search).to_have_value("Ended")

    # The count reads the live widgets via serializeForQuery(): only the purchase
    # of the game with a 2026 PlayEvent matches — not all purchases (the bug
    # pruned the whole filter and counted everything).
    count_badge = page.locator("filter-count")
    expect(count_badge).not_to_contain_text("Counting…")
    expect(count_badge).to_contain_text("≈ 1 purchase")


def test_scoped_aggregate_prefill_hydrates_scope_and_counts(
    authenticated_page: Page, live_server
) -> None:
    """A scoped aggregate in ?filter= (issue #151) hydrates the builder: the
    aggregate leaf renders with its nested scope group (the device leaf shown as
    a pill), the count reads the scoped query from the live widgets, and the
    "− scope" action drops the scope — widening the count — proving the whole
    add/remove wiring works against real server templates."""
    from datetime import timedelta

    from games.models import Device, Session

    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    deck = Device.objects.create(name="Steam Deck", type="Handheld")
    desktop = Device.objects.create(name="Desktop", type="PC")
    deck_game = Game.objects.create(name="DeckGame", platform=platform)
    desktop_game = Game.objects.create(name="DeskGame", platform=platform)
    first_start = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    for index, (game, device) in enumerate(
        [
            (deck_game, deck),
            (deck_game, deck),
            (desktop_game, desktop),
            (desktop_game, desktop),
        ]
    ):
        begin = first_start + timedelta(days=index)
        Session.objects.create(
            game=game,
            device=device,
            timestamp_start=begin,
            timestamp_end=begin + timedelta(hours=1),
        )

    # Both games have 2 sessions; only DeckGame has >1 *on the deck*.
    filter_json = {
        "session_count": {
            "value": 1,
            "modifier": "GREATER_THAN",
            "scope": {
                "device": {
                    "value": [{"id": str(deck.pk), "label": deck.name}],
                    "modifier": "INCLUDES",
                }
            },
        }
    }
    page.goto(
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={_encode_filter(filter_json)}"
    )

    group = page.locator("filter-group")
    expect(group).to_be_attached()

    # The scope group hydrated: addressed through the "scope" path sentinel, with
    # the device leaf's include pill rendered from the {id, label} value.
    scope_group = group.locator('[data-kind="group"][data-path*="scope"]')
    expect(scope_group).to_be_attached()
    scope_pill = scope_group.locator("[data-search-select-pills] [data-pill]")
    expect(scope_pill).to_contain_text("Steam Deck")

    # The count reads the scoped query via serializeForQuery(): only DeckGame.
    count_badge = page.locator("filter-count")
    expect(count_badge).not_to_contain_text("Counting…")
    expect(count_badge).to_contain_text("≈ 1 game")

    # "− scope" drops the scope: unscoped, both games have >1 session.
    page.locator('filter-group button[data-action="remove-scope"]').click()
    expect(scope_group).not_to_be_attached()
    expect(count_badge).to_contain_text("≈ 2 games")


def test_scoped_aggregate_narrows_game_list(
    authenticated_page: Page, live_server
) -> None:
    """The list round-trip for a scoped aggregate: ?filter= JSON → GameFilter
    (scope resolved via the aggregates spec) → filtered aggregate queryset."""
    from datetime import timedelta

    from games.models import Device, Session

    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    deck = Device.objects.create(name="Steam Deck", type="Handheld")
    desktop = Device.objects.create(name="Desktop", type="PC")
    deck_game = Game.objects.create(name="DeckGame", platform=platform)
    desktop_game = Game.objects.create(name="DeskGame", platform=platform)
    first_start = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    for index, (game, device) in enumerate(
        [
            (deck_game, deck),
            (deck_game, deck),
            (desktop_game, desktop),
            (desktop_game, desktop),
        ]
    ):
        begin = first_start + timedelta(days=index)
        Session.objects.create(
            game=game,
            device=device,
            timestamp_start=begin,
            timestamp_end=begin + timedelta(hours=1),
        )

    filter_json = {
        "session_count": {
            "value": 1,
            "modifier": "GREATER_THAN",
            "scope": {"device": {"value": [deck.pk], "modifier": "INCLUDES"}},
        }
    }
    page.goto(
        f"{live_server.url}{reverse('games:list_games')}?filter={_encode_filter(filter_json)}"
    )
    # Scope to the results table: the navbar log dropdown (#419) also lists recent
    # games by name, so a bare page-level text match would be ambiguous.
    table = page.locator("table")
    expect(table.locator("[data-truncated-clip]", has_text="DeckGame")).to_be_visible()
    expect(
        table.locator("[data-truncated-clip]", has_text="DeskGame")
    ).not_to_be_visible()


def test_cross_model_year_comparison_filters_sessions(
    authenticated_page: Page, live_server
) -> None:
    """Cross-model year-space field comparison round-trip (#169).

    Drives the sessions filter BUILDER UI (the builder is the comparison UI
    for sessions, #315): adds a comparison leaf with left='timestamp_start',
    operator='EQUALS:year' (year comparison space), right='game__year_released',
    applies, and asserts that only the session whose play year matches
    the game's release year remains visible on the list.

    Data:
    - One game released in 2020.
    - MatchSession: started in 2020 — timestamp_start year == game.year_released.
    - MissSession: started in 2021 — timestamp_start year != game.year_released.
    """
    from datetime import timedelta

    from games.models import Session

    page = authenticated_page

    platform = Platform.objects.create(name="PC")
    match_game = Game.objects.create(
        name="MatchGame", platform=platform, year_released=2020
    )
    miss_game = Game.objects.create(
        name="MissGame", platform=platform, year_released=2020
    )

    match_start = datetime(2020, 6, 15, 10, 0, tzinfo=timezone.utc)
    Session.objects.create(
        game=match_game,
        timestamp_start=match_start,
        timestamp_end=match_start + timedelta(hours=2),
    )

    miss_start = datetime(2021, 3, 10, 14, 0, tzinfo=timezone.utc)
    Session.objects.create(
        game=miss_game,
        timestamp_start=miss_start,
        timestamp_end=miss_start + timedelta(hours=2),
    )

    # Build the comparison in the sessions filter builder.
    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['session'])}")
    page.locator('filter-group button[data-action="add-comparison"]').first.click()
    row = page.locator('filter-group [data-node-kind="comparison"]').first

    # Select left operand (searchable combobox), year-space operator (native
    # select), and cross-model right operand (searchable combobox).
    _pick_operand(row, "left", "timestamp_start")
    row.locator("[data-fc-op]").select_option("EQUALS:year")
    _pick_operand(row, "right", "game__year_released")

    # Apply navigates to the sessions list carrying the ?filter=.
    with page.expect_navigation():
        page.locator("filter-builder [data-apply]").click()

    # Only the session whose play year (2020) matches the game's release year
    # (also 2020) should appear; the 2021 session should be filtered out.
    # Use a <tr> scoped locator to avoid matching popover/button text that also
    # contains the game name but sits outside the session table rows.
    session_table_rows = page.locator("tr[id^='session-row-']")
    expect(session_table_rows.filter(has_text="MatchGame")).to_be_visible()
    expect(session_table_rows.filter(has_text="MissGame")).not_to_be_visible()


def _select_option_values(select_locator) -> list[str]:
    """The value of every <option> currently in a <select> (optgroups included)."""
    return select_locator.evaluate(
        "select => [...select.options].map(option => option.value)"
    )


def _pick_operand(row, side: str, value: str) -> None:
    """Pick a comparison operand value on its searchable SearchSelect combobox
    (#282): focus the search box to open the panel, then click the option row."""
    operand = row.locator(f"[data-fc-{side}]")
    operand.locator("[data-search-select-search]").click()
    operand.locator(f"[data-search-select-option][data-value='{value}']").click()


def _operand_value_locator(row, side: str):
    """The committed value channel (hidden input) of a comparison operand."""
    return row.locator(
        f"[data-fc-{side}] [data-search-select-pills] input[type='hidden']"
    )


def _operand_option_values(row, side: str) -> list[str]:
    """The data-value of every option row currently in an operand's panel."""
    return row.locator(f"[data-fc-{side}] [data-search-select-option]").evaluate_all(
        "nodes => nodes.map(node => node.getAttribute('data-value'))"
    )


def test_builder_comparison_leaf_clone_seed_and_operator_rewire(
    authenticated_page: Page, live_server
) -> None:
    """The nested <filter-group> comparison leaf against real server templates
    (issue #285 follow-up to #169; previously jsdom-only):

    1. Template clone: a prefilled field-comparison deserializes into a
       comparison leaf whose row is cloned from the server's
       data-fc-row-template (server-owned select styling present).
    2. Packed-operator seed: granularity='date' arrives as the packed
       operator value 'LESS_THAN:date' via the data-selected contract.
    3. Operator-change right-list rewiring: switching the comparison space
       rebuilds the right-column options to that space's accepted groups.
    4. The '+ comparison' action clones a fresh blank row whose dependent
       selects stay disabled until a left column is picked.
    """
    page = authenticated_page

    # created_at/updated_at are Game's datetime columns; year_released is number.
    filter_json = {
        "field_comparisons": [
            {
                "left": "created_at",
                "right": "updated_at",
                "modifier": "LESS_THAN",
                "granularity": "date",
            }
        ]
    }
    page.goto(
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={_encode_filter(filter_json)}"
    )

    # JS initialized: the count badge settled (serializeForQuery ran end-to-end
    # over the hydrated comparison leaf without throwing).
    expect(page.locator("filter-count")).not_to_contain_text("Counting…")

    comparison_row = page.locator('filter-group [data-node-kind="comparison"]')
    expect(comparison_row).to_have_count(1)

    operator_select = comparison_row.locator("[data-fc-op]")

    # 1. Template clone: the left operand came from the server template, so its
    # SearchSelect carries the server-owned container class. This pins that the
    # styling really arrived from the server template — the jsdom suite's
    # synthetic fixtures are classless, so only a browser test can assert this.
    expect(comparison_row.locator("[data-fc-left] search-select")).to_have_class(
        re.compile(r"rounded-base")
    )

    # 2. Packed-operator seed: the stored {modifier, granularity} pair hydrates
    # as the packed operator value, and both operand comboboxes restore their
    # committed values (the hidden-input channel).
    expect(_operand_value_locator(comparison_row, "left")).to_have_value("created_at")
    expect(operator_select).to_have_value("LESS_THAN:date")
    expect(_operand_value_locator(comparison_row, "right")).to_have_value("updated_at")

    # Right list under the restored date-space operator: Game's other datetime
    # column is present, its number columns are not. (A raw datetime comparison
    # would look the same — the packed-operator assert above pins the space.)
    date_space_values = _operand_option_values(comparison_row, "right")
    assert "updated_at" in date_space_values
    assert "year_released" not in date_space_values

    # 3. Operator-change rewiring: switching to the year space rebuilds the
    # right list to that space's groups (number joins date/datetime) while the
    # current right selection survives the rebuild.
    operator_select.select_option("LESS_THAN:year")
    expect(_operand_value_locator(comparison_row, "right")).to_have_value("updated_at")
    year_space_values = _operand_option_values(comparison_row, "right")
    assert "year_released" in year_space_values
    assert "original_year_released" in year_space_values

    # 4. '+ comparison' clones a fresh blank row from the same server template:
    # the operator stays disabled and the right combobox has no options until a
    # left column is chosen.
    page.locator('filter-group button[data-action="add-comparison"]').first.click()
    expect(comparison_row).to_have_count(2)
    new_row = comparison_row.nth(1)
    expect(new_row.locator("[data-fc-op]")).to_be_disabled()
    assert _operand_option_values(new_row, "right") == []
    _pick_operand(new_row, "left", "year_released")
    expect(new_row.locator("[data-fc-op]")).to_be_enabled()
    assert "original_year_released" in _operand_option_values(new_row, "right")


def test_comparison_left_operand_survives_keystroke(
    authenticated_page: Page, live_server
) -> None:
    """A keystroke in a committed left operand emits a transient edit-clear
    (last=null, the single-select pick-only contract). The row listener must
    ignore it: re-deriving would empty the operator and wipe the right operand
    irrecoverably. Only a real pick re-derives the row."""
    page = authenticated_page

    filter_json = {
        "field_comparisons": [
            {
                "left": "created_at",
                "right": "updated_at",
                "modifier": "LESS_THAN",
                "granularity": "date",
            }
        ]
    }
    page.goto(
        f"{live_server.url}{reverse('games:filter_builder', args=['game'])}"
        f"?filter={_encode_filter(filter_json)}"
    )
    expect(page.locator("filter-count")).not_to_contain_text("Counting…")

    comparison_row = page.locator('filter-group [data-node-kind="comparison"]')
    operator_select = comparison_row.locator("[data-fc-op]")
    expect(_operand_value_locator(comparison_row, "left")).to_have_value("created_at")
    expect(operator_select).to_have_value("LESS_THAN:date")

    # Typing in the committed left operand drops its own committed value…
    left_search = comparison_row.locator("[data-fc-left] [data-search-select-search]")
    left_search.click()
    left_search.type("y")
    expect(_operand_value_locator(comparison_row, "left")).to_have_count(0)

    # …but the rest of the row survives the transient clear.
    expect(operator_select).to_have_value("LESS_THAN:date")
    expect(operator_select).to_be_enabled()
    expect(_operand_value_locator(comparison_row, "right")).to_have_value("updated_at")

    # A real pick still re-derives: choosing a number column rebuilds the right
    # list to the number-compatible columns.
    comparison_row.locator(
        "[data-fc-left] [data-search-select-option][data-value='year_released']"
    ).click()
    expect(_operand_value_locator(comparison_row, "left")).to_have_value(
        "year_released"
    )
    assert "original_year_released" in _operand_option_values(comparison_row, "right")


def test_preset_delete_flow_removes_row_and_db_record(
    authenticated_page: Page, live_server, django_user_model
) -> None:
    """The per-row delete ×: confirm → DELETE /api/presets/{id} → the row
    vanishes on the refetch and the DB record is gone (#297). The panel must
    survive the native confirm() — it stays open with focus in the search box,
    showing the remaining preset."""
    user = django_user_model.objects.get(username="tester")
    keep = FilterPreset.objects.create(user=user, mode="games", name="keepme")
    doomed = FilterPreset.objects.create(user=user, mode="games", name="deleteme")

    page = authenticated_page
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['game'])}")

    page.locator("filter-builder [data-preset-picker] [data-toggle]").click()
    picker = page.locator("filter-builder [data-preset-picker]")
    doomed_row = picker.locator("[data-search-select-option]").filter(
        has_text="deleteme"
    )
    expect(doomed_row).to_be_visible(timeout=5_000)

    doomed_row.locator("[data-search-select-action='delete']").click()

    # Refetch after the DELETE: the deleted row is gone, the other remains,
    # the dialog is still open with the search box focused.
    expect(doomed_row).not_to_be_attached(timeout=5_000)
    expect(
        picker.locator("[data-search-select-option]").filter(has_text="keepme")
    ).to_be_visible()
    expect(picker.locator("[data-menu]")).to_be_visible()
    assert not FilterPreset.objects.filter(id=doomed.id).exists()
    assert FilterPreset.objects.filter(id=keep.id).exists()


def test_deleting_last_picked_preset_does_not_resurrect(
    authenticated_page: Page, live_server, django_user_model
) -> None:
    """Pick a preset, then delete that same preset on the next open: the row
    must NOT reappear after the refetch. Guards the transient-pick design —
    a lingering committed selection would pin the stale row through
    renderRows' selected-value preservation (#297 review finding)."""
    user = django_user_model.objects.get(username="tester")
    FilterPreset.objects.create(
        user=user,
        mode="games",
        name="pickme",
        object_filter={"name": {"modifier": "INCLUDES", "value": "x"}},
    )

    page = authenticated_page
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['game'])}")

    picker = page.locator("filter-builder [data-preset-picker]")
    toggle = picker.locator("[data-toggle]")

    # Pick it (loads into the tree and closes the dialog).
    toggle.click()
    row = picker.locator("[data-search-select-option]").filter(has_text="pickme")
    expect(row).to_be_visible(timeout=5_000)
    row.click()
    expect(picker.locator("[data-menu]")).to_be_hidden()
    expect(page.locator("[data-node-kind='criterion']")).to_be_attached(timeout=5_000)

    # Reopen (fresh refetch — the search box must be clean after the transient
    # pick, not holding the committed label as the query) and delete it.
    toggle.click()
    search_box = picker.locator("[data-search-select-search]")
    expect(search_box).to_have_value("")
    expect(row).to_be_visible(timeout=5_000)
    row.locator("[data-search-select-action='delete']").click()

    expect(row).not_to_be_attached(timeout=5_000)
    expect(picker.locator("[data-search-select-no-results]")).to_have_text(
        "No saved presets"
    )
    assert not FilterPreset.objects.filter(name="pickme").exists()


def test_preset_keyboard_pick_and_empty_enter(
    authenticated_page: Page, live_server, django_user_model
) -> None:
    """Keyboard path: Enter on the toggle opens the dialog with focus in the
    search box; ArrowDown + Enter picks the preset into the tree. With no
    options (a non-matching query), Enter neither submits nor navigates —
    free win #297 promised, plus the form-safety guard."""
    user = django_user_model.objects.get(username="tester")
    FilterPreset.objects.create(
        user=user,
        mode="games",
        name="kbpreset",
        object_filter={"name": {"modifier": "INCLUDES", "value": "x"}},
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:filter_builder', args=['game'])}")
    url_before = page.url

    picker = page.locator("filter-builder [data-preset-picker]")
    picker.locator("[data-toggle]").focus()
    page.keyboard.press("Enter")

    search_box = picker.locator("[data-search-select-search]")
    expect(search_box).to_be_focused()
    expect(
        picker.locator("[data-search-select-option]").filter(has_text="kbpreset")
    ).to_be_visible(timeout=5_000)

    # A non-matching query: Enter must be inert (no submit, no navigation).
    search_box.fill("zzz-no-match")
    expect(picker.locator("[data-search-select-no-results]")).to_be_visible()
    page.keyboard.press("Enter")
    assert page.url == url_before

    # Clear the query, pick via keyboard.
    search_box.fill("")
    expect(
        picker.locator("[data-search-select-option]").filter(has_text="kbpreset")
    ).to_be_visible(timeout=5_000)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")

    expect(page.locator("[data-node-kind='criterion']")).to_be_attached(timeout=5_000)
    expect(picker.locator("[data-menu]")).to_be_hidden()
    assert page.url == url_before  # loaded into the tree, no navigation
