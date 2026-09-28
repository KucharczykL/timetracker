"""Browser tests for the quick filter bar: Apply-button facet
serialization (set facets on the games list, the scalar duration facet on the
sessions list), and the degraded "Advanced filter active" pill for a filter
the bar cannot round-trip."""

import json
import re
import urllib.parse
from datetime import UTC

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import ConsoleMessage, Locator, Page, expect
from session_rows import session_row

from e2e.helpers import open_facet
from e2e.tracked_games import create_tracked_game
from games.models import Game, Platform, PlayerGameStatus
from games.reads.calendar import calendar_day_zone


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    _login(page, live_server)
    return page


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _quick_apply(page: Page) -> None:
    page.locator('quick-filter-bar button[type="submit"]').click()


def test_quick_facet_apply_filters_the_list(
    authenticated_page: Page, live_server, e2e_library
):
    """Picking a status in the quick bar and hitting Apply navigates with a
    flat facet-only ?filter= and the list is filtered."""
    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    create_tracked_game(
        e2e_library,
        "Finished Game",
        status=PlayerGameStatus.COMPLETED,
        platform=platform,
    )
    Game.objects.create(library=e2e_library, name="Unplayed Game", platform=platform)

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.locator("#quick-status-dropdownLink").click()
    widget = page.locator('quick-filter-bar search-select[name="status"]')
    widget.locator('[data-search-select-option][data-label="Completed"]').click()
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "status": {
            "value": [{"id": "completed", "label": "Completed"}],
            "excludes": [],
            "modifier": "INCLUDES",
        }
    }
    expect(
        page.locator("[data-truncated-clip]", has_text="Finished Game")
    ).to_be_visible()
    expect(
        page.locator("[data-truncated-clip]", has_text="Unplayed Game")
    ).to_have_count(0)

    # The applied filter round-trips back into an editable quick bar with the
    # picked value rendered as an include pill (the round-trip guarantee).
    pill = page.locator("quick-filter-bar [data-search-select-pills] [data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Completed")


def test_quick_scalar_facet_filters_sessions(
    authenticated_page: Page, live_server, e2e_library
):
    """The sessions quick bar's Duration number facet serializes a flat
    numeric criterion on Apply and the list is filtered by it."""
    from datetime import datetime, timedelta

    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    game = Game.objects.create(
        library=e2e_library, name="Timed Game", platform=platform
    )
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    long_session = session_row(
        game, started_at=start, ended_at=start + timedelta(hours=3)
    )
    short_session = session_row(
        game, started_at=start, ended_at=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.set_viewport_size({"width": 2000, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # Past the body cap, Duration is among the three that spill.
    open_facet(page, "duration_hours")
    duration = page.locator('quick-filter-bar [data-filter-widget][data-kind="number"]')
    duration.locator("select[data-number-modifier-select]").select_option(
        "GREATER_THAN"
    )
    duration.locator('input[name="quick-duration_hours"]').fill("2")
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "duration_hours": {"value": 2, "modifier": "GREATER_THAN"}
    }
    expect(page.locator(f"#session-row-{long_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{short_session.pk}")).to_have_count(0)

    # Round trip: the applied scalar criterion prefills an editable quick bar.
    expect(
        page.locator('quick-filter-bar input[name="quick-duration_hours"]')
    ).to_have_value("2")


def test_advanced_filter_shows_degraded_pill(authenticated_page: Page, live_server):
    """A filter with operator nesting renders the read-only pill (with working
    Advanced filter / Clear segments) instead of facet widgets."""
    filter_json = json.dumps(
        {"AND": [{"status": {"value": [{"id": "completed", "label": "Completed"}]}}]}
    )
    page = authenticated_page
    list_url = reverse("games:list_games")
    page.goto(f"{live_server.url}{list_url}?filter={urllib.parse.quote(filter_json)}")

    expect(page.get_by_text("Advanced filter active")).to_be_visible()
    expect(page.locator("quick-filter-bar form")).to_have_count(0)

    edit_link = page.get_by_role("link", name="Advanced filter", exact=True)
    href = edit_link.get_attribute("href")
    assert href is not None
    assert reverse("games:filter_builder", args=["game"]) in href
    assert "filter=" in href

    clear_link = page.get_by_role("link", name="Clear filter")
    assert clear_link.get_attribute("href") == list_url
    clear_link.click()
    page.wait_for_url(f"{live_server.url}{list_url}")
    assert _filter_from_url(page.url) == {}


def test_dropdown_facet_full_flow(authenticated_page: Page, live_server, e2e_library):
    """The dropdown facets on the sessions list: open the Game panel,
    include a game, remove a pill (the panel must stay open — the composedPath
    close-guard fix), Apply, and round-trip back into an editable bar with the
    pill inside the reopened panel."""
    from datetime import datetime, timedelta

    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    picked = Game.objects.create(
        library=e2e_library, name="Picked Game", platform=platform
    )
    other = Game.objects.create(
        library=e2e_library, name="Other Game", platform=platform
    )
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    picked_session = session_row(
        picked, started_at=start, ended_at=start + timedelta(hours=1)
    )
    other_session = session_row(
        other, started_at=start, ended_at=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # Closed trigger: a ghost "Game ▾" button; the panel is hidden.
    trigger = page.locator("#quick-game-dropdownLink")
    panel = page.locator("#quick-game-dropdown")
    expect(trigger).to_be_visible()
    expect(panel).to_be_hidden()

    # Open: search focused, options fetched (refetch-on-show), pick two games
    # then remove one pill — the panel must survive the pill removal.
    trigger.click()
    expect(panel).to_be_visible()
    widget = panel.locator('search-select[name="game"]')
    expect(widget.locator("[data-search-select-search]")).to_be_focused()
    widget.locator(
        '[data-search-select-option][data-label="Picked Game (PC)"] '
        '[data-search-select-action="include"]'
    ).click()
    widget.locator(
        '[data-search-select-option][data-label="Other Game (PC)"] '
        '[data-search-select-action="include"]'
    ).click()
    expect(widget.locator("[data-pill]")).to_have_count(2)
    widget.locator(
        '[data-pill][data-label="Other Game (PC)"] [data-pill-remove]'
    ).click()
    expect(widget.locator("[data-pill]")).to_have_count(1)
    expect(panel).to_be_visible()

    _quick_apply(page)
    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "game": {
            "value": [{"id": str(picked.pk), "label": "Picked Game (PC)"}],
            "excludes": [],
            "modifier": "INCLUDES",
        }
    }
    expect(page.locator(f"#session-row-{picked_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{other_session.pk}")).to_have_count(0)

    # Round trip: still an editable bar (no degraded pill), and the include
    # pill is server-rendered inside the reopened panel.
    expect(page.get_by_text("Advanced filter active")).to_have_count(0)
    page.locator("#quick-game-dropdownLink").click()
    reopened = page.locator('#quick-game-dropdown search-select[name="game"]')
    pill = reopened.locator("[data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Picked Game (PC)")


def test_date_dropdown_facet_preset_flow(
    authenticated_page: Page, live_server, e2e_library
):
    """The Started facet as a dropdown: a ghost "Started ▾" trigger
    opening a static always-visible calendar (no toggle, no Cancel/Select);
    picking the Today preset and applying serializes a BETWEEN criterion."""
    from datetime import datetime, timedelta

    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    game = Game.objects.create(library=e2e_library, name="Doom", platform=platform)
    #: Noon UTC: near-UTC zones read one day.
    #:
    #: The preset and the filter both answer in the display zone (#949),
    #: which an e2e user leaves at its UTC default, and the row is stored
    #: in UTC. Noon is what keeps them agreeing if that default moves.
    now = datetime.now(UTC)
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    today_session = session_row(
        game,
        started_at=noon,
        ended_at=noon + timedelta(hours=1),
        day_zone=calendar_day_zone(e2e_library).key,
    )
    old_start = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    old_session = session_row(
        game,
        started_at=old_start,
        ended_at=old_start + timedelta(hours=1),
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    trigger = page.locator("#quick-day-dropdownLink")
    panel = page.locator("#quick-day-dropdown")
    expect(trigger).to_be_visible()
    expect(panel).to_be_hidden()

    trigger.click()
    expect(panel).to_be_visible()
    # Static calendar: grid rendered, no toggle / Cancel / Select controls.
    expect(panel.locator("[data-date-range-grid] button[data-date]")).to_have_count(42)
    expect(panel.locator("[data-date-range-calendar-toggle]")).to_have_count(0)
    expect(panel.locator("[data-date-range-cancel]")).to_have_count(0)
    expect(panel.locator("[data-date-range-select]")).to_have_count(0)

    panel.locator('[data-date-range-preset="today"]').click()
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    today_iso = now.date().isoformat()
    assert _filter_from_url(page.url) == {
        "day": {
            "value": today_iso,
            "value2": today_iso,
            "modifier": "BETWEEN",
        }
    }
    expect(page.locator(f"#session-row-{today_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{old_session.pk}")).to_have_count(0)

    # Round trip: reopened panel shows the committed range in the segments.
    page.locator("#quick-day-dropdownLink").click()
    min_hidden = page.locator("#quick-day-dropdown [data-range-min]")
    expect(min_hidden).to_have_value(today_iso)


def test_priority_plus_overflow_collapses_and_restores(
    authenticated_page: Page, live_server, e2e_library
):
    """Priority-plus: narrowing moves idle facets into "⋯", rightmost
    first, and an applied facet spills last; facets keep working from
    inside it.

    Past the body cap, six facets fit: all but Duration."""
    from datetime import datetime, timedelta

    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    game = Game.objects.create(library=e2e_library, name="Doom", platform=platform)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    long_session = session_row(
        game, started_at=start, ended_at=start + timedelta(hours=3)
    )
    short_session = session_row(
        game, started_at=start, ended_at=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.set_viewport_size({"width": 2000, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    overflow = page.locator("[data-quick-overflow]")
    overflow_items = page.locator("[data-quick-overflow-items]")
    duration_facet = page.locator(
        "drop-down[data-quick-facet]:has(#quick-duration_hours-dropdown)"
    )

    # Wide: the rightmost facet spills.
    expect(overflow).to_be_visible()
    expect(overflow_items.locator("[data-quick-facet]")).to_have_count(1)
    expect(
        overflow_items.locator(":scope > drop-down:has(#quick-duration_hours-dropdown)")
    ).to_have_count(1)

    # Narrow: every facet spills.
    page.set_viewport_size({"width": 520, "height": 900})
    expect(overflow).to_be_visible()
    expect(overflow_items.locator("[data-quick-facet]")).to_have_count(7)
    expect(
        overflow_items.locator(":scope > drop-down:has(#quick-duration_hours-dropdown)")
    ).to_have_count(1)

    # The spilled facet still works: open ⋯ → open Duration → edit → Enter.
    page.locator("#quick-sessions-overflowLink").click()
    duration_facet.locator("#quick-duration_hours-dropdownLink").click()
    duration_panel = page.locator("#quick-duration_hours-dropdown")
    expect(duration_panel).to_be_visible()
    duration_panel.locator("select[data-number-modifier-select]").select_option(
        "GREATER_THAN"
    )
    duration_input = duration_panel.locator('input[name="quick-duration_hours"]')
    duration_input.fill("2")
    # The open menu covers the wrapped acts group; Enter applies from inside.
    duration_input.press("Enter")
    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "duration_hours": {"value": 2, "modifier": "GREATER_THAN"}
    }
    expect(page.locator(f"#session-row-{long_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{short_session.pk}")).to_have_count(0)

    # Widen: applied Duration outranks the idle facets declared before it.
    page.set_viewport_size({"width": 2000, "height": 900})
    row_triggers = page.locator("[data-quick-row] > [data-quick-facet] > [data-toggle]")
    expect(row_triggers).to_have_count(5)
    assert [trigger.get_attribute("id") for trigger in row_triggers.all()] == [
        "quick-game-dropdownLink",
        "quick-day-dropdownLink",
        "quick-playthrough_kind-dropdownLink",
        "quick-outside_playthrough_dates-dropdownLink",
        "quick-duration_hours-dropdownLink",
    ]
    menu_triggers = page.locator(
        "[data-quick-overflow-items] > [data-quick-facet] > [data-toggle]"
    )
    assert [trigger.get_attribute("id") for trigger in menu_triggers.all()] == [
        "quick-device-dropdownLink",
        "quick-timing_mode-dropdownLink",
    ]


def test_an_applied_facet_stays_inline_and_marked(
    authenticated_page: Page, live_server
):
    """An applied facet stays inline, marked."""
    page = authenticated_page
    page.set_viewport_size({"width": 2000, "height": 900})
    stated = json.dumps({"outside_playthrough_dates": {"value": True}})
    page.goto(
        f"{live_server.url}{reverse('games:list_sessions')}"
        f"?filter={urllib.parse.quote(stated)}"
    )

    facet = page.locator(
        "[data-quick-row] > drop-down:has(#quick-outside_playthrough_dates-dropdown)"
    )
    expect(facet).to_have_attribute("data-quick-facet-applied", "")
    trigger = page.locator("#quick-outside_playthrough_dates-dropdownLink")
    expect(trigger).to_have_accessible_name("Outside dates (applied)")
    overflow_trigger = page.locator("[data-quick-overflow-trigger]")
    expect(overflow_trigger).to_have_attribute("aria-label", "More filters")

    page.set_viewport_size({"width": 520, "height": 900})
    expect(
        page.locator(
            "[data-quick-overflow-items] > "
            "drop-down:has(#quick-outside_playthrough_dates-dropdown)"
        )
    ).to_have_count(1)
    expect(overflow_trigger).to_have_attribute(
        "aria-label", "More filters, some applied"
    )
    expect(page.locator("[data-quick-overflow-mark]")).not_to_have_class(
        re.compile(r"\binvisible\b")
    )


def test_preset_pick_on_builderless_mode(
    authenticated_page: Page, live_server, django_user_model, e2e_library
):
    """The quick bar's Presets panel loads on a builderless mode
    (devices): picking navigates with the preset's ?filter=; Enter inside the
    picker's search box never applies the facet form."""
    from games.models import FilterPreset

    create_device(library=e2e_library, name="Steam Deck")
    create_device(library=e2e_library, name="Desktop")
    user = django_user_model.objects.get(username="tester")
    stored_filter = {"name": {"modifier": "INCLUDES", "value": "deck"}}
    FilterPreset.objects.create(
        library=user.library,
        name="DeckOnly",
        mode="devices",
        object_filter=stored_filter,
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    picker = page.locator("quick-filter-bar drop-down:has(preset-panel)")
    picker.locator("[data-toggle]").click()
    search = picker.locator("[data-search-select-search]")
    expect(search).to_be_focused()

    # Enter on a name no preset holds saves it and never submits the facet
    # form; with a matching row highlighted, Enter picks the row instead.
    search.fill("zzz-no-such-preset")
    expect(picker.locator("[data-search-select-create]")).to_be_visible()
    search.press("Enter")
    expect(search).to_have_value("")
    expect(page).to_have_url(f"{live_server.url}{reverse('games:list_devices')}")
    assert FilterPreset.objects.filter(name="zzz-no-such-preset").exists()

    search.fill("")
    row = picker.locator("[data-search-select-option]").filter(has_text="DeckOnly")
    expect(row).to_be_visible(timeout=5_000)
    with page.expect_navigation():
        row.click()

    assert "?filter=" in page.url
    expect(page.locator("table")).to_contain_text("Steam Deck")
    expect(page.locator("table")).not_to_contain_text("Desktop")


def test_the_search_field_applies_on_enter(
    authenticated_page: Page, live_server, e2e_library
):
    """Typing and pressing Enter applies, and the URL carries the search."""
    page = authenticated_page
    create_tracked_game(e2e_library, name="Hollow Knight")
    create_tracked_game(e2e_library, name="Celeste")
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.locator("search-field [data-match-value]").fill("Hollow")
    page.locator("search-field [data-match-value]").press("Enter")
    page.wait_for_url("**filter=**")

    assert _filter_from_url(page.url)["search"] == {
        "value": "Hollow",
        "modifier": "INCLUDES",
    }
    expect(page.locator("table")).to_contain_text("Hollow Knight")
    expect(page.locator("table")).not_to_contain_text("Celeste")


def test_a_chosen_mode_reaches_the_filter(
    authenticated_page: Page, live_server, e2e_library
):
    """The mode the menu states is the one applied, not the default."""
    page = authenticated_page
    create_tracked_game(e2e_library, name="Hollow Knight")
    create_tracked_game(e2e_library, name="Celeste")
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.locator("search-field [data-match-trigger]").click()
    page.locator('search-field [data-match-mode="EXCLUDES"]').click()
    # The trigger states the mode it now holds.
    expect(page.locator("search-field [data-match-trigger]")).to_have_attribute(
        "aria-label", "Match mode: excludes"
    )
    # A picked mode closes the menu, which covers the box.
    #
    # Playwright's fill does no hit-testing, so the assertion below would pass
    # either way.
    expect(page.locator("search-field [role='menu']")).to_be_hidden()

    page.locator("search-field [data-match-value]").fill("Hollow")
    _quick_apply(page)
    page.wait_for_url("**filter=**")

    assert _filter_from_url(page.url)["search"]["modifier"] == "EXCLUDES"
    expect(page.locator("table")).to_contain_text("Celeste")
    expect(page.locator("table")).not_to_contain_text("Hollow Knight")


def test_the_menu_is_operable_by_keyboard(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    menu = page.locator("search-field [role='menu']")

    page.locator("search-field [data-match-trigger]").focus()
    page.keyboard.press("Enter")
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()


def test_a_stated_search_prefills_the_field(
    authenticated_page: Page, live_server, e2e_library
):
    """A filter the bar can edit renders its search in the field, not a pill."""
    page = authenticated_page
    stated = json.dumps({"search": {"value": "zelda", "modifier": "MATCHES_REGEX"}})
    page.goto(
        f"{live_server.url}{reverse('games:list_games')}"
        f"?filter={urllib.parse.quote(stated)}"
    )
    expect(page.locator("search-field [data-match-value]")).to_have_value("zelda")
    expect(page.locator("search-field")).to_have_attribute(
        "data-modifier", "MATCHES_REGEX"
    )
    expect(page.locator("text=Advanced filter active")).to_have_count(0)


def test_a_search_the_field_cannot_state_degrades(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    stated = json.dumps({"search": {"value": "zelda", "modifier": "IS_NULL"}})
    page.goto(
        f"{live_server.url}{reverse('games:list_games')}"
        f"?filter={urllib.parse.quote(stated)}"
    )
    expect(page.locator("text=Advanced filter active")).to_be_visible()
    # The pill holds no field and mounts no element.
    expect(page.locator("search-field")).to_have_count(0)


def test_the_field_stays_in_the_row_on_a_phone(
    authenticated_page: Page, live_server, e2e_library
):
    """At 390px the field keeps its place and the row keeps its gutter."""
    page = authenticated_page
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    field = page.locator("search-field")
    expect(field).to_be_visible()
    # Never in the overflow menu, at any width.
    expect(page.locator("[data-quick-overflow-items] search-field")).to_have_count(0)
    # The row does not scroll the page sideways.
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_the_bar_logs_no_console_error(
    authenticated_page: Page, live_server, e2e_library
):
    page = authenticated_page
    # Collected before navigating so nothing is missed.
    messages: list[ConsoleMessage] = []

    def record(message: ConsoleMessage) -> None:
        messages.append(message)

    page.on("console", record)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.locator("search-field [data-match-trigger]").click()
    page.locator('search-field [data-match-mode="EQUALS"]').click()
    errors = [message.text for message in messages if message.type == "error"]
    assert errors == [], errors


def _presets(page: Page) -> Locator:
    return page.locator("quick-filter-bar drop-down:has(preset-panel)")


def _saved_filter(library, name: str) -> dict:
    from games.models import FilterPreset

    return FilterPreset.objects.for_library(library).get(name=name).object_filter


def test_a_preset_saves_the_unapplied_bar_and_loads_back(
    authenticated_page: Page, live_server, e2e_library
):
    """One box names the save; Save stores what the bar states, applied or
    not, and never applies the bar's form."""
    platform = Platform.objects.create(name="PC", icon="pc", library=e2e_library)
    Game.objects.create(name="Halo", platform=platform, library=e2e_library)
    Game.objects.create(name="Doom", platform=platform, library=e2e_library)
    page = authenticated_page
    list_url = f"{live_server.url}{reverse('games:list_games')}"
    page.goto(list_url)

    page.locator('input[name="quick-games-search"]').fill("halo")
    presets = _presets(page)
    presets.locator("[data-toggle]").click()
    box = presets.locator("[data-search-select-search]")
    save_row = presets.locator("[data-search-select-create]")
    box.fill("Halo search")
    expect(save_row).to_have_text("Save \u201cHalo search\u201d")
    box.press("Enter")
    expect(box).to_have_value("")
    expect(page).to_have_url(list_url)
    assert _saved_filter(e2e_library, "Halo search") == {
        "search": {"value": "halo", "modifier": "INCLUDES"}
    }

    # A held name offers Overwrite, which a click takes.
    bar_search = page.locator('input[name="quick-games-search"]')
    bar_search.click()
    expect(box).to_be_hidden()
    bar_search.fill("doom")
    presets.locator("[data-toggle]").click()
    box.fill("Halo search")
    expect(save_row).to_have_text("Overwrite \u201cHalo search\u201d")
    save_row.click()
    expect(box).to_have_value("")
    expect(page).to_have_url(list_url)
    assert _saved_filter(e2e_library, "Halo search")["search"]["value"] == "doom"

    page.reload()
    presets.locator("[data-toggle]").click()
    row = presets.locator("[data-search-select-option]").filter(has_text="Halo search")
    expect(row).to_be_visible(timeout=5_000)
    with page.expect_navigation():
        row.click()
    assert _filter_from_url(page.url)["search"]["value"] == "doom"
    expect(page.locator("table")).not_to_contain_text("Halo")


def test_the_degraded_pill_saves_the_pages_filter(
    authenticated_page: Page, live_server, e2e_library
):
    stated = {
        "AND": [{"status": {"value": [{"id": "completed", "label": "Completed"}]}}]
    }
    page = authenticated_page
    list_url = reverse("games:list_games")
    page.goto(
        f"{live_server.url}{list_url}?filter={urllib.parse.quote(json.dumps(stated))}"
    )
    expect(page.get_by_text("Advanced filter active")).to_be_visible()

    presets = _presets(page)
    presets.locator("[data-toggle]").click()
    box = presets.locator("[data-search-select-search]")
    box.fill("Completed")
    presets.locator("[data-search-select-create]").click()
    expect(box).to_have_value("")
    assert _saved_filter(e2e_library, "Completed") == stated
