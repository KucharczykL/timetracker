"""Tests for OperatorFilter.where() — Django-.filter()-style ergonomic
construction of filters (issue #56, Component 1b)."""

import pytest

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    StringCriterion,
)
from games.filters import GameFilter


def test_no_suffix_defaults_to_equals_for_scalar():
    assert GameFilter.where(year_released=2010) == GameFilter(
        year_released=IntCriterion(value=2010, modifier=Modifier.EQUALS)
    )


def test_no_suffix_defaults_to_includes_for_set_criterion():
    assert GameFilter.where(status=["f", "p"]) == GameFilter(
        status=ChoiceCriterion(value=["f", "p"], modifier=Modifier.INCLUDES)
    )


def test_gt_suffix_maps_to_greater_than():
    assert GameFilter.where(year_released__gt=2010) == GameFilter(
        year_released=IntCriterion(value=2010, modifier=Modifier.GREATER_THAN)
    )


def test_contains_suffix_maps_to_includes_for_string():
    assert GameFilter.where(name__contains="Zelda") == GameFilter(
        name=StringCriterion(value="Zelda", modifier=Modifier.INCLUDES)
    )


def test_between_suffix_consumes_tuple_into_value_and_value2():
    assert GameFilter.where(year_released__between=(2010, 2020)) == GameFilter(
        year_released=IntCriterion(value=2010, value2=2020, modifier=Modifier.BETWEEN)
    )


def test_isnull_suffix_ignores_value():
    assert GameFilter.where(playtime_hours__isnull=True) == GameFilter(
        playtime_hours=IntCriterion(modifier=Modifier.IS_NULL)
    )


def test_bool_field_resolves_bool_criterion():
    assert GameFilter.where(mastered=True) == GameFilter(
        mastered=BoolCriterion(value=True, modifier=Modifier.EQUALS)
    )


def test_multi_field_resolves_multi_criterion():
    assert GameFilter.where(platform_group=[1, 2]) == GameFilter(
        platform_group=MultiCriterion(value=[1, 2], modifier=Modifier.INCLUDES)
    )


def test_multiple_lookups_are_combined_on_one_filter():
    assert GameFilter.where(year_released__gt=2010, mastered=True) == GameFilter(
        year_released=IntCriterion(value=2010, modifier=Modifier.GREATER_THAN),
        mastered=BoolCriterion(value=True, modifier=Modifier.EQUALS),
    )


def test_unknown_field_raises():
    with pytest.raises((TypeError, ValueError)):
        GameFilter.where(does_not_exist=1)


def test_unknown_suffix_raises():
    with pytest.raises((TypeError, ValueError)):
        GameFilter.where(year_released__nope=1)
