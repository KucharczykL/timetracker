"""Tests for the per-field value-widget builder ``field_widget`` (issue #242).

``field_widget`` is the single entry point that turns a filter field into its value
control, dispatching by the field's ``FieldMeta`` kind to the existing builders. The
flat bars consume it and #192's nested leaf row clones it, so these tests pin the
acceptance cases from the issue plus the dispatch, prefill, and guard behaviour.
"""

import pytest

from common.components.filters import field_widget, field_widget_templates
from games.filters import GameFilter, PurchaseFilter


class TestFieldWidgetKindDispatch:
    """Each field renders the widget its kind implies."""

    def test_status_renders_enum_set_without_m2m_modifiers(self):
        html = str(field_widget(GameFilter, "status"))
        assert 'data-kind="set"' in html
        assert 'name="status"' in html
        # status is a static enum: its five Game.Status options are pre-rendered,
        # and single-valued, so no (All)/(Only) M2M modifiers.
        assert "INCLUDES_ALL" not in html
        assert "INCLUDES_ONLY" not in html

    def test_platform_renders_search_backed_set_without_m2m(self):
        html = str(field_widget(GameFilter, "platform"))
        assert 'data-kind="set"' in html
        assert 'search-url="/api/platforms/search"' in html
        # platform is a single FK (not many-to-many) → no (All)/(Only).
        assert "INCLUDES_ALL" not in html

    def test_year_released_renders_number(self):
        html = str(field_widget(GameFilter, "year_released"))
        assert 'data-kind="number"' in html
        assert 'name="filter-year_released"' in html

    def test_mastered_renders_bool(self):
        html = str(field_widget(GameFilter, "mastered"))
        assert 'data-kind="bool"' in html
        assert 'value="true"' in html
        assert 'value="false"' in html

    def test_created_at_renders_date_range_picker(self):
        html = str(field_widget(GameFilter, "created_at"))
        assert "<date-range-picker" in html
        assert 'name="filter-created_at-min"' in html
        assert 'name="filter-created_at-max"' in html

    def test_games_set_surfaces_all_and_only(self):
        # games is many-to-many on Purchase → field_widget derives is_m2m and
        # surfaces the (All)/(Only) modifiers, the one set field that needs them.
        html = str(field_widget(PurchaseFilter, "games"))
        assert 'data-kind="set"' in html
        assert "INCLUDES_ALL" in html
        assert "INCLUDES_ONLY" in html


class TestFieldWidgetNullableModifiers:
    """The (None)/IS_NULL presence modifier follows the field's nullability."""

    def test_nullable_fk_offers_is_null(self):
        # Game.platform is nullable → presence modifier available.
        assert "IS_NULL" in str(field_widget(GameFilter, "platform"))

    def test_non_nullable_enum_omits_is_null(self):
        # status has a default and is NOT NULL → no IS_NULL presence option.
        assert "IS_NULL" not in str(field_widget(GameFilter, "status"))


class TestFieldWidgetPrefill:
    """A criterion blob prefills the widget; None yields a blank widget."""

    def test_number_blob_prefills_value_and_modifier(self):
        html = str(
            field_widget(
                GameFilter,
                "year_released",
                value={"value": "2015", "modifier": "GREATER_THAN"},
            )
        )
        assert 'value="2015"' in html
        assert "GREATER_THAN" in html

    def test_date_blob_prefills_both_bounds(self):
        html = str(
            field_widget(
                GameFilter,
                "created_at",
                value={
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                },
            )
        )
        assert 'value="2024-01-01"' in html
        assert 'value="2024-12-31"' in html

    def test_none_value_is_blank(self):
        # A blank widget (what #192 clones) renders without error and with no
        # prefilled value.
        html = str(field_widget(GameFilter, "year_released", value=None))
        assert 'data-kind="number"' in html
        assert 'value=""' in html


class TestFieldWidgetPathAndOverride:
    """Cross-entity callers repoint the widget via path + field_name_override."""

    def test_path_overrides_serialized_chain(self):
        html = str(
            field_widget(
                PurchaseFilter,
                "type",
                path=["purchase_filter", "type"],
                field_name_override="purchase_type",
            )
        )
        assert 'name="purchase_type"' in html
        assert "purchase_filter" in html


class TestFieldWidgetGuards:
    def test_relation_field_is_rejected(self):
        with pytest.raises(ValueError):
            field_widget(GameFilter, "session_filter")

    def test_unknown_field_raises(self):
        with pytest.raises(KeyError):
            field_widget(GameFilter, "does_not_exist")


class TestFieldWidgetTemplates:
    """One blank value-widget <template> per non-relation leaf field (for #192)."""

    def test_templates_cover_leaf_fields_and_skip_relations(self):
        templates = field_widget_templates(GameFilter)
        assert "status" in templates
        assert "year_released" in templates
        # relation fields carry no value widget.
        assert "session_filter" not in templates
        assert "purchase_filter" not in templates

    def test_each_template_is_a_template_element_keyed_by_field(self):
        templates = field_widget_templates(GameFilter)
        status_html = str(templates["status"])
        assert status_html.startswith("<template")
        assert 'data-field="status"' in status_html
