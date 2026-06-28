"""Tests for the filtering system."""

import dataclasses
import json
from dataclasses import dataclass
from dataclasses import field as dc_field

import pytest
from django.db.models import F, Q
from django.test import SimpleTestCase as TestCase

from common.criteria import (
    AggregateCriterion,
    BoolCriterion,
    ChoiceCriterion,
    ComparisonGranularity,
    DateCriterion,
    FieldComparisonCriterion,
    FilterError,
    FilterField,
    FloatCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    StringCriterion,
    _ScalarCriterion,
    _allowed_comparison_modifiers,
    _comparison_group_for,
    _criterion_class_for,
    _field_comparison_to_q,
    _maybe_group_for,
    bool_isnull_handler,
    bool_nonzero_duration_handler,
    comparable_columns,
    duration_hours_handler,
    filter_from_json,
    search_q,
)
from common.components import FilterBar
from games.filters import (
    DeviceFilter,
    GameFilter,
    PlatformFilter,
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    parse_game_filter,
    parse_purchase_filter,
    parse_session_filter,
)


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
        # Must raise FilterError (catchable user-input error), NOT AssertionError
        # (which vanishes under `python -O` and would re-open the 500 path).
        with pytest.raises(FilterError, match="requires a filter-level"):
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
        # Must raise FilterError (catchable user-input error), NOT AssertionError
        # (which vanishes under `python -O` and would re-open the 500 path).
        with pytest.raises(FilterError, match="requires a filter-level"):
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

    def test_platform_criterion_coerces_ids_to_int(self):
        # platform is a MultiCriterion over the int FK platform_id; string ids
        # from the widget are coerced to int at parse (issue #157).
        gf = GameFilter.from_json(
            {"platform": {"value": ["1", "3"], "modifier": "INCLUDES"}}
        )
        assert gf is not None
        assert gf.platform is not None
        assert gf.platform.value == [1, 3]

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

    def test_game_filter_purchase_price_total(self):
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        # data["pur"] has converted_price=45.00 linked to data["game"]
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
        with pytest.raises(ValueError, match="BETWEEN requires"):
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
        with pytest.raises(ValueError, match="NOT_BETWEEN requires"):
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


class TestFilterErrorBoundary:
    """Issue #131: a parseable-but-invalid ``?filter=`` must raise FilterError
    (a catchable user-input error) at parse time, never escape as an uncaught
    ValueError/AssertionError that 500s the list views. ``filter_from_json``
    validates eagerly by building the whole Q once, so every nested criterion
    precondition is exercised."""

    def test_bad_modifier_enum(self):
        bad = json.dumps({"name": {"modifier": "BOGUS", "value": "x"}})
        with pytest.raises(FilterError, match="Unknown filter modifier"):
            parse_game_filter(bad)

    def test_bad_relation_match(self):
        bad = json.dumps({"session_filter": {"match": "MOST", "note": {"value": "x"}}})
        with pytest.raises(FilterError, match="Unknown relation match"):
            parse_game_filter(bad)

    def test_between_without_value2_int(self):
        bad = json.dumps({"year_released": {"modifier": "BETWEEN", "value": 2000}})
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_game_filter(bad)

    def test_between_without_value2_date(self):
        bad = json.dumps(
            {"timestamp_start": {"modifier": "BETWEEN", "value": "2024-01-01"}}
        )
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_session_filter(bad)

    def test_between_without_value2_duration(self):
        bad = json.dumps({"duration_total_hours": {"modifier": "BETWEEN", "value": 1}})
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_session_filter(bad)

    def test_unsupported_modifier_for_bool(self):
        bad = json.dumps({"mastered": {"modifier": "GREATER_THAN", "value": True}})
        with pytest.raises(FilterError, match="for bool field"):
            parse_game_filter(bad)

    def test_unsupported_modifier_for_string(self):
        bad = json.dumps({"name": {"modifier": "BETWEEN", "value": "a"}})
        with pytest.raises(FilterError, match="for string field"):
            parse_game_filter(bad)

    def test_m2m_only_modifier_on_generic_layer(self):
        """INCLUDES_ALL on a non-M2M-routed field hits the generic _SetCriterion
        path: now FilterError (formerly a bare AssertionError)."""
        bad = json.dumps({"platform_group": {"modifier": "INCLUDES_ALL", "value": [1]}})
        with pytest.raises(FilterError, match="requires a filter-level"):
            parse_game_filter(bad)

    def test_malformed_json(self):
        with pytest.raises(FilterError, match="not valid JSON"):
            parse_game_filter("{not json")

    def test_empty_returns_none(self):
        assert parse_game_filter("") is None

    def test_json_null_returns_none(self):
        assert parse_game_filter("null") is None

    def test_invalid_criterion_nested_in_operator_raises(self):
        """An invalid criterion buried inside AND must still raise — proves the
        eager validation walks sub-filters, not just the top level."""
        bad = json.dumps(
            {"AND": [{"year_released": {"modifier": "BETWEEN", "value": 2000}}]}
        )
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_game_filter(bad)

    def test_invalid_criterion_nested_in_relation_raises(self):
        """An invalid criterion inside a cross-entity sub-filter must raise —
        relation_to_q exercises sub.to_q() during the eager build."""
        bad = json.dumps(
            {
                "session_filter": {
                    "duration_total_hours": {"modifier": "BETWEEN", "value": 1}
                }
            }
        )
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_game_filter(bad)

    def test_not_between_without_value2(self):
        bad = json.dumps({"year_released": {"modifier": "NOT_BETWEEN", "value": 2000}})
        with pytest.raises(FilterError, match="NOT_BETWEEN requires"):
            parse_game_filter(bad)

    def test_between_without_value2_float(self):
        bad = json.dumps({"price": {"modifier": "BETWEEN", "value": 1.0}})
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_purchase_filter(bad)

    def test_between_with_null_value(self):
        """value explicitly null (not just value2) must be a clean FilterError,
        not a TypeError from min(None, x)."""
        bad = json.dumps(
            {"year_released": {"modifier": "BETWEEN", "value": None, "value2": 2000}}
        )
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_game_filter(bad)

    def test_non_numeric_duration_value(self):
        """A non-numeric duration value makes timedelta() raise TypeError during
        the eager build; the boundary reclassifies it to FilterError."""
        bad = json.dumps(
            {"duration_total_hours": {"modifier": "GREATER_THAN", "value": "x"}}
        )
        with pytest.raises(FilterError):
            parse_session_filter(bad)

    def test_non_integer_games_id(self):
        """A hand-edited non-integer game id must raise FilterError, not let a
        bare ValueError from int() escape the boundary."""
        bad = json.dumps({"games": {"modifier": "INCLUDES", "value": ["not-a-number"]}})
        with pytest.raises(FilterError, match="games filter values must be integers"):
            parse_purchase_filter(bad)

    def test_invalid_criterion_nested_in_all_match_relation(self):
        """ALL match drives a distinct relation_to_q branch (~sub.to_q()); an
        invalid nested criterion under it must still raise."""
        bad = json.dumps(
            {
                "session_filter": {
                    "match": "ALL",
                    "duration_total_hours": {"modifier": "BETWEEN", "value": 1},
                }
            }
        )
        with pytest.raises(FilterError, match="BETWEEN requires"):
            parse_game_filter(bad)

    def test_non_object_json_returns_none(self):
        """Valid JSON that isn't an object carries no filter → None, not raise."""
        assert parse_game_filter("5") is None
        assert parse_game_filter("[1, 2]") is None

    def test_valid_filter_still_parses(self):
        good = json.dumps({"name": {"modifier": "INCLUDES", "value": "halo"}})
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_valid_nested_relation_filter_parses_and_reusable(self):
        """A valid cross-entity sub-filter survives eager validation and its
        to_q() is reusable afterward (guards game.py's session_filter path)."""
        good = json.dumps(
            {"session_filter": {"note": {"modifier": "INCLUDES", "value": "boss"}}}
        )
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise
        assert result.session_filter is not None
        result.session_filter.to_q()  # the exact second call game.py makes


# Wrong-typed value per coercible criterion class (issue #157). Criteria whose
# value is a free string against a char column (String/Choice) or a bool never
# 500 at the DB, so they are not in this map and are skipped by the matrix below.
_WRONG_VALUE_BY_CRITERION = {
    IntCriterion: "not-a-number",
    FloatCriterion: "not-a-number",
    AggregateCriterion: "not-a-number",
    DateCriterion: "garbage",
    MultiCriterion: ["not-an-int"],
}

_ALL_FILTERS = [
    GameFilter,
    SessionFilter,
    PurchaseFilter,
    DeviceFilter,
    PlatformFilter,
    PlayEventFilter,
]


def _coercible_field_cases():
    """Every (filter, criterion field) whose value type the DB would reject at
    query execution — derived from the criterion class via _criterion_class_for so
    the matrix grows automatically as new fields/filters are added (e.g. #168)."""
    cases = []
    for filter_cls in _ALL_FILTERS:
        for dataclass_field in dataclasses.fields(filter_cls):
            criterion_cls = _criterion_class_for(filter_cls, dataclass_field.name)
            if criterion_cls in _WRONG_VALUE_BY_CRITERION:
                cases.append((filter_cls, dataclass_field.name, criterion_cls))
    return cases


class TestValueTypeBoundaryMatrix:
    """Issue #157: a hand-edited ``?filter=`` carrying a value of the wrong type
    for its column must raise ``FilterError`` at parse (caught by the web/API
    boundary) rather than escaping to a query-execution 500. Covers every
    coercible criterion field across every filter, so the boundary promise holds
    as fields are added."""

    @pytest.mark.parametrize(
        "filter_cls,field_name,criterion_cls",
        _coercible_field_cases(),
        ids=lambda value: getattr(value, "__name__", value),
    )
    def test_wrong_typed_value_raises_filter_error(
        self, filter_cls, field_name, criterion_cls
    ):
        bad_value = _WRONG_VALUE_BY_CRITERION[criterion_cls]
        modifier = "INCLUDES" if criterion_cls is MultiCriterion else "EQUALS"
        payload = json.dumps({field_name: {"value": bad_value, "modifier": modifier}})
        with pytest.raises(FilterError):
            filter_from_json(filter_cls, payload)

    def test_matrix_is_non_empty(self):
        # Guard against the derivation silently yielding nothing (e.g. annotation
        # format change), which would make the parametrized test vacuously pass.
        assert _coercible_field_cases()


class TestValueTypeBoundaryEdges:
    """Coercion paths the EQUALS/value-only matrix doesn't exercise (issue #157
    review): value2/BETWEEN bounds, the excludes channel, an omitted date value,
    silent-accept inputs (bool/non-integral float), nested criteria, and the
    id-less set element. Each must raise FilterError at parse, not 500 at eval."""

    def test_bad_value2_between_bound_raises(self):
        # The upper BETWEEN bound goes through a separate coercion-loop iteration.
        bad = json.dumps(
            {"year_released": {"modifier": "BETWEEN", "value": 2000, "value2": "x"}}
        )
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_bad_excludes_element_raises(self):
        # The excludes channel is coerced too, not just the include value list.
        bad = json.dumps({"platform": {"modifier": "INCLUDES", "excludes": ["xyz"]}})
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_omitted_date_value_with_value_using_modifier_raises(self):
        # Finding #157: DateCriterion's "" default must still be rejected when the
        # value key is absent (else Q(field='') 500s at eval, bypassing the
        # boundary with a non-ValueError ValidationError).
        bad = json.dumps({"created_at": {"modifier": "EQUALS"}})
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_bool_value_rejected_for_int_field(self):
        # int(True) == 1 would silently accept wrong-typed input; reject instead.
        bad = json.dumps({"year_released": {"modifier": "EQUALS", "value": True}})
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_non_integral_float_rejected_for_int_field(self):
        # int(3.9) == 3 would silently truncate; reject instead.
        bad = json.dumps({"year_released": {"modifier": "EQUALS", "value": 3.9}})
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_integral_float_accepted_for_int_field(self):
        good = json.dumps({"year_released": {"modifier": "EQUALS", "value": 2000.0}})
        result = parse_game_filter(good)
        assert result is not None and result.year_released is not None
        assert result.year_released.value == 2000

    def test_decimal_string_accepted_for_float_field(self):
        good = json.dumps({"price": {"modifier": "EQUALS", "value": "3.5"}})
        result = parse_purchase_filter(good)
        assert result is not None and result.price is not None
        assert result.price.value == 3.5

    def test_bad_value_nested_in_operator_raises(self):
        # The fix lives in criterion from_json, so it must hold under AND/OR/NOT.
        bad = json.dumps(
            {"AND": [{"year_released": {"modifier": "EQUALS", "value": "nope"}}]}
        )
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_bad_value_nested_in_relation_subfilter_raises(self):
        bad = json.dumps(
            {"session_filter": {"created_at": {"modifier": "EQUALS", "value": "nope"}}}
        )
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_set_element_dict_without_id_raises(self):
        # A hand-edited {label-only} element must be a clean FilterError, not a
        # boundary-bypassing KeyError.
        bad = json.dumps(
            {"platform": {"modifier": "INCLUDES", "value": [{"label": "PC"}]}}
        )
        with pytest.raises(FilterError):
            parse_game_filter(bad)

    def test_scalar_subclass_without_coercer_is_rejected_at_definition(self):
        # _ScalarCriterion enforces that every scalar criterion declares a _coerce,
        # so a future field type can't silently revert to the pre-#157 500 vector.
        with pytest.raises(TypeError, match="_coerce"):

            @dataclass
            class _NoCoercer(_ScalarCriterion):
                value: int = 0


class TestFieldComparisonCriterion:
    """Tests for FieldComparisonCriterion and _field_comparison_to_q."""

    # ── _field_comparison_to_q helper ────────────────────────────────────────

    def test_helper_equals(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.EQUALS
        ) == Q(date_refunded=F("date_purchased"))

    def test_helper_not_equals(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.NOT_EQUALS
        ) == ~Q(date_refunded=F("date_purchased"))

    def test_helper_greater_than(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.GREATER_THAN
        ) == Q(date_refunded__gt=F("date_purchased"))

    def test_helper_less_than(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.LESS_THAN
        ) == Q(date_refunded__lt=F("date_purchased"))

    def test_helper_includes(self):
        assert _field_comparison_to_q("name", "sort_name", Modifier.INCLUDES) == Q(
            name__icontains=F("sort_name")
        )

    def test_helper_excludes(self):
        assert _field_comparison_to_q("name", "sort_name", Modifier.EXCLUDES) == ~Q(
            name__icontains=F("sort_name")
        )

    def test_helper_greater_than_or_equal(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.GREATER_THAN_OR_EQUAL
        ) == Q(date_refunded__gte=F("date_purchased"))

    def test_helper_less_than_or_equal(self):
        assert _field_comparison_to_q(
            "date_refunded", "date_purchased", Modifier.LESS_THAN_OR_EQUAL
        ) == Q(date_refunded__lte=F("date_purchased"))

    def test_helper_unsupported_modifier_raises(self):
        with pytest.raises(FilterError, match="Unsupported modifier"):
            _field_comparison_to_q("date_refunded", "date_purchased", Modifier.BETWEEN)

    # ── date-granular comparison (granularity="date") ────────────────────────

    def test_helper_date_granular_equals(self):
        from django.db.models.functions import TruncDate

        assert _field_comparison_to_q(
            "timestamp_start", "timestamp_end", Modifier.EQUALS, "date"
        ) == Q(timestamp_start__date=TruncDate(F("timestamp_end")))

    def test_helper_date_granular_gte(self):
        from django.db.models.functions import TruncDate

        assert _field_comparison_to_q(
            "timestamp_start",
            "timestamp_end",
            Modifier.GREATER_THAN_OR_EQUAL,
            "date",
        ) == Q(timestamp_start__date__gte=TruncDate(F("timestamp_end")))

    def test_helper_date_granular_not_equals(self):
        from django.db.models.functions import TruncDate

        assert _field_comparison_to_q(
            "timestamp_start", "timestamp_end", Modifier.NOT_EQUALS, "date"
        ) == ~Q(timestamp_start__date=TruncDate(F("timestamp_end")))

    def test_to_q_passes_granularity(self):
        from django.db.models.functions import TruncDate

        criterion = FieldComparisonCriterion(
            left="timestamp_start",
            right="timestamp_end",
            modifier=Modifier.LESS_THAN_OR_EQUAL,
            granularity="date",
        )
        assert criterion.to_q() == Q(
            timestamp_start__date__lte=TruncDate(F("timestamp_end"))
        )

    def test_to_json_emits_granularity_only_when_date(self):
        raw = FieldComparisonCriterion(left="a", right="b")
        assert "granularity" not in raw.to_json()
        dated = FieldComparisonCriterion(
            left="timestamp_start", right="timestamp_end", granularity="date"
        )
        assert dated.to_json()["granularity"] == "date"

    def test_roundtrip_granularity_date(self):
        criterion = FieldComparisonCriterion(
            left="timestamp_start",
            right="timestamp_end",
            modifier=Modifier.EQUALS,
            granularity="date",
        )
        assert FieldComparisonCriterion.from_json(criterion.to_json()) == criterion

    def test_from_json_defaults_granularity_to_raw(self):
        restored = FieldComparisonCriterion.from_json(
            {"left": "a", "right": "b", "modifier": "EQUALS"}
        )
        assert restored is not None
        assert restored.granularity == "raw"

    def test_from_json_rejects_unknown_granularity(self):
        with pytest.raises(FilterError, match="unknown granularity"):
            FieldComparisonCriterion.from_json(
                {
                    "left": "a",
                    "right": "b",
                    "modifier": "EQUALS",
                    "granularity": "month",
                }
            )

    def test_helper_date_granular_strict_ordering(self):
        from django.db.models.functions import TruncDate

        assert _field_comparison_to_q(
            "timestamp_start", "timestamp_end", Modifier.GREATER_THAN, "date"
        ) == Q(timestamp_start__date__gt=TruncDate(F("timestamp_end")))
        assert _field_comparison_to_q(
            "timestamp_start", "timestamp_end", Modifier.LESS_THAN, "date"
        ) == Q(timestamp_start__date__lt=TruncDate(F("timestamp_end")))

    # ── FieldComparisonCriterion.to_q ────────────────────────────────────────

    def test_to_q_delegates_to_helper(self):
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        assert criterion.to_q() == Q(a__lt=F("b"))

    def test_to_q_ignores_field_name_argument(self):
        """field_name is ignored; operands are self-contained in left/right."""
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        assert criterion.to_q("ignored_field") == Q(a__lt=F("b"))

    # ── JSON roundtrip ───────────────────────────────────────────────────────

    def test_to_json_emits_left_right_and_modifier(self):
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        assert criterion.to_json() == {
            "left": "a",
            "right": "b",
            "modifier": Modifier.LESS_THAN,
        }

    def test_to_json_always_emits_left_right_even_when_empty(self):
        """left/right default to '' — to_json must force-emit them even at default."""
        criterion = FieldComparisonCriterion()
        serialized = criterion.to_json()
        assert "left" in serialized
        assert "right" in serialized
        assert serialized["left"] == ""
        assert serialized["right"] == ""

    def test_roundtrip_less_than(self):
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        assert FieldComparisonCriterion.from_json(criterion.to_json()) == criterion

    def test_roundtrip_default_equals_modifier(self):
        """Default modifier (EQUALS) must also survive a roundtrip."""
        criterion = FieldComparisonCriterion(left="x", right="y")
        restored = FieldComparisonCriterion.from_json(criterion.to_json())
        assert restored == criterion
        assert restored.modifier == Modifier.EQUALS

    # ── Modifier.for_field_comparisons ───────────────────────────────────────

    def test_for_ordered_field_comparisons(self):
        assert Modifier.for_ordered_field_comparisons() == [
            Modifier.EQUALS,
            Modifier.NOT_EQUALS,
            Modifier.GREATER_THAN,
            Modifier.LESS_THAN,
            Modifier.GREATER_THAN_OR_EQUAL,
            Modifier.LESS_THAN_OR_EQUAL,
        ]

    def test_for_field_comparisons(self):
        """Full set = ordered subset plus string containment (INCLUDES/EXCLUDES)."""
        assert Modifier.for_field_comparisons() == [
            Modifier.EQUALS,
            Modifier.NOT_EQUALS,
            Modifier.GREATER_THAN,
            Modifier.LESS_THAN,
            Modifier.GREATER_THAN_OR_EQUAL,
            Modifier.LESS_THAN_OR_EQUAL,
            Modifier.INCLUDES,
            Modifier.EXCLUDES,
        ]


class TestComparisonGroupResolver:
    """Tests for _comparison_group_for and _allowed_comparison_modifiers."""

    # ── concrete field → group ───────────────────────────────────────────────

    def test_date_field(self):
        from games.models import Purchase

        assert _comparison_group_for(Purchase, "date_purchased") == "date"

    def test_datetime_field(self):
        from games.models import Session

        assert _comparison_group_for(Session, "timestamp_start") == "datetime"

    def test_generated_field_duration(self):
        """GeneratedField (duration_total) resolves via output_field to 'duration'."""
        from games.models import Session

        assert _comparison_group_for(Session, "duration_total") == "duration"

    def test_generated_field_number(self):
        """GeneratedField (days_to_finish) resolves via output_field to 'number'."""
        from games.models import PlayEvent

        assert _comparison_group_for(PlayEvent, "days_to_finish") == "number"

    def test_float_field(self):
        from games.models import Purchase

        assert _comparison_group_for(Purchase, "price") == "number"

    def test_integer_field(self):
        from games.models import Game

        assert _comparison_group_for(Game, "year_released") == "number"

    def test_char_field(self):
        from games.models import Game

        assert _comparison_group_for(Game, "name") == "string"

    def test_bool_field(self):
        from games.models import Game

        assert _comparison_group_for(Game, "mastered") == "bool"

    def test_slug_field_is_string(self):
        """SlugField.get_internal_type() is "SlugField" (not "CharField"); it must
        still resolve to the string group so e.g. Platform.icon is comparable."""
        from games.models import Platform

        assert _comparison_group_for(Platform, "icon") == "string"

    # ── excluded columns ────────────────────────────────────────────────────

    def test_fk_relation_raises(self):
        from games.models import Session

        with pytest.raises(FilterError):
            _comparison_group_for(Session, "game")

    def test_m2m_relation_raises(self):
        from games.models import Purchase

        with pytest.raises(FilterError):
            _comparison_group_for(Purchase, "games")

    def test_auto_pk_raises(self):
        """AutoField / BigAutoField has no comparison group."""
        from games.models import Game

        with pytest.raises(FilterError):
            _comparison_group_for(Game, "id")

    def test_nonexistent_column_raises(self):
        from games.models import Game

        with pytest.raises(FilterError):
            _comparison_group_for(Game, "nonexistent")

    # ── _allowed_comparison_modifiers ────────────────────────────────────────

    def test_bool_group_is_equality_only(self):
        assert _allowed_comparison_modifiers("bool") == [
            Modifier.EQUALS,
            Modifier.NOT_EQUALS,
        ]

    def test_date_group_is_ordered(self):
        assert (
            _allowed_comparison_modifiers("date")
            == Modifier.for_ordered_field_comparisons()
        )

    def test_number_group_excludes_containment(self):
        allowed = _allowed_comparison_modifiers("number")
        assert allowed == Modifier.for_ordered_field_comparisons()
        assert Modifier.INCLUDES not in allowed
        assert Modifier.EXCLUDES not in allowed

    def test_string_group_adds_containment(self):
        allowed = _allowed_comparison_modifiers("string")
        assert allowed == Modifier.for_field_comparisons()
        assert Modifier.INCLUDES in allowed
        assert Modifier.EXCLUDES in allowed
        # string keeps lexicographic ordering too
        assert Modifier.GREATER_THAN in allowed
        assert Modifier.LESS_THAN in allowed


class TestMaybeGroupFor:
    """_maybe_group_for mirrors _comparison_group_for but returns None instead of
    raising for non-comparable columns."""

    # ── comparable columns → group (parity with _comparison_group_for) ───────

    def test_date_field(self):
        from games.models import Purchase

        assert _maybe_group_for(Purchase, "date_purchased") == "date"

    def test_datetime_field(self):
        from games.models import Session

        assert _maybe_group_for(Session, "timestamp_start") == "datetime"

    def test_generated_field_duration(self):
        from games.models import Session

        assert _maybe_group_for(Session, "duration_total") == "duration"

    def test_integer_field(self):
        from games.models import Game

        assert _maybe_group_for(Game, "year_released") == "number"

    def test_char_field(self):
        from games.models import Game

        assert _maybe_group_for(Game, "name") == "string"

    def test_bool_field(self):
        from games.models import Game

        assert _maybe_group_for(Game, "mastered") == "bool"

    # ── non-comparable columns → None (where _comparison_group_for raises) ───

    def test_nonexistent_column_returns_none(self):
        from games.models import Game

        assert _maybe_group_for(Game, "nonexistent") is None

    def test_fk_relation_returns_none(self):
        from games.models import Game

        assert _maybe_group_for(Game, "platform") is None

    def test_m2m_relation_returns_none(self):
        from games.models import Purchase

        assert _maybe_group_for(Purchase, "games") is None

    def test_auto_pk_returns_none(self):
        from games.models import Game

        assert _maybe_group_for(Game, "id") is None

    def test_contract_parity_with_raising_wrapper(self):
        """Every column that makes _comparison_group_for raise must return None
        from _maybe_group_for, and vice-versa for comparable ones."""
        from games.models import Game

        for column in ("nonexistent", "platform", "id"):
            assert _maybe_group_for(Game, column) is None
            with pytest.raises(FilterError):
                _comparison_group_for(Game, column)
        for column in ("name", "year_released", "mastered"):
            assert _maybe_group_for(Game, column) is not None
            assert _comparison_group_for(Game, column) == _maybe_group_for(Game, column)


class TestComparableColumns:
    """comparable_columns enumerates a model's comparable columns, labelled and
    grouped, sorted by label."""

    def _by_value(self, model):
        return {entry["value"]: entry for entry in comparable_columns(model)}

    def test_entries_have_value_label_group_keys(self):
        from games.models import Game

        for entry in comparable_columns(Game):
            assert set(entry.keys()) == {"value", "label", "group"}

    def test_known_game_columns(self):
        from games.models import Game

        columns = self._by_value(Game)
        assert columns["name"]["group"] == "string"
        assert columns["year_released"]["group"] == "number"
        assert columns["mastered"]["group"] == "bool"

    def test_session_datetime_column(self):
        from games.models import Session

        columns = self._by_value(Session)
        assert columns["timestamp_end"]["group"] == "datetime"
        assert columns["timestamp_start"]["group"] == "datetime"

    def test_purchase_date_columns(self):
        from games.models import Purchase

        columns = self._by_value(Purchase)
        assert columns["date_purchased"]["group"] == "date"
        assert columns["date_refunded"]["group"] == "date"

    def test_relations_and_pk_absent(self):
        from games.models import Game, Purchase

        game_columns = self._by_value(Game)
        assert "platform" not in game_columns
        assert "id" not in game_columns
        assert "games" not in self._by_value(Purchase)

    def test_labels_are_title_cased_verbose_names(self):
        from games.models import Game

        columns = self._by_value(Game)
        assert columns["name"]["label"] == "Name"
        assert columns["year_released"]["label"] == "Year Released"

    def test_sorted_by_label_case_insensitive(self):
        from games.models import Session

        labels = [entry["label"] for entry in comparable_columns(Session)]
        assert labels == sorted(labels, key=str.lower)


# ── T3 — OperatorFilter field_comparisons wiring ─────────────────────────────


@dataclass
class _PurchaseStub(OperatorFilter):
    AND: list["_PurchaseStub"] = dc_field(default_factory=list)
    OR: list["_PurchaseStub"] = dc_field(default_factory=list)
    NOT: list["_PurchaseStub"] = dc_field(default_factory=list)

    def _comparison_model(self):
        from games.models import Purchase

        return Purchase


@dataclass
class _NoModelStub(OperatorFilter):
    """Stub that does NOT override _comparison_model — base returns None."""

    AND: list["_NoModelStub"] = dc_field(default_factory=list)
    OR: list["_NoModelStub"] = dc_field(default_factory=list)
    NOT: list["_NoModelStub"] = dc_field(default_factory=list)


@dataclass
class _SessionStub(OperatorFilter):
    AND: list["_SessionStub"] = dc_field(default_factory=list)
    OR: list["_SessionStub"] = dc_field(default_factory=list)
    NOT: list["_SessionStub"] = dc_field(default_factory=list)

    def _comparison_model(self):
        from games.models import Session

        return Session


@pytest.mark.django_db
class TestFieldComparisonWiring:
    # 1. Happy path — to_q produces the expected Q

    def test_happy_path_to_q(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        assert stub.to_q() == Q(date_refunded__lt=F("date_purchased"))

    # 2. Serialization roundtrip

    def test_to_json_includes_field_comparisons(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        serialized = stub.to_json()
        assert "field_comparisons" in serialized
        assert serialized["field_comparisons"] == [
            {
                "left": "date_refunded",
                "right": "date_purchased",
                "modifier": Modifier.LESS_THAN,
            }
        ]

    def test_empty_field_comparisons_omitted_from_json(self):
        stub = _PurchaseStub()
        assert "field_comparisons" not in stub.to_json()

    # granularity="date" — valid on datetime operands, rejected elsewhere

    def test_date_granularity_on_datetime_ok(self):
        from django.db.models.functions import TruncDate

        stub = _SessionStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start",
                    right="timestamp_end",
                    modifier=Modifier.LESS_THAN_OR_EQUAL,
                    granularity="date",
                )
            ]
        )
        assert stub.to_q() == Q(
            timestamp_start__date__lte=TruncDate(F("timestamp_end"))
        )

    def test_date_granularity_on_non_datetime_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.EQUALS,
                    granularity="date",
                )
            ]
        )
        with pytest.raises(FilterError, match="datetime operands"):
            stub.to_q()

    def test_includes_on_datetime_rejected_before_granularity(self):
        """INCLUDES/EXCLUDES (string-only) and date-granular (datetime-only) are
        mutually exclusive by group: an INCLUDES on a datetime pair is rejected by
        the modifier gate, so the nonsense __date__icontains query is unreachable."""
        stub = _SessionStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start",
                    right="timestamp_end",
                    modifier=Modifier.INCLUDES,
                    granularity="date",
                )
            ]
        )
        with pytest.raises(FilterError, match="not allowed"):
            stub.to_q()

    def test_roundtrip_restores_equal_object(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        restored = _PurchaseStub.from_json(stub.to_json())
        assert restored == stub

    # 3. Validation → FilterError via to_q()

    def test_unknown_column_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="nonexistent",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_cross_group_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="price",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_disallowed_modifier_for_bool_group_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="infinite",
                    right="needs_price_update",
                    modifier=Modifier.GREATER_THAN,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_self_compare_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_purchased",
                    right="date_purchased",
                    modifier=Modifier.EQUALS,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_includes_on_string_group_ok(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="price_currency",
                    right="converted_currency",
                    modifier=Modifier.INCLUDES,
                )
            ]
        )
        assert stub.to_q() == Q(price_currency__icontains=F("converted_currency"))

    def test_includes_on_number_group_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="price",
                    right="converted_price",
                    modifier=Modifier.INCLUDES,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_relation_column_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="games",
                    right="date_purchased",
                    modifier=Modifier.EQUALS,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    def test_relation_fk_column_raises(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="platform",
                    right="date_purchased",
                    modifier=Modifier.EQUALS,
                )
            ]
        )
        with pytest.raises(FilterError):
            stub.to_q()

    # 4. No model — base default returns None → FilterError

    def test_no_model_raises(self):
        stub = _NoModelStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        with pytest.raises(FilterError, match="does not support field comparisons"):
            stub.to_q()

    # 5. Integration — serialize to JSON, parse back, eager to_q validation

    def test_integration_valid_roundtrip_via_json(self):
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        json_data = stub.to_json()
        restored = _PurchaseStub.from_json(json_data)
        assert restored is not None
        assert restored.to_q() == Q(date_refunded__lt=F("date_purchased"))

    def test_integration_bad_column_raises_on_to_q(self):
        bad_json = {
            "field_comparisons": [
                {
                    "left": "nonexistent",
                    "right": "date_purchased",
                    "modifier": "LESS_THAN",
                }
            ]
        }
        parsed = _PurchaseStub.from_json(bad_json)
        assert parsed is not None
        with pytest.raises(FilterError):
            parsed.to_q()

    # 6. Malformed field_comparisons entries — Finding 1 (fail-open robustness)

    def test_null_entry_in_field_comparisons_raises(self):
        """[null] in field_comparisons raises FilterError instead of silently dropping."""
        with pytest.raises(FilterError):
            _PurchaseStub.from_json({"field_comparisons": [None]})

    def test_non_dict_string_entry_raises(self):
        """A string entry in field_comparisons raises FilterError."""
        with pytest.raises(FilterError):
            _PurchaseStub.from_json({"field_comparisons": ["oops"]})

    def test_single_dict_not_wrapped_parses_as_one_comparison(self):
        """A single dict (not in a list) is wrapped to a one-entry list."""
        data = {
            "field_comparisons": {
                "left": "date_refunded",
                "right": "date_purchased",
                "modifier": "LESS_THAN",
            }
        }
        stub = _PurchaseStub.from_json(data)
        assert stub is not None
        assert len(stub.field_comparisons) == 1
        assert stub.field_comparisons[0].left == "date_refunded"
        assert stub.field_comparisons[0].right == "date_purchased"

    def test_null_field_comparisons_key_parses_to_empty_list(self):
        """field_comparisons: null → empty list (not an error)."""
        stub = _PurchaseStub.from_json({"field_comparisons": None})
        assert stub is not None
        assert stub.field_comparisons == []

    # 7. Inherited value field shadowed — Finding 3

    def test_stray_value_key_is_not_stored_and_not_re_emitted(self):
        """A stray 'value' key in JSON is ignored: not stored and not in to_json()."""
        instance = FieldComparisonCriterion.from_json(
            {"left": "a", "right": "b", "modifier": "EQUALS", "value": "x"}
        )
        assert instance is not None
        assert "value" not in instance.to_json()

    def test_constructing_with_value_is_rejected(self):
        """init=False means FieldComparisonCriterion(value=...) raises TypeError."""
        with pytest.raises(TypeError):
            FieldComparisonCriterion(value="x")  # type: ignore[call-arg]


# ── T4 — per-filter _comparison_model overrides ───────────────────────────────


class TestFilterComparisonModels:
    """T4: each real filter overrides _comparison_model() to return its model."""

    def test_all_six_filters_return_their_model(self):
        from games.filters import (
            DeviceFilter,
            GameFilter,
            PlayEventFilter,
            PlatformFilter,
            PurchaseFilter,
            SessionFilter,
        )
        from games.models import Device, Game, PlayEvent, Platform, Purchase, Session

        assert GameFilter()._comparison_model() is Game
        assert SessionFilter()._comparison_model() is Session
        assert PurchaseFilter()._comparison_model() is Purchase
        assert DeviceFilter()._comparison_model() is Device
        assert PlatformFilter()._comparison_model() is Platform
        assert PlayEventFilter()._comparison_model() is PlayEvent

    @pytest.mark.django_db
    def test_purchase_filter_happy_path_to_q(self):
        from games.filters import PurchaseFilter

        pf = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        assert pf.to_q() == Q(date_refunded__lt=F("date_purchased"))

    @pytest.mark.django_db
    def test_purchase_filter_json_parse_roundtrip(self):
        from common.criteria import filter_to_json
        from games.filters import PurchaseFilter, parse_purchase_filter

        pf = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        parsed = parse_purchase_filter(filter_to_json(pf))
        assert parsed is not None
        assert len(parsed.field_comparisons) == 1
        assert parsed.field_comparisons[0].left == "date_refunded"
        assert parsed.field_comparisons[0].right == "date_purchased"
        assert parsed.field_comparisons[0].modifier == Modifier.LESS_THAN
        assert parsed.to_q() == Q(date_refunded__lt=F("date_purchased"))

    @pytest.mark.django_db
    def test_cross_group_pair_raises_filter_error_via_parse(self):
        from games.filters import parse_purchase_filter

        bad = json.dumps(
            {
                "field_comparisons": [
                    {
                        "left": "date_refunded",
                        "right": "price",
                        "modifier": "LESS_THAN",
                    }
                ]
            }
        )
        with pytest.raises(FilterError):
            parse_purchase_filter(bad)

    @pytest.mark.django_db
    def test_session_filter_comparison_resolves(self):
        from games.filters import SessionFilter

        sf = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_end",
                    right="timestamp_start",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        assert sf.to_q() == Q(timestamp_end__lt=F("timestamp_start"))


# ── T5 — end-to-end DB + integration tests ───────────────────────────────────


@pytest.mark.django_db
class TestFieldComparisonEndToEnd:
    """T5: DB-backed field-comparison tests through the full parse → to_q → filter path.

    Covers: NULL-operand exclusion, raw-datetime comparison (same calendar day),
    GeneratedField as a comparison operand, and JSON round-trip through the parser.
    """

    def _make_platform_and_game(self):
        """Create a minimal Platform + Game for Session-based tests."""
        from games.models import Game, Platform

        platform, _ = Platform.objects.get_or_create(
            name="FieldCmpTest", icon="fieldcmptest"
        )
        game, _ = Game.objects.get_or_create(
            name="FieldCmpGame", defaults={"platform": platform}
        )
        return platform, game

    def test_purchase_refund_before_purchase(self):
        """date_refunded < date_purchased finds only A.

        B (refund after purchase) and C (NULL date_refunded) are excluded,
        proving both the comparison and NULL-operand exclusion semantics.
        """
        import datetime

        from games.filters import PurchaseFilter
        from games.models import Platform, Purchase

        platform, _ = Platform.objects.get_or_create(
            name="FieldCmpTest", icon="fieldcmptest"
        )

        # A: refund BEFORE purchase — the data-error case; must be returned
        purchase_a = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 3, 1),
            date_refunded=datetime.date(2024, 1, 1),
        )
        # B: refund AFTER purchase — normal order; must NOT be returned
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            date_refunded=datetime.date(2024, 3, 1),
        )
        # C: no refund (NULL operand) — SQL comparison against NULL yields no match
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
        )

        purchase_filter = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        result = set(Purchase.objects.filter(purchase_filter.to_q()))
        assert result == {purchase_a}

    def test_session_end_before_start_same_day(self):
        """timestamp_end < timestamp_start finds X (same calendar day, end 22:00 < start 23:00).

        Y (normal order) is excluded. Proves raw-datetime comparison, not date-truncated:
        __date truncation would make both timestamps equal on the same day and miss X.
        """
        import datetime

        from games.filters import SessionFilter
        from games.models import Session

        _, game = self._make_platform_and_game()

        # X: end BEFORE start on the same calendar day — must be returned
        session_x = Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 6, 1, 23, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2024, 6, 1, 22, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )
        # Y: normal session (end after start) — must NOT be returned
        Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 6, 2, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2024, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )

        session_filter = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_end",
                    right="timestamp_start",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        result = set(Session.objects.filter(session_filter.to_q()))
        assert result == {session_x}

    def test_date_granular_same_day_behavior(self):
        """granularity='date' matches by calendar day, unlike a raw comparison.

        SAME spans one day (different clock times); CROSS spans two days. Uses
        timestamps far from midnight in any near-UTC timezone so the active tz of
        the test run cannot flip which calendar day a boundary falls on.
        """
        import datetime

        from games.filters import SessionFilter
        from games.models import Session

        _, game = self._make_platform_and_game()

        same = Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2024, 6, 1, 14, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )
        cross = Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2024, 6, 3, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )

        def run(modifier: Modifier, granularity: ComparisonGranularity) -> set:
            session_filter = SessionFilter(
                field_comparisons=[
                    FieldComparisonCriterion(
                        left="timestamp_start",
                        right="timestamp_end",
                        modifier=modifier,
                        granularity=granularity,
                    )
                ]
            )
            return set(Session.objects.filter(session_filter.to_q()))

        # date-granular EQUALS: only the same-calendar-day session.
        assert run(Modifier.EQUALS, "date") == {same}
        # raw EQUALS: neither (clock times always differ) — the contrast that
        # motivates the feature.
        assert run(Modifier.EQUALS, "raw") == set()
        # date-granular LESS_THAN (start day < end day): only the cross-day one.
        assert run(Modifier.LESS_THAN, "date") == {cross}

    def test_generated_field_as_comparison_operand(self):
        """duration_total > duration_manual finds only P.

        P has timestamp_start/end 1 hour apart and duration_manual=0, so
        duration_total (1 h) > duration_manual (0). Q has no timestamp_end
        (duration_calculated=0) and duration_manual=2 h, so duration_total
        equals duration_manual and is NOT strictly greater.
        """
        import datetime
        from datetime import timedelta

        from games.filters import SessionFilter
        from games.models import Session

        _, game = self._make_platform_and_game()

        # P: 1-hour calc, 0 manual → duration_total=1h > duration_manual=0
        session_p = Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 7, 1, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            timestamp_end=datetime.datetime(
                2024, 7, 1, 11, 0, 0, tzinfo=datetime.timezone.utc
            ),
            duration_manual=timedelta(0),
        )
        # Q: no timestamp_end (calculated=0), 2h manual → duration_total=2h == duration_manual=2h
        Session.objects.create(
            game=game,
            timestamp_start=datetime.datetime(
                2024, 7, 2, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            duration_manual=timedelta(hours=2),
        )

        session_filter = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="duration_total",
                    right="duration_manual",
                    modifier=Modifier.GREATER_THAN,
                )
            ]
        )
        result = set(Session.objects.filter(session_filter.to_q()))
        assert result == {session_p}

    def test_unknown_right_column_raises(self):
        """An unknown right-operand raises FilterError via to_q()."""
        from games.filters import PurchaseFilter

        purchase_filter = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="nonexistent",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        with pytest.raises(FilterError):
            purchase_filter.to_q()

    def test_not_equals_null_semantics(self):
        """date_refunded NOT_EQUALS date_purchased:
        - equal row (B) is excluded by NOT_EQUALS.
        - NULL row (C) is INCLUDED: Django 6's ~Q on nullable operands generates
          NOT (date_refunded = date_purchased AND date_refunded IS NOT NULL
               AND date_purchased IS NOT NULL),
          i.e. date_refunded != date_purchased OR date_refunded IS NULL
               OR date_purchased IS NULL.
        So NOT_EQUALS returns rows A (different dates) and C (NULL date_refunded),
        but not B (equal dates). This Purchase case only exercises the left-NULL
        branch because date_purchased is non-nullable; the symmetric right-NULL
        branch is covered by test_not_equals_null_symmetric (PlayEvent).
        """
        import datetime

        from games.filters import PurchaseFilter
        from games.models import Platform, Purchase

        platform, _ = Platform.objects.get_or_create(
            name="FieldCmpTest", icon="fieldcmptest"
        )

        # A: date_refunded differs from date_purchased → returned
        purchase_a = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            date_refunded=datetime.date(2024, 3, 1),
        )
        # B: date_refunded equals date_purchased → excluded (NOT FALSE = FALSE)
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 2, 1),
            date_refunded=datetime.date(2024, 2, 1),
        )
        # C: date_refunded is NULL → included (IS NULL branch of Django's ~Q)
        purchase_c = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
        )

        purchase_filter = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.NOT_EQUALS,
                )
            ]
        )
        result = set(Purchase.objects.filter(purchase_filter.to_q()))
        assert result == {purchase_a, purchase_c}

    def test_not_equals_null_symmetric(self):
        """NOT_EQUALS NULL inclusion is symmetric across BOTH operands.

        Django 6 null-guards both sides of the F() comparison, so ~Q includes a
        row when EITHER operand is NULL — not just the left one. PlayEvent has two
        nullable date columns (started, ended), letting us exercise the right-NULL
        branch that the Purchase test cannot (its date_purchased is non-nullable).
        """
        import datetime

        from games.filters import PlayEventFilter
        from games.models import Game, PlayEvent, Platform

        platform, _ = Platform.objects.get_or_create(name="PESym", icon="pesym")
        game = Game.objects.create(name="PESymGame", platform=platform)

        # different (both set) → included
        differ = PlayEvent.objects.create(
            game=game,
            started=datetime.date(2024, 1, 1),
            ended=datetime.date(2024, 2, 1),
        )
        # equal (both set) → excluded
        PlayEvent.objects.create(
            game=game,
            started=datetime.date(2024, 3, 1),
            ended=datetime.date(2024, 3, 1),
        )
        # left NULL → included
        left_null = PlayEvent.objects.create(game=game, ended=datetime.date(2024, 4, 1))
        # right NULL → included (the symmetric branch)
        right_null = PlayEvent.objects.create(
            game=game, started=datetime.date(2024, 5, 1)
        )

        play_filter = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started", right="ended", modifier=Modifier.NOT_EQUALS
                )
            ]
        )
        result = set(PlayEvent.objects.filter(play_filter.to_q()))
        assert result == {differ, left_null, right_null}

    def test_two_comparisons_both_must_hold(self):
        """Two field comparisons in one filter AND-accumulate:
        a row must satisfy BOTH to be returned; satisfying only one is not enough.
        Proves _apply_operators ANDs rather than replaces.
        """
        import datetime

        from games.filters import PurchaseFilter
        from games.models import Platform, Purchase

        platform, _ = Platform.objects.get_or_create(
            name="FieldCmpTest", icon="fieldcmptest"
        )

        # A: refund after purchase AND price > converted_price → returned
        purchase_a = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            date_refunded=datetime.date(2024, 3, 1),
            price=50.0,
            converted_price=40.0,
            needs_price_update=False,
        )
        # B: refund after purchase BUT price < converted_price → excluded (fails comparison 2)
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            date_refunded=datetime.date(2024, 3, 1),
            price=30.0,
            converted_price=40.0,
            needs_price_update=False,
        )
        # C: price > converted_price BUT no refund (NULL) → excluded (fails comparison 1)
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            price=50.0,
            converted_price=40.0,
            needs_price_update=False,
        )

        purchase_filter = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.GREATER_THAN,
                ),
                FieldComparisonCriterion(
                    left="price",
                    right="converted_price",
                    modifier=Modifier.GREATER_THAN,
                ),
            ]
        )
        result = set(Purchase.objects.filter(purchase_filter.to_q()))
        assert result == {purchase_a}

    def test_json_round_trip_purchase_comparison(self):
        """Serializing and re-parsing the purchase filter queries identically.

        Takes the PurchaseFilter from test_purchase_refund_before_purchase,
        round-trips it through filter_to_json → parse_purchase_filter, then
        confirms the parsed filter returns the same single purchase A.
        """
        import datetime

        from common.criteria import filter_to_json
        from games.filters import PurchaseFilter, parse_purchase_filter
        from games.models import Platform, Purchase

        platform, _ = Platform.objects.get_or_create(
            name="FieldCmpTest", icon="fieldcmptest"
        )

        # A: refund BEFORE purchase — should be returned
        purchase_a = Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 3, 1),
            date_refunded=datetime.date(2024, 1, 1),
        )
        # B: refund AFTER purchase — should NOT be returned
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
            date_refunded=datetime.date(2024, 3, 1),
        )
        # C: NULL date_refunded — should NOT be returned
        Purchase.objects.create(
            platform=platform,
            date_purchased=datetime.date(2024, 1, 1),
        )

        purchase_filter = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="date_refunded",
                    right="date_purchased",
                    modifier=Modifier.LESS_THAN,
                )
            ]
        )
        json_string = filter_to_json(purchase_filter)
        parsed_filter = parse_purchase_filter(json_string)
        assert parsed_filter is not None
        result = set(Purchase.objects.filter(parsed_filter.to_q()))
        assert result == {purchase_a}

    def test_string_includes_excludes_end_to_end(self):
        """Game.name INCLUDES/EXCLUDES Game.sort_name, case-insensitively.

        - M (name contains sort_name) matches INCLUDES, not EXCLUDES.
        - N (name does not contain sort_name) matches EXCLUDES, not INCLUDES.
        - P (different case) matches INCLUDES — __icontains is case-insensitive.
        - O (empty sort_name) matches INCLUDES — "" is a substring of every name.
        Both operands are non-nullable, so EXCLUDES is the exact complement.
        """
        from games.filters import GameFilter
        from games.models import Game, Platform

        platform, _ = Platform.objects.get_or_create(
            name="StrCmpTest", icon="strcmptest"
        )
        match = Game.objects.create(
            name="The Legend of Zelda", sort_name="Zelda", platform=platform
        )
        no_match = Game.objects.create(name="Halo", sort_name="Doom", platform=platform)
        case_insensitive = Game.objects.create(
            name="DARK SOULS", sort_name="dark", platform=platform
        )
        empty_sort = Game.objects.create(name="Tetris", sort_name="", platform=platform)

        includes = GameFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name", right="sort_name", modifier=Modifier.INCLUDES
                )
            ]
        )
        assert set(Game.objects.filter(includes.to_q())) == {
            match,
            case_insensitive,
            empty_sort,
        }

        excludes = GameFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name", right="sort_name", modifier=Modifier.EXCLUDES
                )
            ]
        )
        assert set(Game.objects.filter(excludes.to_q())) == {no_match}

    def test_json_round_trip_game_string_includes(self):
        """A string INCLUDES field comparison survives JSON serialization."""
        from common.criteria import filter_to_json
        from games.filters import GameFilter, parse_game_filter
        from games.models import Game, Platform

        platform, _ = Platform.objects.get_or_create(
            name="StrCmpTest", icon="strcmptest"
        )
        match = Game.objects.create(
            name="Super Mario Bros", sort_name="Mario", platform=platform
        )
        Game.objects.create(name="Pong", sort_name="Snake", platform=platform)

        game_filter = GameFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name", right="sort_name", modifier=Modifier.INCLUDES
                )
            ]
        )
        parsed_filter = parse_game_filter(filter_to_json(game_filter))
        assert parsed_filter is not None
        assert set(Game.objects.filter(parsed_filter.to_q())) == {match}


class FieldComparisonPrefillTest(TestCase):
    """_field_comparison_rows: the two on-disk shapes the widget round-trips."""

    def test_empty(self):
        from common.components.filters import _field_comparison_rows

        rows, mode = _field_comparison_rows({})
        self.assertEqual(rows, [])
        self.assertEqual(mode, "AND")

    def test_and_shape(self):
        from common.components.filters import _field_comparison_rows

        rows, mode = _field_comparison_rows(
            {
                "field_comparisons": [
                    {"left": "a", "right": "b", "modifier": "LESS_THAN"},
                    {"left": "c", "right": "d", "modifier": "EQUALS"},
                ]
            }
        )
        self.assertEqual(mode, "AND")
        self.assertEqual([r.left for r in rows], ["a", "c"])
        self.assertEqual(rows[0].modifier, "LESS_THAN")

    def test_or_shape(self):
        from common.components.filters import _field_comparison_rows

        rows, mode = _field_comparison_rows(
            {
                "AND": [
                    {
                        "OR": [
                            {
                                "field_comparisons": [
                                    {"left": "a", "right": "b", "modifier": "EQUALS"}
                                ]
                            },
                            {
                                "field_comparisons": [
                                    {"left": "c", "right": "d", "modifier": "INCLUDES"}
                                ]
                            },
                        ]
                    }
                ]
            }
        )
        self.assertEqual(mode, "OR")
        self.assertEqual([(r.left, r.right) for r in rows], [("a", "b"), ("c", "d")])
        self.assertEqual(rows[1].modifier, "INCLUDES")

    def test_and_wins_over_or(self):
        from common.components.filters import _field_comparison_rows

        rows, mode = _field_comparison_rows(
            {
                "field_comparisons": [
                    {"left": "a", "right": "b", "modifier": "EQUALS"}
                ],
                "AND": [
                    {
                        "OR": [
                            {
                                "field_comparisons": [
                                    {"left": "c", "right": "d", "modifier": "EQUALS"}
                                ]
                            }
                        ]
                    }
                ],
            }
        )
        self.assertEqual(mode, "AND")
        self.assertEqual(rows[0].left, "a")

    def test_section_none_without_model(self):
        from common.components.filters import _field_comparison_section

        self.assertIsNone(_field_comparison_section({}, None))

    def test_section_present_for_real_model(self):
        from common.components.filters import _field_comparison_section
        from games.models import Session

        node = _field_comparison_section({}, Session)
        self.assertIsNotNone(node)
        self.assertIn("field-comparison-set", str(node))


# ── Descriptor drift guard (issue #161) ──────────────────────────────────────


class TestFilterFieldDescriptors:
    """Guard the declarative ``fields`` table against drift from the dataclass.

    Each concrete filter's generic ``to_q`` walks ``fields`` for its simple
    criteria and delegates the rest to ``_extra_q``. These tests assert that
    every declared criterion field is accounted for exactly once — in ``fields``,
    as an aggregate, or in ``_IMPERATIVE_CRITERIA`` — so a newly added field can't
    silently fall through (and thus be ignored by ``to_q``).
    """

    ALL_FILTERS = [
        GameFilter,
        SessionFilter,
        PurchaseFilter,
        DeviceFilter,
        PlatformFilter,
        PlayEventFilter,
    ]

    @staticmethod
    def _declared_criterion_fields(filter_cls) -> set[str]:
        """Every dataclass field whose annotation resolves to a criterion type."""
        return {
            f.name
            for f in dataclasses.fields(filter_cls)
            if _criterion_class_for(filter_cls, f.name) is not None
        }

    @classmethod
    def _aggregate_fields(cls, filter_cls) -> set[str]:
        result: set[str] = set()
        for name in cls._declared_criterion_fields(filter_cls):
            criterion_cls = _criterion_class_for(filter_cls, name)
            if criterion_cls is not None and issubclass(
                criterion_cls, AggregateCriterion
            ):
                result.add(name)
        return result

    @pytest.mark.parametrize("filter_cls", ALL_FILTERS)
    def test_partition_covers_every_criterion_field(self, filter_cls):
        declared = self._declared_criterion_fields(filter_cls)
        descriptor_keys = set(filter_cls.fields)
        aggregates = self._aggregate_fields(filter_cls)
        imperative = set(filter_cls._IMPERATIVE_CRITERIA)
        covered = descriptor_keys | aggregates | imperative
        assert covered == declared, (
            f"{filter_cls.__name__}: fields∪aggregates∪imperative != declared "
            f"criterion fields; missing={declared - covered}, "
            f"extra={covered - declared}"
        )

    @pytest.mark.parametrize("filter_cls", ALL_FILTERS)
    def test_partition_has_no_overlap(self, filter_cls):
        descriptor_keys = set(filter_cls.fields)
        aggregates = self._aggregate_fields(filter_cls)
        imperative = set(filter_cls._IMPERATIVE_CRITERIA)
        assert descriptor_keys.isdisjoint(aggregates)
        assert descriptor_keys.isdisjoint(imperative)
        assert aggregates.isdisjoint(imperative)

    @pytest.mark.parametrize("filter_cls", ALL_FILTERS)
    def test_descriptor_keys_are_real_criterion_fields(self, filter_cls):
        declared = self._declared_criterion_fields(filter_cls)
        for key in filter_cls.fields:
            assert key in declared, (
                f"{filter_cls.__name__}.fields[{key!r}] is not a criterion field"
            )


# ── FilterField handlers (issue #161) ────────────────────────────────────────


class TestFilterField:
    """The descriptor's lookup/handler contract."""

    def test_plain_field_defaults_lookup_to_attr_name(self):
        assert FilterField().to_q("name", StringCriterion(value="x")) == Q(name="x")

    def test_lookup_override(self):
        assert FilterField("platform_id").to_q(
            "platform", MultiCriterion(value=[1, 2])
        ) == Q(platform_id__in=[1, 2])

    def test_lookup_and_handler_together_rejected(self):
        with pytest.raises(ValueError, match="lookup OR handler"):
            FilterField("x", handler=lambda c: Q())


class TestFilterFieldHandlers:
    """Each handler factory's Q output, and that the right handler is wired to the
    field it serves (a plain FilterField regression would pass the drift guard but
    fail here)."""

    def test_duration_hours_equals_bucket(self):
        from datetime import timedelta

        handler = duration_hours_handler("duration_total")
        assert handler(IntCriterion(value=4, modifier=Modifier.EQUALS)) == Q(
            duration_total__gte=timedelta(hours=4),
            duration_total__lt=timedelta(hours=5),
        )

    def test_duration_hours_between_passes_value2(self):
        # The refactor reads value2 via getattr — confirm it actually flows through.
        from datetime import timedelta

        handler = duration_hours_handler("duration_total")
        assert handler(IntCriterion(value=1, value2=5, modifier=Modifier.BETWEEN)) == Q(
            duration_total__gte=timedelta(hours=1),
            duration_total__lte=timedelta(hours=5),
        )

    def test_bool_isnull_handler_direct(self):
        assert bool_isnull_handler("timestamp_end")(BoolCriterion(value=True)) == Q(
            timestamp_end__isnull=True
        )
        assert bool_isnull_handler("timestamp_end")(BoolCriterion(value=False)) == Q(
            timestamp_end__isnull=False
        )

    def test_bool_isnull_handler_invert(self):
        assert bool_isnull_handler("date_refunded", invert=True)(
            BoolCriterion(value=True)
        ) == Q(date_refunded__isnull=False)
        assert bool_isnull_handler("date_refunded", invert=True)(
            BoolCriterion(value=False)
        ) == Q(date_refunded__isnull=True)

    def test_bool_nonzero_duration_handler(self):
        from datetime import timedelta

        handler = bool_nonzero_duration_handler("duration_manual")
        assert handler(BoolCriterion(value=True)) == ~Q(duration_manual=timedelta(0))
        assert handler(BoolCriterion(value=False)) == Q(duration_manual=timedelta(0))

    # ── wiring: the field maps to the intended handler via the generic to_q ──

    def test_is_active_wired(self):
        assert SessionFilter(is_active=BoolCriterion(value=True)).to_q() == Q(
            timestamp_end__isnull=True
        )

    def test_is_manual_wired(self):
        from datetime import timedelta

        assert SessionFilter(is_manual=BoolCriterion(value=True)).to_q() == ~Q(
            duration_manual=timedelta(0)
        )

    def test_is_refunded_wired(self):
        # value=False must select non-refunded (date_refunded IS NULL).
        assert PurchaseFilter(is_refunded=BoolCriterion(value=False)).to_q() == Q(
            date_refunded__isnull=True
        )

    def test_playtime_hours_wired(self):
        from datetime import timedelta

        assert GameFilter(
            playtime_hours=IntCriterion(value=2, modifier=Modifier.GREATER_THAN)
        ).to_q() == Q(playtime__gt=timedelta(hours=2))


class TestSearchQHelper:
    """search_q: empty short-circuit, multi-column OR, EXCLUDES negation."""

    def test_empty_value_no_constraint(self):
        assert search_q(StringCriterion(value=""), "name", "note") == Q()

    def test_empty_value_excludes_still_no_constraint(self):
        # Matches the old `if search and search.value` guard: empty value never
        # negates to zero rows, regardless of modifier.
        assert (
            search_q(StringCriterion(value="", modifier=Modifier.EXCLUDES), "name")
            == Q()
        )

    def test_multi_column_or(self):
        assert search_q(StringCriterion(value="x"), "a", "b") == (
            Q(a__icontains="x") | Q(b__icontains="x")
        )

    def test_excludes_negates_whole_disjunction(self):
        assert search_q(
            StringCriterion(value="x", modifier=Modifier.EXCLUDES), "a", "b"
        ) == ~(Q(a__icontains="x") | Q(b__icontains="x"))


class TestValueTypeBoundaryIntegration:
    """End-to-end: a wrong-typed ``?filter=`` reaches a real list view / API
    endpoint and degrades gracefully instead of 500-ing at query execution
    (issue #157). Pre-fix these payloads built a Q fine and raised at eval."""

    @pytest.fixture
    def auth_client(self, client, django_user_model):
        user = django_user_model.objects.create_user(username="u", password="p")
        client.force_login(user)
        return client

    @pytest.mark.django_db
    def test_web_list_view_warn_ignores_bad_value(self, auth_client):
        from django.urls import reverse

        bad = json.dumps({"year_released": {"modifier": "EQUALS", "value": "nope"}})
        response = auth_client.get(reverse("games:list_games"), {"filter": bad})
        # Boundary warns and ignores → the page still renders, never a 500.
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_api_list_returns_400_on_bad_value(self, auth_client):
        bad = json.dumps({"timestamp_start": {"modifier": "EQUALS", "value": "nope"}})
        response = auth_client.get("/api/session/", {"filter": bad})
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_created_at_filter_is_date_granular(self):
        # The temporal StringCriterion → DateCriterion + __date reclass must match
        # a non-midnight created_at datetime by its calendar date (a regression
        # dropping __date would make equality silently never match).
        from datetime import datetime, timezone

        from games.models import Game, Platform

        platform = Platform.objects.create(name="PC")
        game = Game.objects.create(name="Hades", platform=platform)
        # auto_now_add can't be set on create; stamp an afternoon time directly.
        moment = datetime(2024, 3, 14, 15, 9, 0, tzinfo=timezone.utc)
        Game.objects.filter(pk=game.pk).update(created_at=moment)

        good = json.dumps({"created_at": {"modifier": "EQUALS", "value": "2024-03-14"}})
        parsed = parse_game_filter(good)
        assert parsed is not None
        assert Game.objects.filter(parsed.to_q()).filter(pk=game.pk).exists()
