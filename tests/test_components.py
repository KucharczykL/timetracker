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


if __name__ == "__main__":
    unittest.main()
