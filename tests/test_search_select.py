"""Tests for the SearchSelect component, the Pill primitive, the games resolver,
the search API endpoint, and the shared Game.search_label."""

import unittest

import django.test
from django.utils.safestring import SafeText

from common.components import (
    FilterSelect,
    Pill,
    SearchSelect,
    searchselect_selected,
)
from games.models import Game, Platform


class PillTest(unittest.TestCase):
    def test_returns_safetext(self):
        self.assertIsInstance(Pill("hi"), SafeText)

    def test_plain_pill_has_data_pill_no_remove(self):
        html = Pill("hi")
        self.assertIn("data-pill", html)
        self.assertNotIn("data-pill-remove", html)

    def test_removable_adds_remove_button(self):
        html = Pill("hi", removable=True)
        self.assertIn("data-pill-remove", html)
        self.assertIn('aria-label="Remove"', html)

    def test_value_becomes_data_value(self):
        html = Pill("hi", value="42")
        self.assertIn('data-value="42"', html)

    def test_no_value_omits_data_value(self):
        self.assertNotIn("data-value", Pill("hi"))

    def test_label_is_escaped(self):
        html = Pill("<b>x</b>")
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>x</b>", html)

    def test_extra_data_attributes(self):
        html = Pill("hi", attributes=[("data-platform", "3")])
        self.assertIn('data-platform="3"', html)


class SearchSelectComponentTest(unittest.TestCase):
    def test_returns_safetext(self):
        self.assertIsInstance(SearchSelect(name="games"), SafeText)

    def test_empty_options_renders_no_results_scaffold(self):
        html = SearchSelect(name="games")
        self.assertIn("data-search-select-no-results", html)
        self.assertIn("No results", html)

    def test_outer_container_carries_config(self):
        html = SearchSelect(
            name="games", search_url="/api/games/search", multi_select=True
        )
        self.assertIn("data-search-select", html)
        self.assertIn('data-name="games"', html)
        self.assertIn('data-search-url="/api/games/search"', html)
        self.assertIn('data-multi="true"', html)

    def test_multi_selected_renders_pills_and_hidden_inputs(self):
        html = SearchSelect(
            name="games",
            multi_select=True,
            selected=[{"value": 7, "label": "Game A", "data": {"platform": "2"}}],
        )
        self.assertIn("data-pill", html)
        self.assertIn('<input name="games" value="7" type="hidden">', html)
        self.assertIn('data-platform="2"', html)
        # exactly one submitted value (the hidden input) — the search box has no
        # name. The leading space avoids matching the container's data-name.
        self.assertEqual(html.count(' name="games"'), 1)

    def test_single_selected_has_no_pill_and_value_in_search_box(self):
        html = SearchSelect(
            name="games",
            selected=[{"value": 7, "label": "Game A", "data": {"platform": "2"}}],
        )
        # single-select renders no pill — the label lives in the search box
        self.assertNotIn("data-pill", html)
        self.assertIn('value="Game A"', html)
        # the value is still submitted via a lone hidden input
        self.assertIn('<input name="games" value="7" type="hidden">', html)
        self.assertEqual(html.count(' name="games"'), 1)

    def test_search_box_has_no_name(self):
        html = SearchSelect(name="games")
        self.assertIn("data-search-select-search", html)
        # container exposes data-name, never a submittable name on the search box
        self.assertEqual(html.count(' name="games"'), 0)

    def test_tuple_options_are_normalized(self):
        html = SearchSelect(name="t", options=[("1", "One")])
        self.assertIn('data-search-select-option=""', html)
        self.assertIn('data-value="1"', html)
        self.assertIn("One", html)

    def test_options_omitted_when_search_url_set(self):
        html = SearchSelect(
            name="t", options=[("1", "One")], search_url="/api/games/search"
        )
        # No pre-rendered rows in the live panel; the row prototype lives only in
        # the cloneable <template>.
        panel = html.split("data-search-select-template")[0]
        self.assertNotIn('data-search-select-option=""', panel)
        self.assertIn('data-search-select-template="row"', html)

    def test_templates_carry_label_slot_for_js_cloning(self):
        # The dynamic shapes the JS clones expose a [data-search-select-label] slot so the JS
        # only fills text — classes/structure stay server-side.
        html = SearchSelect(name="t", search_url="/api/games/search", multi_select=True)
        self.assertIn('data-search-select-template="row"', html)
        self.assertIn('data-search-select-template="pill"', html)
        self.assertIn("data-search-select-label", html)

    def test_shell_region_order_pills_search_options(self):
        # The shared shell assembles the three regions in a fixed order; option
        # rows precede the trailing no-results node inside the options panel.
        html = SearchSelect(name="t", options=[("1", "One")])
        pills = html.index("data-search-select-pills")
        search = html.index("data-search-select-search")
        options = html.index("data-search-select-options")
        option_row = html.index('data-search-select-option=""')
        no_results = html.index("data-search-select-no-results")
        self.assertLess(pills, search)
        self.assertLess(search, options)
        self.assertLess(options, option_row)
        self.assertLess(option_row, no_results)

    def test_prefetch_attribute_and_defaults(self):
        # Default prefetch is 0 in SearchSelect
        html_default = SearchSelect(name="t")
        self.assertIn('data-prefetch="0"', html_default)

        # Custom prefetch is rendered
        html_custom = SearchSelect(name="t", prefetch=42)
        self.assertIn('data-prefetch="42"', html_custom)


class FilterSelectComponentTest(unittest.TestCase):
    MODIFIERS = [("NOT_NULL", "(Any)"), ("IS_NULL", "(None)")]

    def test_returns_safetext(self):
        self.assertIsInstance(FilterSelect(field_name="type"), SafeText)

    def test_is_filter_mode_on_shared_shell(self):
        html = FilterSelect(field_name="type")
        # Reuses the SearchSelect shell (data-search-select) but flags filter mode.
        self.assertIn("data-search-select", html)
        self.assertIn('data-search-select-mode="filter"', html)
        self.assertIn('data-name="type"', html)
        # No name is submitted — state is read from the DOM into the filter JSON.
        self.assertEqual(html.count(' name="type"'), 0)

    def test_value_rows_have_include_exclude_buttons(self):
        html = FilterSelect(field_name="type", options=[("g", "Game")])
        self.assertIn('data-search-select-action="include"', html)
        self.assertIn('data-search-select-action="exclude"', html)
        self.assertIn('data-value="g"', html)

    def test_included_renders_check_pill_excluded_renders_cross_pill(self):
        html = FilterSelect(
            field_name="platform",
            options=[("1", "Steam"), ("2", "GOG")],
            included=[("1", "Steam")],
            excluded=[("2", "GOG")],
        )
        # Labels live in a [data-search-select-label] slot (so JS can fill clones); the ✓/✗
        # symbol is a sibling text node.
        self.assertIn('data-search-select-type="include"', html)
        self.assertIn("✓", html)
        self.assertIn(">Steam</span>", html)
        self.assertIn('data-search-select-type="exclude"', html)
        self.assertIn("✗", html)
        self.assertIn(">GOG</span>", html)
        self.assertIn("line-through", html)  # excluded pill styling

    def test_modifier_options_render_pinned_rows(self):
        html = FilterSelect(field_name="platform", modifier_options=self.MODIFIERS)
        # Pinned pseudo-options carry data-search-select-modifier-option, never data-search-select-option,
        # so the text filter leaves them visible.
        self.assertIn('data-search-select-modifier-option="NOT_NULL"', html)
        self.assertIn('data-search-select-modifier-option="IS_NULL"', html)

    def test_modifier_pill_coexists_with_value_pills(self):
        """Modifier and value pills both render server-side; the JS handles
        mutual exclusivity for presence modifiers (PRESENCE_MODIFIERS)."""
        html = FilterSelect(
            field_name="platform",
            options=[("1", "Steam")],
            included=[("1", "Steam")],
            modifier="IS_NULL",
            modifier_options=self.MODIFIERS,
        )
        # Both the modifier pill and the value pill render.
        self.assertIn('data-search-select-modifier="IS_NULL"', html)
        self.assertIn("(None)", html)
        self.assertIn(
            'data-search-select-type="include"', html
        )  # value pill present
        self.assertIn('data-modifier="IS_NULL"', html)  # container carries it too

    def test_search_url_omits_value_rows_but_keeps_modifiers(self):
        html = FilterSelect(
            field_name="game",
            search_url="/api/games/search",
            prefetch=20,
            modifier_options=self.MODIFIERS,
        )
        # No value rows in the live panel (they're fetched); the row prototype
        # lives only in a <template>.
        panel = html.split("data-search-select-template")[0]
        self.assertNotIn('data-search-select-option=""', panel)
        self.assertIn('data-search-select-template="row"', html)
        self.assertIn(
            'data-search-select-modifier-option="NOT_NULL"', html
        )  # still pinned
        self.assertIn('data-prefetch="20"', html)

    def test_search_url_pills_use_resolved_labels(self):
        # A selected value outside the fetched window still shows its label.
        html = FilterSelect(
            field_name="game",
            search_url="/api/games/search",
            excluded=[{"value": 4172, "label": "Obscure Game", "data": {}}],
        )
        self.assertIn(">Obscure Game</span>", html)
        self.assertIn('data-value="4172"', html)

    M2M_MODIFIERS = [
        ("INCLUDES_ALL", "(All)"),
        ("INCLUDES_ONLY", "(Only)"),
    ]

    def test_m2m_modifiers_render_as_option_rows(self):
        """M2M modifiers (All)/(Only) render as modifier-option rows in the
        dropdown, not as a separate <select>."""
        html = FilterSelect(
            field_name="games",
            modifier_options=[
                ("NOT_NULL", "(Any)"),
                ("IS_NULL", "(None)"),
                ("INCLUDES_ALL", "(All)"),
                ("INCLUDES_ONLY", "(Only)"),
            ],
        )
        self.assertIn(
            'data-search-select-modifier-option="INCLUDES_ALL"', html
        )
        self.assertIn(
            'data-search-select-modifier-option="INCLUDES_ONLY"', html
        )
        self.assertIn(
            'data-search-select-modifier-option="NOT_NULL"', html
        )
        # No legacy match-mode <select>.
        self.assertNotIn("data-search-select-match", html)

    def test_active_modifier_renders_pill(self):
        """When modifier is INCLUDES_ALL, the modifier pill renders with the
        (All) label alongside any value pills."""
        html = FilterSelect(
            field_name="games",
            modifier="INCLUDES_ALL",
            modifier_options=[
                ("NOT_NULL", "(Any)"),
                ("IS_NULL", "(None)"),
                ("INCLUDES_ALL", "(All)"),
                ("INCLUDES_ONLY", "(Only)"),
            ],
            included=[{"value": 5, "label": "Hollow Knight", "data": {}}],
        )
        self.assertIn('data-modifier="INCLUDES_ALL"', html)
        self.assertIn("(All)", html)
        self.assertIn("Hollow Knight", html)
        self.assertIn('data-search-select-type="include"', html)

    def test_presence_only_modifiers_no_m2m_rows(self):
        """When modifier_options only has presence entries, no M2M rows appear."""
        html = FilterSelect(
            field_name="status",
            modifier_options=[("NOT_NULL", "(Any)"), ("IS_NULL", "(None)")],
            options=[("f", "Finished")],
        )
        self.assertNotIn("INCLUDES_ALL", html)
        self.assertNotIn("INCLUDES_ONLY", html)


class SearchLabelTest(django.test.TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name="Steam", icon="steam")
        cls.game = Game.objects.create(
            name="Mario", sort_name="Mario", platform=cls.platform, year_released=2020
        )

    def test_format(self):
        self.assertEqual(self.game.search_label, "Mario (Steam, 2020)")

    def test_choice_fields_use_search_label(self):
        from games.forms import MultipleGameChoiceField, SingleGameChoiceField

        multi = MultipleGameChoiceField(queryset=Game.objects.all())
        single = SingleGameChoiceField(queryset=Game.objects.all())
        self.assertEqual(multi.label_from_instance(self.game), self.game.search_label)
        self.assertEqual(single.label_from_instance(self.game), self.game.search_label)

    def test_api_uses_search_label(self):
        from games.api import search_games

        results = search_games(None, q="Mario")
        self.assertEqual(results[0]["label"], self.game.search_label)


class GameResolverTest(django.test.TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name="Steam", icon="steam")
        cls.g1 = Game.objects.create(name="A", sort_name="A", platform=cls.platform)
        cls.g2 = Game.objects.create(name="B", sort_name="B", platform=cls.platform)

    def test_resolver_one_query(self):
        from games.forms import _game_options

        with self.assertNumQueries(1):
            options = list(_game_options([self.g1.id, self.g2.id]))
        self.assertEqual(len(options), 2)
        self.assertEqual({o["value"] for o in options}, {self.g1.id, self.g2.id})

    def test_searchselect_selected_wraps_resolver(self):
        from games.forms import _game_options

        options = searchselect_selected([self.g1.id], _game_options)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["value"], self.g1.id)
        self.assertEqual(options[0]["data"]["platform"], self.platform.id)

    def test_searchselect_selected_empty(self):
        self.assertEqual(searchselect_selected([], lambda v: []), [])


class SearchGamesApiTest(django.test.TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name="Steam", icon="steam")
        for name in ["Mario", "Zelda", "Metroid"]:
            Game.objects.create(name=name, sort_name=name, platform=cls.platform)

    def test_filters_by_q(self):
        from games.api import search_games

        results = search_games(None, q="mar")
        self.assertEqual([r["label"].split(" (")[0] for r in results], ["Mario"])

    def test_respects_limit(self):
        from games.api import search_games

        results = search_games(None, q="", limit=2)
        self.assertEqual(len(results), 2)

    def test_data_carries_platform(self):
        from games.api import search_games

        results = search_games(None, q="Zelda")
        self.assertEqual(results[0]["data"]["platform"], self.platform.id)


if __name__ == "__main__":
    unittest.main()
