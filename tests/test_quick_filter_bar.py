"""Tests for the quick filter bar (#197): the pinned degrade predicate, both
render states, and the round-trip guarantee (a filter shaped like the bar's own
serializer output must reload as editable, never flip to "advanced")."""

import json
import re
from urllib.parse import quote

from django.test import SimpleTestCase, TestCase

from common.components import (
    QUICK_FACET_KINDS,
    QUICK_FACETS,
    QuickFilterBar,
    is_quick_editable,
)
from common.components.custom_elements import FILTER_MODE_MODELS, list_url_for
from common.criteria import field_metadata
from games.filters import MODE_PARSERS, filter_for_model
from games.views.filtering import BUILDER_MODES, builder_url_for

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
        # The facets live in a form with an Apply submit button (Enter applies)
        # and a Clear link back to the bare list URL (radios/selects have no
        # per-widget unset).
        self.assertIn("<form", html)
        self.assertIn('type="submit"', html)
        self.assertIn(">Apply<", html)
        self.assertIn(">Clear<", html)
        self.assertIn(f'href="{list_url_for(mode)}"', html)
        derived_labels = {
            meta["name"]: meta["label"]
            for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
        }
        for facet in QUICK_FACETS[mode]:
            expected_label = facet.label or derived_labels[facet.field]
            if facet.dropdown:
                # A dropdown facet (#315 tryout) renders a "Label ▾" trigger
                # opening a combobox dialog — no "Label:" span.
                self.assertNotIn(f"{expected_label}:", html)
                self.assertIn(f">{expected_label}<svg", html)
                self.assertIn(f'id="quick-{facet.field}-dropdown"', html)
                self.assertIn(f'aria-label="{expected_label}"', html)
            else:
                self.assertIn(f"{expected_label}:", html)
            # Attribute values are escaped, so the data-path JSON renders with
            # &quot; entities. Present for every facet — the serializer finds
            # dropdown-facet widgets inside the (hidden) dialog panel too.
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

    def test_bool_and_aggregate_round_trip_shapes_are_editable(self):
        """The games bar's bool facet (readBoolWidget output) and aggregate
        number facets (readNumberWidget output over flat aggregate keys) must
        render editable with the values prefilled."""
        filter_json = json.dumps(
            {
                "mastered": {"value": True, "modifier": "EQUALS"},
                "session_count": {"value": 3, "modifier": "GREATER_THAN"},
                "purchase_price_total": {
                    "value": 10,
                    "value2": 100,
                    "modifier": "BETWEEN",
                },
            }
        )
        html = str(
            QuickFilterBar(mode="games", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)
        self.assertIn('value="3"', html)
        self.assertIn('value="10"', html)
        self.assertIn('value="100"', html)
        # The bool prefill checks exactly the True radio.
        mastered_radios = re.findall(r'<input[^>]*name="quick-mastered"[^>]*>', html)
        checked = [tag for tag in mastered_radios if "checked" in tag]
        self.assertEqual(len(checked), 1)
        self.assertIn('value="true"', checked[0])

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

    def test_facet_labels_default_from_field_metadata(self):
        """A facet without a label override renders the FieldMeta-derived label
        (e.g. games.status → "Status"), so filter-layer renames propagate."""
        html = str(QuickFilterBar(mode="games", filter_json="", builder_url="/x"))
        self.assertIn("Status:", html)
        self.assertIn("Platform:", html)
        # And an override still wins where the compact wording differs.
        self.assertIn("Year:", html)
        self.assertNotIn("Year Released:", html)

    def test_degraded_pill_without_builder_url_omits_edit_link(self):
        """Modes without a nested-builder page (devices/platforms) pass no
        builder_url; the pill offers only Clear — an Edit link would 404."""
        filter_json = json.dumps({"session_filter": {"emulated": {"value": True}}})
        html = str(QuickFilterBar(mode="devices", filter_json=filter_json))
        self.assertIn("Advanced filter active", html)
        self.assertNotIn("Edit in builder", html)
        self.assertIn("Clear", html)
        self.assertIn(f'href="{list_url_for("devices")}"', html)


class QuickFacetsContractTest(TestCase):
    """QUICK_FACETS stays consistent with the filter layer as it evolves."""

    def test_modes_are_known_filter_modes(self):
        self.assertLessEqual(set(QUICK_FACETS), set(MODE_PARSERS))
        self.assertEqual(set(QUICK_FACETS), set(FILTER_MODE_MODELS))
        # The canonical mapping resolves every mode to a real filter class.
        self.assertEqual(set(FILTER_MODE_MODELS), set(MODE_PARSERS))
        for mode, model in FILTER_MODE_MODELS.items():
            with self.subTest(mode=mode):
                filter_for_model(model)

    def test_every_facet_is_an_own_model_leaf_field(self):
        for mode, facets in QUICK_FACETS.items():
            metadata = {
                meta["name"]: meta
                for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
            }
            for facet in facets:
                with self.subTest(mode=mode, facet=facet.field):
                    self.assertIn(facet.field, metadata)
                    self.assertIn(metadata[facet.field]["kind"], QUICK_FACET_KINDS)


class BuilderUrlForTest(TestCase):
    """builder_url_for is the single home of the builder URL format and of
    which modes have a builder page at all (BUILDER_MODES)."""

    def test_builder_modes_produce_the_builder_url(self):
        for mode in BUILDER_MODES:
            with self.subTest(mode=mode):
                bare = builder_url_for(mode, "")
                self.assertTrue(bare.endswith("/filter"))
                self.assertIn(f"/{FILTER_MODE_MODELS[mode]}/", bare)
                self.assertNotIn("?", bare)

    def test_filter_json_is_quoted_into_the_url(self):
        filter_json = json.dumps({"status": {"value": ["f"]}})
        url = builder_url_for("games", filter_json)
        self.assertIn(f"?filter={quote(filter_json)}", url)

    def test_builderless_modes_raise(self):
        for mode in ("devices", "platforms"):
            with self.subTest(mode=mode):
                with self.assertRaises(LookupError):
                    builder_url_for(mode, "")


class DropdownFacetGuardTest(TestCase):
    """The two ValueError guards behind the #315 dropdown facets: misuse must
    fail loudly at render, never emit a broken widget."""

    def test_dropdown_facet_requires_a_set_field(self):
        from common.components.quick_filter import QuickFacet

        bar = QuickFilterBar(mode="sessions", filter_json="")
        filter_cls = filter_for_model(FILTER_MODE_MODELS["sessions"])
        date_facet = QuickFacet("timestamp_start", "Started", dropdown=True)
        with self.assertRaises(ValueError):
            bar._facet(filter_cls, date_facet)

    def test_field_widget_panel_layout_requires_a_set_field(self):
        from common.components.filters import field_widget

        filter_cls = filter_for_model(FILTER_MODE_MODELS["sessions"])
        with self.assertRaises(ValueError):
            field_widget(filter_cls, "duration_total_hours", layout="panel")

    def test_sessions_dropdown_facets_name_their_search_inputs(self):
        # The visible label lives on the trigger, so the combobox input inside
        # the panel must carry the accessible name itself.
        html = str(QuickFilterBar(mode="sessions", filter_json=""))
        for label in ("Game", "Device"):
            with self.subTest(label=label):
                self.assertRegex(
                    html,
                    rf'data-search-select-search[^>]*aria-label="{label}"',
                )
