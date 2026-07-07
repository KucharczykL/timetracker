"""Filter widget + nested-builder shell contracts.

Pins the Stash-style NumberFilter modifier widget, the comparable-columns
gate + reachable-model registry the nested builder renders from, the
FilterGroup template emission, and the mode->list-URL table.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from common.components import (
    FilterBuilder,
    NumberFilter,
)
from common.components.custom_elements import FILTER_MODE_LIST_URLS, list_url_for

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input", "&lt;a"]


class NumberFilterRenderTest(TestCase):
    """Render-level contract for the Stash-style NumberFilter component."""

    def test_renders_all_eight_modifier_options(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        for modifier in (
            "EQUALS",
            "NOT_EQUALS",
            "GREATER_THAN",
            "LESS_THAN",
            "BETWEEN",
            "NOT_BETWEEN",
            "IS_NULL",
            "NOT_NULL",
        ):
            self.assertIn(f'value="{modifier}"', html)
        self.assertIn("data-number-modifier-select", html)

    def test_renders_two_number_inputs(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        self.assertIn('type="number"', html)
        self.assertIn('name="filter-year"', html)
        self.assertIn('name="filter-year-value2"', html)
        self.assertIn("data-number-value2", html)

    def test_default_modifier_hides_second_input_and_enables_inputs(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        # value2 is hidden for the default EQUALS modifier.
        self.assertRegex(html, r'data-number-value2="" class="[^"]*\bhidden\b')
        # Inputs are not disabled by default (the select's class carries the
        # `disabled:` utility variants, so match the real disabled attribute).
        self.assertNotIn('disabled="true"', html)

    def test_between_shows_second_input_and_prefills_values(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                value="2000",
                value2="2010",
                modifier="BETWEEN",
                path=["year_released"],
            )
        )
        self.assertIn('value="2000"', html)
        self.assertIn('value="2010"', html)
        # The second input must NOT carry the hidden class under BETWEEN.
        self.assertNotRegex(html, r'data-number-value2="" class="[^"]*\bhidden\b')

    def test_presence_modifier_disables_and_clears_inputs(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                value="2000",
                value2="2010",
                modifier="IS_NULL",
                path=["year_released"],
            )
        )
        self.assertIn('disabled="true"', html)
        self.assertIn("cursor-not-allowed", html)
        # Values are cleared while disabled.
        self.assertNotIn('value="2000"', html)
        self.assertNotIn('value="2010"', html)

    def test_invalid_modifier_falls_back_to_equals(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                modifier="INCLUDES",
                path=["year_released"],
            )
        )
        # EQUALS is the selected option when an invalid modifier is given.
        self.assertRegex(html, r'value="EQUALS"[^>]*selected')
        self.assertNotRegex(html, r'value="INCLUDES"')


class HasComparableGroupTest(TestCase):
    """The ≥2-columns-of-one-group gate behind the nested builder's
    `+ comparison` affordance / row template."""

    def _column(self, value, group):
        return {"value": value, "label": value.title(), "group": group, "operators": []}

    def test_empty_is_false(self):
        from common.components.filters import has_comparable_group

        self.assertFalse(has_comparable_group([]))

    def test_single_column_is_false(self):
        from common.components.filters import has_comparable_group

        self.assertFalse(has_comparable_group([self._column("a", "number")]))

    def test_two_columns_different_groups_is_false(self):
        from common.components.filters import has_comparable_group

        columns = [self._column("a", "number"), self._column("b", "datetime")]
        self.assertFalse(has_comparable_group(columns))

    def test_two_columns_same_group_is_true(self):
        from common.components.filters import has_comparable_group

        columns = [self._column("a", "number"), self._column("b", "number")]
        self.assertTrue(has_comparable_group(columns))


class ReachableModelsTest(TestCase):
    """The relation-reachable model set the nested builder needs to render any
    relation's child group offline."""

    def test_reachable_models_is_the_closed_relation_set(self):
        from games.filters import reachable_models

        self.assertEqual(
            set(reachable_models("game")),
            {"game", "session", "purchase", "playevent", "platform", "device"},
        )

    def test_reachable_models_maps_keys_to_filter_classes(self):
        from games.filters import GameFilter, SessionFilter, reachable_models

        models = reachable_models("game")
        self.assertIs(models["game"], GameFilter)
        self.assertIs(models["session"], SessionFilter)

    def test_registry_bundles_fields_and_columns_per_model(self):
        from games.filters import model_field_registry

        registry = model_field_registry("game")
        self.assertEqual(
            set(registry),
            {"game", "session", "purchase", "playevent", "platform", "device"},
        )
        session = registry["session"]
        self.assertIn("fields", session)
        self.assertIn("columns", session)
        # Session's datetime pair reaches the comparison columns.
        column_names = {column["value"] for column in session["columns"]}
        self.assertLessEqual({"timestamp_start", "timestamp_end"}, column_names)
        # The relation entries are discoverable in the field metadata (game→session).
        game_relations = {
            relation["field"]
            for meta in registry["game"]["fields"]
            if meta["kind"] == "relation"
            for relation in meta["relations"]
        }
        self.assertIn("session_filter", game_relations)

    def test_reachable_set_is_the_same_from_any_root(self):
        """The relation graph is strongly connected, so the builder reaches the whole
        model set regardless of which list it is opened from (game/session/…)."""
        from games.filters import reachable_models

        full = {"game", "session", "purchase", "playevent", "platform", "device"}
        for root in full:
            self.assertEqual(set(reachable_models(root)), full, f"root={root}")

    def test_registry_covers_every_reachable_model_and_relation_target(self):
        """The server invariant the client's bundle() fallback relies on: every
        reachable model has a bundle, and every relation target named in any bundle is
        itself a registry key — so a relation descent never lands on a missing model
        (which the client would otherwise silently paper over with the root bundle)."""
        from games.filters import model_field_registry, reachable_models

        for root in ["game", "session", "purchase", "playevent", "platform", "device"]:
            registry = model_field_registry(root)
            self.assertEqual(set(registry), set(reachable_models(root)), f"root={root}")
            for key, bundle in registry.items():
                for meta in bundle["fields"]:
                    for relation in meta["relations"]:
                        self.assertIn(
                            relation["model"].lower(),
                            registry,
                            f"root={root}: relation target {relation['model']!r} "
                            f"(from {key}.{meta['name']}) missing from registry",
                        )


class FilterGroupComparisonTest(TestCase):
    """The nested-builder shell: the multi-model `models` prop + the
    per-model, namespaced templates it emits for the leaf and relation rows."""

    def test_models_prop_carries_every_reachable_model(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        self.assertIn("models=", html)
        # Session's datetime pair — the field-comparison driving use case — reaches
        # the child-model bundle even though the root is game.
        self.assertIn("timestamp_start", html)
        self.assertIn("timestamp_end", html)

    def test_emits_model_namespaced_templates_for_each_reachable_model(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        for key in ("game", "session", "purchase", "playevent", "platform", "device"):
            self.assertIn(f'data-model="{key}"', html)

    def test_emits_comparison_row_template_when_model_has_comparable_group(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="session"))
        self.assertIn("data-fc-row-template", html)
        # The reused single row's hooks reach the cloned template.
        self.assertIn("data-fc-left", html)

    def test_columns_prop_has_no_double_escaped_markup(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="session"))
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)

    def test_emits_chip_and_relation_select_templates(self):
        """Chip + relation-select styling is server-owned: one chip
        template per visual state and one styled <select> template, all
        model-agnostic (emitted once, not per reachable model)."""
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        for state in ("connective-and", "connective-or", "negate-on", "negate-off"):
            self.assertEqual(html.count(f'data-chip-template="{state}"'), 1)
        self.assertEqual(html.count("data-relation-select-template"), 1)


class FilterBuilderApplyUrlTest(SimpleTestCase):
    """FilterBuilder derives apply-url from mode via list_url_for."""

    def test_apply_url_derived_from_mode(self):
        html = str(
            FilterBuilder(model="game", mode="games", preset_api_url="/api/presets/")
        )
        self.assertIn(f'apply-url="{list_url_for("games")}"', html)


class ListUrlForTest(SimpleTestCase):
    """list_url_for is the single mode->list-URL source for filter UIs."""

    def test_known_modes_reverse_to_their_list_views(self):
        for mode, url_name in [
            ("games", "games:list_games"),
            ("sessions", "games:list_sessions"),
            ("purchases", "games:list_purchases"),
            ("playevents", "games:list_playevents"),
            ("devices", "games:list_devices"),
            ("platforms", "games:list_platforms"),
        ]:
            self.assertEqual(list_url_for(mode), reverse(url_name))

    def test_unknown_mode_fails_loudly(self):
        with self.assertRaises(KeyError):
            list_url_for("nonsense")

    def test_keyset_matches_mode_parsers(self):
        # The mode->URL map is the third parallel mode registry (after
        # MODE_PARSERS and FilterPreset.MODE_CHOICES); pin the keysets so a
        # future mode cannot silently miss the URL map.
        from games.filters import MODE_PARSERS

        self.assertEqual(set(FILTER_MODE_LIST_URLS), set(MODE_PARSERS))
