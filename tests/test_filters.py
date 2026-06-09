"""Tests for the filtering system."""

import json

import pytest
from django.db.models import Q

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    StringCriterion,
)
from common.components import FilterBar
from games.filters import GameFilter


class TestModifier:
    def test_includes_only_in_enum(self):
        assert Modifier.INCLUDES_ONLY == "INCLUDES_ONLY"

    def test_includes_only_in_for_multi(self):
        assert Modifier.INCLUDES_ONLY in Modifier.for_multi()

    def test_for_multi_includes_all_four_match_modes(self):
        modes = Modifier.for_multi()
        assert Modifier.INCLUDES in modes
        assert Modifier.INCLUDES_ALL in modes
        assert Modifier.INCLUDES_ONLY in modes
        assert Modifier.EXCLUDES in modes


class TestStringCriterion:
    def test_equals(self):
        c = StringCriterion(value="zelda", modifier=Modifier.EQUALS)
        assert c.to_q("name") == Q(name="zelda")

    def test_is_null(self):
        c = StringCriterion(value="", modifier=Modifier.IS_NULL)
        assert c.to_q("name") == Q(name__isnull=True)


class TestIntCriterion:
    def test_between(self):
        c = IntCriterion(value=2020, value2=2024, modifier=Modifier.BETWEEN)
        assert c.to_q("year_released") == Q(
            year_released__gte=2020, year_released__lte=2024
        )


class TestBoolCriterion:
    def test_equals_true(self):
        c = BoolCriterion(value=True, modifier=Modifier.EQUALS)
        assert c.to_q("mastered") == Q(mastered=True)


class TestChoiceCriterion:
    def test_includes(self):
        c = ChoiceCriterion(value=["f", "p"], modifier=Modifier.INCLUDES)
        assert c.to_q("status") == Q(status__in=["f", "p"])

    def test_excludes(self):
        c = ChoiceCriterion(value=["a"], modifier=Modifier.EXCLUDES)
        assert c.to_q("status") == ~Q(status__in=["a"])

    def test_excludes_only_empty_value(self):
        """Excluding a single status with no includes — value=[], excludes=["f"]."""
        c = ChoiceCriterion(value=[], excludes=["f"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == ~Q(status__in=["f"])

    def test_excludes_two(self):
        """Excluding two statuses with no includes."""
        c = ChoiceCriterion(value=[], excludes=["f", "a"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == ~Q(status__in=["f", "a"])

    def test_include_and_exclude(self):
        """Include f, exclude a — both lists set."""
        c = ChoiceCriterion(value=["f"], excludes=["a"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == Q(status__in=["f"]) & ~Q(status__in=["a"])

    def test_include_two_and_exclude_one(self):
        c = ChoiceCriterion(
            value=["f", "p"], excludes=["a"], modifier=Modifier.INCLUDES
        )
        q = c.to_q("status")
        assert q == Q(status__in=["f", "p"]) & ~Q(status__in=["a"])

    def test_is_null(self):
        c = ChoiceCriterion(value=[], modifier=Modifier.IS_NULL)
        assert c.to_q("status") == Q(status__isnull=True)

    def test_not_null(self):
        c = ChoiceCriterion(value=[], modifier=Modifier.NOT_NULL)
        assert c.to_q("status") == Q(status__isnull=False)

    def test_excludes_modifier(self):
        """EXCLUDES modifier with value set."""
        c = ChoiceCriterion(value=["f"], modifier=Modifier.EXCLUDES)
        assert c.to_q("status") == ~Q(status__in=["f"])

    def test_excludes_modifier_empty_value(self):
        """EXCLUDES modifier with empty value — should produce empty Q."""
        c = ChoiceCriterion(value=[], modifier=Modifier.EXCLUDES)
        q = c.to_q("status")
        assert q == Q()

    def test_excludes_modifier_keeps_excludes_orthogonal(self):
        """Harmonized (Stash model): under EXCLUDES the ``excludes`` channel stays
        an orthogonal AND'd negative — it is *not* swapped into a positive
        include (the old divergent ChoiceCriterion behaviour)."""
        c = ChoiceCriterion(value=["f"], excludes=["a"], modifier=Modifier.EXCLUDES)
        assert c.to_q("status") == ~Q(status__in=["f"]) & ~Q(status__in=["a"])

    @pytest.mark.parametrize(
        "modifier", [Modifier.INCLUDES_ALL, Modifier.INCLUDES_ONLY]
    )
    def test_m2m_modifiers_require_filter_builder(self, modifier):
        """INCLUDES_ALL / INCLUDES_ONLY cannot be built by the generic criterion
        layer — they require a filter-level Q builder (see
        PurchaseFilter._games_to_q)."""
        c = ChoiceCriterion(value=["f", "p"], modifier=modifier)
        with pytest.raises(AssertionError, match="requires a filter-level"):
            c.to_q("status")

    def test_not_equals(self):
        c = ChoiceCriterion(value=["f"], modifier=Modifier.NOT_EQUALS)
        assert c.to_q("status") == ~Q(status__in=["f"])


class TestMultiCriterion:
    def test_includes(self):
        c = MultiCriterion(value=[797], modifier=Modifier.INCLUDES)
        assert c.to_q("game_id") == Q(game_id__in=[797])

    def test_excludes_only_empty_value(self):
        """Exclude one device with no includes — value=[], excludes=[11].

        Regression: an empty ``value`` must not add ``__in=[]`` (which matches
        nothing); the criterion should mean "all rows except device 11".
        """
        c = MultiCriterion(value=[], excludes=[11], modifier=Modifier.INCLUDES)
        assert c.to_q("device_id") == ~Q(device_id__in=[11])

    def test_include_and_exclude(self):
        c = MultiCriterion(value=[1], excludes=[2], modifier=Modifier.INCLUDES)
        assert c.to_q("game_id") == Q(game_id__in=[1]) & ~Q(game_id__in=[2])

    def test_excludes_modifier_applies_excludes_channel(self):
        """Harmonized (Stash model): EXCLUDES negates ``value`` AND still applies
        the orthogonal ``excludes`` channel. Previously MultiCriterion.EXCLUDES
        dropped the excludes list entirely."""
        c = MultiCriterion(value=[1], excludes=[2], modifier=Modifier.EXCLUDES)
        assert c.to_q("game_id") == ~Q(game_id__in=[1]) & ~Q(game_id__in=[2])

    @pytest.mark.parametrize(
        "modifier", [Modifier.INCLUDES_ALL, Modifier.INCLUDES_ONLY]
    )
    def test_m2m_modifiers_require_filter_builder(self, modifier):
        """INCLUDES_ALL / INCLUDES_ONLY cannot be built by the generic criterion
        layer — they require a filter-level Q builder (see
        PurchaseFilter._games_to_q)."""
        c = MultiCriterion(value=[1, 2], modifier=modifier)
        with pytest.raises(AssertionError, match="requires a filter-level"):
            c.to_q("games")

    def test_is_null(self):
        c = MultiCriterion(value=[], modifier=Modifier.IS_NULL)
        assert c.to_q("device_id") == Q(device_id__isnull=True)

    def test_from_json_strips_embedded_labels(self):
        """from_json normalises {id, label} dicts to bare ids."""
        c = MultiCriterion.from_json(
            {
                "value": [{"id": 797, "label": "Hollow Knight"}],
                "excludes": [{"id": 11, "label": "Steam Deck"}],
            }
        )
        assert c.value == [797]
        assert c.excludes == [11]
        assert c.to_q("game_id") == Q(game_id__in=[797]) & ~Q(game_id__in=[11])


class TestChoiceCriterionAgainstDB:
    """Verify ChoiceCriterion produces correct DB results."""

    @pytest.fixture(autouse=True)
    def setup(self, django_db_blocker):
        pass

    def _seed_games(self):
        """Create test games with different statuses."""
        from games.models import Game, Platform

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        statuses = ["u", "p", "f", "r", "a"]
        for i, s in enumerate(statuses):
            Game.objects.get_or_create(
                name=f"Test Game {i}",
                defaults={"platform": platform, "status": s},
            )

    def _count(self, c: ChoiceCriterion) -> int:
        from games.models import Game

        return Game.objects.filter(c.to_q("status")).count()

    def _statuses(self, c: ChoiceCriterion) -> set[str]:
        from games.models import Game

        return set(
            Game.objects.filter(c.to_q("status")).values_list("status", flat=True)
        )

    @pytest.mark.django_db
    def test_include_finished_includes_only_finished(self):
        self._seed_games()
        c = ChoiceCriterion(value=["f"], modifier=Modifier.INCLUDES)
        assert self._statuses(c) == {"f"}

    @pytest.mark.django_db
    def test_exclude_finished_excludes_finished(self):
        self._seed_games()
        c = ChoiceCriterion(value=[], excludes=["f"], modifier=Modifier.INCLUDES)
        assert "f" not in self._statuses(c)
        assert len(self._statuses(c)) == 4  # u, p, r, a

    @pytest.mark.django_db
    def test_include_and_exclude(self):
        """Include Finished but exclude Abandoned."""
        self._seed_games()
        c = ChoiceCriterion(
            value=["f", "a"], excludes=["a"], modifier=Modifier.INCLUDES
        )
        # Include f and a, but exclude a → only f
        assert self._statuses(c) == {"f"}

    @pytest.mark.django_db
    def test_include_two(self):
        """Include Finished AND Played."""
        self._seed_games()
        c = ChoiceCriterion(value=["f", "p"], modifier=Modifier.INCLUDES)
        assert self._statuses(c) == {"f", "p"}

    @pytest.mark.django_db
    def test_exclude_two(self):
        """Exclude Finished AND Abandoned."""
        self._seed_games()
        c = ChoiceCriterion(value=[], excludes=["f", "a"], modifier=Modifier.INCLUDES)
        statuses = self._statuses(c)
        assert "f" not in statuses
        assert "a" not in statuses
        assert statuses == {"u", "p", "r"}

    @pytest.mark.django_db
    def test_not_null_has_results(self):
        self._seed_games()
        c = ChoiceCriterion(value=[], modifier=Modifier.NOT_NULL)
        assert self._count(c) == 5

    @pytest.mark.django_db
    def test_is_null_no_results(self):
        """IS_NULL on a non-null field returns zero."""
        self._seed_games()
        c = ChoiceCriterion(value=[], modifier=Modifier.IS_NULL)
        assert self._count(c) == 0


class TestPurchaseGamesIncludesAllAgainstDB:
    """INCLUDES_ALL on the many-to-many ``Purchase.games`` should match only
    purchases linked to *all* of the given games — Stash's ``includes all``."""

    def _seed(self):
        import datetime

        from games.models import Game, Platform, Purchase

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        a, _ = Game.objects.get_or_create(name="A", defaults={"platform": platform})
        b, _ = Game.objects.get_or_create(name="B", defaults={"platform": platform})
        c, _ = Game.objects.get_or_create(name="C", defaults={"platform": platform})

        def make(linked):
            purchase = Purchase.objects.create(
                platform=platform, date_purchased=datetime.date(2024, 1, 1)
            )
            purchase.games.set(linked)
            return purchase

        return {
            "a": a,
            "b": b,
            "both": make([a, b]),
            "only_a": make([a]),
            "all_three": make([a, b, c]),
        }

    @pytest.mark.django_db
    def test_includes_all_matches_only_supersets(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id, seeded["b"].id],
                    "modifier": "INCLUDES_ALL",
                }
            }
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["both"], seeded["all_three"]}

    @pytest.mark.django_db
    def test_includes_any_is_broader(self):
        """Contrast: plain INCLUDES (any) also matches the A-only purchase."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id, seeded["b"].id],
                    "modifier": "INCLUDES",
                }
            }
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["both"], seeded["only_a"], seeded["all_three"]}

    @pytest.mark.django_db
    def test_includes_any_no_duplicates(self):
        """INCLUDES [A, B] must not return duplicate rows for a purchase linked
        to both A and B — the M2M join must not inflate the result.

        Regression: ``games__in`` on a many-to-many field produces one row per
        matching through-table entry, so a purchase linked to N of the selected
        games would appear N times.  The fix uses a subquery so each purchase
        appears at most once.
        """
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id, seeded["b"].id],
                    "modifier": "INCLUDES",
                }
            }
        )
        result = list(Purchase.objects.filter(pf.to_q()))
        # Must have 3 distinct purchases, not duplicates
        assert len(result) == 3
        assert set(result) == {seeded["both"], seeded["only_a"], seeded["all_three"]}

    @pytest.mark.django_db
    def test_includes_all_strips_embedded_labels(self):
        """Stash-style {id, label} value items are normalised to bare ids."""
        from common.criteria import Modifier
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [
                        {"id": seeded["a"].id, "label": "A"},
                        {"id": seeded["b"].id, "label": "B"},
                    ],
                    "modifier": "INCLUDES_ALL",
                }
            }
        )
        assert pf.games is not None
        assert pf.games.modifier == Modifier.INCLUDES_ALL
        assert pf.games.value == [seeded["a"].id, seeded["b"].id]
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["both"], seeded["all_three"]}


class TestPurchaseGamesIncludesOnlyAgainstDB:
    """INCLUDES_ONLY on the many-to-many ``Purchase.games`` should match only
    purchases linked to *exactly* the given games — Stash's ``only`` mode,
    which INCLUDES_ALL does not provide (it includes supersets)."""

    def _seed(self):
        import datetime

        from games.models import Game, Platform, Purchase

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        a, _ = Game.objects.get_or_create(name="A", defaults={"platform": platform})
        b, _ = Game.objects.get_or_create(name="B", defaults={"platform": platform})
        c, _ = Game.objects.get_or_create(name="C", defaults={"platform": platform})

        def make(linked):
            purchase = Purchase.objects.create(
                platform=platform, date_purchased=datetime.date(2024, 1, 1)
            )
            purchase.games.set(linked)
            return purchase

        return {
            "a": a,
            "b": b,
            "both": make([a, b]),
            "only_a": make([a]),
            "all_three": make([a, b, c]),
        }

    @pytest.mark.django_db
    def test_includes_only_matches_exact_set(self):
        """INCLUDES_ONLY [A, B] returns only purchases with exactly A and B."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id, seeded["b"].id],
                    "modifier": "INCLUDES_ONLY",
                }
            }
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["both"]}

    @pytest.mark.django_db
    def test_includes_only_single_game(self):
        """INCLUDES_ONLY [A] = exactly game A, no others."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id],
                    "modifier": "INCLUDES_ONLY",
                }
            }
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["only_a"]}

    @pytest.mark.django_db
    def test_includes_only_contrast_with_includes_all(self):
        """INCLUDES_ONLY excludes the superset that INCLUDES_ALL would match."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [seeded["a"].id, seeded["b"].id],
                    "modifier": "INCLUDES_ONLY",
                }
            }
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        # all_three has A, B, C — INCLUDES_ALL would match it, ONLY does not.
        assert seeded["all_three"] not in result
        assert seeded["both"] in result


class TestGameFilterFromJson:
    def test_status_choice_criterion(self):
        gf = GameFilter.from_json(
            {"status": {"value": ["f", "p"], "modifier": "INCLUDES"}}
        )
        assert gf is not None
        assert gf.status is not None
        assert gf.status.value == ["f", "p"]
        assert gf.status.modifier == Modifier.INCLUDES

    def test_status_not_null(self):
        gf = GameFilter.from_json({"status": {"modifier": "NOT_NULL"}})
        assert gf is not None
        assert gf.status is not None
        assert gf.status.modifier == Modifier.NOT_NULL

    def test_platform_choice_criterion(self):
        gf = GameFilter.from_json(
            {"platform": {"value": ["1", "3"], "modifier": "INCLUDES"}}
        )
        assert gf is not None
        assert gf.platform is not None
        assert gf.platform.value == ["1", "3"]

    def test_round_trip(self):
        data = {
            "status": {"value": ["f"], "modifier": "INCLUDES"},
            "mastered": {"value": True, "modifier": "EQUALS"},
        }
        gf = GameFilter.from_json(data)
        json_out = gf.to_json()
        gf2 = GameFilter.from_json(json_out)
        assert gf2 is not None
        assert gf2.status is not None
        assert gf2.mastered is not None


class TestGameFilterToQ:
    def test_status_choice_includes(self):
        gf = GameFilter.from_json(
            {"status": {"value": ["f", "p"], "modifier": "INCLUDES"}}
        )
        q = gf.to_q()
        assert q == Q(status__in=["f", "p"])

    def test_status_not_null(self):
        gf = GameFilter.from_json({"status": {"modifier": "NOT_NULL"}})
        q = gf.to_q()
        assert q == Q(status__isnull=False)


class TestFilterBarRendering:
    """Tests for FilterBar with FilterSelect widgets."""

    def test_status_uses_filter_select(self):
        html = str(FilterBar())
        assert 'data-search-select-mode="filter"' in html
        assert 'data-name="status"' in html

    def test_mastered_not_checked_by_default(self):
        html = str(FilterBar(filter_json=""))
        assert 'checked="true"' not in html

    def test_mastered_checked_when_filtered(self):
        html = str(
            FilterBar(
                filter_json=json.dumps(
                    {"mastered": {"value": True, "modifier": "EQUALS"}}
                ),
            )
        )
        assert 'checked="true"' in html

    def test_status_prefilled(self):
        html = str(
            FilterBar(
                filter_json=json.dumps(
                    {
                        "status": {
                            "value": [{"id": "f", "label": "Finished"}],
                            "modifier": "INCLUDES",
                        }
                    }
                ),
            )
        )
        assert 'data-value="f"' in html
        assert "Finished" in html

    def test_no_hx_get(self):
        html = str(FilterBar())
        assert "hx-get" not in html

    def test_platform_uses_search_url(self):
        """Platform is model-backed: rows are fetched, not pre-rendered."""
        html = str(FilterBar())
        assert 'data-search-url="/api/platforms/search"' in html

    def test_status_has_no_modifiers(self):
        """Non-nullable fields should not show (None) but MUST show (Any)."""
        html = str(FilterBar())
        status_start = html.find('data-name="status"')
        platform_start = html.find('data-name="platform"')
        status_section = html[status_start:platform_start]
        # Must have (Any) — always available
        assert "(Any)" in status_section
        # Must NOT have (None) — field is non-nullable
        assert "(None)" not in status_section

    def test_platform_has_modifiers(self):
        """Nullable ForeignKey fields should show (Any)/(None)."""
        html = str(FilterBar())
        platform_start = html.find('data-name="platform"')
        platform_section = html[platform_start:]
        # Should have at least one modifier option
        assert "(Any)" in platform_section or "(None)" in platform_section


class TestPurchaseNumPurchasesAgainstDB:
    """num_purchases IntCriterion filters purchases by game count."""

    def _seed(self):
        import datetime

        from games.models import Game, Platform, Purchase

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        a, _ = Game.objects.get_or_create(name="A", defaults={"platform": platform})
        b, _ = Game.objects.get_or_create(name="B", defaults={"platform": platform})
        c, _ = Game.objects.get_or_create(name="C", defaults={"platform": platform})

        single = Purchase.objects.create(
            platform=platform, date_purchased=datetime.date(2024, 1, 1)
        )
        single.games.set([a])

        double = Purchase.objects.create(
            platform=platform, date_purchased=datetime.date(2024, 1, 1)
        )
        double.games.set([a, b])

        triple = Purchase.objects.create(
            platform=platform, date_purchased=datetime.date(2024, 1, 1)
        )
        triple.games.set([a, b, c])

        return {"single": single, "double": double, "triple": triple}

    @pytest.mark.django_db
    def test_between_two_and_three(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {"num_purchases": {"value": 2, "value2": 3, "modifier": "BETWEEN"}}
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["double"], seeded["triple"]}

    @pytest.mark.django_db
    def test_greater_than_one(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {"num_purchases": {"value": 1, "modifier": "GREATER_THAN"}}
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["double"], seeded["triple"]}

    @pytest.mark.django_db
    def test_equals_one(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {"num_purchases": {"value": 1, "modifier": "EQUALS"}}
        )
        result = set(Purchase.objects.filter(pf.to_q()))
        assert result == {seeded["single"]}


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
        from games.filters import DeviceFilter
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
        from games.filters import PlatformFilter
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
