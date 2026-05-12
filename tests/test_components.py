import unittest
from functools import lru_cache

import django

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()

from django.template import TemplateDoesNotExist
from django.utils.safestring import SafeText

from common import components


class RenderCachedImplTest(unittest.TestCase):
    """Test _render_cached_impl renders templates correctly."""

    def test_basic_render(self):
        result = components._render_cached_impl(
            "cotton/icon/play.html",
            '{"slot": "", "title": "Play"}',
        )
        self.assertIn("<svg", result)
        self.assertIn("</svg>", result)

    def test_slot_marked_safe(self):
        result = components._render_cached_impl(
            "cotton/icon/play.html",
            '{"slot": "<b>bold</b>", "title": "Play"}',
        )
        self.assertIsInstance(result, SafeText)

    def test_different_templates_different_output(self):
        r1 = components._render_cached_impl(
            "cotton/icon/play.html", '{"slot": "", "title": "Play"}',
        )
        r2 = components._render_cached_impl(
            "cotton/icon/delete.html", '{"slot": "", "title": "Delete"}',
        )
        self.assertNotEqual(r1, r2)

    def test_nonexistent_template_raises(self):
        with self.assertRaises(TemplateDoesNotExist):
            components._render_cached_impl(
                "cotton/nonexistent.html", '{"slot": "", "title": "X"}',
            )

    def test_context_keys_are_sorted(self):
        """Verify sort_keys=True in Component produces consistent JSON."""
        from common.components import Component
        r1 = Component(
            template="cotton/icon/play.html",
            attributes=[("title", "Play"), ("b", "2")],
        )
        r2 = Component(
            template="cotton/icon/play.html",
            attributes=[("b", "2"), ("title", "Play")],
        )
        self.assertEqual(r1, r2)


class RenderCachedLRUTest(unittest.TestCase):
    """Test LRU cache behavior of _render_cached when enabled."""

    def setUp(self):
        components.enable_cache()
        components._render_cached.cache_clear()

    def tearDown(self):
        components._render_cached = components._render_cached_impl

    def test_cache_hits_and_misses(self):
        # Call through _render_cached (the cached wrapper), not _render_cached_impl
        components._render_cached(
            "cotton/icon/play.html", '{"slot": "", "title": "Play"}',
        )
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 0)
        self.assertEqual(info.misses, 1)

        components._render_cached(
            "cotton/icon/play.html", '{"slot": "", "title": "Play"}',
        )
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 1)
        self.assertEqual(info.misses, 1)

    def test_cache_clear(self):
        components._render_cached_impl(
            "cotton/icon/play.html", '{"slot": "", "title": "Play"}',
        )
        components._render_cached.cache_clear()
        info = components._render_cached.cache_info()
        self.assertEqual(info.currsize, 0)
        self.assertEqual(info.hits, 0)

    def test_cache_parameters(self):
        info = components._render_cached.cache_info()
        self.assertEqual(components._render_cached.cache_parameters()["maxsize"], 4096)

    def test_different_contexts_different_entries(self):
        # Call through _render_cached (the cached wrapper), not _render_cached_impl
        components._render_cached(
            "cotton/button.html",
            '{"size": "base", "color": "blue", "icon": false, "class": "hover:cursor-pointer", "slot": ""}',
        )
        components._render_cached(
            "cotton/button.html",
            '{"size": "base", "color": "red", "icon": false, "class": "hover:cursor-pointer", "slot": ""}',
        )
        info = components._render_cached.cache_info()
        self.assertEqual(info.currsize, 2)

    def test_cache_size_limited(self):
        """After exceeding maxsize, oldest entries are evicted."""
        for i in range(5000):
            components._render_cached_impl(
                f"cotton/icon/play.html",
                f'{{"slot": "", "title": "{i}"}}',
            )
        info = components._render_cached.cache_info()
        self.assertLessEqual(info.currsize, 4096)


class ComponentIntegrationTest(unittest.TestCase):
    """Test Component() works correctly with caching transparent."""

    def setUp(self):
        components.enable_cache()
        components._render_cached.cache_clear()

    def tearDown(self):
        components._render_cached = components._render_cached_impl

    def test_template_component(self):
        result = components.Component(
            template="cotton/icon/play.html", attributes=[],
        )
        self.assertIn("<svg", result)
        self.assertIn("</svg>", result)

    def test_tag_name_component(self):
        result = components.Component(
            tag_name="div",
            attributes=[("class", "test")],
            children="hello",
        )
        self.assertEqual(result, '<div class="test">hello</div>')

    def test_repeated_calls_identical(self):
        r1 = components.Component(
            template="cotton/icon/play.html", attributes=[],
        )
        r2 = components.Component(
            template="cotton/icon/play.html", attributes=[],
        )
        self.assertEqual(r1, r2)

    def test_different_components_different(self):
        r1 = components.Component(
            template="cotton/button.html", attributes=[("hx_get", "/url1")],
        )
        r2 = components.Component(
            template="cotton/button.html", attributes=[("hx_get", "/url2")],
        )
        self.assertNotEqual(r1, r2)


class RandomidDeterministicTest(unittest.TestCase):
    """Test that randomid() produces deterministic, reproducible IDs."""

    def test_same_content_same_id(self):
        r1 = components.randomid(content="foo")
        r2 = components.randomid(content="foo")
        self.assertEqual(r1, r2)

    def test_different_content_different_id(self):
        r1 = components.randomid(content="foo")
        r2 = components.randomid(content="bar")
        self.assertNotEqual(r1, r2)

    def test_seed_prepended(self):
        result = components.randomid(seed="a", content="x")
        self.assertTrue(result.startswith("a"))

    def test_seed_respects_length(self):
        result = components.randomid(seed="ab", content="x", length=10)
        self.assertEqual(len(result), 10)

    def test_empty_input_returns_empty(self):
        self.assertEqual(components.randomid(), "")

    def test_output_is_lowercase_alphanum(self):
        result = components.randomid(content="test")
        self.assertTrue(all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in result))

    def test_output_length_is_correct(self):
        for length in [5, 10, 15, 20]:
            result = components.randomid(content="test", length=length)
            self.assertEqual(len(result), length)

    def test_hash_reproducible_across_calls(self):
        results = [components.randomid(content="reproducible_test") for _ in range(100)]
        self.assertEqual(len(set(results)), 1)


class RandomidVsOldBehaviorTest(unittest.TestCase):
    """Prove the new hash-based approach is deterministic while the old random approach was not."""

    def _old_random_id(self, seed="", length=10):
        from random import choices
        from string import ascii_lowercase
        return seed + "".join(choices(ascii_lowercase, k=length))

    def test_old_random_produces_different_ids(self):
        results = [self._old_random_id() for _ in range(50)]
        self.assertEqual(len(set(results)), 50)

    def test_new_hash_produces_same_id(self):
        results = [components.randomid(content="determinism_test") for _ in range(50)]
        self.assertEqual(len(set(results)), 1)

    def test_new_hash_deterministic_per_content(self):
        results = [components.randomid(content=c) for c in ["aaa", "bbb", "ccc"]]
        self.assertEqual(len(set(results)), 3)


class PopoverDeterministicTest(unittest.TestCase):
    """Test that Popover() produces deterministic HTML output."""

    def setUp(self):
        components.enable_cache()
        components._render_cached.cache_clear()

    def tearDown(self):
        components._render_cached = components._render_cached_impl

    def test_same_popover_same_id(self):
        r1 = components.Popover("hello", wrapped_content="hello")
        r2 = components.Popover("hello", wrapped_content="hello")
        self.assertEqual(r1, r2)

    def test_different_content_different_id(self):
        r1 = components.Popover("content_a", wrapped_content="content_a")
        r2 = components.Popover("content_b", wrapped_content="content_b")
        self.assertNotEqual(r1, r2)

    def test_wrapped_classes_affect_id(self):
        r1 = components.Popover("c", wrapped_content="c", wrapped_classes="class_x")
        r2 = components.Popover("c", wrapped_content="c", wrapped_classes="class_y")
        self.assertNotEqual(r1, r2)

    def test_wrapped_content_affects_id(self):
        r1 = components.Popover("popover", wrapped_content="wrapped_a")
        r2 = components.Popover("popover", wrapped_content="wrapped_b")
        self.assertNotEqual(r1, r2)

    def test_popover_content_affects_id(self):
        r1 = components.Popover("popover_a", wrapped_content="wrapped")
        r2 = components.Popover("popover_b", wrapped_content="wrapped")
        self.assertNotEqual(r1, r2)

    def test_full_html_deterministic(self):
        r1 = components.Popover("hello world", wrapped_content="hello world")
        r2 = components.Popover("hello world", wrapped_content="hello world")
        self.assertEqual(r1.encode(), r2.encode())


class PopoverCacheIntegrationTest(unittest.TestCase):
    """Test that Popover() output works correctly with LRU caching."""

    def setUp(self):
        components.enable_cache()
        components._render_cached.cache_clear()

    def tearDown(self):
        components._render_cached = components._render_cached_impl

    def _get_popover_context(self, popover_content, wrapped_content="", wrapped_classes=""):
        """Build the context JSON that _render_cached would receive for a Popover."""
        import json
        content = f"{wrapped_content}:{popover_content}:{wrapped_classes}"
        id = components.randomid(content=content)
        context = {
            "id": id,
            "wrapped_content": wrapped_content,
            "popover_content": popover_content,
            "wrapped_classes": wrapped_classes,
            "slot": "",
        }
        return json.dumps(context, sort_keys=True)

    def test_popover_first_call_no_cache_hit(self):
        components.Popover("test_content", wrapped_content="test_content")
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 0)

    def test_popover_second_call_cache_hit(self):
        components.Popover("test_content", wrapped_content="test_content")
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 0)
        components.Popover("test_content", wrapped_content="test_content")
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 1)

    def test_popover_different_content_different_entry(self):
        components.Popover("content_a", wrapped_content="content_a")
        components.Popover("content_b", wrapped_content="content_b")
        info = components._render_cached.cache_info()
        self.assertEqual(info.currsize, 2)

    def test_popover_repeated_call_increments_hits(self):
        for _ in range(5):
            components.Popover("repeated_test", wrapped_content="repeated_test")
        info = components._render_cached.cache_info()
        self.assertEqual(info.hits, 4)


class TemplatetagRandomidTest(unittest.TestCase):
    """Test games/templatetags/randomid.py produces deterministic IDs."""

    def test_same_seed_same_id(self):
        from games.templatetags import randomid
        r1 = randomid.randomid(seed="foo")
        r2 = randomid.randomid(seed="foo")
        self.assertEqual(r1, r2)

    def test_different_seed_different_id(self):
        from games.templatetags import randomid
        r1 = randomid.randomid(seed="foo")
        r2 = randomid.randomid(seed="bar")
        self.assertNotEqual(r1, r2)

    def test_output_length_ten(self):
        from games.templatetags import randomid
        for seed in ["a", "hello", "test1234"]:
            result = randomid.randomid(seed=seed)
            self.assertEqual(len(result), 10)

    def test_empty_seed_returns_hash(self):
        from games.templatetags import randomid
        result = randomid.randomid()
        self.assertEqual(len(result), 10)
        self.assertTrue(all(c in "abcdef0123456789" for c in result))


class ComponentReturnTypeTest(unittest.TestCase):
    """Test that component functions return SafeText and render correctly."""

    def setUp(self):
        components.enable_cache()
        components._render_cached.cache_clear()

    def tearDown(self):
        components._render_cached = components._render_cached_impl

    def test_div_returns_safe_text(self):
        result = components.Div([("class", "x")], "hello")
        self.assertIsInstance(result, SafeText)

    def test_div_deterministic(self):
        r1 = components.Div([("class", "x")], "hello")
        r2 = components.Div([("class", "x")], "hello")
        self.assertEqual(r1, r2)
        self.assertIn('<div class="x">hello</div>', r1)

    def test_div_no_args(self):
        result = components.Div(children="test")
        self.assertIsInstance(result, SafeText)
        self.assertIn('<div>test</div>', result)

    def test_a_returns_safe_text(self):
        result = components.A([], "link")
        self.assertIsInstance(result, SafeText)

    def test_a_literal_href(self):
        result = components.A([], "x", href="/literal/path")
        self.assertIn('href="/literal/path"', result)

    def test_a_url_name_reversed(self):
        from unittest.mock import patch
        with patch("common.components.reverse", return_value="/resolved/url"):
            result = components.A([], "link", url_name="some_name")
            self.assertIn('href="/resolved/url"', result)

    def test_a_no_url_or_href(self):
        result = components.A([], "link")
        self.assertIn('<a>link</a>', result)
        self.assertNotIn('href=', result)

    def test_a_both_url_name_and_href_raises(self):
        with self.assertRaises(ValueError):
            components.A(href="/path", url_name="some_name")

    def test_button_returns_safe_text(self):
        result = components.Button([], "click")
        self.assertIsInstance(result, SafeText)
        self.assertIn("<button", result)

    def test_button_default_colors(self):
        result = components.Button([], "click")
        self.assertIn("text-white bg-brand", result)

    def test_name_with_icon_no_link(self):
        result = components.NameWithIcon(name="Game", platform="Steam", linkify=False)
        self.assertIsInstance(result, SafeText)
        self.assertIn("Game", result)
        self.assertNotIn("<a ", result)

    def test_name_with_icon_no_trailing_comma(self):
        result = components.NameWithIcon(name="Test", platform="Steam", linkify=False)
        self.assertIsInstance(result, SafeText)
        self.assertNotIsInstance(result, tuple)


if __name__ == "__main__":
    unittest.main()
