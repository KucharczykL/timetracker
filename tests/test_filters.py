"""Tests for the filtering system."""

import json

import pytest
from django.db.models import Q

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    IntCriterion,
    Modifier,
    StringCriterion,
)
from common.components import FilterBar
from games.filters import GameFilter


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

    def test_not_equals(self):
        c = ChoiceCriterion(value=["f"], modifier=Modifier.NOT_EQUALS)
        assert c.to_q("status") == ~Q(status__in=["f"])


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
        assert 'data-ss-mode="filter"' in html
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
                    {"status": {"value": ["f"], "modifier": "INCLUDES"}}
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
