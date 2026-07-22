"""Tests for the quick filter bar: the pinned degrade predicate, both
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
    """The pinned degrade predicate: editable iff empty or all top-level keys are
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
        # Apply + Clear are one segmented ButtonGroup — a single visual unit
        # that row wrapping can't separate. Order is asserted inside
        # the group's slice: the date facets' calendars carry their own
        # ">Clear<" buttons earlier in the document.
        self.assertIn('role="group"', html)
        group_html = html[html.index('role="group"') :]
        self.assertLess(group_html.index(">Apply<"), group_html.index(">Clear<"))
        derived_labels = {
            meta["name"]: meta["label"]
            for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
        }
        for facet in QUICK_FACETS[mode]:
            expected_label = facet.label or derived_labels[facet.field]
            # Every facet is a "Label ▾" dropdown trigger opening a combobox
            # dialog — no inline "Label:" span anywhere.
            self.assertNotIn(f"{expected_label}:", html)
            self.assertIn(f">{expected_label}<svg", html)
            self.assertIn(f'id="quick-{facet.field}-dropdown"', html)
            self.assertIn(f'aria-label="{expected_label}"', html)
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
        # parse_filter_dict is lenient: garbage parses to {}.
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
        editable — the bar can never lock itself out."""
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
        (e.g. games.status → "Status") on the dropdown trigger, so filter-layer
        renames propagate."""
        html = str(QuickFilterBar(mode="games", filter_json="", builder_url="/x"))
        self.assertIn(">Status<svg", html)
        self.assertIn(">Platform<svg", html)
        # And an override still wins where the compact wording differs.
        self.assertIn(">Year<svg", html)
        self.assertNotIn("Year Released", html)

    def test_degraded_pill_without_builder_url_omits_edit_link(self):
        """With no builder_url the degraded pill offers only Clear — an Edit link
        would 404. (Every mode now has a builder page, #336; this guards the
        component's empty-builder_url branch directly.)"""
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

    def test_sort_is_quoted_into_the_url(self):
        # The active sort threads into the builder so a preset saved there can
        # capture it and Apply preserves it (#77).
        url = builder_url_for("games", "", "-playtime,name")
        self.assertIn(f"?sort={quote('-playtime,name')}", url)

    def test_filter_and_sort_combine_with_ampersand(self):
        filter_json = json.dumps({"status": {"value": ["f"]}})
        url = builder_url_for("games", filter_json, "-playtime")
        self.assertIn(f"?filter={quote(filter_json)}", url)
        self.assertIn(f"&sort={quote('-playtime')}", url)

    def test_no_sort_leaves_url_sortless(self):
        self.assertNotIn("sort=", builder_url_for("games", "", None))
        self.assertNotIn("sort=", builder_url_for("games", "", ""))

    def test_non_default_per_page_is_carried(self):
        url = builder_url_for("games", "", None, 100)
        self.assertIn("?per_page=100", url)

    def test_explicit_default_per_page_is_carried(self):
        from games.filters import FindFilter

        self.assertIn(
            f"per_page={FindFilter.per_page}",
            builder_url_for("games", "", None, FindFilter.per_page),
        )

    def test_inherited_per_page_is_not_carried(self):
        self.assertNotIn("per_page=", builder_url_for("games", "", None, None))

    def test_quick_bar_receives_normalized_per_page_override(self):
        html = str(
            QuickFilterBar(mode="games", apply_url="/games", per_page_override=25)
        )
        self.assertIn('per-page="25"', html)

    def test_quick_bar_emits_empty_override_when_inherited(self):
        html = str(QuickFilterBar(mode="games", apply_url="/games"))
        self.assertIn('per-page=""', html)

    def test_sort_and_per_page_combine_with_ampersand(self):
        url = builder_url_for("games", "", "-playtime", 50)
        self.assertIn(f"?sort={quote('-playtime')}", url)
        self.assertIn("&per_page=50", url)

    def test_devices_and_platforms_have_builder_urls(self):
        # Every filterable mode now has a builder page (#336).
        for mode in ("devices", "platforms"):
            with self.subTest(mode=mode):
                url = builder_url_for(mode, "")
                self.assertIn(f"/{FILTER_MODE_MODELS[mode]}/", url)
                self.assertTrue(url.endswith("/filter"))

    def test_devices_and_platforms_carry_active_sort(self):
        # #335 gave devices/platforms sort maps, so their views thread the active
        # sort into the builder URL — a preset saved there then captures it.
        for mode in ("devices", "platforms"):
            with self.subTest(mode=mode):
                url = builder_url_for(mode, "", "-created")
                self.assertIn(f"sort={quote('-created')}", url)

    def test_unknown_mode_raises(self):
        with self.assertRaises(LookupError):
            builder_url_for("nonsense", "")


class DropdownFacetA11yTest(TestCase):
    def test_set_facets_name_their_search_inputs(self):
        # The visible label lives on the trigger, so the combobox input inside
        # the panel must carry the accessible name itself.
        html = str(QuickFilterBar(mode="sessions", filter_json=""))
        for label in ("Game", "Device"):
            with self.subTest(label=label):
                self.assertRegex(
                    html,
                    rf'data-search-select-search[^>]*aria-label="{label}"',
                )


class ActionGroupTest(TestCase):
    """The action group: Apply | Clear, plus the builder entry point
    whenever the mode has a builder page (builder_url non-empty)."""

    def test_builder_url_adds_advanced_filter_segment(self):
        html = str(
            QuickFilterBar(mode="sessions", filter_json="", builder_url="/builder-url")
        )
        group_html = html[html.index('role="group"') :]
        self.assertIn(">Advanced filter…<", group_html)
        self.assertIn('href="/builder-url"', group_html)

    def test_no_builder_url_no_advanced_segment(self):
        html = str(QuickFilterBar(mode="devices", filter_json=""))
        self.assertNotIn("Advanced filter…", html)


class PresetPickerTest(TestCase):
    """The Load-preset picker rides in the bar as non-collapsible row
    furniture when a preset API URL is given — load-only."""

    def test_preset_api_url_renders_the_picker_after_the_overflow_host(self):
        html = str(
            QuickFilterBar(mode="games", filter_json="", preset_api_url="/api/presets/")
        )
        self.assertIn("data-preset-picker", html)
        self.assertIn('id="quick-games-preset-picker"', html)
        self.assertIn('search-url="/api/presets/?mode=games"', html)
        # Furniture placement: picker AFTER the ⋯ overflow host (the TS
        # reserve calc treats post-overflow siblings as non-collapsible).
        self.assertLess(
            html.index("data-quick-overflow"), html.index("data-preset-picker")
        )

    def test_no_preset_api_url_no_picker(self):
        html = str(QuickFilterBar(mode="games", filter_json=""))
        self.assertNotIn("data-preset-picker", html)


class ApplyUrlOverrideTest(TestCase):
    """apply_url gates every derived list URL: synthetic e2e harnesses
    render the bar under a stripped ROOT_URLCONF where reverse() would crash."""

    def test_apply_url_reaches_element_and_clear(self):
        html = str(QuickFilterBar(mode="games", filter_json="", apply_url="/synthetic"))
        self.assertIn('apply-url="/synthetic"', html)
        self.assertIn('href="/synthetic"', html)

    def test_apply_url_reaches_the_degraded_pill(self):
        filter_json = json.dumps({"AND": [{"status": {"value": ["f"]}}]})
        html = str(
            QuickFilterBar(
                mode="games", filter_json=filter_json, apply_url="/synthetic"
            )
        )
        self.assertIn("Advanced filter active", html)
        self.assertIn('href="/synthetic"', html)
