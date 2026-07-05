"""Tests for the quick filter bar (#197): the pinned degrade predicate, both
render states, and the round-trip guarantee (a filter shaped like the bar's own
serializer output must reload as editable, never flip to "advanced")."""

import json
from urllib.parse import quote

from django.test import SimpleTestCase, TestCase

from common.components import (
    QUICK_FACET_KINDS,
    QUICK_FACETS,
    QuickFilterBar,
    is_quick_editable,
)
from common.components.custom_elements import list_url_for
from common.components.quick_filter import _MODE_MODELS
from common.criteria import field_metadata
from games.filters import MODE_PARSERS, filter_for_model

_GAME_FACETS = {"status", "platform"}


class IsQuickEditableTest(SimpleTestCase):
    """The pinned #197 predicate: editable iff empty or all top-level keys are
    facet fields with dict (criterion) values."""

    def test_empty_filter_is_editable(self):
        self.assertTrue(is_quick_editable({}, _GAME_FACETS))

    def test_single_facet_is_editable(self):
        parsed = {"status": {"value": [{"id": "f", "label": "Finished"}]}}
        self.assertTrue(is_quick_editable(parsed, _GAME_FACETS))

    def test_all_facets_are_editable(self):
        parsed = {
            "status": {"value": [{"id": "f", "label": "Finished"}]},
            "platform": {"value": [{"id": "1", "label": "PC"}]},
        }
        self.assertTrue(is_quick_editable(parsed, _GAME_FACETS))

    def test_presence_modifier_facet_is_editable(self):
        self.assertTrue(
            is_quick_editable({"platform": {"modifier": "IS_NULL"}}, _GAME_FACETS)
        )

    def test_operator_keys_degrade(self):
        criterion = {"status": {"value": ["f"], "modifier": "INCLUDES"}}
        for operator in ("AND", "OR", "NOT"):
            with self.subTest(operator=operator):
                self.assertFalse(
                    is_quick_editable({operator: [criterion]}, _GAME_FACETS)
                )

    def test_relation_key_degrades(self):
        parsed = {"session_filter": {"device": {"value": [{"id": "1", "label": "PC"}]}}}
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS))

    def test_field_comparisons_degrade(self):
        parsed = {"field_comparisons": [{"left": "created_at", "right": "updated_at"}]}
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS))

    def test_search_degrades(self):
        self.assertFalse(
            is_quick_editable(
                {"search": {"value": "mario", "modifier": "INCLUDES"}}, _GAME_FACETS
            )
        )

    def test_non_facet_flat_leaf_degrades(self):
        self.assertFalse(
            is_quick_editable(
                {"year_released": {"value": 2020, "modifier": "EQUALS"}}, _GAME_FACETS
            )
        )

    def test_facet_mixed_with_operator_degrades(self):
        parsed = {
            "status": {"value": ["f"], "modifier": "INCLUDES"},
            "AND": [{"platform": {"value": ["1"]}}],
        }
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS))

    def test_facet_with_non_dict_value_degrades(self):
        self.assertFalse(is_quick_editable({"status": "f"}, _GAME_FACETS))
        self.assertFalse(is_quick_editable({"status": ["f"]}, _GAME_FACETS))


class QuickFilterBarRenderingTest(TestCase):
    def _editable_markers(self, html: str, mode: str) -> None:
        self.assertIn("<quick-filter-bar", html)
        self.assertIn(f'apply-url="{list_url_for(mode)}"', html)
        # The facets live in a form with an Apply submit button (Enter applies).
        self.assertIn("<form", html)
        self.assertIn('type="submit"', html)
        self.assertIn(">Apply<", html)
        for facet in QUICK_FACETS[mode]:
            self.assertIn(f"{facet.label}:", html)
            # Attribute values are escaped, so the data-path JSON renders with
            # &quot; entities.
            self.assertIn(f'data-path="[&quot;{facet.field}&quot;]"', html)

    def test_blank_filter_renders_editable_for_every_mode(self):
        for mode in QUICK_FACETS:
            with self.subTest(mode=mode):
                html = str(QuickFilterBar(mode=mode, filter_json="", builder_url="/x"))
                self._editable_markers(html, mode)

    def test_unparseable_json_renders_editable(self):
        # Same leniency as the flat bar's _filter_parse: garbage parses to {}.
        html = str(QuickFilterBar(mode="games", filter_json="{oops", builder_url="/x"))
        self.assertIn("<quick-filter-bar", html)

    def test_facet_prefill_renders_include_pill(self):
        filter_json = json.dumps(
            {
                "status": {
                    "value": [{"id": "f", "label": "Finished"}],
                    "modifier": "INCLUDES",
                }
            }
        )
        html = str(
            QuickFilterBar(mode="games", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertIn("Finished", html)

    def test_round_trip_guarantee_serializer_shape_is_editable(self):
        """A filter shaped exactly like ts/elements/quick-filter-bar.ts emits
        (buildSetCriterion output, incl. the empty excludes list) must render
        editable — the bar can never lock itself out (#197)."""
        filter_json = json.dumps(
            {
                "status": {
                    "value": [{"id": "f", "label": "Finished"}],
                    "excludes": [],
                    "modifier": "INCLUDES",
                },
                "platform": {"modifier": "IS_NULL"},
            }
        )
        html = str(
            QuickFilterBar(mode="games", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)

    def test_scalar_round_trip_serializer_shapes_are_editable(self):
        """The scalar facets' serializer output (number criterion from
        readNumberWidget, date criterion from readDateWidget) must render an
        editable sessions bar with the values prefilled."""
        filter_json = json.dumps(
            {
                "duration_total_hours": {"value": 2, "modifier": "GREATER_THAN"},
                "timestamp_start": {
                    "value": "2026-01-01",
                    "value2": "2026-02-01",
                    "modifier": "BETWEEN",
                },
            }
        )
        html = str(
            QuickFilterBar(mode="sessions", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)
        # NumberFilter prefill: value + modifier selection survive the round trip.
        self.assertIn('value="2"', html)
        self.assertIn('value="GREATER_THAN" selected', html)
        # DateRangePicker prefill: both hidden ISO bounds carry the range.
        self.assertIn('value="2026-01-01"', html)
        self.assertIn('value="2026-02-01"', html)

    def test_advanced_filter_renders_degraded_pill(self):
        filter_json = json.dumps(
            {"AND": [{"status": {"value": [{"id": "f", "label": "Finished"}]}}]}
        )
        builder_url = f"/tracker/game/filter?filter={quote(filter_json)}"
        html = str(
            QuickFilterBar(
                mode="games", filter_json=filter_json, builder_url=builder_url
            )
        )
        self.assertNotIn("<quick-filter-bar", html)
        self.assertIn("Advanced filter active", html)
        self.assertIn("Edit in builder", html)
        self.assertIn(f'href="{builder_url.replace("&", "&amp;")}"', html)
        self.assertIn("Clear", html)
        self.assertIn(f'href="{list_url_for("games")}"', html)


class QuickFacetsContractTest(TestCase):
    """QUICK_FACETS stays consistent with the filter layer as it evolves."""

    def test_modes_are_known_filter_modes(self):
        self.assertLessEqual(set(QUICK_FACETS), set(MODE_PARSERS))
        self.assertEqual(set(QUICK_FACETS), set(_MODE_MODELS))

    def test_every_facet_is_an_own_model_leaf_field(self):
        for mode, facets in QUICK_FACETS.items():
            metadata = {
                meta["name"]: meta
                for meta in field_metadata(filter_for_model(_MODE_MODELS[mode]))
            }
            for facet in facets:
                with self.subTest(mode=mode, facet=facet.field):
                    self.assertIn(facet.field, metadata)
                    self.assertIn(metadata[facet.field]["kind"], QUICK_FACET_KINDS)
