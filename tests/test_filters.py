"""Tests for the filtering system."""

import json

import pytest
from django.db.models import Q

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
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

    def test_not_equals(self):
        c = StringCriterion(value="zelda", modifier=Modifier.NOT_EQUALS)
        assert c.to_q("name") == ~Q(name="zelda")

    def test_includes(self):
        c = StringCriterion(value="zelda", modifier=Modifier.INCLUDES)
        assert c.to_q("name") == Q(name__icontains="zelda")

    def test_excludes(self):
        c = StringCriterion(value="zelda", modifier=Modifier.EXCLUDES)
        assert c.to_q("name") == ~Q(name__icontains="zelda")

    def test_matches_regex(self):
        c = StringCriterion(value="zelda", modifier=Modifier.MATCHES_REGEX)
        assert c.to_q("name") == Q(name__regex="zelda")

    def test_not_matches_regex(self):
        c = StringCriterion(value="zelda", modifier=Modifier.NOT_MATCHES_REGEX)
        assert c.to_q("name") == ~Q(name__regex="zelda")

    def test_is_null(self):
        c = StringCriterion(value="", modifier=Modifier.IS_NULL)
        assert c.to_q("name") == Q(name__isnull=True)

    def test_not_null(self):
        c = StringCriterion(value="", modifier=Modifier.NOT_NULL)
        assert c.to_q("name") == Q(name__isnull=False)


class TestIntCriterion:
    def test_between(self):
        c = IntCriterion(value=2020, value2=2024, modifier=Modifier.BETWEEN)
        assert c.to_q("year_released") == Q(
            year_released__gte=2020, year_released__lte=2024
        )

    def test_not_between(self):
        c = IntCriterion(value=2020, value2=2024, modifier=Modifier.NOT_BETWEEN)
        assert c.to_q("year_released") == Q(year_released__lt=2020) | Q(
            year_released__gt=2024
        )

    def test_greater_than(self):
        c = IntCriterion(value=10, modifier=Modifier.GREATER_THAN)
        assert c.to_q("session_count") == Q(session_count__gt=10)

    def test_less_than(self):
        c = IntCriterion(value=10, modifier=Modifier.LESS_THAN)
        assert c.to_q("session_count") == Q(session_count__lt=10)

    def test_is_null(self):
        c = IntCriterion(modifier=Modifier.IS_NULL)
        assert c.to_q("year_released") == Q(year_released__isnull=True)

    def test_not_null(self):
        c = IntCriterion(modifier=Modifier.NOT_NULL)
        assert c.to_q("year_released") == Q(year_released__isnull=False)

    def test_round_trip_json_between(self):
        """value/value2/modifier survive dict → dataclass → dict unchanged."""
        original = IntCriterion(value=2020, value2=2024, modifier=Modifier.BETWEEN)
        as_dict = original.to_json()
        assert as_dict == {
            "value": 2020,
            "value2": 2024,
            "modifier": Modifier.BETWEEN,
        }
        assert IntCriterion.from_json(as_dict) == original

    def test_round_trip_json_is_null(self):
        original = IntCriterion(modifier=Modifier.IS_NULL)
        restored = IntCriterion.from_json(original.to_json())
        assert restored == original
        assert restored.to_q("year_released") == Q(year_released__isnull=True)


class TestBoolCriterion:
    def test_equals_true(self):
        c = BoolCriterion(value=True, modifier=Modifier.EQUALS)
        assert c.to_q("mastered") == Q(mastered=True)

    def test_value_false_survives_to_json(self):
        """value=False must serialize — it equals the dataclass default, so the
        base to_json would drop it, losing e.g. is_refunded=False."""
        assert BoolCriterion(value=False).to_json() == {"value": False}

    def test_value_false_round_trip(self):
        restored = BoolCriterion.from_json(BoolCriterion(value=False).to_json())
        assert restored.value is False


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
        assert 'filter-mode="true"' in html
        assert 'name="status"' in html

    def test_mastered_not_checked_by_default(self):
        html = str(FilterBar(filter_json=""))
        assert (
            'name="filter-mastered" value="true" class="rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand" checked="true"'
            not in html
        )
        assert (
            'name="filter-mastered" value="false" class="rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand" checked="true"'
            not in html
        )

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
        assert 'search-url="/api/platforms/search"' in html

    def test_status_has_no_modifiers(self):
        """Non-nullable fields should not show (None) but MUST show (Any)."""
        html = str(FilterBar())
        status_start = html.find('name="status"')
        platform_start = html.find('name="platform"')
        status_section = html[status_start:platform_start]
        # Must have (Any) — always available
        assert "(Any)" in status_section
        # Must NOT have (None) — field is non-nullable
        assert "(None)" not in status_section

    def test_platform_has_modifiers(self):
        """Nullable ForeignKey fields should show (Any)/(None)."""
        html = str(FilterBar())
        platform_start = html.find('name="platform"')
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
        plat, _ = Platform.objects.get_or_create(
            name="Retro Console", group="Nintendo", icon="retro"
        )
        game, _ = Game.objects.get_or_create(
            name="Super Mario World", defaults={"platform": plat, "status": "f"}
        )
        game2, _ = Game.objects.get_or_create(
            name="Zelda", defaults={"platform": plat, "status": "u"}
        )

        # 2. Device & Session
        dev, _ = Device.objects.get_or_create(name="Super Famicom", type="Console")

        # Session 1: total 4 hours (3 hours calc, 1 hour manual)
        s1 = Session.objects.create(
            game=game,
            device=dev,
            timestamp_start=datetime.datetime(
                2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2026, 6, 1, 15, 0, 0, tzinfo=datetime.timezone.utc
            ),
            duration_manual=timedelta(hours=1),
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
            needs_price_update=False,
        )
        pur.games.add(game)

        # 4. PlayEvent
        pe = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2026, 6, 1),
            ended=datetime.date(2026, 6, 2),
            note="Completed 100%",
        )

        return {
            "plat": plat,
            "game": game,
            "game2": game2,
            "dev": dev,
            "s1": s1,
            "pur": pur,
            "pe": pe,
        }

    def test_device_filter_and_cross_entity(self):
        from games.filters import DeviceFilter
        from games.models import Device

        data = self._setup_entities()
        # Find devices that have sessions on "Super Mario World"
        df = DeviceFilter.from_json(
            {
                "session_filter": {
                    "game_filter": {
                        "name": {"value": "Super Mario World", "modifier": "EQUALS"}
                    }
                }
            }
        )
        # The cross-entity sub-filters must actually deserialize — otherwise the
        # query is unconstrained and the assertion below passes by accident on a
        # single-device fixture (issue #120 false positive).
        assert df.session_filter is not None
        assert df.session_filter.game_filter is not None
        results = list(Device.objects.filter(df.to_q()))
        assert data["dev"] in results

    def test_platform_filter_and_cross_entity(self):
        from games.filters import PlatformFilter
        from games.models import Platform

        data = self._setup_entities()
        # Find platforms with games that are finished
        pf = PlatformFilter.from_json(
            {"game_filter": {"status": {"value": ["f"], "modifier": "INCLUDES"}}}
        )
        results = list(Platform.objects.filter(pf.to_q()))
        assert data["plat"] in results

    def test_session_filter_duration_splits(self):
        from games.filters import SessionFilter
        from games.models import Session

        self._setup_entities()

        # Test duration_total_hours equals 4
        sf_tot = SessionFilter.from_json(
            {"duration_total_hours": {"value": 4, "modifier": "EQUALS"}}
        )
        assert Session.objects.filter(sf_tot.to_q()).count() == 1

        # Test duration_manual_hours equals 1
        sf_man = SessionFilter.from_json(
            {"duration_manual_hours": {"value": 1, "modifier": "EQUALS"}}
        )
        assert Session.objects.filter(sf_man.to_q()).count() == 1

        # Test duration_calculated_hours equals 3
        sf_calc = SessionFilter.from_json(
            {"duration_calculated_hours": {"value": 3, "modifier": "EQUALS"}}
        )
        assert Session.objects.filter(sf_calc.to_q()).count() == 1

    def test_purchase_filter_new_fields(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        self._setup_entities()

        pf = PurchaseFilter.from_json(
            {
                "infinite": {"value": True, "modifier": "EQUALS"},
                "needs_price_update": {"value": False, "modifier": "EQUALS"},
                "converted_currency": {"value": "USD", "modifier": "EQUALS"},
            }
        )
        assert Purchase.objects.filter(pf.to_q()).count() == 1

    def test_game_filter_stats_and_existence(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()

        # purchase_count == 1 (replaces removed has_purchases boolean)
        gf_pur = GameFilter.from_json(
            {"purchase_count": {"value": 1, "modifier": "EQUALS"}}
        )
        assert data["game"] in list(Game.objects.filter(gf_pur.to_q()))
        assert data["game2"] not in list(Game.objects.filter(gf_pur.to_q()))

        # session_count = 1
        gf_cnt = GameFilter.from_json(
            {"session_count": {"value": 1, "modifier": "EQUALS"}}
        )
        assert data["game"] in list(Game.objects.filter(gf_cnt.to_q()))

    def test_game_filter_purchase_count_range(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()

        # game has 1 purchase, game2 has 0
        gf = GameFilter.from_json(
            {"purchase_count": {"value": 1, "modifier": "EQUALS"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

    def test_game_filter_playevent_count(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        gf = GameFilter.from_json(
            {"playevent_count": {"value": 1, "modifier": "EQUALS"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

    def test_game_filter_device(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        gf = GameFilter.from_json(
            {"device": {"value": [data["dev"].id], "modifier": "INCLUDES"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

    def test_game_filter_platform_group(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        gf = GameFilter.from_json(
            {"platform_group": {"value": ["Nintendo"], "modifier": "INCLUDES"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        # both games are on the same Nintendo platform
        assert data["game"] in results
        assert data["game2"] in results

    def test_game_filter_session_emulated(self):
        from games.filters import GameFilter
        from games.models import Game, Session
        import datetime
        from datetime import timedelta

        data = self._setup_entities()
        Session.objects.create(
            game=data["game2"],
            device=data["dev"],
            timestamp_start=datetime.datetime(
                2026, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2026, 6, 2, 12, 30, 0, tzinfo=datetime.timezone.utc
            ),
            duration_manual=timedelta(0),
            emulated=True,
        )
        gf = GameFilter.from_json(
            {"session_emulated": {"value": True, "modifier": "EQUALS"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert data["game2"] in results
        assert data["game"] not in results

    def test_game_filter_purchase_refunded_and_infinite(self):
        from games.filters import GameFilter
        from games.models import Game, Purchase
        import datetime

        data = self._setup_entities()
        # data["pur"] is infinite=True, non-refunded.
        gf_inf = GameFilter.from_json(
            {"purchase_infinite": {"value": True, "modifier": "EQUALS"}}
        )
        assert data["game"] in set(Game.objects.filter(gf_inf.to_q()))
        assert data["game2"] not in set(Game.objects.filter(gf_inf.to_q()))

        # Add a refunded purchase for game2.
        refunded = Purchase.objects.create(
            platform=data["plat"],
            date_purchased=datetime.date(2026, 1, 1),
            date_refunded=datetime.date(2026, 2, 1),
            price=10.0,
            price_currency="USD",
            converted_price=10.0,
            converted_currency="USD",
        )
        refunded.games.add(data["game2"])
        gf_ref = GameFilter.from_json(
            {"purchase_refunded": {"value": True, "modifier": "EQUALS"}}
        )
        results = set(Game.objects.filter(gf_ref.to_q()))
        assert data["game2"] in results
        assert data["game"] not in results

    def test_game_filter_purchase_type_and_ownership(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        # data["pur"] defaults to type=game, ownership_type=digital
        gf = GameFilter.from_json(
            {"purchase_type": {"value": ["game"], "modifier": "INCLUDES"}}
        )
        assert data["game"] in set(Game.objects.filter(gf.to_q()))

        gf = GameFilter.from_json(
            {"purchase_ownership_type": {"value": ["di"], "modifier": "INCLUDES"}}
        )
        assert data["game"] in set(Game.objects.filter(gf.to_q()))

    def test_game_filter_purchase_price_any_and_total(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        # data["pur"] has converted_price=45.00 linked to data["game"]
        gf_any = GameFilter.from_json(
            {
                "purchase_price_any": {
                    "value": 40.0,
                    "value2": 50.0,
                    "modifier": "BETWEEN",
                }
            }
        )
        results = set(Game.objects.filter(gf_any.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

        gf_total = GameFilter.from_json(
            {
                "purchase_price_total": {
                    "value": 40.0,
                    "value2": 50.0,
                    "modifier": "BETWEEN",
                }
            }
        )
        results = set(Game.objects.filter(gf_total.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

    def test_game_filter_playevent_note_includes(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        # data["pe"] has note="Completed 100%" on data["game"]
        gf = GameFilter.from_json(
            {
                "playevent_note": {
                    "value": "Completed",
                    "modifier": "INCLUDES",
                }
            }
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert data["game"] in results
        assert data["game2"] not in results

    def test_game_filter_manual_and_calculated_playtime(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        # data["s1"] has 1 hour manual + 3 hours calculated
        gf_manual = GameFilter.from_json(
            {"manual_playtime_hours": {"value": 1, "modifier": "EQUALS"}}
        )
        assert data["game"] in set(Game.objects.filter(gf_manual.to_q()))

        gf_calc = GameFilter.from_json(
            {"calculated_playtime_hours": {"value": 3, "modifier": "EQUALS"}}
        )
        assert data["game"] in set(Game.objects.filter(gf_calc.to_q()))


class TestDateCriterion:
    def test_equals(self):
        c = DateCriterion(value="2025-06-01", modifier=Modifier.EQUALS)
        assert c.to_q("date_purchased") == Q(date_purchased="2025-06-01")

    def test_not_equals(self):
        c = DateCriterion(value="2025-06-01", modifier=Modifier.NOT_EQUALS)
        assert c.to_q("date_purchased") == ~Q(date_purchased="2025-06-01")

    def test_greater_than(self):
        c = DateCriterion(value="2025-06-01", modifier=Modifier.GREATER_THAN)
        assert c.to_q("date_purchased") == Q(date_purchased__gt="2025-06-01")

    def test_less_than(self):
        c = DateCriterion(value="2025-06-01", modifier=Modifier.LESS_THAN)
        assert c.to_q("date_purchased") == Q(date_purchased__lt="2025-06-01")

    def test_between(self):
        c = DateCriterion(
            value="2025-01-01", value2="2025-12-31", modifier=Modifier.BETWEEN
        )
        assert c.to_q("date_purchased") == Q(
            date_purchased__gte="2025-01-01", date_purchased__lte="2025-12-31"
        )

    def test_between_missing_value2_raises(self):
        c = DateCriterion(value="2025-01-01", modifier=Modifier.BETWEEN)
        with pytest.raises(ValueError, match="BETWEEN requires value2"):
            c.to_q("date_purchased")

    def test_not_between(self):
        c = DateCriterion(
            value="2025-01-01", value2="2025-12-31", modifier=Modifier.NOT_BETWEEN
        )
        assert c.to_q("date_purchased") == Q(date_purchased__lt="2025-01-01") | Q(
            date_purchased__gt="2025-12-31"
        )

    def test_not_between_missing_value2_raises(self):
        c = DateCriterion(value="2025-01-01", modifier=Modifier.NOT_BETWEEN)
        with pytest.raises(ValueError, match="NOT_BETWEEN requires value2"):
            c.to_q("date_purchased")

    def test_is_null(self):
        c = DateCriterion(value="", modifier=Modifier.IS_NULL)
        assert c.to_q("date_refunded") == Q(date_refunded__isnull=True)

    def test_not_null(self):
        c = DateCriterion(value="", modifier=Modifier.NOT_NULL)
        assert c.to_q("date_refunded") == Q(date_refunded__isnull=False)

    def test_unsupported_modifier_raises(self):
        c = DateCriterion(value="2025-06-01", modifier=Modifier.INCLUDES)
        with pytest.raises(ValueError, match="Unsupported modifier"):
            c.to_q("date_purchased")

    def test_round_trip_json(self):
        """Dataclass → dict → dataclass survives unchanged for a full BETWEEN."""
        original = DateCriterion(
            value="2025-06-01", value2="2025-12-31", modifier=Modifier.BETWEEN
        )
        as_dict = original.to_json()
        assert as_dict == {
            "value": "2025-06-01",
            "value2": "2025-12-31",
            "modifier": Modifier.BETWEEN,
        }
        restored = DateCriterion.from_json(
            {
                "value": "2025-06-01",
                "value2": "2025-12-31",
                "modifier": "BETWEEN",
            }
        )
        assert restored == original


class TestPurchaseFilterDates:
    """End-to-end: a PurchaseFilter built from JSON narrows the queryset
    correctly across the two DateCriterion fields and composes with
    BoolCriterion (is_refunded)."""

    def _seed(self):
        import datetime

        from games.models import Platform, Purchase

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        early = Purchase.objects.create(
            platform=platform, date_purchased=datetime.date(2024, 1, 15)
        )
        mid = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 6, 15),
            date_refunded=datetime.date(2024, 7, 1),
        )
        late = Purchase.objects.create(
            platform=platform, date_purchased=datetime.date(2025, 1, 15)
        )
        return {"early": early, "mid": mid, "late": late}

    @pytest.mark.django_db
    def test_date_purchased_between(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "date_purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert results == {seeded["early"], seeded["mid"]}

    @pytest.mark.django_db
    def test_date_purchased_greater_than(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "date_purchased": {
                    "value": "2024-06-15",
                    "modifier": "GREATER_THAN",
                }
            }
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert results == {seeded["late"]}

    @pytest.mark.django_db
    def test_date_refunded_is_null(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {"date_refunded": {"value": "", "modifier": "IS_NULL"}}
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert results == {seeded["early"], seeded["late"]}

    @pytest.mark.django_db
    def test_date_refunded_not_null(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {"date_refunded": {"value": "", "modifier": "NOT_NULL"}}
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert results == {seeded["mid"]}

    @pytest.mark.django_db
    def test_purchased_between_and_refunded_not_null(self):
        """AND-composition: only the mid purchase satisfies both."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        seeded = self._seed()
        pf = PurchaseFilter.from_json(
            {
                "date_purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                },
                "date_refunded": {"value": "", "modifier": "NOT_NULL"},
            }
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert results == {seeded["mid"]}

    @pytest.mark.django_db
    def test_purchase_filter_json_round_trip(self):
        """PurchaseFilter with both DateCriterion fields and is_refunded
        survives a json → object → json round-trip — confirms
        DateCriterion is dispatched correctly by OperatorFilter.from_json
        via the criterion_types lookup."""
        from games.filters import PurchaseFilter

        payload = {
            "date_purchased": {
                "value": "2024-01-01",
                "value2": "2024-12-31",
                "modifier": "BETWEEN",
            },
            "date_refunded": {"value": "", "modifier": "NOT_NULL"},
            "is_refunded": {"value": True, "modifier": "EQUALS"},
        }
        pf = PurchaseFilter.from_json(payload)
        assert isinstance(pf.date_purchased, DateCriterion)
        assert isinstance(pf.date_refunded, DateCriterion)
        # round-trip back out
        out = pf.to_json()
        assert out["date_purchased"]["value"] == "2024-01-01"
        assert out["date_purchased"]["value2"] == "2024-12-31"
        assert out["date_purchased"]["modifier"] == Modifier.BETWEEN
        assert out["date_refunded"]["modifier"] == Modifier.NOT_NULL

    @pytest.mark.django_db
    def test_cross_entity_subfilter_json_round_trip(self):
        """A PurchaseFilter nesting game_filter → playevent_filter survives the
        JSON round-trip the stats links / list views perform (issue #120)."""
        from games.filters import GameFilter, PlayEventFilter, PurchaseFilter

        original = PurchaseFilter(
            game_filter=GameFilter(
                playevent_filter=PlayEventFilter(
                    ended=DateCriterion(
                        value="2024-01-01",
                        value2="2024-12-31",
                        modifier=Modifier.BETWEEN,
                    )
                )
            )
        )
        out = original.to_json()
        # The nested structure must actually be serialized, not dropped.
        assert out["game_filter"]["playevent_filter"]["ended"]["value"] == "2024-01-01"

        restored = PurchaseFilter.from_json(json.loads(json.dumps(out)))
        assert restored.game_filter is not None
        assert restored.game_filter.playevent_filter is not None
        ended = restored.game_filter.playevent_filter.ended
        assert isinstance(ended, DateCriterion)
        assert ended.value2 == "2024-12-31"
        assert str(restored.to_q()) == str(original.to_q())

    def test_empty_subfilter_is_omitted_not_serialized_as_empty(self):
        """An all-None sub-filter contributes no constraint, so to_json omits it
        entirely rather than emitting `{"game_filter": {}}`."""
        from games.filters import GameFilter, PurchaseFilter

        assert PurchaseFilter(game_filter=GameFilter()).to_json() == {}

    def test_flat_finished_field_round_trip(self):
        """The flat `finished` DateCriterion on Game/Purchase filters (#121)
        round-trips through JSON like any other criterion field."""
        from games.filters import GameFilter, PurchaseFilter

        for cls in (GameFilter, PurchaseFilter):
            payload = {
                "finished": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
            obj = cls.from_json(payload)
            assert isinstance(obj.finished, DateCriterion)
            out = obj.to_json()
            assert out == payload


class TestPlayEventFilterDates:
    """End-to-end: a PlayEventFilter built from JSON narrows the queryset
    correctly across the started/ended DateCriterion fields. PlayEvent.started
    and ended are DateField columns, so the criteria apply with bare field
    names (no __date lookup)."""

    def _seed(self):
        import datetime

        from games.models import Game, Platform, PlayEvent

        platform, _ = Platform.objects.get_or_create(name="Test", icon="test")
        game = Game.objects.create(name="Test Game", platform=platform)
        early = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2024, 1, 10),
            ended=datetime.date(2024, 1, 20),
        )
        mid = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2024, 6, 1),
            ended=datetime.date(2024, 6, 30),
        )
        late = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2025, 2, 1),
            ended=datetime.date(2025, 2, 15),
        )
        return {"early": early, "mid": mid, "late": late}

    @pytest.mark.django_db
    def test_ended_between_finds_year(self):
        """'Finished in 2024' expressed as a BETWEEN range over ended."""
        from games.filters import PlayEventFilter
        from games.models import PlayEvent

        seeded = self._seed()
        pf = PlayEventFilter.from_json(
            {
                "ended": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
        )
        results = set(PlayEvent.objects.filter(pf.to_q()))
        assert results == {seeded["early"], seeded["mid"]}

    @pytest.mark.django_db
    def test_started_greater_than(self):
        from games.filters import PlayEventFilter
        from games.models import PlayEvent

        seeded = self._seed()
        pf = PlayEventFilter.from_json(
            {"started": {"value": "2024-06-01", "modifier": "GREATER_THAN"}}
        )
        results = set(PlayEvent.objects.filter(pf.to_q()))
        assert results == {seeded["late"]}

    @pytest.mark.django_db
    def test_ended_less_than(self):
        from games.filters import PlayEventFilter
        from games.models import PlayEvent

        seeded = self._seed()
        pf = PlayEventFilter.from_json(
            {"ended": {"value": "2024-06-30", "modifier": "LESS_THAN"}}
        )
        results = set(PlayEvent.objects.filter(pf.to_q()))
        assert results == {seeded["early"]}

    @pytest.mark.django_db
    def test_playevent_filter_json_round_trip(self):
        """PlayEventFilter started/ended survive json → object → json,
        confirming DateCriterion is dispatched by from_json (not
        StringCriterion)."""
        from games.filters import PlayEventFilter

        payload = {
            "started": {"value": "2024-01-01", "modifier": "GREATER_THAN"},
            "ended": {
                "value": "2024-01-01",
                "value2": "2024-12-31",
                "modifier": "BETWEEN",
            },
        }
        pf = PlayEventFilter.from_json(payload)
        assert isinstance(pf.started, DateCriterion)
        assert isinstance(pf.ended, DateCriterion)
        out = pf.to_json()
        assert out["ended"]["value"] == "2024-01-01"
        assert out["ended"]["value2"] == "2024-12-31"
        assert out["ended"]["modifier"] == Modifier.BETWEEN
        assert out["started"]["modifier"] == Modifier.GREATER_THAN


class TestFinishedFilter:
    """The flat `finished` DateCriterion (#121): a game/purchase is matched when
    the game has a PlayEvent whose `ended` date falls in the range."""

    def _seed(self):
        import datetime

        from games.models import Game, Platform, PlayEvent, Purchase

        pc = Platform.objects.create(name="PC")
        in_range = Game.objects.create(name="Done2024", platform=pc)
        out_range = Game.objects.create(name="Done2023", platform=pc)
        never = Game.objects.create(name="Unfinished", platform=pc)
        PlayEvent.objects.create(game=in_range, ended=datetime.date(2024, 6, 1))
        PlayEvent.objects.create(game=out_range, ended=datetime.date(2023, 6, 1))
        # never: no playevent with an `ended` date
        PlayEvent.objects.create(game=never, started=datetime.date(2024, 1, 1))

        p_in = Purchase.objects.create(
            type=Purchase.GAME, date_purchased=datetime.date(2024, 1, 1)
        )
        p_in.games.set([in_range])
        p_out = Purchase.objects.create(
            type=Purchase.GAME, date_purchased=datetime.date(2023, 1, 1)
        )
        p_out.games.set([out_range])
        return {
            "in_range": in_range,
            "out_range": out_range,
            "never": never,
            "p_in": p_in,
            "p_out": p_out,
        }

    @pytest.mark.django_db
    def test_game_finished_in_range(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._seed()
        gf = GameFilter.where(finished__between=("2024-01-01", "2024-12-31"))
        results = set(Game.objects.filter(gf.to_q()).distinct())
        assert results == {data["in_range"]}

    @pytest.mark.django_db
    def test_purchase_finished_in_range(self):
        from games.filters import PurchaseFilter
        from games.models import Purchase

        data = self._seed()
        pf = PurchaseFilter.where(finished__between=("2024-01-01", "2024-12-31"))
        results = set(Purchase.objects.filter(pf.to_q()).distinct())
        assert results == {data["p_in"]}

    @pytest.mark.django_db
    def test_game_finished_greater_than_min_only(self):
        """A min-only (GREATER_THAN) finished bound maps to playevents__ended__gt."""
        from games.filters import GameFilter
        from games.models import Game

        data = self._seed()
        gf = GameFilter.where(finished__gt="2024-01-01")
        results = set(Game.objects.filter(gf.to_q()).distinct())
        assert results == {data["in_range"]}

    @pytest.mark.django_db
    def test_purchase_finished_less_than_max_only(self):
        """A max-only (LESS_THAN) finished bound maps to playevents__ended__lt."""
        from games.filters import PurchaseFilter
        from games.models import Purchase

        data = self._seed()
        pf = PurchaseFilter.where(finished__lt="2024-01-01")
        results = set(Purchase.objects.filter(pf.to_q()).distinct())
        assert results == {data["p_out"]}

    @pytest.mark.django_db
    def test_game_finished_no_duplicate_rows(self):
        """A game with several finished playevents in range appears once."""
        import datetime

        from games.filters import GameFilter
        from games.models import Game, Platform, PlayEvent

        pc = Platform.objects.create(name="PC")
        game = Game.objects.create(name="Multi", platform=pc)
        PlayEvent.objects.create(game=game, ended=datetime.date(2024, 3, 1))
        PlayEvent.objects.create(game=game, ended=datetime.date(2024, 9, 1))
        gf = GameFilter.where(finished__between=("2024-01-01", "2024-12-31"))
        assert Game.objects.filter(gf.to_q()).distinct().count() == 1
