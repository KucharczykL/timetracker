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
