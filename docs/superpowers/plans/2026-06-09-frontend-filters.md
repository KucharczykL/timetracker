# Frontend Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a comprehensive frontend filter bar interface for all 6 list views (Games, Sessions, Purchases, Devices, Platforms, PlayEvents) with specific field controls, simple cross-entity toggles, and full JSON preset support.

**Architecture:** We will extend existing components in `common/components/filters.py` and implement new filter bars (`DeviceFilterBar`, `PlatformFilterBar`, `PlayEventFilterBar`). We will update the views in `games/views/` to parse standard filter JSON from `request.GET.get('filter')`, apply them to querysets, render the filter bars, and export them in `common/components/__init__.py`.

**Tech Stack:** Django, Python dataclasses, Pytest.

---

### Task 1: Update existing FilterBars in `common/components/filters.py`

**Files:**
- Modify: `common/components/filters.py`

- [ ] **Step 1: Add new fields to GameFilterBar**
Add checkboxes for `has_purchases`, `has_playevents` and RangeSliders for `session_count`, `session_average`.

```python
# Inside common/components/filters.py: FilterBar()

    # Parse new values
    has_purchases_value = _parse_bool(existing, "has_purchases")
    has_playevents_value = _parse_bool(existing, "has_playevents")
    session_count_min, session_count_max = _parse_range(existing, "session_count")
    session_avg_min, session_avg_max = _parse_range(existing, "session_average")

    # Add components to fields:
    # 1. Under status and platform, add the checkboxes for purchases/playevents
    # 2. Add RangeSliders for session count and average
```

Code change to apply in `FilterBar`:
```python
    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Status",
                    _enum_filter(
                        "status",
                        status_options,
                        status_choice,
                        nullable=not Game._meta.get_field("status").has_default(),
                    ),
                ),
                _filter_field(
                    "Platform",
                    _model_filter(
                        "platform",
                        platform_choice,
                        search_url="/api/platforms/search",
                        nullable=Game._meta.get_field("platform").null,
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Year",
            input_name_prefix="filter-year",
            min_value=year_min,
            max_value=year_max,
            range_min=year_range_min,
            range_max=year_range_max,
            min_placeholder="e.g. 2020",
            max_placeholder="e.g. 2024",
        ),
        Component(
            tag_name="div",
            attributes=[("class", "flex items-end gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-mastered", "Mastered", mastered_value),
                _filter_checkbox("filter-has-purchases", "Has Purchases", has_purchases_value),
                _filter_checkbox("filter-has-playevents", "Has Play Events", has_playevents_value),
            ],
        ),
        RangeSlider(
            label="Playtime",
            input_name_prefix="filter-playtime",
            min_value=playtime_min,
            max_value=playtime_max,
            range_min=0,
            range_max=playtime_range_max,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 100",
        ),
        RangeSlider(
            label="Session Count",
            input_name_prefix="filter-session-count",
            min_value=session_count_min,
            max_value=session_count_max,
            range_min=0,
            range_max=100,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 50",
        ),
        RangeSlider(
            label="Average Session Duration (mins)",
            input_name_prefix="filter-session-average",
            min_value=session_avg_min,
            max_value=session_avg_max,
            range_min=0,
            range_max=240,
            step="1",
            min_placeholder="e.g. 10",
            max_placeholder="e.g. 120",
        ),
    ]
```

- [ ] **Step 2: Update SessionFilterBar to support split duration fields**
Replace old `duration_minutes` RangeSlider with split total, manual, and calculated duration RangeSliders.

```python
# Inside common/components/filters.py: SessionFilterBar()

    dur_tot_min, dur_tot_max = _parse_range(existing, "duration_total_minutes")
    dur_man_min, dur_man_max = _parse_range(existing, "duration_manual_minutes")
    dur_calc_min, dur_calc_max = _parse_range(existing, "duration_calculated_minutes")

    # Inside fields array, replace RangeSlider "Duration" with:
        RangeSlider(
            label="Total Duration (mins)",
            input_name_prefix="filter-duration-total-minutes",
            min_value=dur_tot_min,
            max_value=dur_tot_max,
            range_min=0,
            range_max=duration_range_max * 60,  # Range sliders use minutes now
            step="1",
            min_placeholder="e.g. 30",
            max_placeholder="e.g. 180",
        ),
        RangeSlider(
            label="Manual Duration (mins)",
            input_name_prefix="filter-duration-manual-minutes",
            min_value=dur_man_min,
            max_value=dur_man_max,
            range_min=0,
            range_max=240,
            step="1",
            min_placeholder="e.g. 10",
            max_placeholder="e.g. 120",
        ),
        RangeSlider(
            label="Calculated Duration (mins)",
            input_name_prefix="filter-duration-calculated-minutes",
            min_value=dur_calc_min,
            max_value=dur_calc_max,
            range_min=0,
            range_max=duration_range_max * 60,
            step="1",
            min_placeholder="e.g. 30",
            max_placeholder="e.g. 180",
        ),
```

- [ ] **Step 3: Update PurchaseFilterBar to support original and converted currencies and infinite flag**
Add Checkboxes `infinite`, `needs_price_update` and currency StringCriterion text field / Choice options.

```python
# Inside common/components/filters.py: PurchaseFilterBar()

    infinite_value = _parse_bool(existing, "infinite")
    needs_price_update_value = _parse_bool(existing, "needs_price_update")
    price_currency_value = existing.get("price_currency", {}).get("value", "")
    converted_currency_value = existing.get("converted_currency", {}).get("value", "")

    # Expand fields component array with:
        Component(
            tag_name="div",
            attributes=[("class", "flex gap-4 mb-4")],
            children=[
                _filter_checkbox("filter-refunded", "Refunded", is_refunded_value),
                _filter_checkbox("filter-infinite", "Infinite", infinite_value),
                _filter_checkbox("filter-needs-price-update", "Needs Price Update", needs_price_update_value),
            ],
        ),
```

Add currency text filters (as primitive `Input` controls for string criteria):
```python
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Original Currency",
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("name", "filter-price_currency"),
                            ("value", price_currency_value),
                            ("placeholder", "e.g. USD, EUR"),
                            ("class", "w-full rounded border-default-medium p-2 bg-neutral-secondary-medium text-body"),
                        ],
                    ),
                ),
                _filter_field(
                    "Converted Currency",
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("name", "filter-converted_currency"),
                            ("value", converted_currency_value),
                            ("placeholder", "e.g. USD, EUR"),
                            ("class", "w-full rounded border-default-medium p-2 bg-neutral-secondary-medium text-body"),
                        ],
                    ),
                ),
            ],
        ),
```

---

### Task 2: Create New FilterBars in `common/components/filters.py`

**Files:**
- Modify: `common/components/filters.py`

- [ ] **Step 1: Implement DeviceFilterBar, PlatformFilterBar, and PlayEventFilterBar**

Append these three new filter bar components to `common/components/filters.py`:

```python
def DeviceFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Device list."""
    from games.models import Device

    existing = _filter_parse(filter_json)
    type_options = Device.DEVICE_TYPES
    type_choice = _filter_get_choice(existing, "type")

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Device Type",
                    _enum_filter(
                        "type",
                        type_options,
                        type_choice,
                        nullable=True,
                    ),
                ),
            ],
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def PlatformFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the Platform list."""
    existing = _filter_parse(filter_json)

    name_value = existing.get("name", {}).get("value", "")
    group_value = existing.get("group", {}).get("value", "")

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Platform Name",
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("name", "filter-name"),
                            ("value", name_value),
                            ("placeholder", "e.g. Nintendo Switch"),
                            ("class", "w-full rounded border-default-medium p-2 bg-neutral-secondary-medium text-body"),
                        ],
                    ),
                ),
                _filter_field(
                    "Platform Group",
                    Component(
                        tag_name="input",
                        attributes=[
                            ("type", "text"),
                            ("name", "filter-group"),
                            ("value", group_value),
                            ("placeholder", "e.g. Nintendo"),
                            ("class", "w-full rounded border-default-medium p-2 bg-neutral-secondary-medium text-body"),
                        ],
                    ),
                ),
            ],
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)


def PlayEventFilterBar(
    filter_json="", preset_list_url="", preset_save_url=""
) -> SafeText:
    """Collapsible filter bar for the PlayEvent list."""
    from games.models import PlayEvent

    existing = _filter_parse(filter_json)
    game_choice = _filter_get_choice(existing, "game")
    days_min, days_max = _parse_range(existing, "days_to_finish")

    fields = [
        Component(
            tag_name="div",
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "game",
                        game_choice,
                        search_url="/api/games/search",
                        nullable=False,
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Days to Finish",
            input_name_prefix="filter-days-to-finish",
            min_value=days_min,
            max_value=days_max,
            range_min=0,
            range_max=365,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 30",
        ),
    ]
    return _filter_bar(fields, filter_json, preset_list_url, preset_save_url)
```

- [ ] **Step 2: Export new FilterBars in `common/components/__init__.py`**

Modify: `common/components/__init__.py` to import and expose `DeviceFilterBar`, `PlatformFilterBar`, and `PlayEventFilterBar`.

```python
# Import section:
from common.components.filters import (
    FilterBar,
    PurchaseFilterBar,
    SessionFilterBar,
    DeviceFilterBar,
    PlatformFilterBar,
    PlayEventFilterBar,
)

# In __all__:
    "FilterBar",
    "PurchaseFilterBar",
    "SessionFilterBar",
    "DeviceFilterBar",
    "PlatformFilterBar",
    "PlayEventFilterBar",
```

---

### Task 3: Integrate FilterBars into `Device`, `Platform`, and `PlayEvent` views

**Files:**
- Modify: `games/views/device.py`
- Modify: `games/views/platform.py`
- Modify: `games/views/playevent.py`

- [ ] **Step 1: Integrate FilterBar in `list_devices` in `games/views/device.py`**

Import and parse the filter, apply to queryset, instantiate `DeviceFilterBar`, prepend it to the output page content.

```python
# At top of games/views/device.py:
from django.utils.safestring import mark_safe
from common.components import DeviceFilterBar, ModuleScript
from games.filters import parse_device_filter

# Inside list_devices(request):
    devices = Device.objects.order_by("-created_at")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        device_filter = parse_device_filter(filter_json)
        if device_filter is not None:
            devices = devices.filter(device_filter.to_q())

    devices, page_obj, elided_page_range = paginate(request, devices)
    
    # ... create data dict ...

    # Prepend the filter bar above table:
    filter_bar = DeviceFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets") + "?mode=devices",
        preset_save_url=reverse("games:save_preset") + "?mode=devices",
    )
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage devices",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("search_select.js")
        + ModuleScript("filter_bar.js"),
    )
```

- [ ] **Step 2: Integrate FilterBar in `list_platforms` in `games/views/platform.py`**

Import and parse the filter, apply to platform queryset, instantiate platform filter bar, prepend to page content.

```python
# At top of games/views/platform.py:
from django.utils.safestring import mark_safe
from common.components import PlatformFilterBar, ModuleScript
from games.filters import parse_platform_filter

# Inside list_platforms(request):
    platforms = Platform.objects.order_by("name")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        platform_filter = parse_platform_filter(filter_json)
        if platform_filter is not None:
            platforms = platforms.filter(platform_filter.to_q())

    platforms, page_obj, elided_page_range = paginate(request, platforms)

    # ... create data dict ...

    filter_bar = PlatformFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets") + "?mode=platforms",
        preset_save_url=reverse("games:save_preset") + "?mode=platforms",
    )
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage platforms",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("search_select.js")
        + ModuleScript("filter_bar.js"),
    )
```

- [ ] **Step 3: Integrate FilterBar in `list_playevents` in `games/views/playevent.py`**

Import and parse the filter, apply to playevent queryset, instantiate playevent filter bar, prepend to page content.

```python
# At top of games/views/playevent.py:
from django.utils.safestring import mark_safe
from common.components import PlayEventFilterBar
from games.filters import parse_playevent_filter

# Inside list_playevents(request):
    playevents = PlayEvent.objects.order_by("-created_at")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        playevent_filter = parse_playevent_filter(filter_json)
        if playevent_filter is not None:
            playevents = playevents.filter(playevent_filter.to_q())

    playevents, page_obj, elided_page_range = paginate(request, playevents)

    # ... create data ...

    filter_bar = PlayEventFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets") + "?mode=playevents",
        preset_save_url=reverse("games:save_preset") + "?mode=playevents",
    )
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage play events",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("search_select.js")
        + ModuleScript("filter_bar.js"),
    )
```

---

### Task 4: Support new preset modes in Preset View/Model

Ensure FilterPreset allows `devices` and `platforms` modes.

**Files:**
- Modify: `games/models.py`
- Modify: `games/views/filter_presets.py`

- [ ] **Step 1: Expand FilterPreset mode choices**

Verify or expand `MODE_CHOICES` inside `FilterPreset` model in `games/models.py`.

```python
# Inside FilterPreset class:
    MODE_CHOICES = [
        ("games", "Games"),
        ("sessions", "Sessions"),
        ("purchases", "Purchases"),
        ("playevents", "Play Events"),
        ("devices", "Devices"),
        ("platforms", "Platforms"),
    ]
```

---

### Task 5: Add Render Tests for new FilterBars

**Files:**
- Modify: `tests/test_filter_bars.py`

- [ ] **Step 1: Write tests to verify new FilterBars render correctly**

Add test cases in `tests/test_filter_bars.py`:

```python
    def test_device_filter_bar(self):
        from common.components import DeviceFilterBar
        html = str(
            DeviceFilterBar(
                filter_json="",
                preset_list_url="/presets/devices/list",
                preset_save_url="/presets/devices/save",
            )
        )
        self._assert_shell(html, "/presets/devices/list", "/presets/devices/save")

    def test_platform_filter_bar(self):
        from common.components import PlatformFilterBar
        html = str(
            PlatformFilterBar(
                filter_json="",
                preset_list_url="/presets/platforms/list",
                preset_save_url="/presets/platforms/save",
            )
        )
        self._assert_shell(html, "/presets/platforms/list", "/presets/platforms/save")

    def test_playevent_filter_bar(self):
        from common.components import PlayEventFilterBar
        html = str(
            PlayEventFilterBar(
                filter_json="",
                preset_list_url="/presets/playevents/list",
                preset_save_url="/presets/playevents/save",
            )
        )
        self._assert_shell(html, "/presets/playevents/list", "/presets/playevents/save")
```

- [ ] **Step 2: Run all test suites to confirm complete success**

Run: `pytest tests/test_filter_bars.py -v`
Expected: ALL filter bar render tests pass.
