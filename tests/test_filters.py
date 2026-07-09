"""Tests for the filtering system."""

import dataclasses
import json
import logging
import operator
from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import reduce

import pytest
from django.db.models import F, Q

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
    MAX_FIELD_COMPARISONS,
    MAX_FILTER_BREADTH,
    MAX_FILTER_DEPTH,
    MAX_REGEX_PATTERN_LENGTH,
    MAX_SET_VALUES,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    RelationMatch,
    StringCriterion,
    _ScalarCriterion,
    _allowed_comparison_modifiers,
    _comparison_group_for,
    _comparison_operand_info,
    _criterion_class_for,
    _field_comparison_to_q,
    _filter_class_for,
    _maybe_group_for,
    _resolve_model_field,
    bool_isnull_handler,
    bool_nonzero_duration_handler,
    comparable_columns,
    duration_hours_handler,
    FieldMeta,
    field_metadata,
    filter_from_json,
    filter_to_json,
    search_q,
)
from games.filters import (
    DeviceFilter,
    GameFilter,
    PlatformFilter,
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    parse_device_filter,
    parse_game_filter,
    parse_platform_filter,
    parse_playevent_filter,
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
        assert c.to_q("name") == Q(name__isnull=True) | Q(name__exact="")

    def test_not_null(self):
        c = StringCriterion(value="", modifier=Modifier.NOT_NULL)
        assert c.to_q("name") == ~(Q(name__isnull=True) | Q(name__exact=""))

    def test_empty_value_survives_to_json(self):
        """An EQUALS "" match (empty string, not unset — "unset" is the criterion
        being absent at the filter level) must serialize. The base to_json drops
        value=="" as it equals the default. Symmetric with the scalar #223 fix."""
        assert StringCriterion(value="", modifier=Modifier.EQUALS).to_json() == {
            "value": ""
        }

    def test_empty_value_survives_filter_round_trip(self):
        """The real drop path: parent OperatorFilter.to_json must not drop an
        EQUALS "" criterion. Unlike DateCriterion, StringCriterion has no coercion,
        so "" round-trips fully."""
        original = GameFilter(name=StringCriterion(value="", modifier=Modifier.EQUALS))
        restored = filter_from_json(GameFilter, filter_to_json(original))
        assert restored is not None
        assert restored.name == StringCriterion(value="", modifier=Modifier.EQUALS)

    def test_is_null_round_trips_json(self):
        original = StringCriterion(value="", modifier=Modifier.IS_NULL)
        restored = StringCriterion.from_json(original.to_json())
        assert restored == original
        assert restored.to_q("note") == Q(note__isnull=True) | Q(note__exact="")


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

    def test_value_zero_survives_to_json(self):
        """value=0 with a value-using modifier must serialize — it equals the
        dataclass default, so the base to_json would drop it, losing a meaningful
        EQUALS 0 (e.g. free price, zero-duration). Regression for #223."""
        assert IntCriterion(value=0, modifier=Modifier.EQUALS).to_json() == {"value": 0}


class TestScalarCriterionZeroValue:
    """#223: every scalar criterion must serialize a meaningful default-valued
    `value` rather than dropping it (the base to_json omits value==default)."""

    def test_float_zero_survives_to_json(self):
        as_dict = FloatCriterion(value=0.0, modifier=Modifier.LESS_THAN).to_json()
        assert as_dict["value"] == 0.0
        assert as_dict["modifier"] == Modifier.LESS_THAN

    def test_date_empty_value_survives_to_json(self):
        # `""` is not a valid ISO date (from_json rightly rejects it on round-trip),
        # but to_json must still force-emit value for shape-consistency with the
        # other scalars rather than silently dropping it.
        assert "value" in DateCriterion(value="", modifier=Modifier.EQUALS).to_json()

    def test_aggregate_zero_survives_to_json(self):
        """'games with 0 sessions' — the latent stats hazard from #223."""
        as_dict = AggregateCriterion(value=0, modifier=Modifier.EQUALS).to_json()
        assert as_dict["value"] == 0

    # The actual #223 bug path: `OperatorFilter.to_json` drops a field whose
    # criterion serializes to `{}` (the `if j:` guard, criteria.py:1343-1346). A
    # criterion-in-isolation round-trip can NEVER catch this — `from_json` refills
    # the dropped value from the dataclass default, so it passes even on the
    # buggy code. Only a full filter-level round-trip exercises the drop site and
    # genuinely fails when the fix is reverted.

    def test_int_zero_survives_filter_round_trip(self):
        original = GameFilter(
            year_released=IntCriterion(value=0, modifier=Modifier.EQUALS)
        )
        restored = filter_from_json(GameFilter, filter_to_json(original))
        assert restored is not None
        assert restored.year_released == IntCriterion(value=0, modifier=Modifier.EQUALS)

    def test_aggregate_zero_survives_filter_round_trip(self):
        """'games with 0 sessions' through the full filter serializer."""
        original = GameFilter(
            session_count=AggregateCriterion(value=0, modifier=Modifier.EQUALS)
        )
        restored = filter_from_json(GameFilter, filter_to_json(original))
        assert restored is not None
        assert restored.session_count == AggregateCriterion(
            value=0, modifier=Modifier.EQUALS
        )


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
        # Negative membership carries an explicit isnull arm (issue #290) so
        # NULL-keeping is stated in the Q tree, not left to Django's
        # negated-lookup guard.
        c = ChoiceCriterion(value=["a"], modifier=Modifier.EXCLUDES)
        assert c.to_q("status") == ~Q(status__in=["a"]) | Q(status__isnull=True)

    def test_excludes_only_empty_value(self):
        """Excluding a single status with no includes — value=[], excludes=["f"]."""
        c = ChoiceCriterion(value=[], excludes=["f"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == ~Q(status__in=["f"]) | Q(status__isnull=True)

    def test_excludes_two(self):
        """Excluding two statuses with no includes."""
        c = ChoiceCriterion(value=[], excludes=["f", "a"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == ~Q(status__in=["f", "a"]) | Q(status__isnull=True)

    def test_include_and_exclude(self):
        """Include f, exclude a — both lists set."""
        c = ChoiceCriterion(value=["f"], excludes=["a"], modifier=Modifier.INCLUDES)
        q = c.to_q("status")
        assert q == Q(status__in=["f"]) & (
            ~Q(status__in=["a"]) | Q(status__isnull=True)
        )

    def test_include_two_and_exclude_one(self):
        c = ChoiceCriterion(
            value=["f", "p"], excludes=["a"], modifier=Modifier.INCLUDES
        )
        q = c.to_q("status")
        assert q == Q(status__in=["f", "p"]) & (
            ~Q(status__in=["a"]) | Q(status__isnull=True)
        )

    def test_is_null(self):
        c = ChoiceCriterion(value=[], modifier=Modifier.IS_NULL)
        assert c.to_q("status") == Q(status__isnull=True)

    def test_not_null(self):
        c = ChoiceCriterion(value=[], modifier=Modifier.NOT_NULL)
        assert c.to_q("status") == Q(status__isnull=False)

    def test_excludes_modifier(self):
        """EXCLUDES modifier with value set."""
        c = ChoiceCriterion(value=["f"], modifier=Modifier.EXCLUDES)
        assert c.to_q("status") == ~Q(status__in=["f"]) | Q(status__isnull=True)

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
        assert c.to_q("status") == (~Q(status__in=["f"]) | Q(status__isnull=True)) & (
            ~Q(status__in=["a"]) | Q(status__isnull=True)
        )

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
        assert c.to_q("status") == ~Q(status__in=["f"]) | Q(status__isnull=True)

    def test_to_json_emits_bare_codes(self):
        """Enum criteria never set labels, so the shared _SetCriterion.to_json
        leaves their codes bare (#224)."""
        assert ChoiceCriterion(value=["f", "p"]).to_json() == {"value": ["f", "p"]}


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
        # The explicit isnull arm (issue #290): "exclude device 11" keeps
        # device-less sessions by construction, not via ORM negation internals.
        assert c.to_q("device_id") == ~Q(device_id__in=[11]) | Q(device_id__isnull=True)

    def test_include_and_exclude(self):
        c = MultiCriterion(value=[1], excludes=[2], modifier=Modifier.INCLUDES)
        assert c.to_q("game_id") == Q(game_id__in=[1]) & (
            ~Q(game_id__in=[2]) | Q(game_id__isnull=True)
        )

    def test_excludes_modifier_applies_excludes_channel(self):
        """Harmonized (Stash model): EXCLUDES negates ``value`` AND still applies
        the orthogonal ``excludes`` channel. Previously MultiCriterion.EXCLUDES
        dropped the excludes list entirely."""
        c = MultiCriterion(value=[1], excludes=[2], modifier=Modifier.EXCLUDES)
        assert c.to_q("game_id") == (~Q(game_id__in=[1]) | Q(game_id__isnull=True)) & (
            ~Q(game_id__in=[2]) | Q(game_id__isnull=True)
        )

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
        assert c.to_q("game_id") == Q(game_id__in=[797]) & (
            ~Q(game_id__in=[11]) | Q(game_id__isnull=True)
        )

    def test_to_json_embeds_known_labels(self):
        """to_json folds the labels map back into {id, label} wire shape (#224)."""
        c = MultiCriterion(value=[797], labels={797: "Hollow Knight"})
        assert c.to_json() == {"value": [{"id": 797, "label": "Hollow Knight"}]}

    def test_to_json_without_labels_emits_bare_ids(self):
        """No labels -> serialization is unchanged (bare ids)."""
        assert MultiCriterion(value=[797]).to_json() == {"value": [797]}

    def test_to_json_emits_bare_id_for_unlabelled_element(self):
        """Only ids present in the labels map get a label; others stay bare."""
        c = MultiCriterion(value=[1, 2], labels={1: "One"})
        assert c.to_json() == {"value": [{"id": 1, "label": "One"}, 2]}

    def test_to_json_embeds_labels_on_excludes_channel(self):
        """The excludes channel is labelled symmetrically with value."""
        c = MultiCriterion(value=[], excludes=[2], labels={2: "Two"})
        assert c.to_json() == {"excludes": [{"id": 2, "label": "Two"}]}

    def test_labels_do_not_affect_query(self):
        """Labels are display-only: to_q is identical with and without them."""
        labelled = MultiCriterion(value=[1], excludes=[2], labels={1: "a", 2: "b"})
        bare = MultiCriterion(value=[1], excludes=[2])
        assert labelled.to_q("game_id") == bare.to_q("game_id")

    def test_labels_round_trip_strips_back_to_bare(self):
        """to_json embeds labels; from_json strips them — the query value is the
        same bare id list either way."""
        original = MultiCriterion(value=[797], labels={797: "Hollow Knight"})
        restored = MultiCriterion.from_json(original.to_json())
        assert restored.value == [797]
        assert restored.labels == {}


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


def _games_bar(filter_json: str = "") -> str:
    from common.components import QuickFilterBar

    return str(
        QuickFilterBar(mode="games", filter_json=filter_json, apply_url="/games")
    )


class TestFilterBarRendering:
    """The games quick bar renders FilterSelect facet widgets."""

    def test_status_uses_filter_select(self):
        html = _games_bar()
        assert 'filter-mode="true"' in html
        assert 'name="status"' in html

    def test_mastered_not_checked_by_default(self):
        html = _games_bar()
        assert (
            'name="filter-mastered" value="true" class="rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand" checked="true"'
            not in html
        )
        assert (
            'name="filter-mastered" value="false" class="rounded-full border-default-medium bg-neutral-secondary-medium text-brand focus:ring-brand" checked="true"'
            not in html
        )

    def test_mastered_checked_when_filtered(self):
        html = _games_bar(
            json.dumps({"mastered": {"value": True, "modifier": "EQUALS"}})
        )
        assert 'checked="true"' in html

    def test_status_prefilled(self):
        html = _games_bar(
            json.dumps(
                {
                    "status": {
                        "value": [{"id": "f", "label": "Finished"}],
                        "modifier": "INCLUDES",
                    }
                }
            )
        )
        assert 'data-value="f"' in html
        assert "Finished" in html

    def test_no_hx_get(self):
        html = _games_bar()
        assert "hx-get" not in html

    def test_platform_uses_search_url(self):
        """Platform is model-backed: rows are fetched, not pre-rendered."""
        html = _games_bar()
        assert 'search-url="/api/platforms/search"' in html

    def test_status_has_no_modifiers(self):
        """Non-nullable fields should not show (None) but MUST show (Any)."""
        html = _games_bar()
        status_start = html.find('name="status"')
        platform_start = html.find('name="platform"')
        status_section = html[status_start:platform_start]
        # Must have (Any) — always available
        assert "(Any)" in status_section
        # Must NOT have (None) — field is non-nullable
        assert "(None)" not in status_section

    def test_platform_has_modifiers(self):
        """Nullable ForeignKey fields should show (Any)/(None)."""
        html = _games_bar()
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

    def test_game_filter_platform_group_excludes_keeps_platformless(self):
        """DB proof of the excludes isnull arm on a join path: the direct FK
        (``Game.platform``) is covered elsewhere, but ``platform_group``
        traverses ``platform__group`` (a LEFT JOIN), so excluding a group must
        keep platformless games too — not just games on other platforms."""
        from games.filters import GameFilter
        from games.models import Game

        data = self._setup_entities()
        platformless = Game.objects.create(name="Homebrew Game", platform=None)
        gf = GameFilter.from_json(
            {"platform_group": {"value": ["Nintendo"], "modifier": "EXCLUDES"}}
        )
        results = set(Game.objects.filter(gf.to_q()))
        assert platformless in results
        assert data["game"] not in results
        assert data["game2"] not in results

    def test_purchase_games_excludes_keeps_gameless_purchase(self):
        """DB proof of the deliberate M2M asymmetry: ``games`` excludes go
        through ``_games_to_q``'s plain ``~Q(games__in=...)``, not
        ``_SetCriterion._not_in_q`` — the isnull arm is an FK-column device,
        while ORM negation over the M2M join already keeps purchases with no
        linked games."""
        import datetime

        from games.filters import PurchaseFilter
        from games.models import Purchase

        data = self._setup_entities()
        gameless = Purchase.objects.create(
            platform=data["plat"], date_purchased=datetime.date(2026, 2, 1)
        )
        pf = PurchaseFilter.from_json(
            {
                "games": {
                    "value": [],
                    "excludes": [data["game"].pk],
                    "modifier": "INCLUDES",
                }
            }
        )
        results = set(Purchase.objects.filter(pf.to_q()))
        assert gameless in results
        assert data["pur"] not in results

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
        via field-type introspection (``_field_types``)."""
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

    def test_invalid_regex_pattern_raises(self):
        """A malformed regex would raise at query-execution time (the DB's REGEXP
        compiles it with ``re``) — past the error boundary, a 500. Validate it at
        parse instead. ``.*{12,}`` (multiple repeat) is the reported case."""
        bad = json.dumps({"name": {"modifier": "MATCHES_REGEX", "value": ".*{12,}"}})
        with pytest.raises(FilterError, match="invalid regex pattern"):
            parse_game_filter(bad)

    def test_invalid_regex_nested_in_relation_raises(self):
        """The reported 500: a purchase filter whose nested ``game_filter`` carries
        an invalid regex. Validation must reach into the cross-entity sub-filter."""
        bad = json.dumps(
            {"game_filter": {"name": {"modifier": "MATCHES_REGEX", "value": "[unbal"}}}
        )
        with pytest.raises(FilterError, match="invalid regex pattern"):
            parse_purchase_filter(bad)

    def test_valid_regex_pattern_parses(self):
        """A well-formed regex is unaffected by the parse-time compile check."""
        good = json.dumps(
            {"name": {"modifier": "MATCHES_REGEX", "value": "[a-z]{12,}"}}
        )
        parsed = parse_game_filter(good)
        assert parsed is not None

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

    def test_invalid_regex_pattern(self):
        """An uncompilable pattern (unbalanced group) is a clean FilterError, not a
        500 from re.error escaping the boundary."""
        bad = json.dumps({"name": {"modifier": "MATCHES_REGEX", "value": "(a"}})
        with pytest.raises(FilterError, match="invalid regex pattern"):
            parse_game_filter(bad)

    def test_overlong_regex_pattern(self):
        bad = json.dumps(
            {
                "name": {
                    "modifier": "MATCHES_REGEX",
                    "value": "a" * (MAX_REGEX_PATTERN_LENGTH + 1),
                }
            }
        )
        with pytest.raises(FilterError, match="regex pattern too long"):
            parse_game_filter(bad)

    def test_redos_nested_quantifier(self):
        """The classic catastrophic-backtracking signature ``(a+)+$`` is rejected at
        parse — otherwise SQLite's per-row REGEXP would hang a worker."""
        bad = json.dumps({"name": {"modifier": "MATCHES_REGEX", "value": "(a+)+$"}})
        with pytest.raises(FilterError, match="too complex"):
            parse_game_filter(bad)

    def test_redos_nested_lazy_quantifier(self):
        """A lazy inner repeat (MIN_REPEAT) is caught too — backtracking is just as
        catastrophic."""
        bad = json.dumps({"name": {"modifier": "MATCHES_REGEX", "value": "(a+?)+"}})
        with pytest.raises(FilterError, match="too complex"):
            parse_game_filter(bad)

    def test_redos_guard_applies_to_not_matches_regex(self):
        """NOT_MATCHES_REGEX runs the same per-row engine, so it is guarded too."""
        bad = json.dumps({"name": {"modifier": "NOT_MATCHES_REGEX", "value": "(a*)*"}})
        with pytest.raises(FilterError, match="too complex"):
            parse_game_filter(bad)

    def test_non_string_regex_value(self):
        """A hand-edited non-string regex value must raise FilterError, not a
        TypeError from len()/re.compile escaping the boundary."""
        bad = json.dumps({"name": {"modifier": "MATCHES_REGEX", "value": 123}})
        with pytest.raises(FilterError, match="expected a regex string"):
            parse_game_filter(bad)

    def test_benign_regex_still_parses(self):
        """A sane pattern — including a single (non-nested) quantifier — is accepted."""
        good = json.dumps(
            {"name": {"modifier": "MATCHES_REGEX", "value": "hal+o|zelda"}}
        )
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_redos_lookalike_value_allowed_for_non_regex_modifier(self):
        """The guard is scoped to the regex modifiers: a ``(a+)+`` value under
        INCLUDES is a literal substring match, never compiled, so it is accepted."""
        good = json.dumps({"name": {"modifier": "INCLUDES", "value": "(a+)+"}})
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise


class TestFilterErrorLogging:
    """Issue #203: ``apply_structured_filter`` must log a server-side warning
    (entity/user/path/exc) when it drops an invalid ``?filter=``, so operators
    can spot DoS-probing — without changing the fail-open toast/None UX."""

    def _request(self, path="/game/"):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.cookie import CookieStorage
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = AnonymousUser()
        # apply_structured_filter queues messages.warning, which needs storage.
        # CookieStorage needs no session middleware (FallbackStorage would).
        setattr(request, "_messages", CookieStorage(request))
        return request

    def test_invalid_filter_logs_warning_and_fails_open(self, capture_games_logger):
        from games.views.filtering import apply_structured_filter

        request = self._request()
        bad = json.dumps({"name": {"modifier": "BOGUS", "value": "x"}})
        with capture_games_logger() as caplog:
            result = apply_structured_filter(request, parse_game_filter, bad)

        assert result is None  # fail-open unchanged
        records = [record for record in caplog.records if record.name == "games"]
        # Assert each interpolated field by its labelled token so a swapped or
        # dropped positional arg (entity/user/path/exc) is caught, not just the
        # message prefix.
        assert any(
            record.levelno == logging.WARNING
            and "rejected invalid filter" in record.getMessage()
            and "entity=game" in record.getMessage()
            and "user=AnonymousUser" in record.getMessage()
            and "path=/game/" in record.getMessage()
            and "Unknown filter modifier" in record.getMessage()  # the exc detail
            for record in records
        )

    @pytest.mark.parametrize(
        "parse, expected_entity",
        [
            (parse_game_filter, "game"),
            (parse_session_filter, "session"),
            (parse_purchase_filter, "purchase"),
            (parse_device_filter, "device"),
            (parse_platform_filter, "platform"),
            (parse_playevent_filter, "playevent"),
        ],
    )
    def test_entity_label_derived_for_every_parser(
        self, parse, expected_entity, capture_games_logger
    ):
        """The log line's ``entity=`` token is derived from ``parse.__name__``;
        verify the derivation for all six ``parse_*_filter`` callers, not just
        ``game`` — a parser renamed off-convention would silently mislabel."""
        from games.views.filtering import apply_structured_filter

        request = self._request()
        # Malformed JSON raises FilterError in every parser regardless of which
        # fields that entity's filter declares, so the same input exercises all
        # six derivation cases.
        bad = "{not json"
        with capture_games_logger() as caplog:
            result = apply_structured_filter(request, parse, bad)

        assert result is None
        records = [record for record in caplog.records if record.name == "games"]
        assert any(
            f"entity={expected_entity}" in record.getMessage() for record in records
        )

    def test_valid_filter_logs_nothing(self, capture_games_logger):
        from games.views.filtering import apply_structured_filter

        request = self._request()
        good = json.dumps({"name": {"modifier": "INCLUDES", "value": "halo"}})
        with capture_games_logger() as caplog:
            result = apply_structured_filter(request, parse_game_filter, good)

        assert result is not None
        assert not [record for record in caplog.records if record.name == "games"]


class TestUnknownSortLogging:
    """Issue #207: ``warn_unknown_sort`` must log a server-side warning
    (entity/user/path/keys) when it drops an unknown ``?sort=`` key, mirroring the
    #203 filter boundary — while keeping the existing per-key toast UX."""

    def _request(self, path="/game/"):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.cookie import CookieStorage
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = AnonymousUser()
        setattr(request, "_messages", CookieStorage(request))
        return request

    def test_unknown_sort_logs_warning_and_toasts(self, capture_games_logger):
        from games.views.filtering import warn_unknown_sort

        request = self._request()
        with capture_games_logger() as caplog:
            warn_unknown_sort(request, ["bogus", "alsobad"], entity="game")

        records = [record for record in caplog.records if record.name == "games"]
        # Assert each interpolated field by its labelled token, matching the filter
        # test, so a swapped/dropped positional arg is caught.
        assert any(
            record.levelno == logging.WARNING
            and "rejected unknown sort field(s)" in record.getMessage()
            and "entity=game" in record.getMessage()
            and "user=AnonymousUser" in record.getMessage()
            and "path=/game/" in record.getMessage()
            and "bogus" in record.getMessage()
            and "alsobad" in record.getMessage()
            for record in records
        )
        # Existing per-key toast UX is preserved (one message per unknown key).
        messages = list(request._messages)  # type: ignore[attr-defined]
        assert len(messages) == 2

    def test_no_unknown_logs_nothing(self, capture_games_logger):
        from games.views.filtering import warn_unknown_sort

        request = self._request()
        with capture_games_logger() as caplog:
            warn_unknown_sort(request, [], entity="game")

        assert not [record for record in caplog.records if record.name == "games"]
        assert not list(request._messages)  # type: ignore[attr-defined]

    def test_newline_in_key_does_not_forge_log_line(self, capture_games_logger):
        """CWE-117: ``parse_sort_terms`` only strips outer whitespace, so an
        embedded newline reaches ``unknown`` verbatim. The log message must
        ``repr()`` the key so the newline is escaped, not emitted raw — otherwise
        an attacker could forge log lines via ``?sort=a%0Afake``."""
        from games.views.filtering import warn_unknown_sort

        request = self._request()
        with capture_games_logger() as caplog:
            warn_unknown_sort(request, ["a\nFORGED"], entity="game")

        records = [record for record in caplog.records if record.name == "games"]
        assert records
        message = records[0].getMessage()
        assert "\n" not in message  # the raw newline must not survive into the line
        assert "\\n" in message  # repr escaped it
        assert "FORGED" in message


def _nest_relation(levels: int) -> dict:
    """Build ``levels`` deep of alternating session_filter <-> game_filter relation
    descent (the cyclic DoS vector named in issue #186). The outermost class is
    GameFilter (parse_game_filter), so position 0 must be a key GameFilter accepts
    (session_filter); SessionFilter at position 1 accepts game_filter; and so on.
    Each nested dict is one from_json frame, so ``levels`` == the recursion depth
    the guard counts. The empty innermost filter keeps the chain valid — an empty
    sub-filter parses and its to_q() does not raise."""
    node: dict = {}
    for position in range(levels - 1, -1, -1):
        key = "session_filter" if position % 2 == 0 else "game_filter"
        node = {key: node}
    return node


def _nest_operator(levels: int) -> dict:
    """Build ``levels`` deep of nested ``AND`` operator groups (the same-entity
    recursion site). Each AND-list element is one from_json frame."""
    node: dict = {"name": {"modifier": "INCLUDES", "value": "x"}}
    for _ in range(levels):
        node = {"AND": [node]}
    return node


def _deep_json_string(levels: int) -> str:
    """A ``levels``-deep nested-``AND`` blob built as a raw string, NOT via
    json.dumps — dumping a dict this deep would itself overflow and die in the
    harness, masking the point. ``json.loads`` of this overflows the C stack
    (RecursionError) before OperatorFilter.from_json's depth guard can run, so it
    exercises the pre-parse vector (issue #186)."""
    return '{"AND":[' * levels + "{}" + "]}" * levels


class TestFilterDepthGuard:
    """Issue #186: a hand-edited / shared cyclic or pathologically deep ``?filter=``
    must raise FilterError at parse, never recurse into a RecursionError/500 or a
    runaway nested-subquery build (DoS). The guard lives in OperatorFilter.from_json
    and bounds both recursion sites (AND/OR/NOT and cross-entity relation descent)."""

    def test_relation_nesting_past_cap_raises(self):
        bad = json.dumps(_nest_relation(MAX_FILTER_DEPTH + 5))
        with pytest.raises(FilterError, match="too deep"):
            parse_game_filter(bad)

    def test_operator_nesting_past_cap_raises(self):
        bad = json.dumps(_nest_operator(MAX_FILTER_DEPTH + 5))
        with pytest.raises(FilterError, match="too deep"):
            parse_game_filter(bad)

    def test_post_parse_depth_raises_filter_error(self):
        """A well-formed but deep blob (json.loads succeeds) must be cut by the
        from_json depth guard as a catchable FilterError, never an uncaught
        RecursionError that would 500 the list view."""
        bad = json.dumps(_nest_relation(500))
        with pytest.raises(FilterError, match="too deep"):
            parse_game_filter(bad)

    def test_json_loads_recursion_raises_filter_error_not_500(self):
        """A blob deep enough that json.loads itself overflows the C stack
        (RecursionError, raised *before* the from_json guard runs) must still
        surface as a catchable FilterError — otherwise it escapes the view's
        FilterError boundary and 500s. Reachable un-capped via a stored
        FilterPreset blob (issue #186)."""
        bad = _deep_json_string(100_000)
        with pytest.raises(FilterError, match="too deep"):
            parse_game_filter(bad)

    def test_nesting_within_cap_parses(self):
        """A filter nested below the cap (covers the builder's <=5 soft cap with
        headroom) parses and builds its Q without raising — guards against an
        off-by-one that would reject legitimately built filters."""
        good = json.dumps(_nest_relation(MAX_FILTER_DEPTH - 1))
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_nesting_at_cap_parses(self):
        """Exactly at the cap is accepted (the guard rejects only *past* the cap)."""
        good = json.dumps(_nest_relation(MAX_FILTER_DEPTH))
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_operator_nesting_within_cap_parses(self):
        good = json.dumps(_nest_operator(MAX_FILTER_DEPTH - 1))
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_mixed_operator_and_relation_share_one_depth_budget(self):
        """Both recursion sites increment the same ``_depth``, so a tree alternating
        AND groups with relation descents sums their frames against one budget — each
        kind does not get its own cap. Build the chain outer->inner tracking the
        current entity so every key is valid (AND preserves the entity; session_filter
        descends game->session, game_filter descends session->game), then a
        combined-deep-but-modest-per-kind blob raises."""
        entity = "game"
        keys: list[str] = []
        for index in range(MAX_FILTER_DEPTH + 4):
            if index % 2 == 0:
                keys.append("AND")
            elif entity == "game":
                keys.append("session_filter")
                entity = "session"
            else:
                keys.append("game_filter")
                entity = "game"
        node: dict = {}
        for key in reversed(keys):
            node = {"AND": [node]} if key == "AND" else {key: node}
        with pytest.raises(FilterError, match="too deep"):
            parse_game_filter(json.dumps(node))

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


class TestFilterBreadthGuard:
    """Issue #204: a shallow-but-very-wide ``?filter=`` (a huge AND/OR/NOT sibling
    list, a long field_comparisons list, or a massive set-criterion value/excludes
    array) must raise FilterError at parse, never amplify a tiny blob into an
    expensive parse + Q build (DoS). The depth guard bounds nesting, not width;
    these caps bound the three per-list breadth vectors."""

    def test_operator_list_past_cap_raises(self):
        bad = json.dumps({"AND": [{} for _ in range(MAX_FILTER_BREADTH + 1)]})
        with pytest.raises(FilterError, match="operator list too long"):
            parse_game_filter(bad)

    def test_operator_list_at_cap_parses(self):
        good = json.dumps({"AND": [{} for _ in range(MAX_FILTER_BREADTH)]})
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_field_comparisons_past_cap_raises(self):
        entry = {
            "left": "date_purchased",
            "right": "date_refunded",
            "modifier": "LESS_THAN",
        }
        bad = json.dumps(
            {"field_comparisons": [entry for _ in range(MAX_FIELD_COMPARISONS + 1)]}
        )
        with pytest.raises(FilterError, match="field_comparisons list too long"):
            parse_purchase_filter(bad)

    def test_field_comparisons_at_cap_parses(self):
        entry = {
            "left": "date_purchased",
            "right": "date_refunded",
            "modifier": "LESS_THAN",
        }
        good = json.dumps(
            {"field_comparisons": [entry for _ in range(MAX_FIELD_COMPARISONS)]}
        )
        result = parse_purchase_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_set_value_past_cap_raises(self):
        bad = json.dumps(
            {
                "platform": {
                    "value": list(range(MAX_SET_VALUES + 1)),
                    "modifier": "INCLUDES",
                }
            }
        )
        with pytest.raises(FilterError, match="set list too long"):
            parse_game_filter(bad)

    def test_set_excludes_past_cap_raises(self):
        bad = json.dumps(
            {
                "platform": {
                    "value": [],
                    "excludes": list(range(MAX_SET_VALUES + 1)),
                    "modifier": "INCLUDES",
                }
            }
        )
        with pytest.raises(FilterError, match="set list too long"):
            parse_game_filter(bad)

    def test_set_value_at_cap_parses(self):
        good = json.dumps(
            {
                "platform": {
                    "value": list(range(MAX_SET_VALUES)),
                    "modifier": "INCLUDES",
                }
            }
        )
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_set_excludes_at_cap_parses(self):
        good = json.dumps(
            {
                "platform": {
                    "value": [],
                    "excludes": list(range(MAX_SET_VALUES)),
                    "modifier": "INCLUDES",
                }
            }
        )
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise

    def test_set_string_value_rejected_not_char_split(self):
        """A hand-edited *string* value on a ChoiceCriterion field (whose ``_coerce``
        is None, so type-coercion wouldn't reject it first) must raise — it would
        otherwise be silently split into characters by ``_strip_set_label`` (a
        quietly-wrong filter)."""
        bad = json.dumps({"status": {"value": "u"}})
        with pytest.raises(FilterError, match="must be a list"):
            parse_game_filter(bad)

    def test_set_scalar_value_rejected_not_500(self):
        """A hand-edited *scalar* (non-iterable) value must raise FilterError, not
        escape ``_strip_set_label`` as an uncaught ``TypeError`` (a 500 outside the
        filter error boundary)."""
        bad = json.dumps({"platform": {"value": 5, "modifier": "INCLUDES"}})
        with pytest.raises(FilterError, match="must be a list"):
            parse_game_filter(bad)

    def test_set_null_value_normalizes_to_empty(self):
        """A JSON ``null`` value/excludes normalizes to an empty list (mirrors the
        AND/OR/NOT None->[] handling) rather than 500-ing in ``_strip_set_label``."""
        good = json.dumps({"platform": {"value": None, "modifier": "INCLUDES"}})
        result = parse_game_filter(good)
        assert result is not None
        result.to_q()  # does not raise


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

    def test_aggregate_integral_value_round_trips_as_int(self):
        # A count bound stays int (5, not 5.0) so saved-filter JSON stays clean;
        # a fractional sum/avg bound keeps its float.
        result = parse_game_filter(
            json.dumps({"session_count": {"modifier": "GREATER_THAN", "value": 5}})
        )
        assert result is not None and result.session_count is not None
        assert result.session_count.value == 5
        assert isinstance(result.session_count.value, int)
        fractional = parse_game_filter(
            json.dumps({"session_average": {"modifier": "GREATER_THAN", "value": 3.5}})
        )
        assert fractional is not None and fractional.session_average is not None
        assert fractional.session_average.value == 3.5

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
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.EQUALS,
                left_group="date",
                right_group="date",
            )
            == Q(date_refunded=F("date_purchased")) & guards
        )

    def test_helper_not_equals(self):
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.NOT_EQUALS,
                left_group="date",
                right_group="date",
            )
            == ~Q(date_refunded=F("date_purchased")) & guards
        )

    def test_helper_greater_than(self):
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.GREATER_THAN,
                left_group="date",
                right_group="date",
            )
            == Q(date_refunded__gt=F("date_purchased")) & guards
        )

    def test_helper_less_than(self):
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.LESS_THAN,
                left_group="date",
                right_group="date",
            )
            == Q(date_refunded__lt=F("date_purchased")) & guards
        )

    def test_helper_includes(self):
        guards = Q(name__isnull=False) & Q(sort_name__isnull=False)
        assert (
            _field_comparison_to_q(
                "name",
                "sort_name",
                Modifier.INCLUDES,
                left_group="string",
                right_group="string",
            )
            == Q(name__icontains=F("sort_name")) & guards
        )

    def test_helper_excludes(self):
        guards = Q(name__isnull=False) & Q(sort_name__isnull=False)
        assert (
            _field_comparison_to_q(
                "name",
                "sort_name",
                Modifier.EXCLUDES,
                left_group="string",
                right_group="string",
            )
            == ~Q(name__icontains=F("sort_name")) & guards
        )

    def test_helper_greater_than_or_equal(self):
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.GREATER_THAN_OR_EQUAL,
                left_group="date",
                right_group="date",
            )
            == Q(date_refunded__gte=F("date_purchased")) & guards
        )

    def test_helper_less_than_or_equal(self):
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert (
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.LESS_THAN_OR_EQUAL,
                left_group="date",
                right_group="date",
            )
            == Q(date_refunded__lte=F("date_purchased")) & guards
        )

    def test_helper_unsupported_modifier_raises(self):
        with pytest.raises(FilterError, match="Unsupported modifier"):
            _field_comparison_to_q(
                "date_refunded",
                "date_purchased",
                Modifier.BETWEEN,
                left_group="date",
                right_group="date",
            )

    # ── date-granular comparison (granularity="date") ────────────────────────

    def test_helper_date_granular_equals(self):
        from django.db.models.functions import TruncDate

        guards = Q(timestamp_start__isnull=False) & Q(timestamp_end__isnull=False)
        assert (
            _field_comparison_to_q(
                "timestamp_start",
                "timestamp_end",
                Modifier.EQUALS,
                "date",
                left_group="datetime",
                right_group="datetime",
            )
            == Q(timestamp_start__date=TruncDate(F("timestamp_end"))) & guards
        )

    def test_helper_date_granular_gte(self):
        from django.db.models.functions import TruncDate

        guards = Q(timestamp_start__isnull=False) & Q(timestamp_end__isnull=False)
        assert (
            _field_comparison_to_q(
                "timestamp_start",
                "timestamp_end",
                Modifier.GREATER_THAN_OR_EQUAL,
                "date",
                left_group="datetime",
                right_group="datetime",
            )
            == Q(timestamp_start__date__gte=TruncDate(F("timestamp_end"))) & guards
        )

    def test_helper_date_granular_not_equals(self):
        from django.db.models.functions import TruncDate

        guards = Q(timestamp_start__isnull=False) & Q(timestamp_end__isnull=False)
        assert (
            _field_comparison_to_q(
                "timestamp_start",
                "timestamp_end",
                Modifier.NOT_EQUALS,
                "date",
                left_group="datetime",
                right_group="datetime",
            )
            == ~Q(timestamp_start__date=TruncDate(F("timestamp_end"))) & guards
        )

    def test_to_q_raises_runtime_error(self):
        """to_q() requires model context; callers must use _apply_operators."""
        criterion = FieldComparisonCriterion(
            left="timestamp_start",
            right="timestamp_end",
            modifier=Modifier.LESS_THAN_OR_EQUAL,
            granularity="date",
        )
        with pytest.raises(RuntimeError, match="model context"):
            criterion.to_q()

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

        guards = Q(timestamp_start__isnull=False) & Q(timestamp_end__isnull=False)
        assert (
            _field_comparison_to_q(
                "timestamp_start",
                "timestamp_end",
                Modifier.GREATER_THAN,
                "date",
                left_group="datetime",
                right_group="datetime",
            )
            == Q(timestamp_start__date__gt=TruncDate(F("timestamp_end"))) & guards
        )
        assert (
            _field_comparison_to_q(
                "timestamp_start",
                "timestamp_end",
                Modifier.LESS_THAN,
                "date",
                left_group="datetime",
                right_group="datetime",
            )
            == Q(timestamp_start__date__lt=TruncDate(F("timestamp_end"))) & guards
        )

    # ── FieldComparisonCriterion.to_q ────────────────────────────────────────

    def test_to_q_raises_runtime_error_no_args(self):
        """to_q() raises RuntimeError — operand groups needed; use _apply_operators."""
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        with pytest.raises(RuntimeError, match="model context"):
            criterion.to_q()

    def test_to_q_raises_runtime_error_with_field_name(self):
        """to_q(field_name=...) also raises — context cannot be injected via field_name."""
        criterion = FieldComparisonCriterion(
            left="a", right="b", modifier=Modifier.LESS_THAN
        )
        with pytest.raises(RuntimeError, match="model context"):
            criterion.to_q("ignored_field")

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

    def test_entries_have_value_label_group_operators_keys(self):
        from games.models import Game

        for entry in comparable_columns(Game):
            assert set(entry.keys()) == {
                "value",
                "label",
                "group",
                "operators",
                "source",
                "multivalued",
            }

    def test_operators_match_allowed_comparison_modifiers(self):
        """Each column carries the server-derived operator list (#152) so the TS
        widget renders it directly instead of re-deriving group->operators."""
        from games.models import Game

        from common.criteria import _allowed_comparison_modifiers

        columns = self._by_value(Game)
        # string adds containment; number is ordered-only; bool is equality-only.
        assert columns["name"]["operators"] == [
            modifier.value for modifier in _allowed_comparison_modifiers("string")
        ]
        assert "INCLUDES" in columns["name"]["operators"]
        assert columns["year_released"]["operators"] == [
            modifier.value for modifier in _allowed_comparison_modifiers("number")
        ]
        assert columns["mastered"]["operators"] == ["EQUALS", "NOT_EQUALS"]

    def test_operators_for_datetime_and_date_groups(self):
        """Close the group matrix: datetime (Session) and date (Purchase) carry
        the ordered-only operator set, like number."""
        from games.models import Purchase, Session

        from common.criteria import _allowed_comparison_modifiers

        ordered = [
            modifier.value for modifier in _allowed_comparison_modifiers("number")
        ]
        assert self._by_value(Session)["timestamp_end"]["operators"] == ordered
        assert self._by_value(Purchase)["date_purchased"]["operators"] == ordered

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
        # verbose_name="Session start"/"Session end" drives the comparison label.
        assert columns["timestamp_start"]["label"] == "Session Start"
        assert columns["timestamp_end"]["label"] == "Session End"

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
        """Own columns are sorted by label; each FK block is sorted by its column
        label too.  The global list is NOT re-sorted — FK blocks follow own
        columns in _meta declaration order."""
        from games.models import Session

        columns = comparable_columns(Session)
        own_source = "Session"
        own_labels = [
            entry["label"] for entry in columns if entry["source"] == own_source
        ]
        assert own_labels == sorted(own_labels, key=str.lower)
        # Each FK block is internally sorted by column label too.
        fk_sources = {
            entry["source"] for entry in columns if entry["source"] != own_source
        }
        assert fk_sources  # Session has FK hops (game, device) — guard the loop
        for fk_source in fk_sources:
            fk_labels = [
                entry["label"] for entry in columns if entry["source"] == fk_source
            ]
            assert fk_labels == sorted(fk_labels, key=str.lower)


class TestComparableColumnsCrossModel:
    """comparable_columns enumerates related-model columns via forward FK hops."""

    def test_session_includes_game_and_device_columns(self):
        from games.models import Session

        columns = comparable_columns(Session)
        values = {column["value"] for column in columns}
        assert "game__year_released" in values
        assert "device__name" in values

    def test_purchase_includes_both_fk_sources(self):
        # Purchase has TWO forward FKs: platform and related_game, plus its own source.
        from games.models import Purchase

        columns = comparable_columns(Purchase)
        sources = {column["source"] for column in columns}
        assert "Purchase" in sources  # own columns
        assert len(sources) >= 3
        # related_game carries an explicit verbose_name="Base game" (#283) so it
        # reads as "Base Game", not the Django default "Related Game".
        assert "Base Game" in sources
        by_value = {column["value"]: column for column in columns}
        base_game_year = by_value["related_game__year_released"]
        assert base_game_year["source"] == "Base Game"
        assert base_game_year["label"].startswith("Base Game: ")

    def test_related_labels_are_qualified_and_own_labels_bare(self):
        from games.models import Session

        columns = comparable_columns(Session)
        by_value = {column["value"]: column for column in columns}
        assert by_value["note"]["source"] == "Session"
        assert ": " not in by_value["note"]["label"]
        related = by_value["game__year_released"]
        assert related["source"] == "Game"
        assert related["label"].startswith("Game: ")

    def test_own_columns_first_then_relation_blocks(self):
        from games.models import Session

        columns = comparable_columns(Session)
        own_source = "Session"
        # Own-model block comes first; FK blocks follow in _meta declaration order.
        first_non_own = next(
            (
                index
                for index, column in enumerate(columns)
                if column["source"] != own_source
            ),
            len(columns),
        )
        assert all(column["source"] == own_source for column in columns[:first_non_own])
        own_labels = [
            column["label"] for column in columns if column["source"] == own_source
        ]
        assert own_labels == sorted(own_labels, key=str.lower)

    def test_m2m_and_reverse_enumerated_as_multivalued(self):
        # #282: M2M + reverse relations are now enumerated as multi-valued operand
        # blocks (marked so the widget offers a quantifier).
        from games.models import Game, Purchase, Session

        purchase_columns = {c["value"]: c for c in comparable_columns(Purchase)}
        assert "games__name" in purchase_columns
        assert purchase_columns["games__name"]["multivalued"] is True

        game_columns = {c["value"]: c for c in comparable_columns(Game)}
        assert "sessions__note" in game_columns
        assert game_columns["sessions__note"]["multivalued"] is True

        # Own + to-one-FK columns stay single-valued.
        assert game_columns["name"]["multivalued"] is False

        # The #282 headline path (Session → game → playevents) is a to-one-prefixed
        # multi-valued operand.
        session_columns = {c["value"]: c for c in comparable_columns(Session)}
        assert "game__playevents__ended" in session_columns
        assert session_columns["game__playevents__ended"]["multivalued"] is True

    def test_platform_and_device_have_no_to_one_related_columns(self):
        # Platform/Device declare no forward FKs, so every *single-valued* column
        # is own-model (model-sourced). Their reverse relations (Platform.games,
        # Device.sessions) are enumerated as multi-valued blocks (#282), so allow
        # those to carry a relation source.
        from games.models import Device, Platform

        for model in (Platform, Device):
            model_source = str(model._meta.verbose_name).title()
            for column in comparable_columns(model):
                if not column["multivalued"]:
                    assert column["source"] == model_source


# ── T3 — OperatorFilter field_comparisons wiring ─────────────────────────────


@dataclass
class _PurchaseStub(OperatorFilter):
    AND: list[_PurchaseStub] = dc_field(default_factory=list)
    OR: list[_PurchaseStub] = dc_field(default_factory=list)
    NOT: list[_PurchaseStub] = dc_field(default_factory=list)

    @classmethod
    def _comparison_model(cls):
        from games.models import Purchase

        return Purchase


@dataclass
class _NoModelStub(OperatorFilter):
    """Stub that does NOT override _comparison_model — base returns None."""

    AND: list[_NoModelStub] = dc_field(default_factory=list)
    OR: list[_NoModelStub] = dc_field(default_factory=list)
    NOT: list[_NoModelStub] = dc_field(default_factory=list)


@dataclass
class _SessionStub(OperatorFilter):
    AND: list[_SessionStub] = dc_field(default_factory=list)
    OR: list[_SessionStub] = dc_field(default_factory=list)
    NOT: list[_SessionStub] = dc_field(default_factory=list)

    @classmethod
    def _comparison_model(cls):
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
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert stub.to_q() == Q(date_refunded__lt=F("date_purchased")) & guards

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
        guards = Q(timestamp_start__isnull=False) & Q(timestamp_end__isnull=False)
        assert (
            stub.to_q()
            == Q(timestamp_start__date__lte=TruncDate(F("timestamp_end"))) & guards
        )

    def test_date_granularity_on_non_temporal_raises(self):
        # Under the new space rules, date space accepts date and datetime
        # operands; a string field is outside the accepted group set.
        stub = _PurchaseStub(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name",
                    right="date_purchased",
                    modifier=Modifier.EQUALS,
                    granularity="date",
                )
            ]
        )
        with pytest.raises(FilterError, match="cannot take part in"):
            stub.to_q()

    def test_includes_on_datetime_rejected_before_granularity(self):
        """INCLUDES in a non-raw space is rejected before SQL is built.

        Non-raw spaces (date, year) restrict modifiers to
        Modifier.for_ordered_field_comparisons(), which excludes INCLUDES/EXCLUDES
        (string containment, raw-space/string-group only). The modifier gate fires
        before any SQL is emitted, so the nonsense __date__icontains query is
        unreachable."""
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
        guards = Q(price_currency__isnull=False) & Q(converted_currency__isnull=False)
        assert (
            stub.to_q() == Q(price_currency__icontains=F("converted_currency")) & guards
        )

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
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert restored.to_q() == Q(date_refunded__lt=F("date_purchased")) & guards

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
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert pf.to_q() == Q(date_refunded__lt=F("date_purchased")) & guards

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
        guards = Q(date_refunded__isnull=False) & Q(date_purchased__isnull=False)
        assert parsed.to_q() == Q(date_refunded__lt=F("date_purchased")) & guards

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
        guards = Q(timestamp_end__isnull=False) & Q(timestamp_start__isnull=False)
        assert sf.to_q() == Q(timestamp_end__lt=F("timestamp_start")) & guards


# ── T4b — comparison spaces ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestComparisonSpaces:
    def test_year_space_accepts_two_datetimes(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start",
                    right="timestamp_end",
                    modifier=Modifier.EQUALS,
                    granularity="year",
                )
            ]
        )
        filter_object.to_q()  # must not raise

    def test_date_space_accepts_date_vs_datetime(self):
        # PlayEvent.started is a DateField, created_at a DateTimeField
        filter_object = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started",
                    right="created_at",
                    modifier=Modifier.EQUALS,
                    granularity="date",
                )
            ]
        )
        filter_object.to_q()

    def test_raw_space_keeps_same_group_rule(self):
        filter_object = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started",
                    right="created_at",
                    modifier=Modifier.EQUALS,
                )
            ]
        )
        with pytest.raises(FilterError, match="cannot compare"):
            filter_object.to_q()

    def test_year_space_rejects_string_operand(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note",
                    right="timestamp_start",
                    modifier=Modifier.EQUALS,
                    granularity="year",
                )
            ]
        )
        with pytest.raises(FilterError, match="year"):
            filter_object.to_q()

    def test_non_raw_space_rejects_containment_modifiers(self):
        filter_object = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start",
                    right="timestamp_end",
                    modifier=Modifier.INCLUDES,
                    granularity="year",
                )
            ]
        )
        with pytest.raises(FilterError, match="not allowed"):
            filter_object.to_q()

    def test_from_json_accepts_year_granularity(self):
        parsed = FieldComparisonCriterion.from_json(
            {
                "left": "timestamp_start",
                "right": "timestamp_end",
                "modifier": "EQUALS",
                "granularity": "year",
            }
        )
        assert parsed is not None and parsed.granularity == "year"

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

    def test_year_granularity_roundtrips_json(self):
        criterion = FieldComparisonCriterion(
            left="timestamp_start",
            right="timestamp_end",
            modifier=Modifier.EQUALS,
            granularity="year",
        )
        assert criterion.to_json()["granularity"] == "year"


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

    def test_not_equals_strict_null_semantics(self):
        """date_refunded NOT_EQUALS date_purchased with strict two-valued NULL semantics (#169):
        - A (different dates, both set) → included.
        - B (equal dates) → excluded by NOT_EQUALS.
        - C (NULL date_refunded) → EXCLUDED: the explicit isnull=False guard fires.
        Previously C was included (Django's ~Q treated NULL as "not equal"); strict
        semantics require BOTH operands to be non-NULL for any match.
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
        # C: date_refunded is NULL → EXCLUDED (strict NULL guard, behavior change from #169)
        Purchase.objects.create(
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
        assert result == {purchase_a}

    def test_not_equals_strict_null_symmetric(self):
        """NOT_EQUALS strict two-valued semantics: BOTH operand NULLs are excluded (#169).

        The explicit isnull=False guards on both operand paths ensure symmetry —
        a NULL on either side excludes the row, regardless of which side is nullable.
        Previously ~Q included rows with NULL on either nullable side.
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
        # left NULL → EXCLUDED (strict guard)
        PlayEvent.objects.create(game=game, ended=datetime.date(2024, 4, 1))
        # right NULL → EXCLUDED (strict guard, symmetric)
        PlayEvent.objects.create(game=game, started=datetime.date(2024, 5, 1))

        play_filter = PlayEventFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="started", right="ended", modifier=Modifier.NOT_EQUALS
                )
            ]
        )
        result = set(PlayEvent.objects.filter(play_filter.to_q()))
        assert result == {differ}

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

    def test_cross_model_includes_empty_string_right_operand(self):
        """INCLUDES where the right operand is a cross-model column with value "".

        Empty-string caveat (documented in FieldComparisonCriterion): "" is a
        substring of every non-NULL string, so ``left INCLUDES right`` where
        right == "" matches every row whose left operand is non-NULL — including
        rows where both operands are "".

        This test pins the behaviour cross-model: Session.note INCLUDES
        game__wikidata, where the game has wikidata="" (the empty default).
        - HIT: note is non-empty, game.wikidata is "" → matches (left contains "")
        - NO_HIT_NULL_GAME: game is None → excluded by the strict NULL guard on
          game__wikidata.
        """
        from django.utils import timezone

        from games.filters import SessionFilter
        from games.models import Game, Platform, Session

        platform, _ = Platform.objects.get_or_create(
            name="CrossModelIncludesTest", icon="crossmodelincludestest"
        )
        game_with_empty_wikidata = Game.objects.create(
            name="WikilessGame",
            platform=platform,
            wikidata="",  # the default — empty string, not NULL
        )

        # HIT: note is non-empty; game.wikidata is "" → "" is substring of note
        session_hit = Session.objects.create(
            timestamp_start=timezone.now(),
            note="some note",
            game=game_with_empty_wikidata,
        )

        # NULL guard: no game → game__wikidata is NULL → excluded
        session_no_game = Session.objects.create(
            timestamp_start=timezone.now(),
            note="also non-empty",
            game=None,
        )

        session_filter = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note",
                    right="game__wikidata",
                    modifier=Modifier.INCLUDES,
                )
            ]
        )
        result = set(Session.objects.filter(session_filter.to_q()))
        assert session_hit in result
        assert session_no_game not in result


class TestStrictNullSemantics:
    """#169: a row matches only if BOTH operands are non-NULL — every modifier,
    either side. Kills the raw-ORM asymmetry (A≠B vs B≠A) and supersedes the
    old NULL-counts-as-not-equal same-model behavior."""

    @pytest.fixture
    def game(self, db):
        from games.models import Game, Platform

        platform, _ = Platform.objects.get_or_create(
            name="NullSemanticsTest", icon="nullsemanticstest"
        )
        return Game.objects.create(name="NullGame", platform=platform)

    @pytest.fixture
    def session_without_game(self, db):
        from games.models import Session

        from django.utils import timezone

        return Session.objects.create(
            timestamp_start=timezone.now(),
            note="orphan",
            game=None,
        )

    def test_not_equals_excludes_null_operand_rows_lookup_side(
        self, session_without_game
    ):
        from games.models import Session

        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="game__name",
                    right="note",
                    modifier=Modifier.NOT_EQUALS,
                )
            ]
        ).to_q()
        assert session_without_game not in Session.objects.filter(q)

    def test_not_equals_excludes_null_operand_rows_expression_side(
        self, session_without_game
    ):
        from games.models import Session

        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note",
                    right="game__name",
                    modifier=Modifier.NOT_EQUALS,
                )
            ]
        ).to_q()
        assert session_without_game not in Session.objects.filter(q)

    def test_not_equals_is_side_symmetric(self, db, game, session_without_game):
        from games.models import Session

        from django.utils import timezone

        Session.objects.create(
            timestamp_start=timezone.now(),
            note="differs",
            game=game,
        )
        left_form = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="game__name", right="note", modifier=Modifier.NOT_EQUALS
                )
            ]
        ).to_q()
        right_form = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="note", right="game__name", modifier=Modifier.NOT_EQUALS
                )
            ]
        ).to_q()
        assert list(Session.objects.filter(left_form)) == list(
            Session.objects.filter(right_form)
        )

    def test_same_model_not_equals_now_excludes_null_rows(self, db):
        # Behavior change pinned: previously included (NULL counted as "not equal").
        from games.models import Session

        from django.utils import timezone

        session = Session.objects.create(
            timestamp_start=timezone.now(),
            timestamp_end=None,
        )
        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_end",
                    right="timestamp_start",
                    modifier=Modifier.NOT_EQUALS,
                )
            ]
        ).to_q()
        assert session not in Session.objects.filter(q)

    def test_equals_includes_null_guards(self):
        q = _field_comparison_to_q(
            "timestamp_start",
            "timestamp_end",
            Modifier.EQUALS,
            "raw",
            left_group="datetime",
            right_group="datetime",
        )
        assert str(q).count("isnull") == 2

    def test_not_equals_includes_null_guards(self):
        q = _field_comparison_to_q(
            "timestamp_start",
            "timestamp_end",
            Modifier.NOT_EQUALS,
            "raw",
            left_group="datetime",
            right_group="datetime",
        )
        assert str(q).count("isnull") == 2


class TestYearProjection:
    def test_year_space_headline_example(self, db):
        # Session started in the game's release year — the #169 headline query.
        from datetime import UTC, datetime

        from games.models import Game, Platform, Session

        platform, _ = Platform.objects.get_or_create(
            name="YearProjTest", icon="yearprojtest"
        )
        game = Game.objects.create(name="Doom", year_released=2020, platform=platform)
        hit = Session.objects.create(
            game=game,
            timestamp_start=datetime(2020, 6, 1, tzinfo=UTC),
        )
        miss = Session.objects.create(
            game=game,
            timestamp_start=datetime(2021, 6, 1, tzinfo=UTC),
        )
        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="timestamp_start",
                    right="game__year_released",
                    modifier=Modifier.EQUALS,
                    granularity="year",
                )
            ]
        ).to_q()
        results = Session.objects.filter(q)
        assert hit in results and miss not in results

    def test_year_space_number_left_temporal_right(self, db):
        # Symmetric: number on the lookup side, temporal behind F().
        from datetime import UTC, datetime

        from games.models import Game, Platform, Session

        platform, _ = Platform.objects.get_or_create(
            name="YearProjTest", icon="yearprojtest"
        )
        game = Game.objects.create(name="Doom", year_released=2020, platform=platform)
        hit = Session.objects.create(
            game=game,
            timestamp_start=datetime(2020, 6, 1, tzinfo=UTC),
        )
        q = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="game__year_released",
                    right="timestamp_start",
                    modifier=Modifier.EQUALS,
                    granularity="year",
                )
            ]
        ).to_q()
        assert hit in Session.objects.filter(q)

    def test_year_projection_datetime_to_year_lookup(self):
        """'year' granularity: datetime on left produces __year suffix."""
        q = _field_comparison_to_q(
            "timestamp_start",
            "timestamp_end",
            Modifier.EQUALS,
            "year",
            left_group="datetime",
            right_group="datetime",
        )
        assert "timestamp_start__year" in str(q)

    def test_year_projection_number_left_temporal_right(self):
        """'year' granularity: number left is unchanged; temporal right uses ExtractYear."""
        q = _field_comparison_to_q(
            "year_released",
            "timestamp_start",
            Modifier.EQUALS,
            "year",
            left_group="number",
            right_group="datetime",
        )
        # number left: no __year suffix on lookup
        assert "year_released__year" not in str(q)
        # temporal right: ExtractYear wrapper appears
        assert "ExtractYear" in str(q)

    def test_year_projection_datetime_left_number_right(self):
        """'year' granularity: datetime left gets __year; number right stays plain F."""
        q = _field_comparison_to_q(
            "timestamp_start",
            "year_released",
            Modifier.EQUALS,
            "year",
            left_group="datetime",
            right_group="number",
        )
        # datetime left: __year lookup suffix
        assert "timestamp_start__year" in str(q)
        # number right: no ExtractYear wrapper
        assert "ExtractYear" not in str(q)

    def test_year_projection_date_left_date_right(self):
        """'year' granularity: both date operands get projected (left __year, right ExtractYear)."""
        q = _field_comparison_to_q(
            "started",
            "ended",
            Modifier.EQUALS,
            "year",
            left_group="date",
            right_group="date",
        )
        # date left: __year lookup suffix
        assert "started__year" in str(q)
        # date right: ExtractYear wrapper
        assert "ExtractYear" in str(q)

    def test_year_projection_date_left_number_right(self):
        """'year' granularity: date left gets __year; number right stays plain F."""
        q = _field_comparison_to_q(
            "started",
            "year_released",
            Modifier.EQUALS,
            "year",
            left_group="date",
            right_group="number",
        )
        # date left: __year lookup suffix
        assert "started__year" in str(q)
        # number right: no ExtractYear wrapper
        assert "ExtractYear" not in str(q)

    def test_year_projection_number_left_number_right(self):
        """'year' granularity: both number operands pass through — no projection applied."""
        q = _field_comparison_to_q(
            "year_released",
            "year_released",
            Modifier.EQUALS,
            "year",
            left_group="number",
            right_group="number",
        )
        # neither side gets projected
        assert "year_released__year" not in str(q)
        assert "ExtractYear" not in str(q)
        # plain lookup appears without transformation
        assert "year_released" in str(q)

    def test_date_space_date_left_datetime_right_projects_right(self):
        """'date' granularity: date left passes through; datetime right gets TruncDate."""
        q = _field_comparison_to_q(
            "started",
            "created_at",
            Modifier.EQUALS,
            "date",
            left_group="date",
            right_group="datetime",
        )
        # date left: no __date suffix (only datetime needs truncation)
        assert "started__date" not in str(q)
        # datetime right: TruncDate wrapper
        assert "TruncDate" in str(q)


class TestFilterFieldDescriptors:
    """Guard the declarative ``fields`` table against drift from the dataclass.

    Each concrete filter's generic ``to_q`` walks ``fields`` for its simple
    criteria and the ``aggregates`` table for aggregates, delegating the rest
    to ``_extra_q``. These tests assert that
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
    def test_aggregates_table_matches_aggregate_fields(self, filter_cls):
        """The ``aggregates`` spec table must cover exactly the
        AggregateCriterion-annotated fields — a new aggregate field without a
        spec would silently drop out of ``to_q``; a spec for a non-aggregate
        field is dead wiring (issue #151)."""
        assert set(filter_cls.aggregates) == self._aggregate_fields(filter_cls)

    @pytest.mark.parametrize("filter_cls", ALL_FILTERS)
    def test_aggregate_accessor_reaches_the_scope_filter_model(self, filter_cls):
        """Each spec's ``accessor`` must reach exactly ``scope_filter``'s model —
        ``aggregate_to_q`` builds ``Q(accessor__in=<scope_filter's queryset>)``,
        so a mismatched pair produces a wrong-model pk subquery that returns
        silently wrong results rather than raising (issue #151)."""
        parent_model = filter_cls._comparison_model()
        for name, spec in filter_cls.aggregates.items():
            related_model = parent_model._meta.get_field(spec.accessor).related_model
            assert related_model is spec.scope_filter._comparison_model(), name
        declared = self._declared_criterion_fields(filter_cls)
        for key in filter_cls.fields:
            assert key in declared, (
                f"{filter_cls.__name__}.fields[{key!r}] is not a criterion field"
            )

    @pytest.mark.parametrize("filter_cls", ALL_FILTERS)
    def test_imperative_descriptors_carry_a_lookup(self, filter_cls):
        """An ``imperative`` descriptor must have a lookup (so ``field_metadata``
        can build its widget) — mirrors ``FilterField.__post_init__``."""
        for name, descriptor in filter_cls.fields.items():
            if descriptor.imperative:
                assert descriptor.lookup is not None, (
                    f"{filter_cls.__name__}.fields[{name!r}] is imperative but has "
                    f"no lookup"
                )

    @pytest.mark.django_db
    def test_imperative_field_is_applied_once_via_extra_q(self):
        """``to_q`` must skip an ``imperative`` descriptor field (its Q is built in
        ``_extra_q``) — never double-apply it.

        The M2M ``games`` is in ``PurchaseFilter.fields`` with ``imperative=True``.
        With only ``games`` set, the generic ``fields`` loop must contribute
        nothing, so ``to_q()`` carries exactly the one ``games`` clause ``_extra_q``
        builds — not two. (``Q``s can't be compared with ``==`` because each
        ``_games_to_q`` call builds a fresh, unequal subquery, so we count clauses:
        a double-apply would add a second child.)
        """
        from games.filters import PurchaseFilter

        pf = PurchaseFilter.from_json(
            {"games": {"value": [1, 2], "modifier": "INCLUDES"}}
        )
        assert pf is not None
        assert len(pf.to_q().children) == len(pf._extra_q().children) == 1
        assert str(pf.to_q()) == str(pf._extra_q())


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

    def test_imperative_with_handler_rejected(self):
        # ``to_q`` skips imperative fields, so a handler would be dead code.
        with pytest.raises(ValueError, match="dead code"):
            FilterField(handler=lambda c: Q(), imperative=True)

    def test_imperative_without_lookup_rejected(self):
        with pytest.raises(ValueError, match="needs a lookup"):
            FilterField(imperative=True)

    def test_search_url_with_handler_rejected(self):
        with pytest.raises(ValueError, match="search_url has no effect"):
            FilterField(handler=lambda c: Q(), search_url="/x")

    def test_imperative_with_lookup_is_accepted(self):
        # The legitimate shape (the M2M ``games``): widget config in the table,
        # Q built in ``_extra_q``.
        field = FilterField(
            lookup="games", search_url="/api/games/search", imperative=True
        )
        assert field.imperative and field.lookup == "games"


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


class TestPerFilterSearchColumns:
    """Pin the exact columns each filter's free-text ``search`` spans.

    ``search_q`` and the drift guard verify *that* ``search`` is wired, but not
    *which* columns it covers — a dropped/typo'd column (e.g. losing
    ``sort_name``) would silently change results while every other test stays
    green. This asserts the actual ``_extra_q`` column list per filter.
    """

    # filter class → the icontains columns its ``search`` OR's over, in order.
    SEARCH_COLUMNS = {
        GameFilter: ("name", "sort_name", "platform__name"),
        SessionFilter: (
            "game__name",
            "game__platform__name",
            "device__name",
            "device__type",
        ),
        PurchaseFilter: ("name", "games__name", "platform__name"),
        DeviceFilter: ("name", "type"),
        PlatformFilter: ("name", "group"),
        PlayEventFilter: ("game__name", "note"),
    }

    @pytest.mark.parametrize("filter_cls,columns", list(SEARCH_COLUMNS.items()))
    def test_search_spans_expected_columns(self, filter_cls, columns):
        produced = filter_cls(search=StringCriterion(value="needle")).to_q()
        expected = reduce(
            operator.or_, (Q(**{f"{col}__icontains": "needle"}) for col in columns)
        )
        assert produced == expected

    def test_every_filter_with_search_is_pinned(self):
        # Guard the guard: every filter that declares ``search`` must appear above,
        # so a new filter can't add a free-text search this test silently skips.
        declared = {
            cls
            for cls in _ALL_FILTERS
            if "search" in {f.name for f in dataclasses.fields(cls)}
        }
        assert declared == set(self.SEARCH_COLUMNS)


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


# ── Component 9 — per-model field-metadata registry (issue #187) ──────────────


class TestFieldMetadata:
    """``field_metadata`` returns one entry per filterable field with the
    {name, label, kind, nullable, choices, relations} shape the nested filter
    builder's pickers read."""

    @staticmethod
    def _by_name(filter_cls) -> dict[str, FieldMeta]:
        return {entry["name"]: entry for entry in field_metadata(filter_cls)}

    @staticmethod
    def _expected_choices(model, field_name) -> list[dict]:
        choices = model._meta.get_field(field_name).choices
        return [{"value": str(value), "label": str(label)} for value, label in choices]

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_does_not_raise_and_excludes_search(self, filter_cls):
        names = {entry["name"] for entry in field_metadata(filter_cls)}
        # search is a declared StringCriterion on every filter but is deliberately
        # excluded from the per-field picker: it is the filter bar's dedicated
        # free-text box, applied in _extra_q via search_q, not a pickable field.
        assert "search" in {f.name for f in dataclasses.fields(filter_cls)}
        assert "search" not in names

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_covers_every_criterion_and_relation_field(self, filter_cls):
        expected = {
            f.name
            for f in dataclasses.fields(filter_cls)
            if f.name != "search"
            and (
                _criterion_class_for(filter_cls, f.name) is not None
                or _filter_class_for(filter_cls, f.name) is not None
            )
        }
        names = {entry["name"] for entry in field_metadata(filter_cls)}
        assert names == expected

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_non_filter_fields_skipped(self, filter_cls):
        names = {entry["name"] for entry in field_metadata(filter_cls)}
        for skipped in ("AND", "OR", "NOT", "field_comparisons", "match"):
            assert skipped not in names

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_leaf_kind_matches_criterion(self, filter_cls):
        from common.criteria import AggregateCriterion, criterion_kind

        for entry in field_metadata(filter_cls):
            if entry["kind"] == "relation":
                continue
            criterion_cls = _criterion_class_for(filter_cls, entry["name"])
            assert criterion_cls is not None
            if issubclass(criterion_cls, AggregateCriterion):
                # aggregates set kind directly, bypassing the exact-class dict
                assert entry["kind"] == "number"
            else:
                assert entry["kind"] == criterion_kind(criterion_cls)

    def test_aggregate_field_is_number(self):
        entry = self._by_name(GameFilter)["session_count"]
        assert entry["kind"] == "number"
        assert entry["nullable"] is False
        assert entry["choices"] == []
        assert entry["relations"] == []

    def test_session_timestamp_field_labels(self):
        # timestamp_start/end carry explicit FilterField labels so the field
        # picker reads "Session Start"/"Session End" rather than the title-cased
        # field name "Timestamp Start"/"Timestamp End".
        by_name = self._by_name(SessionFilter)
        assert by_name["timestamp_start"]["label"] == "Session Start"
        assert by_name["timestamp_end"]["label"] == "Session End"

    def test_aggregate_scope_model_names_the_reduced_relation(self):
        by_name = self._by_name(GameFilter)
        assert by_name["session_count"]["scope_model"] == "session"
        assert by_name["purchase_price_total"]["scope_model"] == "purchase"
        assert by_name["playevent_count"]["scope_model"] == "playevent"

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_scope_model_nonempty_iff_aggregate(self, filter_cls):
        """The FieldMeta invariant (issue #151): ``scope_model`` is populated
        exactly on aggregate fields."""
        from common.criteria import AggregateCriterion

        for entry in field_metadata(filter_cls):
            criterion_cls = _criterion_class_for(filter_cls, entry["name"])
            is_aggregate = criterion_cls is not None and issubclass(
                criterion_cls, AggregateCriterion
            )
            assert bool(entry["scope_model"]) == is_aggregate, entry["name"]

    def test_reachable_models_include_scope_targets(self):
        from games.filters import reachable_models

        for root_model in ("game", "session", "purchase", "device", "platform"):
            reachable = reachable_models(root_model)
            for filter_cls in reachable.values():
                for entry in field_metadata(filter_cls):
                    if entry["scope_model"]:
                        assert entry["scope_model"] in reachable

    def test_relation_entry_targets_subfilter(self):
        entry = self._by_name(GameFilter)["session_filter"]
        assert entry["kind"] == "relation"
        assert entry["choices"] == []
        assert entry["nullable"] is False
        assert entry["relations"] == [
            {"field": "session_filter", "filter": "SessionFilter", "model": "Session"}
        ]

    def test_static_choices_game_status(self):
        from games.models import Game

        entry = self._by_name(GameFilter)["status"]
        assert entry["kind"] == "set"
        assert entry["choices"] == self._expected_choices(Game, "status")

    def test_static_choices_purchase(self):
        from games.models import Purchase

        by_name = self._by_name(PurchaseFilter)
        assert by_name["ownership_type"]["choices"] == self._expected_choices(
            Purchase, "ownership_type"
        )
        assert by_name["type"]["choices"] == self._expected_choices(Purchase, "type")

    def test_static_choices_device(self):
        from games.models import Device

        entry = self._by_name(DeviceFilter)["type"]
        assert entry["choices"] == self._expected_choices(Device, "type")

    def test_dynamic_fk_and_m2m_have_no_choices(self):
        game_fields = self._by_name(GameFilter)
        assert game_fields["platform"]["choices"] == []
        assert game_fields["platform_group"]["choices"] == []
        # M2M ``games`` must resolve without AttributeError on ``.null``.
        purchase_fields = self._by_name(PurchaseFilter)
        assert purchase_fields["games"]["choices"] == []
        assert purchase_fields["games"]["nullable"] is False

    def test_nullable_reads_fk_attname(self):
        from games.models import Game

        # platform → lookup "platform_id" (FK attname) resolves to the FK's .null
        entry = self._by_name(GameFilter)["platform"]
        assert entry["nullable"] == bool(Game._meta.get_field("platform").null)

    def test_handler_field_defaults_not_nullable(self):
        # playtime_hours is handler-mapped (no model column) → nullable False
        entry = self._by_name(GameFilter)["playtime_hours"]
        assert entry["kind"] == "number"
        assert entry["nullable"] is False

    def test_multi_hop_descent_label(self):
        # platform_group (lookup platform__group) descends to Platform.group; the
        # label is the field name title-cased (not "Group" from verbose_name).
        entry = self._by_name(GameFilter)["platform_group"]
        assert entry["label"] == "Platform Group"

    def test_explicit_filterfield_label_wins(self):
        from common.criteria import FilterField

        assert GameFilter.fields["platform"].lookup == "platform_id"
        # default label fallback is the title-cased name
        assert self._by_name(GameFilter)["name"]["label"] == "Name"
        # a FilterField.label override would take precedence (plumbing check)
        assert FilterField(lookup="x", label="Custom").label == "Custom"

    def test_resolve_model_field_descent_and_transform(self):
        from games.models import Game, Platform, Session

        # multi-hop FK descent reaches the terminal related-model field
        assert _resolve_model_field(
            Game, "platform__group"
        ) is Platform._meta.get_field("group")
        # trailing transform is ignored; stops at the first non-relation field
        assert _resolve_model_field(
            Session, "timestamp_start__date"
        ) is Session._meta.get_field("timestamp_start")
        # single-segment FK attname resolves to the FK itself
        assert _resolve_model_field(Game, "platform_id") is Game._meta.get_field(
            "platform"
        )

    def test_resolve_model_field_unresolvable_returns_none(self):
        from games.models import Game

        assert _resolve_model_field(Game, "does_not_exist") is None
        # reverse relation / aggregate-style name resolves to no concrete field
        assert _resolve_model_field(Game, "sessions") is None

    def test_nullable_true_for_plain_column(self):
        # year_released is a nullable plain (non-relation) column — exercises the
        # nullable=True path for a real model column, not just an FK.
        entry = self._by_name(GameFilter)["year_released"]
        assert entry["kind"] == "number"
        assert entry["nullable"] is True

    def test_relation_payload_for_every_subfilter(self):
        for filter_cls in _ALL_FILTERS:
            by_name = self._by_name(filter_cls)
            for dataclass_field in dataclasses.fields(filter_cls):
                sub = _filter_class_for(filter_cls, dataclass_field.name)
                if sub is None:
                    continue
                entry = by_name[dataclass_field.name]
                assert entry["kind"] == "relation"
                assert entry["relations"] == [
                    {
                        "field": dataclass_field.name,
                        "filter": sub.__name__,
                        "model": sub._comparison_model().__name__,
                    }
                ]

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_modifiers_match_helper(self, filter_cls):
        # The list emitted per field is exactly the helper's output for its
        # (kind, nullable) — guards the duplication the metadata layer introduces.
        from common.criteria import _modifiers_for_field

        for entry in field_metadata(filter_cls):
            assert entry["modifiers"] == _modifiers_for_field(
                entry["kind"], entry["nullable"]
            )

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    def test_leaf_modifiers_nonempty_relation_empty(self, filter_cls):
        for entry in field_metadata(filter_cls):
            if entry["kind"] == "relation":
                assert entry["modifiers"] == []
            else:
                assert entry["modifiers"], entry["name"]

    def test_first_modifier_is_reset_default_per_kind(self):
        # The first entry is what the field picker resets to on field change.
        game = self._by_name(GameFilter)
        assert game["name"]["modifiers"][0] == "EQUALS"  # string
        assert game["year_released"]["modifiers"][0] == "EQUALS"  # number
        assert game["status"]["modifiers"][0] == "INCLUDES"  # set

    def test_modifiers_drop_presence_when_not_nullable(self):
        from common.criteria import Modifier

        game = self._by_name(GameFilter)
        # name is a non-nullable CharField → presence modifiers dropped
        name = game["name"]
        assert name["nullable"] is False
        assert Modifier.IS_NULL.value not in name["modifiers"]
        assert Modifier.NOT_NULL.value not in name["modifiers"]
        # year_released is nullable → presence modifiers retained
        year = game["year_released"]
        assert year["nullable"] is True
        assert Modifier.IS_NULL.value in year["modifiers"]
        assert Modifier.NOT_NULL.value in year["modifiers"]

    def test_filterfield_label_and_labels_override_win(self):
        by_name = self._by_name(_LabelStub)
        # FilterField.label (highest precedence) surfaces for an in-`fields` field
        assert by_name["name"]["label"] == "Explicit Name"
        # OperatorFilter.labels override surfaces for a field outside `fields`
        assert by_name["mastered"]["label"] == "Override Mastered"

    def test_mistyped_lookup_raises(self):
        with pytest.raises(ValueError, match="resolves to no field"):
            field_metadata(_BadLookupStub)


@dataclass
class _LabelStub(OperatorFilter):
    """Exercises the two label-override branches of ``_field_label``: a
    ``FilterField.label`` (in ``fields``) and an ``OperatorFilter.labels`` entry
    (for a field outside ``fields``)."""

    AND: list[_LabelStub] = dc_field(default_factory=list)
    OR: list[_LabelStub] = dc_field(default_factory=list)
    NOT: list[_LabelStub] = dc_field(default_factory=list)
    name: StringCriterion | None = None
    mastered: BoolCriterion | None = None

    fields = {"name": FilterField(label="Explicit Name")}
    labels = {"mastered": "Override Mastered"}

    @classmethod
    def _comparison_model(cls):
        from games.models import Game

        return Game


@dataclass
class _BadLookupStub(OperatorFilter):
    """A misconfigured filter whose ``fields`` lookup names no real column — the
    registry must raise rather than silently emit nullable=False/choices=[]."""

    AND: list[_BadLookupStub] = dc_field(default_factory=list)
    OR: list[_BadLookupStub] = dc_field(default_factory=list)
    NOT: list[_BadLookupStub] = dc_field(default_factory=list)
    year_released: IntCriterion | None = None

    fields = {"year_released": FilterField("yeer_released")}

    @classmethod
    def _comparison_model(cls):
        from games.models import Game

        return Game


@pytest.mark.django_db
class TestStringCriterionIsNullAgainstDB:
    """Behavioral tests proving IS_NULL/NOT_NULL on string fields matches
    blank strings (the repo convention: null=False, default="")."""

    def _seed_sessions(self):
        import datetime

        from games.models import Device, Game, Platform, Session

        platform, _ = Platform.objects.get_or_create(name="Test Platform", icon="test")
        game, _ = Game.objects.get_or_create(
            name="Test Game", defaults={"platform": platform, "status": "u"}
        )
        device, _ = Device.objects.get_or_create(name="Test Device", type="PC")
        start = datetime.datetime(2025, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2025, 1, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)

        empty_note_session_1 = Session.objects.create(
            game=game, device=device, timestamp_start=start, timestamp_end=end, note=""
        )
        empty_note_session_2 = Session.objects.create(
            game=game,
            device=device,
            timestamp_start=start + datetime.timedelta(days=1),
            timestamp_end=end + datetime.timedelta(days=1),
            note="",
        )
        nonempty_note_session = Session.objects.create(
            game=game,
            device=device,
            timestamp_start=start + datetime.timedelta(days=2),
            timestamp_end=end + datetime.timedelta(days=2),
            note="Great session",
        )
        return empty_note_session_1, empty_note_session_2, nonempty_note_session

    def test_is_null_matches_blank_string_sessions(self):
        empty_1, empty_2, nonempty = self._seed_sessions()
        from games.models import Session

        criterion = StringCriterion(value="", modifier=Modifier.IS_NULL)
        matching_ids = set(
            Session.objects.filter(criterion.to_q("note")).values_list("id", flat=True)
        )
        assert empty_1.id in matching_ids
        assert empty_2.id in matching_ids
        assert nonempty.id not in matching_ids

    def test_not_null_matches_nonempty_string_sessions(self):
        empty_1, empty_2, nonempty = self._seed_sessions()
        from games.models import Session

        criterion = StringCriterion(value="", modifier=Modifier.NOT_NULL)
        matching_ids = set(
            Session.objects.filter(criterion.to_q("note")).values_list("id", flat=True)
        )
        assert nonempty.id in matching_ids
        assert empty_1.id not in matching_ids
        assert empty_2.id not in matching_ids

    def test_is_null_and_not_null_partition_sessions(self):
        """IS_NULL and NOT_NULL together must cover exactly every session created here."""
        empty_1, empty_2, nonempty = self._seed_sessions()
        from games.models import Session

        is_null_q = StringCriterion(value="", modifier=Modifier.IS_NULL).to_q("note")
        not_null_q = StringCriterion(value="", modifier=Modifier.NOT_NULL).to_q("note")
        seeded_ids = {empty_1.id, empty_2.id, nonempty.id}
        is_null_ids = (
            set(Session.objects.filter(is_null_q).values_list("id", flat=True))
            & seeded_ids
        )
        not_null_ids = (
            set(Session.objects.filter(not_null_q).values_list("id", flat=True))
            & seeded_ids
        )
        assert is_null_ids | not_null_ids == seeded_ids
        assert is_null_ids & not_null_ids == set()


class TestStringFieldNullConvention:
    """Convention guard: every CharField/TextField in the games app must be
    null=False. The StringCriterion IS_NULL/NOT_NULL fix relies on this (empty
    is stored as "", never SQL NULL). If anyone adds a nullable string field this
    test fails loudly so the filter logic can be revisited.

    Known intentional exceptions (pre-existing nullable string fields not used
    in any filter, listed as "ModelName.field_name"):
    - GameStatusChange.old_status: NULL means "no previous status" (first-time set)
    """

    # Fields that are intentionally null=True for domain reasons and are NOT used
    # in any filter class. If you add a new nullable string field that IS used in a
    # filter, update StringCriterion.to_q to handle it, then add it here only if
    # the null=True IS_NULL/NOT_NULL semantics differ from the "" convention.
    KNOWN_NULLABLE_EXCEPTIONS: frozenset[str] = frozenset(
        {"GameStatusChange.old_status"}
    )

    def test_no_nullable_string_fields_in_games_models(self):
        from django.apps import apps
        from django.db.models import CharField, TextField

        games_config = apps.get_app_config("games")
        unexpected_nullable_fields: list[str] = []
        for model in games_config.get_models():
            for field in model._meta.get_fields():  # get_fields() also returns reverse relations; the isinstance check below filters them out
                if isinstance(field, (CharField, TextField)) and field.null:
                    field_key = f"{model.__name__}.{field.name}"
                    if field_key not in self.KNOWN_NULLABLE_EXCEPTIONS:
                        unexpected_nullable_fields.append(field_key)

        assert unexpected_nullable_fields == [], (
            "Found unexpected nullable string fields in the games app. "
            "The repo convention is null=False, default='' for all CharField/TextField fields. "
            "StringCriterion IS_NULL/NOT_NULL matches both NULL and '' — "
            "if you intentionally add a nullable string field, either update StringCriterion.to_q "
            "to handle it correctly and add it to KNOWN_NULLABLE_EXCEPTIONS, or reconsider "
            "whether null=False with default='' would work instead.\n"
            f"Unexpected nullable fields found: {', '.join(unexpected_nullable_fields)}"
        )


# ── Scoped aggregates (issue #151) ───────────────────────────────────────────


@pytest.mark.django_db
class TestScopedAggregatesAgainstDB:
    """``AggregateCriterion.scope`` narrows the reducer to related rows matching
    the sub-filter — "games with > 2 sessions *on the Steam Deck*", "sum of
    *physical* purchase prices > 100".

    The session fixture is deliberately shaped to expose join-duplication bugs:
    ``deck_heavy`` has sessions on two devices, so a cross-join in the filtered
    aggregate would inflate its per-device counts past the assertions.
    """

    def _seed_sessions(self):
        import datetime
        from datetime import timedelta

        from games.models import Device, Game, Platform, Session

        platform = Platform.objects.create(name="PC")
        deck = Device.objects.create(name="Steam Deck", type="Handheld")
        desktop = Device.objects.create(name="Desktop", type="PC")
        deck_heavy = Game.objects.create(name="Deck Heavy", platform=platform)
        desktop_only = Game.objects.create(name="Desktop Only", platform=platform)
        unplayed = Game.objects.create(name="Unplayed", platform=platform)

        first_start = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)

        def make_session(game, device, index, manual_hours=0):
            begin = first_start + timedelta(days=index)
            return Session.objects.create(
                game=game,
                device=device,
                timestamp_start=begin,
                timestamp_end=begin + timedelta(hours=1),
                duration_manual=timedelta(hours=manual_hours),
            )

        # deck_heavy: 3 sessions on the deck (1h manual each) + 1 on the desktop
        # (4h manual) — mixed devices, the join-duplication canary.
        for index in range(3):
            make_session(deck_heavy, deck, index, manual_hours=1)
        make_session(deck_heavy, desktop, 3, manual_hours=4)
        # desktop_only: 3 sessions, none on the deck.
        for index in range(4, 7):
            make_session(desktop_only, desktop, index)

        return {
            "deck": deck,
            "desktop": desktop,
            "deck_heavy": deck_heavy,
            "desktop_only": desktop_only,
            "unplayed": unplayed,
        }

    def _games_matching(self, filter_json: dict) -> set:
        from games.filters import GameFilter
        from games.models import Game

        game_filter = GameFilter.from_json(filter_json)
        assert game_filter is not None
        return set(Game.objects.filter(game_filter.to_q()))

    def test_session_count_scoped_to_device(self):
        data = self._seed_sessions()
        scoped = {
            "session_count": {
                "value": 2,
                "modifier": "GREATER_THAN",
                "scope": {
                    "device": {"value": [data["deck"].id], "modifier": "INCLUDES"}
                },
            }
        }
        # Unscoped, both played games have 3+ sessions — the scope is what
        # excludes desktop_only, so this proves it was applied.
        unscoped = {"session_count": {"value": 2, "modifier": "GREATER_THAN"}}
        assert self._games_matching(unscoped) == {
            data["deck_heavy"],
            data["desktop_only"],
        }
        assert self._games_matching(scoped) == {data["deck_heavy"]}

    def test_scoped_count_ignores_other_device_rows(self):
        """Join-duplication canary: deck_heavy's desktop session must neither
        count toward its deck total nor multiply it."""
        data = self._seed_sessions()
        exactly_three_on_deck = {
            "session_count": {
                "value": 3,
                "modifier": "EQUALS",
                "scope": {
                    "device": {"value": [data["deck"].id], "modifier": "INCLUDES"}
                },
            }
        }
        assert self._games_matching(exactly_three_on_deck) == {data["deck_heavy"]}
        exactly_one_on_desktop = {
            "session_count": {
                "value": 1,
                "modifier": "EQUALS",
                "scope": {
                    "device": {"value": [data["desktop"].id], "modifier": "INCLUDES"}
                },
            }
        }
        assert self._games_matching(exactly_one_on_desktop) == {data["deck_heavy"]}

    def test_scoped_count_equals_zero(self):
        """Zero-row parity (#223): games with no matching related rows still
        compare as count 0 — both the unplayed game and the game whose sessions
        all fail the scope."""
        data = self._seed_sessions()
        zero_on_deck = {
            "session_count": {
                "value": 0,
                "modifier": "EQUALS",
                "scope": {
                    "device": {"value": [data["deck"].id], "modifier": "INCLUDES"}
                },
            }
        }
        assert self._games_matching(zero_on_deck) == {
            data["desktop_only"],
            data["unplayed"],
        }

    def test_scoped_duration_sum(self):
        """A duration-unit aggregate (manual playtime hours) scoped to a device:
        deck_heavy has 3h manual on the deck but 7h in total, so EQUALS 3 only
        matches with the scope applied."""
        data = self._seed_sessions()
        scope = {"device": {"value": [data["deck"].id], "modifier": "INCLUDES"}}
        scoped = {
            "manual_playtime_hours": {"value": 3, "modifier": "EQUALS", "scope": scope}
        }
        unscoped = {"manual_playtime_hours": {"value": 3, "modifier": "EQUALS"}}
        assert self._games_matching(scoped) == {data["deck_heavy"]}
        assert self._games_matching(unscoped) == set()

    def test_purchase_price_total_scoped_to_physical(self):
        """Issue use case: "sum of physical purchase prices > 100". The mixed
        game's digital purchase pushes its unscoped total past 100, so it only
        drops out when the scope filters the summed rows."""
        import datetime

        from games.models import Game, Platform, Purchase

        platform = Platform.objects.create(name="PC")
        physical_expensive = Game.objects.create(name="Boxed", platform=platform)
        mixed = Game.objects.create(name="Mixed", platform=platform)

        def make_purchase(game, price, ownership_type):
            purchase = Purchase.objects.create(
                platform=platform,
                date_purchased=datetime.date(2026, 1, 1),
                price=price,
                price_currency="CZK",
                converted_price=price,
                converted_currency="CZK",
                ownership_type=ownership_type,
            )
            purchase.games.add(game)
            return purchase

        make_purchase(physical_expensive, 150, Purchase.PHYSICAL)
        make_purchase(mixed, 50, Purchase.PHYSICAL)
        make_purchase(mixed, 200, Purchase.DIGITAL)

        scoped = {
            "purchase_price_total": {
                "value": 100,
                "modifier": "GREATER_THAN",
                "scope": {
                    "ownership_type": {
                        "value": [Purchase.PHYSICAL],
                        "modifier": "INCLUDES",
                    }
                },
            }
        }
        unscoped = {"purchase_price_total": {"value": 100, "modifier": "GREATER_THAN"}}
        assert self._games_matching(unscoped) == {physical_expensive, mixed}
        assert self._games_matching(scoped) == {physical_expensive}


class TestScopedAggregateJSON:
    """Serialization contract for the aggregate ``scope`` (issue #151)."""

    def _scoped_filter_json(self) -> dict:
        return {
            "session_count": {
                "value": 5,
                "modifier": "GREATER_THAN",
                "scope": {"device": {"value": [1], "modifier": "INCLUDES"}},
            }
        }

    def test_scope_deserializes_to_the_accessor_filter_class(self):
        from games.filters import GameFilter, SessionFilter

        game_filter = GameFilter.from_json(self._scoped_filter_json())
        assert game_filter is not None
        assert game_filter.session_count is not None
        assert isinstance(game_filter.session_count.scope, SessionFilter)
        assert game_filter.session_count.scope.device is not None

    def test_scoped_aggregate_round_trips(self):
        from games.filters import GameFilter

        original = GameFilter.from_json(self._scoped_filter_json())
        assert original is not None
        reparsed = GameFilter.from_json(original.to_json())
        assert reparsed == original
        assert "scope" in original.to_json()["session_count"]

    def test_empty_scope_normalizes_to_unscoped(self):
        from games.filters import GameFilter

        game_filter = GameFilter.from_json({"session_count": {"value": 5, "scope": {}}})
        assert game_filter is not None
        assert game_filter.session_count is not None
        assert game_filter.session_count.scope is None
        assert "scope" not in game_filter.to_json()["session_count"]

    def test_criterion_alone_ignores_scope_key(self):
        """AggregateCriterion.from_json can't resolve a scope class — the raw
        ``scope`` key must not leak onto the instance (the #139/#144 bug)."""
        criterion = AggregateCriterion.from_json(
            {"value": 5, "scope": {"device": {"value": [1]}}}
        )
        assert criterion is not None
        assert criterion.scope is None

    def test_scope_must_be_an_object(self):
        from games.filters import GameFilter

        with pytest.raises(FilterError, match="must be an object"):
            GameFilter.from_json({"session_count": {"value": 5, "scope": [1, 2]}})

    def test_scope_rejects_match_quantifier(self):
        from games.filters import GameFilter

        with pytest.raises(FilterError, match="match quantifier"):
            GameFilter.from_json(
                {
                    "session_count": {
                        "value": 5,
                        "scope": {"match": "NONE", "emulated": {"value": True}},
                    }
                }
            )

    def test_nested_relation_inside_scope_keeps_its_match(self):
        from games.filters import GameFilter

        game_filter = GameFilter.from_json(
            {
                "session_count": {
                    "value": 1,
                    "scope": {"device_filter": {"match": "NONE"}},
                }
            }
        )
        assert game_filter is not None
        scope = game_filter.session_count.scope
        assert scope is not None
        assert scope.device_filter is not None
        assert scope.device_filter.match == RelationMatch.NONE

    def test_scope_depth_bomb_rejected(self):
        from games.filters import GameFilter

        deep: dict = {"emulated": {"value": True}}
        for _ in range(MAX_FILTER_DEPTH + 1):
            deep = {"AND": [deep]}
        with pytest.raises(FilterError, match="too deep"):
            GameFilter.from_json({"session_count": {"value": 1, "scope": deep}})

    def test_bad_scope_value_is_a_filter_error(self):
        """Eager validation: a wrong-typed value inside the scope surfaces as
        FilterError at the filter_from_json boundary, not a 500."""
        from games.filters import GameFilter

        blob = json.dumps(
            {
                "session_count": {
                    "value": 1,
                    "scope": {"device": {"value": ["x"], "modifier": "INCLUDES"}},
                }
            }
        )
        with pytest.raises(FilterError):
            filter_from_json(GameFilter, blob)


@pytest.mark.django_db
class TestScopedAggregateReducers:
    """Reducer-specific scoped-aggregate semantics the base class doesn't cover:
    the distinct M2M count, the avg reducer, a nested relation inside the scope,
    and the NULL sum for parents whose related rows all fail the scope."""

    def test_scoped_purchase_count_is_distinct_over_the_m2m(self):
        """A bundle purchase linked to two games must count once per game under
        a scope — distinct + FILTER + M2M join is the shape most prone to
        alias/duplication bugs."""
        import datetime

        from games.filters import GameFilter
        from games.models import Game, Platform, Purchase

        platform = Platform.objects.create(name="PC")
        first_game = Game.objects.create(name="First", platform=platform)
        second_game = Game.objects.create(name="Second", platform=platform)

        def make_purchase(games, ownership_type):
            purchase = Purchase.objects.create(
                platform=platform,
                date_purchased=datetime.date(2026, 1, 1),
                ownership_type=ownership_type,
            )
            purchase.games.set(games)
            return purchase

        make_purchase([first_game, second_game], Purchase.PHYSICAL)  # the bundle
        make_purchase([first_game], Purchase.PHYSICAL)
        make_purchase([first_game], Purchase.DIGITAL)  # fails the scope

        game_filter = GameFilter.from_json(
            {
                "purchase_count": {
                    "value": 2,
                    "modifier": "EQUALS",
                    "scope": {
                        "ownership_type": {
                            "value": [Purchase.PHYSICAL],
                            "modifier": "INCLUDES",
                        }
                    },
                }
            }
        )
        assert set(Game.objects.filter(game_filter.to_q())) == {first_game}
        one_physical = GameFilter.from_json(
            {
                "purchase_count": {
                    "value": 1,
                    "modifier": "EQUALS",
                    "scope": {
                        "ownership_type": {
                            "value": [Purchase.PHYSICAL],
                            "modifier": "INCLUDES",
                        }
                    },
                }
            }
        )
        assert set(Game.objects.filter(one_physical.to_q())) == {second_game}

    def _seed_two_device_games(self):
        import datetime
        from datetime import timedelta

        from games.models import Device, Game, Platform, Session

        platform = Platform.objects.create(name="PC")
        deck = Device.objects.create(name="Steam Deck", type="Handheld")
        desktop = Device.objects.create(name="Desktop", type="PC")
        mixed = Game.objects.create(name="Mixed", platform=platform)
        desktop_only = Game.objects.create(name="Desktop Only", platform=platform)
        first_start = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)

        def make_session(game, device, index, hours):
            begin = first_start + timedelta(days=index)
            return Session.objects.create(
                game=game,
                device=device,
                timestamp_start=begin,
                timestamp_end=begin + timedelta(hours=hours),
            )

        # mixed: two 1h sessions on the deck + one 5h on the desktop → the
        # unscoped average (7/3 ≈ 2.3h) differs from the deck-scoped one (1h).
        make_session(mixed, deck, 0, hours=1)
        make_session(mixed, deck, 1, hours=1)
        make_session(mixed, desktop, 2, hours=5)
        # desktop_only: one 1h session, never on the deck.
        make_session(desktop_only, desktop, 3, hours=1)
        return {
            "deck": deck,
            "mixed": mixed,
            "desktop_only": desktop_only,
        }

    def _games_matching(self, filter_json: dict) -> set:
        from games.filters import GameFilter
        from games.models import Game

        game_filter = GameFilter.from_json(filter_json)
        assert game_filter is not None
        return set(Game.objects.filter(game_filter.to_q()))

    def test_scoped_average_executes_against_the_db(self):
        """The avg reducer with a scope: only the deck sessions feed the mean.
        This also pins the spec table's avg wiring (source/unit), which the
        name-coverage drift guard can't."""
        data = self._seed_two_device_games()
        deck_scope = {"device": {"value": [data["deck"].id], "modifier": "INCLUDES"}}
        scoped_hour_average = {
            "session_average": {"value": 1, "modifier": "EQUALS", "scope": deck_scope}
        }
        unscoped_hour_average = {"session_average": {"value": 1, "modifier": "EQUALS"}}
        # Scoped to the deck, mixed averages exactly 1h; unscoped its 5h desktop
        # session pulls the mean into the [2, 3) bucket, leaving only desktop_only.
        assert self._games_matching(scoped_hour_average) == {data["mixed"]}
        assert self._games_matching(unscoped_hour_average) == {data["desktop_only"]}

    def test_nested_relation_inside_scope_executes_against_the_db(self):
        """A scope carrying a relation descent with its own quantifier: count
        sessions whose device does NOT match. This executes the subquery-
        membership design claim — a key-prefix Q rewrite would break exactly
        here and nowhere else in the suite."""
        data = self._seed_two_device_games()
        off_deck_scope = {
            "device_filter": {
                "match": "NONE",
                "name": {"value": "Steam Deck", "modifier": "EQUALS"},
            }
        }
        one_session_off_deck = {
            "session_count": {"value": 1, "modifier": "EQUALS", "scope": off_deck_scope}
        }
        # mixed has exactly one non-deck session; desktop_only has one too.
        assert self._games_matching(one_session_off_deck) == {
            data["mixed"],
            data["desktop_only"],
        }
        two_sessions_off_deck = {
            "session_count": {"value": 2, "modifier": "EQUALS", "scope": off_deck_scope}
        }
        assert self._games_matching(two_sessions_off_deck) == set()

    def test_scoped_sum_is_null_when_no_row_matches_the_scope(self):
        """SUM with a filter= that matches no rows yields SQL NULL (unlike the
        count's 0): a game whose sessions all fail the scope matches neither
        EQUALS 0 (NULL != 0) nor the duration IS_NULL (defined as *zero
        duration*, see duration_hours_to_q) — identical to the pre-existing
        unscoped no-session case. Pin it so a future 'coalesce to 0' change is
        a deliberate decision, with a positive contrast proving the scoped sum
        itself computes."""
        data = self._seed_two_device_games()
        deck_scope = {"device": {"value": [data["deck"].id], "modifier": "INCLUDES"}}

        def scoped(modifier, value=0):
            return {
                "calculated_playtime_hours": {
                    "value": value,
                    "modifier": modifier,
                    "scope": deck_scope,
                }
            }

        # desktop_only's NULL deck-sum is invisible to both zero tests…
        assert self._games_matching(scoped("EQUALS", 0)) == set()
        assert self._games_matching(scoped("IS_NULL")) == set()
        # …while mixed's deck sessions (1h + 1h calculated) sum normally.
        assert self._games_matching(scoped("EQUALS", 2)) == {data["mixed"]}


class TestComparisonOperandPaths:
    """Tests for _comparison_operand_info: path grammar + validation (#169/#282)."""

    def test_fk_path_resolves_related_group(self):
        from games.models import Session

        info = _comparison_operand_info(Session, "game__year_released", side="left")
        assert info.group == "number"
        assert info.multivalued is False
        assert info.relation_path is None

    def test_own_column_still_resolves(self):
        from games.models import Session

        info = _comparison_operand_info(Session, "note", side="left")
        assert info == ("string", False, None)

    def test_m2m_path_is_multivalued(self):
        # #282: a forward M2M hop (Purchase.games) is now an accepted multi-valued
        # operand rather than rejected.
        from games.models import Purchase

        info = _comparison_operand_info(Purchase, "games__name", side="left")
        assert info.group == "string"
        assert info.multivalued is True
        assert info.relation_path == "games"

    def test_reverse_accessor_is_multivalued(self):
        # #282: a reverse-FK hop (Game.sessions) is an accepted multi-valued operand.
        from games.models import Game

        info = _comparison_operand_info(Game, "sessions__note", side="right")
        assert info.group == "string"
        assert info.multivalued is True
        assert info.relation_path == "sessions"

    def test_to_one_then_multi_hop_is_multivalued(self):
        # The #282 headline path: Session → game (to-one) → playevents (multi).
        from games.models import Session

        info = _comparison_operand_info(
            Session, "game__playevents__ended", side="right"
        )
        assert info.group == "date"
        assert info.multivalued is True
        assert info.relation_path == "game__playevents"

    def test_two_to_one_hops_rejected(self):
        # Two to-one hops (Session → game → platform) stay rejected: no
        # multi-valued relation, so the F() would need a two-join same-row path.
        from games.models import Session

        with pytest.raises(FilterError, match="two to-one hops"):
            _comparison_operand_info(Session, "game__platform__name", side="left")

    def test_four_segment_path_rejected(self):
        from games.models import Session

        with pytest.raises(FilterError, match="too many relations"):
            _comparison_operand_info(
                Session, "game__playevents__game__name", side="left"
            )

    def test_unknown_relation_names_path_and_side(self):
        from games.models import Session

        with pytest.raises(FilterError, match=r"right operand.*'nonexistent__name'"):
            _comparison_operand_info(Session, "nonexistent__name", side="right")

    def test_unknown_related_column_names_full_path(self):
        from games.models import Session

        with pytest.raises(FilterError, match="game__nonexistent"):
            _comparison_operand_info(Session, "game__nonexistent", side="left")

    def test_cross_model_wiring_end_to_end(self, db):
        import datetime

        from games.models import Game, Platform, Purchase

        platform, _ = Platform.objects.get_or_create(
            name="OperandPathTest", icon="operandpathtest"
        )
        game = Game.objects.create(name="Doom", platform=platform)
        dlc = Purchase.objects.create(
            name="Doom: Eternal DLC",
            related_game=game,
            date_purchased=datetime.date(2024, 1, 1),
        )
        query = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name",
                    right="related_game__name",
                    modifier=Modifier.INCLUDES,
                )
            ]
        ).to_q()
        assert dlc in Purchase.objects.filter(query)

    def test_shared_join_for_both_side_paths(self, db):
        from games.models import Game

        query = GameFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="platform__name",
                    right="platform__group",
                    modifier=Modifier.EQUALS,
                )
            ]
        ).to_q()
        # Structural probe: count actual join entries in the compiled query's
        # alias map instead of substring-counting "JOIN" in rendered SQL, which
        # is fragile to ORM SQL-rendering changes.
        from django.db.models.sql.datastructures import Join

        alias_map = Game.objects.filter(query).query.alias_map
        joins = [entry for entry in alias_map.values() if isinstance(entry, Join)]
        assert len(joins) == 1
        assert joins[0].table_name == "games_platform"


class TestMultivaluedComparison:
    """#282: field comparison across a multi-valued relation, quantified ANY/ALL/NONE."""

    @staticmethod
    def _dt(year, month=1, day=1):
        import datetime as dt

        return dt.datetime(year, month, day, 12, 0, tzinfo=dt.timezone.utc)

    def _seed(self):
        import datetime as dt

        from games.models import Game, PlayEvent, Session

        def session(game, end):
            return Session.objects.create(
                game=game, timestamp_start=self._dt(2000), timestamp_end=end
            )

        rows = {}
        game_a = Game.objects.create(name="MV-A")
        PlayEvent.objects.create(game=game_a, ended=dt.date(2020, 1, 1))
        PlayEvent.objects.create(game=game_a, ended=dt.date(2020, 6, 1))
        rows["after_all"] = session(game_a, self._dt(2021))
        rows["after_some"] = session(game_a, self._dt(2020, 3, 1))
        rows["after_none"] = session(game_a, self._dt(2019))
        rows["null_end"] = session(game_a, None)

        game_b = Game.objects.create(name="MV-B")
        PlayEvent.objects.create(game=game_b, ended=None)  # null terminal column
        rows["null_terminal"] = session(game_b, self._dt(2021))

        rows["no_events"] = session(Game.objects.create(name="MV-C"), self._dt(2021))
        rows["no_game"] = session(None, self._dt(2021))
        return rows

    def _matched(self, quantifier, *, left, right):
        from games.models import Session

        query = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left=left,
                    right=right,
                    modifier=Modifier.GREATER_THAN,
                    granularity="date",
                    quantifier=quantifier,
                )
            ]
        ).to_q()
        return set(Session.objects.filter(query).values_list("pk", flat=True))

    def test_any_multi_on_right(self, db):
        rows = self._seed()
        matched = self._matched(
            RelationMatch.ANY, left="timestamp_end", right="game__playevents__ended"
        )
        expected = {"after_all", "after_some"}
        assert {k for k, s in rows.items() if s.pk in matched} == expected

    def test_all_multi_on_right(self, db):
        rows = self._seed()
        matched = self._matched(
            RelationMatch.ALL, left="timestamp_end", right="game__playevents__ended"
        )
        # after_all satisfies both events; no_events + no_game are vacuously true.
        expected = {"after_all", "no_events", "no_game"}
        assert {k for k, s in rows.items() if s.pk in matched} == expected

    def test_none_multi_on_right(self, db):
        rows = self._seed()
        matched = self._matched(
            RelationMatch.NONE, left="timestamp_end", right="game__playevents__ended"
        )
        # Complement of ANY.
        expected = {
            "after_none",
            "null_end",
            "null_terminal",
            "no_events",
            "no_game",
        }
        assert {k for k, s in rows.items() if s.pk in matched} == expected

    def test_multi_on_left_mirrors_flipped_operator(self, db):
        # Multi operand on the left with LESS_THAN is the mirror of multi-on-right
        # GREATER_THAN: ended < timestamp_end ⇔ timestamp_end > ended.
        rows = self._seed()
        matched = self._matched(
            RelationMatch.ANY, left="game__playevents__ended", right="timestamp_end"
        )
        # ANY event with ended < session end (date): after_all + after_some.
        # We use LESS_THAN via a separate query since _matched hardcodes GREATER_THAN.
        from games.models import Session

        query = SessionFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="game__playevents__ended",
                    right="timestamp_end",
                    modifier=Modifier.LESS_THAN,
                    granularity="date",
                    quantifier=RelationMatch.ANY,
                )
            ]
        ).to_q()
        matched = set(Session.objects.filter(query).values_list("pk", flat=True))
        assert {k for k, s in rows.items() if s.pk in matched} == {
            "after_all",
            "after_some",
        }

    def test_raw_space_multivalued_string_contains(self, db):
        # Raw string space, multi operand on the right (Purchase.games M2M).
        from games.models import Game, Purchase

        import datetime as dt

        purchased = dt.date(2024, 1, 1)
        game_match = Game.objects.create(name="Zelda")
        game_other = Game.objects.create(name="Doom")
        hit = Purchase.objects.create(
            name="Great Zelda Bundle", date_purchased=purchased
        )
        hit.games.add(game_match)
        # same name...
        miss = Purchase.objects.create(
            name="Great Zelda Bundle", date_purchased=purchased
        )
        miss.games.add(game_other)  # ...but no linked game name it contains
        query = PurchaseFilter(
            field_comparisons=[
                FieldComparisonCriterion(
                    left="name",
                    right="games__name",
                    modifier=Modifier.INCLUDES,
                    quantifier=RelationMatch.ANY,
                )
            ]
        ).to_q()
        matched = set(Purchase.objects.filter(query).values_list("pk", flat=True))
        assert hit.pk in matched
        assert miss.pk not in matched

    def test_both_operands_multivalued_rejected(self, db):
        with pytest.raises(FilterError, match="two multi-valued operands"):
            SessionFilter(
                field_comparisons=[
                    FieldComparisonCriterion(
                        left="game__playevents__started",
                        right="game__playevents__ended",
                        modifier=Modifier.LESS_THAN,
                        granularity="date",
                    )
                ]
            ).to_q()

    def test_quantifier_without_multi_operand_rejected(self, db):
        with pytest.raises(FilterError, match="only meaningful"):
            SessionFilter(
                field_comparisons=[
                    FieldComparisonCriterion(
                        left="timestamp_start",
                        right="timestamp_end",
                        modifier=Modifier.LESS_THAN,
                        granularity="date",
                        quantifier=RelationMatch.ALL,
                    )
                ]
            ).to_q()

    def test_quantifier_json_roundtrip(self):
        criterion = FieldComparisonCriterion(
            left="timestamp_end",
            right="game__playevents__ended",
            modifier=Modifier.GREATER_THAN,
            granularity="date",
            quantifier=RelationMatch.ALL,
        )
        payload = criterion.to_json()
        assert payload["quantifier"] == RelationMatch.ALL
        reparsed = FieldComparisonCriterion.from_json(payload)
        assert reparsed.quantifier == RelationMatch.ALL

    def test_default_quantifier_omitted_from_json(self):
        criterion = FieldComparisonCriterion(
            left="timestamp_start", right="timestamp_end", modifier=Modifier.LESS_THAN
        )
        assert "quantifier" not in criterion.to_json()

    def test_unknown_quantifier_rejected(self):
        with pytest.raises(FilterError, match="quantifier"):
            FieldComparisonCriterion.from_json(
                {
                    "left": "a",
                    "right": "b",
                    "modifier": "EQUALS",
                    "quantifier": "SOME",
                }
            )
