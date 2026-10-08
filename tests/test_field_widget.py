"""Tests for the per-field value-widget builder ``field_widget`` (issue #242).

``field_widget`` is the single entry point that turns a filter field into its value
control, dispatching by the field's ``FieldMeta`` kind to the existing builders. The
flat bars consume it and #192's nested leaf row clones it, so these tests pin the
acceptance cases from the issue plus the dispatch, prefill, and guard behaviour.
"""

import re
from zoneinfo import ZoneInfo

import pytest

from common.components.filters import (
    field_widget as _field_widget,
)
from common.components.filters import (
    field_widget_templates as _field_widget_templates,
)
from common.criteria import DURATION_HOURS, field_metadata
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.filters import (
    DeviceFilter,
    GameFilter,
    HistoricalPlaytimeFilter,
    PlatformFilter,
    PlayerSessionFilter,
    PlaythroughFilter,
    PurchaseFilter,
)

_ALL_FILTERS = [
    GameFilter,
    PlayerSessionFilter,
    PurchaseFilter,
    DeviceFilter,
    PlatformFilter,
    PlaythroughFilter,
    HistoricalPlaytimeFilter,
]

_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def field_widget(*args, **kwargs):
    return _field_widget(*args, presentation=_PRESENTATION, **kwargs)


def field_widget_templates(*args, **kwargs):
    return _field_widget_templates(*args, presentation=_PRESENTATION, **kwargs)


class TestFieldWidgetKindDispatch:
    """Each field renders the widget its kind implies."""

    def test_status_renders_enum_set_without_m2m_modifiers(self):
        html = str(field_widget(GameFilter, "status"))
        assert 'data-kind="set"' in html
        assert 'name="status"' in html
        # Static enum, single-valued: no M2M modifiers.
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

    def test_aggregate_field_renders_number(self):
        # Aggregates (session_count) have no `fields` entry, so field_metadata
        # carries field_spec=None — field_widget must still build a number widget.
        html = str(field_widget(GameFilter, "session_count"))
        assert 'data-kind="number"' in html
        assert 'name="filter-session_count"' in html

    def test_a_string_offers_only_the_modes_its_field_states(self):
        # A mode the field refuses builds an unappliable filter.
        #
        # search reads several columns, so it states no presence pair, and
        # neither does a column that cannot be NULL.
        html = str(field_widget(GameFilter, "search"))
        assert 'data-kind="string"' in html
        assert 'value="IS_NULL"' not in html
        assert 'value="NOT_NULL"' not in html
        assert 'value="INCLUDES"' in html

    @pytest.mark.parametrize("filter_cls", _ALL_FILTERS)
    @pytest.mark.parametrize("kind", ["string", "number"])
    def test_every_widget_offers_its_field_s_own_vocabulary(self, filter_cls, kind):
        for meta in field_metadata(filter_cls):
            if meta["kind"] != kind:
                continue
            html = str(field_widget(filter_cls, meta["name"]))
            rendered = re.findall(
                r'data-search-select-option="" data-value="([A-Z_]+)"', html
            )
            assert rendered == list(meta["modifiers"]), meta["name"]

    def test_a_count_aggregate_offers_no_presence_modifier(self):
        # Count answers 0 over no rows, so "is null" on one matches nothing.
        html = str(field_widget(GameFilter, "session_count"))
        assert 'value="IS_NULL"' not in html
        assert 'value="NOT_NULL"' not in html

    def test_a_duration_average_offers_no_presence_pair(self):
        # A duration average reads 0 h.
        html = str(field_widget(GameFilter, "session_average"))
        assert 'value="IS_NULL"' not in html
        assert 'value="NOT_NULL"' not in html

    def test_a_summed_aggregate_keeps_the_presence_pair(self):
        html = str(field_widget(GameFilter, "purchase_price_total"))
        assert 'value="IS_NULL"' in html

    def test_enum_options_render_in_model_choice_order(self):
        # The enum widget's options come from FieldMeta["choices"] (the model
        # field's choices). Assert all PlayerGameStatus options render, in order,
        # with their labels — a regression in choice sourcing/order would slip
        # past the bare data-kind check.
        from games.models import PlayerGameStatus

        html = str(field_widget(GameFilter, "status"))
        positions = []
        for value, label in PlayerGameStatus.choices:
            assert f'data-value="{value}"' in html, f"missing option {value!r}"
            assert label in html, f"missing label {label!r}"
            positions.append(html.index(f'data-value="{value}"'))
        assert positions == sorted(positions), "status options out of declared order"


class TestFieldWidgetNullableModifiers:
    """The (None)/IS_NULL presence modifier follows the field's nullability."""

    def test_nullable_fk_offers_is_null(self):
        # Game.platform is nullable → presence modifier available.
        assert "IS_NULL" in str(field_widget(GameFilter, "platform"))

    def test_non_nullable_enum_omits_is_null(self):
        # status has a default and is NOT NULL → no IS_NULL presence option.
        assert "IS_NULL" not in str(field_widget(GameFilter, "status"))


class TestFieldWidgetDurationUnit:
    """Duration fields offer plain number labels and no presence pair."""

    def test_duration_offers_no_none_option(self):
        html = str(field_widget(GameFilter, "playtime_hours"))
        assert 'value="IS_NULL"' not in html
        assert 'value="NOT_NULL"' not in html
        assert "is 0 (none)" not in html
        assert "is more than 0" not in html
        assert "is null" not in html

    def test_duration_keeps_plain_number_labels(self):
        html = str(field_widget(GameFilter, "playtime_hours"))
        assert "is at least" in html
        assert "between" in html

    def test_other_numbers_keep_null_labels(self):
        html = str(field_widget(GameFilter, "purchase_price_total"))
        assert "is null" in html

    def test_duration_handler_field_states_step_any(self):
        html = str(field_widget(GameFilter, "playtime_hours", step="1"))
        assert 'step="any"' in html
        assert 'step="1"' not in html

    def test_duration_aggregate_states_step_any(self):
        html = str(field_widget(GameFilter, "session_average", step="1"))
        assert 'step="any"' in html
        assert 'step="1"' not in html

    def test_duration_widget_in_the_builder_layout_states_step_any(self):
        html = str(field_widget(GameFilter, "playtime_hours", step="1", layout="field"))
        assert 'step="any"' in html

    def test_a_duration_fallback_drops_the_presence_pair(self):
        from common.components.filters import NumberFilter

        html = str(
            NumberFilter("playtime", path=["playtime_hours"], unit=DURATION_HOURS)
        )
        assert 'value="IS_NULL"' not in html
        assert 'value="NOT_NULL"' not in html
        assert 'value="EQUALS"' in html

    def test_a_number_fallback_keeps_the_presence_pair(self):
        from common.components.filters import NumberFilter

        html = str(NumberFilter("year", path=["year_released"]))
        assert 'value="IS_NULL"' in html

    @pytest.mark.parametrize("modifier", ["EQUALS", "NOT_EQUALS", "GREATER_THAN"])
    def test_a_decimal_value_survives_in_the_input(self, modifier):
        from common.components.filters import NumberFilter

        html = str(
            NumberFilter(
                "playtime",
                value="1.5",
                modifier=modifier,
                path=["playtime_hours"],
                unit=DURATION_HOURS,
            )
        )
        assert 'value="1.5"' in html


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
                "kind",
                path=["purchase_filter", "kind"],
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
