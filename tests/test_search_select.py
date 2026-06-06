"""Tests for the SearchSelect component, the Pill primitive, the games resolver,
the search API endpoint, and the shared Game.search_label."""

import unittest

import django.test
from django.utils.safestring import SafeText

from common.components import (
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
        self.assertIn("data-ss-no-results", html)
        self.assertIn("No results", html)

    def test_outer_container_carries_config(self):
        html = SearchSelect(
            name="games", search_url="/api/games/search", multi_select=True
        )
        self.assertIn("data-search-select", html)
        self.assertIn('data-name="games"', html)
        self.assertIn('data-search-url="/api/games/search"', html)
        self.assertIn('data-multi="true"', html)

    def test_selected_renders_pills_and_hidden_inputs(self):
        html = SearchSelect(
            name="games",
            selected=[{"value": 7, "label": "Game A", "data": {"platform": "2"}}],
        )
        self.assertIn("data-pill", html)
        self.assertIn('<input type="hidden" name="games" value="7">', html)
        self.assertIn('data-platform="2"', html)
        # exactly one submitted value (the hidden input) — the search box has no
        # name. The leading space avoids matching the container's data-name.
        self.assertEqual(html.count(' name="games"'), 1)

    def test_search_box_has_no_name(self):
        html = SearchSelect(name="games")
        self.assertIn("data-ss-search", html)
        # container exposes data-name, never a submittable name on the search box
        self.assertEqual(html.count(' name="games"'), 0)

    def test_tuple_options_are_normalized(self):
        html = SearchSelect(name="t", options=[("1", "One")])
        self.assertIn('data-ss-option=""', html)
        self.assertIn('data-value="1"', html)
        self.assertIn("One", html)

    def test_options_omitted_when_search_url_set(self):
        html = SearchSelect(
            name="t", options=[("1", "One")], search_url="/api/games/search"
        )
        self.assertNotIn('data-ss-option=""', html)


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
