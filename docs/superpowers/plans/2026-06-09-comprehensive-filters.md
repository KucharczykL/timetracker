# Comprehensive Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a comprehensive suite of backend filter classes and filter field expansions across all 6 main models (Game, Session, Purchase, Device, Platform, PlayEvent) using a subquery-based cross-entity approach.

**Architecture:** We will implement missing filter classes (`DeviceFilter`, `PlatformFilter`, `PlayEventFilter`) in `games/filters.py`. We will extend all filters to support powerful, deeply linked "cross-entity" subqueries (e.g. `GameFilter.session_filter` or `PlatformFilter.game_filter`) which builds robust `Q` objects without causing duplicate join rows in list queries.

**Tech Stack:** Django, Python dataclasses, Pytest.

---

### Task 1: Implement New Filter Classes (Device, Platform, PlayEvent)

**Files:**
- Modify: `games/filters.py`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Implement DeviceFilter, PlatformFilter, and PlayEventFilter**

Add the three new operator filters to `games/filters.py`. Ensure we import all necessary criterion types and add the `parse_device_filter`, `parse_platform_filter`, and `parse_playevent_filter` helper functions at the end of the file.

```python
# Insert new filter imports and classes in games/filters.py

@dataclass
class DeviceFilter(OperatorFilter):
    """Filter for the Device model."""

    AND: DeviceFilter | None = None
    OR: DeviceFilter | None = None
    NOT: DeviceFilter | None = None

    name: StringCriterion | None = None
    type: ChoiceCriterion | None = None
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: Devices that have sessions matching these criteria
    session_filter: SessionFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.name is not None:
            q &= self.name.to_q("name")
        if self.type is not None:
            q &= self.type.to_q("type")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = (
                Q(name__icontains=self.search.value)
                | Q(type__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

        # Cross-entity filter: session_filter
        if self.session_filter is not None:
            from games.models import Session
            session_q = self.session_filter.to_q()
            matching_ids = Session.objects.filter(session_q).values_list("device_id", flat=True)
            q &= Q(id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


@dataclass
class PlatformFilter(OperatorFilter):
    """Filter for the Platform model."""

    AND: PlatformFilter | None = None
    OR: PlatformFilter | None = None
    NOT: PlatformFilter | None = None

    name: StringCriterion | None = None
    group: StringCriterion | None = None
    icon: StringCriterion | None = None
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity
    game_filter: GameFilter | None = None
    purchase_filter: PurchaseFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.name is not None:
            q &= self.name.to_q("name")
        if self.group is not None:
            q &= self.group.to_q("group")
        if self.icon is not None:
            q &= self.icon.to_q("icon")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = (
                Q(name__icontains=self.search.value)
                | Q(group__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

        # Cross-entity filter: game_filter
        if self.game_filter is not None:
            from games.models import Game
            game_q = self.game_filter.to_q()
            matching_ids = Game.objects.filter(game_q).values_list("platform_id", flat=True)
            q &= Q(id__in=matching_ids)

        # Cross-entity filter: purchase_filter
        if self.purchase_filter is not None:
            from games.models import Purchase
            purchase_q = self.purchase_filter.to_q()
            matching_ids = Purchase.objects.filter(purchase_q).values_list("platform_id", flat=True)
            q &= Q(id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


@dataclass
class PlayEventFilter(OperatorFilter):
    """Filter for the PlayEvent model."""

    AND: PlayEventFilter | None = None
    OR: PlayEventFilter | None = None
    NOT: PlayEventFilter | None = None

    game: MultiCriterion | None = None  # filters on game_id
    started: StringCriterion | None = None  # date string
    ended: StringCriterion | None = None  # date string
    days_to_finish: IntCriterion | None = None
    note: StringCriterion | None = None
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: PlayEvents for games matching these criteria
    game_filter: GameFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.game is not None:
            q &= self.game.to_q("game_id")
        if self.started is not None:
            q &= self.started.to_q("started")
        if self.ended is not None:
            q &= self.ended.to_q("ended")
        if self.days_to_finish is not None:
            q &= self.days_to_finish.to_q("days_to_finish")
        if self.note is not None:
            q &= self.note.to_q("note")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = (
                Q(game__name__icontains=self.search.value)
                | Q(note__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

        # Cross-entity filter: game_filter
        if self.game_filter is not None:
            from games.models import Game
            game_q = self.game_filter.to_q()
            matching_ids = Game.objects.filter(game_q).values_list("id", flat=True)
            q &= Q(game_id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


# Add to convenience helpers section:
def parse_device_filter(json_str: str) -> DeviceFilter | None:
    return filter_from_json(DeviceFilter, json_str)


def parse_platform_filter(json_str: str) -> PlatformFilter | None:
    return filter_from_json(PlatformFilter, json_str)


def parse_playevent_filter(json_str: str) -> PlayEventFilter | None:
    return filter_from_json(PlayEventFilter, json_str)
```

- [ ] **Step 2: Run existing tests to verify everything compiles**

Run: `pytest tests/test_filters.py -v`
Expected: All existing tests PASS without issues.

---

### Task 2: Expand SessionFilter (Duration Fields + Cross-Entity)

**Files:**
- Modify: `games/filters.py:SessionFilter`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Refactor SessionFilter and add new duration fields & device_filter**

Modify `SessionFilter` to replace `duration_minutes: IntCriterion` with `duration_total_minutes`, `duration_manual_minutes`, and `duration_calculated_minutes`. Add `device_filter: DeviceFilter`.

Update `to_q()` inside `SessionFilter` to map duration fields correctly to their respective GeneratedFields (`duration_total`, `duration_calculated`) or manual field (`duration_manual`). Use standard Python `timedelta` logic.

```python
# Inside SessionFilter class:
    duration_total_minutes: IntCriterion | None = None
    duration_manual_minutes: IntCriterion | None = None
    duration_calculated_minutes: IntCriterion | None = None

    # Cross-entity: sessions for devices matching these criteria
    device_filter: DeviceFilter | None = None
```

```python
# Helper inside SessionFilter or refactored:
    def _duration_to_q(self, c: IntCriterion, field: str) -> Q:
        from datetime import timedelta
        q = Q()
        td_val = timedelta(minutes=c.value)
        m = c.modifier
        if m == Modifier.EQUALS:
            q &= Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        elif m == Modifier.NOT_EQUALS:
            q &= ~Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        elif m == Modifier.GREATER_THAN:
            q &= Q(**{f"{field}__gt": td_val})
        elif m == Modifier.LESS_THAN:
            q &= Q(**{f"{field}__lt": td_val})
        elif m == Modifier.BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            q &= Q(**{f"{field}__gte": lo, f"{f_field}__lte": hi})
        elif m == Modifier.NOT_BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            q &= Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
        elif m == Modifier.IS_NULL:
            q &= Q(**{f"{field}": timedelta(0)})
        elif m == Modifier.NOT_NULL:
            q &= ~Q(**{f"{field}": timedelta(0)})
        return q
```

Then in `to_q()` inside `SessionFilter`:
```python
        if self.duration_total_minutes is not None:
            q &= self._duration_to_q(self.duration_total_minutes, "duration_total")
        if self.duration_manual_minutes is not None:
            q &= self._duration_to_q(self.duration_manual_minutes, "duration_manual")
        if self.duration_calculated_minutes is not None:
            q &= self._duration_to_q(self.duration_calculated_minutes, "duration_calculated")

        # Cross-entity filter: device_filter
        if self.device_filter is not None:
            from games.models import Device
            device_q = self.device_filter.to_q()
            matching_ids = Device.objects.filter(device_q).values_list("id", flat=True)
            q &= Q(device_id__in=matching_ids)
```

- [ ] **Step 2: Run tests to verify compiles correctly**

Run: `pytest tests/test_filters.py -v`
Expected: PASS (existing tests may need updating if they referenced `duration_minutes`).

---

### Task 3: Expand PurchaseFilter (Original Currency, Infinite, Needs Price Update, Converted Currency)

**Files:**
- Modify: `games/filters.py:PurchaseFilter`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Add new fields to PurchaseFilter and platform_filter**

Expand `PurchaseFilter` with `infinite: BoolCriterion`, `needs_price_update: BoolCriterion`, `converted_currency: StringCriterion`, and `platform_filter: PlatformFilter`.

```python
# Inside PurchaseFilter class:
    infinite: BoolCriterion | None = None
    needs_price_update: BoolCriterion | None = None
    converted_currency: StringCriterion | None = None

    # Cross-entity
    platform_filter: PlatformFilter | None = None
```

Update `to_q()` inside `PurchaseFilter`:
```python
        if self.infinite is not None:
            q &= self.infinite.to_q("infinite")
        if self.needs_price_update is not None:
            q &= self.needs_price_update.to_q("needs_price_update")
        if self.converted_currency is not None:
            q &= self.converted_currency.to_q("converted_currency")

        # Cross-entity filter: platform_filter
        if self.platform_filter is not None:
            from games.models import Platform
            platform_q = self.platform_filter.to_q()
            matching_ids = Platform.objects.filter(platform_q).values_list("id", flat=True)
            q &= Q(platform_id__in=matching_ids)
```

- [ ] **Step 2: Verify test suite continues to pass**

Run: `pytest tests/test_filters.py -v`
Expected: PASS

---

### Task 4: Expand GameFilter (Has Purchases, Has PlayEvents, Session Stats, Cross-Entity)

**Files:**
- Modify: `games/filters.py:GameFilter`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Expand GameFilter with session stats, purchase/playevent existence, and cross-entity filters**

Add fields and cross-entity filters to `GameFilter`:
```python
# Inside GameFilter class:
    has_purchases: BoolCriterion | None = None
    has_playevents: BoolCriterion | None = None
    session_count: IntCriterion | None = None
    session_average: IntCriterion | None = None  # average in minutes

    # Cross-entity filters
    session_filter: SessionFilter | None = None
    purchase_filter: PurchaseFilter | None = None
    playevent_filter: PlayEventFilter | None = None
    platform_filter: PlatformFilter | None = None
```

Update `to_q()` inside `GameFilter`.
For existence and session stats filters, we use Subqueries to avoid complex inline annotations during the generic filter generation (which is much cleaner and less bug-prone):

```python
        if self.has_purchases is not None:
            from games.models import Purchase
            purchased_ids = Purchase.objects.values_list("games__id", flat=True).distinct()
            if self.has_purchases.value:
                q &= Q(id__in=purchased_ids)
            else:
                q &= ~Q(id__in=purchased_ids)

        if self.has_playevents is not None:
            from games.models import PlayEvent
            played_ids = PlayEvent.objects.values_list("game_id", flat=True).distinct()
            if self.has_playevents.value:
                q &= Q(id__in=played_ids)
            else:
                q &= ~Q(id__in=played_ids)

        if self.session_count is not None:
            from games.models import Game
            from django.db.models import Count
            matching_ids = Game.objects.annotate(s_count=Count("sessions")).filter(self.session_count.to_q("s_count")).values_list("id", flat=True)
            q &= Q(id__in=matching_ids)

        if self.session_average is not None:
            from games.models import Game, Session
            from django.db.models import Avg, F, ExpressionWrapper, DurationField
            # Compute average session total duration.
            # Avg returns an interval/duration type, so we can convert it to minutes in Python or do duration comparisons directly.
            # To match the criterion easily, we can filter Game objects using Avg:
            matching_ids = Game.objects.annotate(s_avg=Avg("sessions__duration_total")).filter(self._playtime_to_q_for_field(self.session_average, "s_avg")).values_list("id", flat=True)
            q &= Q(id__in=matching_ids)

        # Cross-entity filters
        if self.session_filter is not None:
            from games.models import Session
            session_q = self.session_filter.to_q()
            matching_ids = Session.objects.filter(session_q).values_list("game_id", flat=True)
            q &= Q(id__in=matching_ids)

        if self.purchase_filter is not None:
            from games.models import Purchase
            purchase_q = self.purchase_filter.to_q()
            matching_ids = Purchase.objects.filter(purchase_q).values_list("games__id", flat=True)
            q &= Q(id__in=matching_ids)

        if self.playevent_filter is not None:
            from games.models import PlayEvent
            playevent_q = self.playevent_filter.to_q()
            matching_ids = PlayEvent.objects.filter(playevent_q).values_list("game_id", flat=True)
            q &= Q(id__in=matching_ids)

        if self.platform_filter is not None:
            from games.models import Platform
            platform_q = self.platform_filter.to_q()
            matching_ids = Platform.objects.filter(platform_q).values_list("id", flat=True)
            q &= Q(platform_id__in=matching_ids)
```

Add a helper `_playtime_to_q_for_field` in `GameFilter` that works exactly like `_playtime_to_q` but accepts a customized field name (e.g. `s_avg`):
```python
    @staticmethod
    def _playtime_to_q_for_field(c: IntCriterion, field: str) -> Q:
        from datetime import timedelta
        m = c.modifier
        td_val = timedelta(minutes=c.value)

        if m == Modifier.EQUALS:
            return Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        if m == Modifier.NOT_EQUALS:
            return ~Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field}__gt": td_val})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field}__lt": td_val})
        if m == Modifier.BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            return Q(**{f"{field}__gte": lo, f"{field}__lte": hi})
        if m == Modifier.NOT_BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            return Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field}": timedelta(0)})
        if m == Modifier.NOT_NULL:
            return ~Q(**{f"{field}": timedelta(0)})
        return Q()
```

- [ ] **Step 2: Update existing `_playtime_to_q` to delegate to `_playtime_to_q_for_field`**
```python
    @staticmethod
    def _playtime_to_q(c: IntCriterion) -> Q:
        return GameFilter._playtime_to_q_for_field(c, "playtime")
```

---

### Task 5: Add Exhaustive DB Tests for the Expanded and New Filters

**Files:**
- Modify: `tests/test_filters.py`

- [ ] **Step 1: Write DB-backed unit tests for the new filter behaviors**

Add comprehensive test cases inside `tests/test_filters.py` covering:
- New cross-entity filters (e.g. Platform -> Game -> Session -> Device chain).
- Session total vs manual vs calculated duration filters.
- Game session stats (`session_count`, `session_average`) and presence flags (`has_purchases`, `has_playevents`).
- Device, Platform, and PlayEvent specific filters.

```python
# Add test class at the end of tests/test_filters.py:

@pytest.mark.django_db
class TestExpandedFiltersAgainstDB:
    def _setup_entities(self):
        from games.models import Game, Platform, Device, Session, Purchase, PlayEvent
        import datetime
        from datetime import timedelta

        # 1. Platform & Game
        plat, _ = Platform.objects.get_or_create(name="Retro Console", group="Nintendo", icon="retro")
        game, _ = Game.objects.get_or_create(name="Super Mario World", defaults={"platform": plat, "status": "f"})
        game2, _ = Game.objects.get_or_create(name="Zelda", defaults={"platform": plat, "status": "u"})

        # 2. Device & Session
        dev, _ = Device.objects.get_or_create(name="Super Famicom", type="Console")
        
        # Session 1: total 40 minutes (30 calc, 10 manual)
        s1 = Session.objects.create(
            game=game,
            device=dev,
            timestamp_start=datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            timestamp_end=datetime.datetime(2026, 6, 1, 12, 30, 0, tzinfo=datetime.timezone.utc),
            duration_manual=timedelta(minutes=10)
        )

        # 3. Purchase
        pur = Purchase.objects.create(
            platform=plat,
            date_purchased=datetime.date(2026, 1, 1),
            infinite=True,
            price=49.99,
            price_currency="JPY",
            converted_price=45.00,
            converted_currency="USD",
            needs_price_update=False
        )
        pur.games.add(game)

        # 4. PlayEvent
        pe = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2026, 6, 1),
            ended=datetime.date(2026, 6, 2),
            note="Completed 100%"
        )

        return {
            "plat": plat,
            "game": game,
            "game2": game2,
            "dev": dev,
            "s1": s1,
            "pur": pur,
            "pe": pe
        }

    def test_device_filter_and_cross_entity(self):
        from games.filters import DeviceFilter, SessionFilter
        from games.models import Device

        data = self._setup_entities()
        # Find devices that have sessions on "Super Mario World"
        df = DeviceFilter.from_json({
            "session_filter": {
                "game_filter": {
                    "name": {"value": "Super Mario World", "modifier": "EQUALS"}
                }
            }
        })
        results = list(Device.objects.filter(df.to_q()))
        assert data["dev"] in results

    def test_platform_filter_and_cross_entity(self):
        from games.filters import PlatformFilter, GameFilter
        from games.models import Platform

        data = self._setup_entities()
        # Find platforms with games that are finished
        pf = PlatformFilter.from_json({
            "game_filter": {
                "status": {"value": ["f"], "modifier": "INCLUDES"}
            }
        })
        results = list(Platform.objects.filter(pf.to_q()))
        assert data["plat"] in results

    def test_session_filter_duration_splits(self):
        from games.filters import SessionFilter
        from games.models import Session

        data = self._setup_entities()
        
        # Test duration_total_minutes equals 40
        sf_tot = SessionFilter.from_json({
            "duration_total_minutes": {"value": 40, "modifier": "EQUALS"}
        })
        assert Session.objects.filter(sf_tot.to_q()).count() == 1

        # Test duration_manual_minutes equals 10
        sf_man = SessionFilter.from_json({
            "duration_manual_minutes": {"value": 10, "modifier": "EQUALS"}
        })
        assert Session.objects.filter(sf_man.to_q()).count() == 1

        # Test duration_calculated_minutes equals 30
        sf_calc = SessionFilter.from_json({
            "duration_calculated_minutes": {"value": 30, "modifier": "EQUALS"}
        })
        assert Session.objects.filter(sf_calc.to_q()).count() == 1

    def test_purchase_filter_new_fields(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        data = self._setup_entities()

        pf = PurchaseFilter.from_json({
            "infinite": {"value": True, "modifier": "EQUALS"},
            "needs_price_update": {"value": False, "modifier": "EQUALS"},
            "converted_currency": {"value": "USD", "modifier": "EQUALS"}
        })
        assert Purchase.objects.filter(pf.to_q()).count() == 1

    def test_game_filter_stats_and_existence(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()

        # has_purchases = True
        gf_pur = GameFilter.from_json({
            "has_purchases": {"value": True, "modifier": "EQUALS"}
        })
        assert data["game"] in list(Game.objects.filter(gf_pur.to_q()))
        assert data["game2"] not in list(Game.objects.filter(gf_pur.to_q()))

        # session_count = 1
        gf_cnt = GameFilter.from_json({
            "session_count": {"value": 1, "modifier": "EQUALS"}
        })
        assert data["game"] in list(Game.objects.filter(gf_cnt.to_q()))
```

- [ ] **Step 2: Run all unit tests to confirm success**

Run: `pytest tests/test_filters.py -v`
Expected: ALL tests pass perfectly.
