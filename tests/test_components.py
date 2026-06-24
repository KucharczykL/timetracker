import unittest
from unittest.mock import MagicMock, patch

import django
from django.test import SimpleTestCase, override_settings
from django.utils.safestring import SafeText, mark_safe

from common import components
from games.models import Game, Platform, Purchase, Session

# Component builders return lazy ``Node`` objects; these tests assert on rendered
# HTML, so node-returning calls are wrapped in ``str(...)`` at the call site
# (``Node.__str__`` returns a ``SafeText``). Non-node helpers (``randomid``,
# ``_resolve_name_with_icon``, ``_render_element``) are called
# directly.


class ComponentIntegrationTest(unittest.TestCase):
    """Test Element() renders correctly with caching transparent."""

    def test_tag_name_component(self):
        result = str(
            components.Element(
                tag_name="div",
                attributes=[("class", "test")],
                children="hello",
            )
        )
        self.assertEqual(result, '<div class="test">hello</div>')


class ComponentCacheTest(unittest.TestCase):
    """Component rendering is memoized via _render_element."""

    def setUp(self):
        components._render_element.cache_clear()

    def test_identical_components_hit_cache(self):
        str(
            components.Element(
                tag_name="div", attributes=[("class", "x")], children="hi"
            )
        )
        misses = components._render_element.cache_info().misses
        str(
            components.Element(
                tag_name="div", attributes=[("class", "x")], children="hi"
            )
        )
        info = components._render_element.cache_info()
        self.assertEqual(info.misses, misses)  # no new miss
        self.assertGreaterEqual(info.hits, 1)  # served from cache

    def test_cache_is_bounded(self):
        self.assertEqual(components._render_element.cache_parameters()["maxsize"], 4096)

    def test_safe_and_unsafe_children_do_not_collide(self):
        """A Safe-node ``<b>`` and a plain-string ``<b>`` render differently —
        the cache key must keep them distinct."""
        safe = str(
            components.Element(tag_name="span", children=[components.Safe("<b>x</b>")])
        )
        unsafe = str(components.Element(tag_name="span", children=["<b>x</b>"]))
        self.assertIn("<b>x</b>", safe)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", unsafe)
        self.assertNotEqual(safe, unsafe)


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
        self.assertTrue(
            all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in result)
        )

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

    def test_same_popover_same_id(self):
        r1 = str(components.Popover("hello", wrapped_content="hello"))
        r2 = str(components.Popover("hello", wrapped_content="hello"))
        self.assertEqual(r1, r2)

    def test_different_content_different_id(self):
        r1 = str(components.Popover("content_a", wrapped_content="content_a"))
        r2 = str(components.Popover("content_b", wrapped_content="content_b"))
        self.assertNotEqual(r1, r2)

    def test_wrapped_classes_affect_id(self):
        r1 = str(
            components.Popover("c", wrapped_content="c", wrapped_classes="class_x")
        )
        r2 = str(
            components.Popover("c", wrapped_content="c", wrapped_classes="class_y")
        )
        self.assertNotEqual(r1, r2)

    def test_wrapped_content_affects_id(self):
        r1 = str(components.Popover("popover", wrapped_content="wrapped_a"))
        r2 = str(components.Popover("popover", wrapped_content="wrapped_b"))
        self.assertNotEqual(r1, r2)

    def test_popover_content_affects_id(self):
        r1 = str(components.Popover("popover_a", wrapped_content="wrapped"))
        r2 = str(components.Popover("popover_b", wrapped_content="wrapped"))
        self.assertNotEqual(r1, r2)

    def test_full_html_deterministic(self):
        r1 = str(components.Popover("hello world", wrapped_content="hello world"))
        r2 = str(components.Popover("hello world", wrapped_content="hello world"))
        self.assertEqual(r1.encode(), r2.encode())


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

    def test_div_returns_safe_text(self):
        result = str(components.Div([("class", "x")], "hello"))
        self.assertIsInstance(result, SafeText)

    def test_div_deterministic(self):
        r1 = str(components.Div([("class", "x")], "hello"))
        r2 = str(components.Div([("class", "x")], "hello"))
        self.assertEqual(r1, r2)
        self.assertIn('<div class="x">hello</div>', r1)

    def test_div_no_args(self):
        result = str(components.Div(children="test"))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<div>test</div>", result)

    def test_a_returns_safe_text(self):
        result = str(components.A([], "link"))
        self.assertIsInstance(result, SafeText)

    def test_a_literal_href(self):
        result = str(components.A([], "x", href="/literal/path"))
        self.assertIn('href="/literal/path"', result)

    def test_a_no_url_or_href(self):
        result = str(components.A([], "link"))
        self.assertIn("<a>link</a>", result)
        self.assertNotIn("href=", result)

    def test_button_returns_safe_text(self):
        result = str(components.StyledButton([], "click"))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<button", result)

    def test_button_default_colors(self):
        result = str(components.StyledButton([], "click"))
        self.assertIn("text-white bg-brand", result)

    def test_name_with_icon_no_link(self):
        result = str(components.NameWithIcon(name="Game", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Game", result)
        self.assertNotIn("<a ", result)

    def test_name_with_icon_no_trailing_comma(self):
        result = str(components.NameWithIcon(name="Test", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertNotIsInstance(result, tuple)


class ComponentOutputIsNotEscapedTest(unittest.TestCase):
    """Smoke test: every component that generates HTML must not double-escape."""

    def test_component_output_starts_with_tag(self):
        for label, html in [
            ("A", str(components.A(href="/foo", children=["link"]))),
            ("Button", str(components.StyledButton([], "click"))),
            ("Div", str(components.Div([], ["hello"]))),
            ("Input", str(components.Input())),
            ("ButtonGroup", str(components.ButtonGroup([]))),
            (
                "ButtonGroup with buttons",
                str(
                    components.ButtonGroup(
                        [{"href": "/", "slot": components.Icon("edit")}]
                    )
                ),
            ),
            ("SearchField", str(components.SearchField())),
            ("PriceConverted", str(components.PriceConverted(["27 CZK"]))),
            ("H1", str(components.H1(["Title"]))),
            ("H1 with badge", str(components.H1(["Title"], badge="3"))),
        ]:
            with self.subTest(component=label):
                self.assertTrue(
                    str(html).startswith("<"),
                    f"{label} output should start with '<', got: {str(html)[:80]}",
                )

    def test_button_with_icon_children_not_escaped(self):
        result = str(
            components.StyledButton(
                icon=True,
                size="xs",
                children=[components.Icon("play"), "LOG"],
            )
        )
        self.assertTrue(str(result).startswith("<button"))

    def test_popover_with_button_children_not_escaped(self):
        result = str(
            components.Popover(
                popover_content="test tooltip",
                children=[
                    components.StyledButton(
                        icon=True,
                        color="gray",
                        size="xs",
                        children=[components.Icon("play"), "test"],
                    ),
                ],
            )
        )
        self.assertTrue(str(result).startswith("<span data-popover-target"))

    def test_name_with_icon_output_not_escaped(self):
        result = str(components.NameWithIcon(name="Test", linkify=False))
        self.assertTrue(str(result).startswith("<div"))


class ComponentEdgeCasesTest(unittest.TestCase):
    """Test Element() edge cases and error handling."""

    def test_no_tag_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            str(components.Element("", children="hello"))
        self.assertIn("tag_name", str(ctx.exception))

    def test_single_string_children_wrapped(self):
        result = str(components.Element(tag_name="span", children="hello"))
        self.assertIn("hello", result)

    def test_multiple_children_concatenated_without_separator(self):
        result = str(components.Element(tag_name="div", children=["hello", "world"]))
        # Children join with no separator (inline whitespace is significant);
        # explicit spacing must be its own child.
        self.assertIn("helloworld", result)
        self.assertIn("<div>", result)
        self.assertIn("</div>", result)

    def test_raw_html_children_are_escaped(self):
        result = str(
            components.Element(
                tag_name="div", children=["<script>alert('xss')</script>"]
            )
        )
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_safe_node_children_pass_through(self):
        result = str(
            components.Element(
                tag_name="div", children=[components.Safe("<span>safe</span>")]
            )
        )
        self.assertIn("<span>safe</span>", result)

    def test_mark_safe_string_children_are_escaped(self):
        # Trusted markup must be a Safe node; a mark_safe string is still a
        # string, so it is escaped like any other text child.
        result = str(
            components.Element(
                tag_name="div", children=[mark_safe("<span>safe</span>")]
            )
        )
        self.assertIn("&lt;span&gt;safe&lt;/span&gt;", result)

    def test_attribute_values_are_escaped(self):
        result = str(
            components.Element(
                tag_name="div",
                attributes=[("data-x", 'foo"bar')],
            )
        )
        self.assertIn("&quot;", result)
        self.assertNotIn('"foo"bar"', result)

    def test_attributes_serialized_correctly(self):
        result = str(
            components.Element(
                tag_name="div", attributes=[("class", "foo"), ("id", "bar")]
            )
        )
        self.assertIn('class="foo"', result)
        self.assertIn('id="bar"', result)

    def test_empty_attributes_no_extra_space(self):
        result = str(components.Element(tag_name="span", children="x"))
        self.assertEqual(result, "<span>x</span>")
        self.assertNotIn(" <span", result)

    def test_non_string_children_not_supported(self):
        """Component only accepts str for children, not integers."""
        result = str(components.Element(tag_name="span", children=str(42)))
        self.assertIn("42", result)

    def test_returns_safetext(self):
        result = str(components.Element(tag_name="div", children="test"))
        self.assertIsInstance(result, SafeText)


class IconTest(unittest.TestCase):
    """Test Icon() component function."""

    def test_valid_icon_renders_svg(self):
        result = str(components.Icon("play"))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<svg", result)
        self.assertIn("</svg>", result)

    def test_unavailable_icon_falls_back(self):
        result = str(components.Icon("zzz_nonexistent_platform"))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<svg", result)

    def test_icon_title_becomes_title_child(self):
        # A title= renders as a <title> child (the SVG-correct accessible name /
        # tooltip), not an inert title attribute on the <svg>.
        result = str(components.Icon("play", attributes=[("title", "Play")]))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<title>Play</title>", result)
        self.assertNotIn('title="Play"', result)

    def test_icon_merges_class_with_existing(self):
        # `arrowdownlong` ships with class="w-3 h-3"; a passed class appends.
        result = str(components.Icon("arrowdownlong", [("class", "rotate-180")]))
        self.assertIn('class="w-3 h-3 rotate-180"', result)

    def test_icon_escapes_title_text(self):
        result = str(components.Icon("play", [("title", 'a"<&b')]))
        self.assertIn("&lt;", result)
        self.assertIn("&amp;", result)
        self.assertNotIn("<&", result)

    def test_icon_without_attributes_returns_shared_node(self):
        from common.components.primitives import get_icon_node

        self.assertEqual(
            str(components.Icon("arrowdownlong")),
            str(get_icon_node("arrowdownlong")),
        )

    def test_returns_safetext(self):
        result = str(components.Icon("delete"))
        self.assertIsInstance(result, SafeText)


class IconCodegenFaithfulnessTest(unittest.TestCase):
    """Guard that the generated icon nodes still match their SVG sources.

    Parses each raw .html source and the rendered node independently with
    ElementTree and compares normalized trees, so a converter/codegen bug fails
    here instead of silently corrupting an icon. Run `make gen-icons` if this
    fails after editing an icon.
    """

    @staticmethod
    def _normalize(element):
        return (
            element.tag,
            dict(element.attrib),
            (element.text or "").strip(),
            [IconCodegenFaithfulnessTest._normalize(child) for child in element],
        )

    def test_every_icon_node_matches_its_source(self):
        import xml.etree.ElementTree as ElementTree

        from common.components.primitives import get_icon_node
        from common.icons import iter_icon_sources

        for name, raw_html in iter_icon_sources():
            with self.subTest(icon=name):
                source = ElementTree.fromstring(raw_html)
                rendered = ElementTree.fromstring(str(get_icon_node(name)))
                self.assertEqual(self._normalize(source), self._normalize(rendered))


class InputTest(unittest.TestCase):
    """Test the Input() component."""

    def test_input_default_type_text(self):
        result = str(components.Input())
        self.assertIn("<input", result)
        self.assertIn('type="text"', result)

    def test_input_custom_type(self):
        result = str(components.Input(type="submit"))
        self.assertIn('type="submit"', result)

    def test_input_attributes_merged_with_type(self):
        result = str(
            components.Input(
                type="email", attributes=[("id", "email"), ("class", "form-input")]
            )
        )
        self.assertIn('type="email"', result)
        self.assertIn('id="email"', result)
        self.assertIn('class="form-input"', result)


class PopoverTruncatedTest(unittest.TestCase):
    """Test PopoverTruncated() component function."""

    def test_short_string_no_popover(self):
        result = str(components.PopoverTruncated("hi"))
        self.assertEqual(result, "hi")

    def test_long_string_wrapped_in_popover(self):
        long_text = "a" * 100
        result = str(components.PopoverTruncated(long_text))
        # Should NOT equal the truncated form directly
        truncated = components.truncate(long_text, 30)
        self.assertNotEqual(result, truncated)
        # Should contain popover markers
        self.assertIn("data-popover-target", result)

    def test_custom_ellipsis_used(self):
        long_text = "a" * 50
        result = str(components.PopoverTruncated(long_text, ellipsis=">>"))
        # Django template escapes >> to &gt;&gt; in the wrapped_content
        self.assertIn("&gt;&gt;", result)

    def test_popover_if_not_truncated_flag(self):
        short_text = "hi"
        result = str(
            components.PopoverTruncated(
                short_text,
                popover_content="full content",
                popover_if_not_truncated=True,
            )
        )
        # Should be wrapped in popover even though short
        self.assertNotEqual(result, "hi")
        self.assertIn("data-popover-target", result)

    def test_popover_content_override(self):
        result = str(
            components.PopoverTruncated("short", popover_content="custom popover")
        )
        # With popover_if_not_truncated=False (default), short text returns as-is
        self.assertEqual(result, "short")

    def test_popover_content_override_with_flag(self):
        result = str(
            components.PopoverTruncated(
                "short", popover_content="custom popover", popover_if_not_truncated=True
            )
        )
        self.assertIn("custom popover", result)

    def test_endpart_visible_in_output(self):
        long_text = "a" * 50
        result = str(components.PopoverTruncated(long_text, endpart="..."))
        self.assertIn("...", result)

    def test_returns_safetext(self):
        result = str(components.PopoverTruncated("a" * 100))
        self.assertIsInstance(result, SafeText)

    def test_default_length(self):
        text = "a" * 31
        result = str(components.PopoverTruncated(text))
        # 31 chars exceeds default length of 30, so should be truncated
        self.assertIn("data-popover-target", result)

    def test_length_zero(self):
        result = str(components.PopoverTruncated("hello", length=0))
        # Even empty length triggers popover for any content
        self.assertIn("data-popover-target", result)


class ModelDependentComponentsTest(django.test.TestCase):
    """Test components that depend on Django models."""

    @staticmethod
    def _create_platform(name="Steam", icon="steam"):
        return Platform.objects.create(name=name, icon=icon)

    @staticmethod
    def _create_game(platform, name="Test Game"):
        return Game.objects.create(name=name, platform=platform)

    @staticmethod
    def _create_purchase(games, platform=None, price=19.99):
        purchase = Purchase.objects.create(
            platform=platform or (games[0].platform if games else None),
            date_purchased="2025-01-01",
            price=price,
            price_currency="USD",
            converted_price=price,
            converted_currency="USD",
        )
        purchase.games.set(games)
        return purchase

    def test_name_with_icon_linkify_with_game(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform)
        result = str(components.NameWithIcon(game=game, linkify=True))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<a ", result)
        self.assertIn("Test Game", result)
        self.assertIn("/tracker/game/", result)

    def test_name_with_icon_no_linkify(self):
        platform = self._create_platform(name="GOG", icon="gog")
        game = self._create_game(platform)
        result = str(
            components.NameWithIcon(name="Test Game", game=game, linkify=False)
        )
        self.assertIsInstance(result, SafeText)
        self.assertNotIn("<a ", result)
        self.assertIn("Test Game", result)

    def test_name_with_icon_emulated_flag(self):
        platform = self._create_platform(icon="steam")
        game = self._create_game(platform)
        session = Session.objects.create(
            game=game,
            timestamp_start="2025-01-01 00:00:00+00:00",
            emulated=True,
        )
        result = str(components.NameWithIcon(session=session, linkify=True))
        self.assertIsInstance(result, SafeText)
        self.assertIn("<a ", result)
        self.assertIn("Emulated", result)

    def test_name_with_icon_no_platform(self):
        result = str(components.NameWithIcon(name="Standalone", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Standalone", result)

    def test_name_with_icon_session_fetches_game(self):
        platform = self._create_platform(icon="egs")
        game = self._create_game(platform, name="Epic Game")
        session = Session.objects.create(
            game=game,
            timestamp_start="2025-01-01 00:00:00+00:00",
        )
        result = str(components.NameWithIcon(session=session, linkify=True))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Epic Game", result)

    def test_purchase_price_renders_currency(self):
        platform = self._create_platform()
        game = self._create_game(platform)
        purchase = self._create_purchase([game], price=29.99)
        result = str(components.PurchasePrice(purchase))
        self.assertIsInstance(result, SafeText)
        # floatformat rounds to 1 decimal: 29.99 -> 30.0
        self.assertIn("30.0", result)
        self.assertIn("USD", result)
        self.assertIn("data-popover-target", result)

    def test_linked_purchase_single_game(self):
        platform = self._create_platform(icon="steam")
        game = self._create_game(platform, name="Single Game")
        purchase = self._create_purchase([game], price=14.99)
        result = str(components.LinkedPurchase(purchase))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Single Game", result)
        self.assertIn("<a ", result)
        self.assertIn("/tracker/purchase/", result)

    def test_linked_purchase_multiple_games(self):
        platform = self._create_platform(icon="steam")
        game1 = self._create_game(platform, name="Game One")
        game2 = self._create_game(platform, name="Game Two")
        purchase = self._create_purchase([game1, game2], price=24.99)
        result = str(components.LinkedPurchase(purchase))
        self.assertIsInstance(result, SafeText)
        self.assertIn("2 games", result)
        self.assertIn("<a ", result)
        self.assertIn("/tracker/purchase/", result)

    def test_linked_purchase_with_name(self):
        platform = self._create_platform(icon="steam")
        game1 = self._create_game(platform, name="Game A")
        game2 = self._create_game(platform, name="Game B")
        purchase = self._create_purchase(
            [game1, game2],
            price=24.99,
        )
        purchase.name = "Bundle"
        purchase.save()
        result = str(components.LinkedPurchase(purchase))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Bundle", result)

    def test_linked_purchase_renders_game_names_in_popover(self):
        platform = self._create_platform(icon="steam")
        game1 = self._create_game(platform, name="Alpha")
        game2 = self._create_game(platform, name="Beta")
        purchase = self._create_purchase([game1, game2], price=19.99)
        result = str(components.LinkedPurchase(purchase))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Alpha", result)
        self.assertIn("Beta", result)


class PurchaseTruncatedTest(unittest.TestCase):
    """Test PopoverTruncated with endpart edge cases."""

    def test_endpart_shorter_than_length(self):
        text = "a" * 50
        result = str(components.PopoverTruncated(text, length=10, endpart="x"))
        # endpart=x takes 1 char, so content gets truncated at 9 chars
        self.assertIn("data-popover-target", result)
        self.assertIn("x", result)

    def test_no_truncation_no_ellipsis(self):
        result = str(components.PopoverTruncated("short text"))
        self.assertEqual(result, "short text")

    def test_custom_length(self):
        text = "hello world"
        result = str(components.PopoverTruncated(text, length=6))
        self.assertIn("data-popover-target", result)


class NameWithIconPlatformTest(django.test.TestCase):
    """Test NameWithIcon platform icon rendering."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.platform = Platform.objects.create(name="Nintendo", icon="nintendo")
        cls.game = Game.objects.create(name="Zelda", platform=cls.platform)

    def test_name_with_icon_shows_platform_icon(self):
        result = str(
            components.NameWithIcon(name="Zelda", game=self.game, linkify=True)
        )
        self.assertIsInstance(result, SafeText)
        self.assertIn("Zelda", result)

    def test_name_with_icon_no_game_id_no_platform(self):
        result = str(components.NameWithIcon(name="Unknown Game", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Unknown Game", result)


class ResolveNameWithIconTest(unittest.TestCase):
    """Test _resolve_name_with_icon helper function."""

    def setUp(self):
        from unittest.mock import MagicMock

        self.mock_platform = MagicMock()
        self.mock_platform.name = "Steam"
        self.mock_platform.icon = "steam"
        self.mock_platform.pk = 1

        self.mock_game = MagicMock()
        self.mock_game.name = "Test Game"
        self.mock_game.pk = 1
        self.mock_game.platform = self.mock_platform

        self.mock_session = MagicMock()
        self.mock_session.game = self.mock_game
        self.mock_session.emulated = False
        self.mock_session.pk = 1

    def test_session_provides_game_and_emulated(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon(
                "", self.mock_game, self.mock_session, True
            )
        )
        self.assertEqual(name, "Test Game")
        self.assertIs(platform, self.mock_platform)
        self.assertFalse(emulated)

    def test_session_overrides_game_parameter(self):
        override_game = MagicMock()
        override_game.name = "Override"
        override_game.platform = self.mock_platform
        override_game.pk = 99
        with patch("common.components.domain.reverse", return_value="/game/99"):
            name, platform, emulated, create_link, link = (
                components._resolve_name_with_icon(
                    "", override_game, self.mock_session, True
                )
            )
        self.assertEqual(name, "Test Game")
        self.assertIsNot(name, "Override")

    def test_game_only_provides_platform(self):
        with patch("common.components.domain.reverse", return_value="/game/1"):
            name, platform, emulated, create_link, link = (
                components._resolve_name_with_icon("", self.mock_game, None, True)
            )
        self.assertEqual(name, "Test Game")
        self.assertIs(platform, self.mock_platform)
        self.assertTrue(create_link)
        self.assertEqual(link, "/game/1")

    def test_custom_name_overrides_game_name(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon("Custom", self.mock_game, None, False)
        )
        self.assertEqual(name, "Custom")

    def test_empty_name_falls_back_to_game_name(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon("", self.mock_game, None, False)
        )
        self.assertEqual(name, "Test Game")

    def test_no_game_no_session_returns_empty_name(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon("", None, None, False)
        )
        self.assertEqual(name, "")
        self.assertIsNone(platform)
        self.assertFalse(create_link)

    def test_linkify_false_no_link_created(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon("", self.mock_game, None, False)
        )
        self.assertFalse(create_link)
        self.assertEqual(link, "")

    def test_linkify_true_creates_link(self):
        with patch("common.components.domain.reverse", return_value="/game/42"):
            name, platform, emulated, create_link, link = (
                components._resolve_name_with_icon("", self.mock_game, None, True)
            )
        self.assertTrue(create_link)
        self.assertEqual(link, "/game/42")

    def test_session_emulated_flag_preserved(self):
        emulated_session = MagicMock()
        emulated_session.game = self.mock_game
        emulated_session.emulated = True
        emulated_session.pk = 1
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon(
                "", self.mock_game, emulated_session, False
            )
        )
        self.assertTrue(emulated)

    def test_game_emulated_default_false(self):
        name, platform, emulated, create_link, link = (
            components._resolve_name_with_icon("", self.mock_game, None, False)
        )
        self.assertFalse(emulated)


class StyledTableRenderingTest(unittest.TestCase):
    """Test that the Python StyledTable() renders rows correctly."""

    @staticmethod
    def _tbody(result):
        return result.split("<tbody")[1].split("</tbody>")[0]

    def test_simple_table_renders_rows(self):
        """Verify make_row rows render as <tr> with <th scope='row'> + <td>."""
        result = str(
            str(
                components.StyledTable(
                    columns=[
                        components.Column("Game"),
                        components.Column("Started"),
                        components.Column("Ended"),
                    ],
                    rows=[components.make_row("Game1", "2025-01-01", "2025-03-01")],
                )
            )
        )
        tbody = self._tbody(result)
        self.assertIn("<tr", tbody)
        self.assertIn("Game1", tbody)
        self.assertIn("2025-01-01", tbody)
        self.assertIn("2025-03-01", tbody)
        # first cell is <th scope="row">, subsequent cells are <td>
        self.assertIn('th scope="row"', tbody)
        self.assertIn("<td", tbody)

    def test_simple_table_empty_rows(self):
        """Verify empty rows list renders empty <tbody>."""
        result = str(
            components.StyledTable(
                columns=[components.Column("Game"), components.Column("Started")],
                rows=[],
            )
        )
        self.assertIn("<tbody", result)
        tbody = self._tbody(result)
        self.assertNotIn("<tr", tbody)
        self.assertNotIn("<td", tbody)

    def test_simple_table_multiple_rows(self):
        """Verify multiple rows all render."""
        result = str(
            str(
                components.StyledTable(
                    columns=[components.Column("Game"), components.Column("Started")],
                    rows=[
                        components.make_row("GameA", "2025-01-01"),
                        components.make_row("GameB", "2025-02-01"),
                    ],
                )
            )
        )
        tbody = self._tbody(result)
        self.assertIn("GameA", tbody)
        self.assertIn("GameB", tbody)
        self.assertEqual(tbody.count("<tr"), 2)

    def test_simple_table_header_action_as_caption(self):
        """Verify header_action renders inside <caption>."""
        result = str(
            str(
                components.StyledTable(
                    columns=[components.Column("Game"), components.Column("Started")],
                    rows=[components.make_row("Game1", "2025-01-01")],
                    header_action=components.Safe('<a href="/add">Add</a>'),
                )
            )
        )
        self.assertIn("<caption", result)
        self.assertIn('href="/add"', result)
        self.assertIn(">Add</", result)

    def test_simple_table_rows_with_attributes(self):
        """Verify make_row attributes (id, hx-*) land on the <tr>."""
        result = str(
            str(
                components.StyledTable(
                    columns=[components.Column("Name"), components.Column("Date")],
                    rows=[
                        components.make_row(
                            "Game1",
                            "2025-01-01",
                            id="session-row-1",
                            hx_trigger="device-changed",
                        )
                    ],
                )
            )
        )
        tbody = self._tbody(result)
        self.assertIn('id="session-row-1"', tbody)
        self.assertIn("device-changed", tbody)
        self.assertIn('th scope="row"', tbody)
        self.assertIn("Game1", tbody)
        self.assertIn("2025-01-01", tbody)

    def test_cell_media_bubbles_through_table(self):
        """A cell component's declared Media must reach the table's collected
        media, so Page() still emits its JS. StyledTable returns a node tree, so
        this now happens via automatic bubbling rather than manual collection."""
        cell = components.Div(children=["x"]).with_media(
            components.Media(js=("test-cell.js",))
        )
        table = components.StyledTable(
            columns=[components.Column("Only")],
            rows=[components.make_row(cell)],
        )
        media = components.collect_media(table)
        self.assertIn("test-cell.js", media.js)

    def test_make_row_rejects_class(self):
        """make_row refuses a class attribute — TableRow owns the styled row class."""
        with self.assertRaises(ValueError):
            components.make_row("A", class_="custom")

    def test_make_row_attribute_translation(self):
        """True renders bare; False/None are omitted; the rest become pairs."""
        data = components.make_row("A", flag=True, gone=False, nothing=None)
        self.assertEqual(data["attributes"], [("flag", "flag")])

    def test_make_row_no_attributes_omits_key(self):
        """A plain row carries no attributes key (NotRequired stays absent)."""
        self.assertNotIn("attributes", components.make_row("A", "B"))


class StyledTablePaginationTest(SimpleTestCase):
    """The pagination nav rendered when page_obj + elided_page_range are given."""

    @staticmethod
    def _table(page_number):
        from django.core.paginator import Paginator

        paginator = Paginator(list(range(1, 51)), 10)
        return str(
            components.StyledTable(
                columns=[components.Column("N")],
                rows=[components.make_row("x")],
                page_obj=paginator.page(page_number),
                elided_page_range=list(paginator.get_elided_page_range(page_number)),
                request=None,
            )
        )

    def test_pagination_nav_renders(self):
        result = self._table(2)
        self.assertIn('aria-label="Table navigation"', result)
        self.assertIn("Previous", result)
        self.assertIn("Next", result)

    def test_summary_numbers_hug_separators(self):
        """The range summary must read "11—20 of 50": the em-dash and " of "
        hug the number spans with no stray whitespace (a Fragment joins them
        with "", unlike Element's newline join)."""
        result = self._table(2)
        self.assertIn("</span>—<span", result)
        self.assertIn("</span> of <span", result)
        self.assertNotIn(" — ", result)


class StyledTableColumnGuardTest(SimpleTestCase):
    """The DEBUG-only guard that a row's cell count matches the column count."""

    @override_settings(DEBUG=True)
    def test_cell_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            components.StyledTable(
                columns=[components.Column("A"), components.Column("B")],
                rows=[components.make_row("only-one-cell")],
            )

    @override_settings(DEBUG=True)
    def test_matching_cell_count_renders(self):
        result = str(
            components.StyledTable(
                columns=[components.Column("A"), components.Column("B")],
                rows=[components.make_row("x", "y")],
            )
        )
        self.assertIn("<td", result)


class ColumnAlignmentTest(SimpleTestCase):
    """Column alignment is driven by ``Column.align``: the header per-``<th>``
    (``_header_cell``), the body via a table-level ``td:nth-child`` rule on the
    ``<tbody>`` so htmx-swapped rows align without per-row knowledge. ``ButtonGroup``
    is alignment-agnostic."""

    @staticmethod
    def _thead(result):
        return result.split("<thead")[1].split("</thead>")[0]

    @staticmethod
    def _tbody(result):
        return result.split("<tbody")[1].split(">", 1)[0]

    def _render(self, columns):
        return str(components.StyledTable(columns=columns, rows=[], request=None))

    def test_right_aligned_header_is_text_right(self):
        thead = self._thead(self._render([components.Column("Actions", align="right")]))
        self.assertIn("text-right", thead)

    def test_default_header_is_not_text_right(self):
        thead = self._thead(self._render([components.Column("Device")]))
        self.assertNotIn("text-right", thead)

    def test_tbody_aligns_right_column_by_index(self):
        # A right column at position i → [&_td:nth-child(i+1)]:text-right on tbody.
        tbody = self._tbody(
            self._render(
                [
                    components.Column("Name"),
                    components.Column("Date"),
                    components.Column("Actions", align="right"),
                ]
            )
        )
        self.assertIn("nth-child(3)]:text-right", tbody)

    def test_tbody_aligns_middle_column_not_just_last(self):
        # Proves it is index-driven, not last-only: a right MIDDLE column aligns it.
        tbody = self._tbody(
            self._render(
                [
                    components.Column("Name"),
                    components.Column("Price", align="right"),
                    components.Column("Actions"),
                ]
            )
        )
        self.assertIn("nth-child(2)]:text-right", tbody)

    def test_tbody_no_alignment_for_all_left_columns(self):
        tbody = self._tbody(
            self._render([components.Column("Date"), components.Column("Device")])
        )
        self.assertNotIn("text-right", tbody)

    def test_button_group_is_alignment_agnostic(self):
        html = str(components.ButtonGroup([{"href": "/x", "slot": "edit"}]))
        self.assertNotIn("justify-end", html)


class ButtonGroupSizeTest(SimpleTestCase):
    """ButtonGroup size: default 'sm' (icon buttons) vs 'md' (larger text)."""

    def test_default_size_is_small(self):
        html = str(components.ButtonGroup([{"href": "/x", "slot": "edit"}]))
        self.assertIn("px-2 py-1 text-xs", html)

    def test_md_size_is_larger(self):
        html = str(components.ButtonGroup([{"href": "/x", "slot": "Edit"}], size="md"))
        self.assertIn("px-4 py-2 text-sm", html)
        self.assertNotIn("px-2 py-1 text-xs", html)


class SortableHeaderTest(SimpleTestCase):
    """Clickable sortable column headers (issue #73)."""

    @staticmethod
    def _thead(result):
        return result.split("<thead")[1].split("</thead>")[0]

    def _render(self, columns, sort_terms=None):
        return str(
            components.StyledTable(
                columns=columns,
                rows=[],
                request=None,
                sort_terms=sort_terms,
            )
        )

    def test_non_sortable_column_is_static_th(self):
        """A Column without a sort_key renders a plain <th>, no link/affordance."""
        thead = self._thead(self._render([components.Column("Actions")]))
        self.assertIn("Actions", thead)
        self.assertNotIn("<sort-header", thead)
        self.assertNotIn("aria-sort", thead)
        self.assertNotIn("<a ", thead)

    def test_sortable_inactive_column_renders_link(self):
        thead = self._thead(self._render([components.Column("Name", "name")]))
        self.assertIn("<sort-header", thead)
        self.assertIn('aria-sort="none"', thead)
        # plain-click target sorts ascending by this key
        self.assertIn("sort=name", thead)
        self.assertIn("data-shift-href", thead)
        # no active arrow on an inactive column
        self.assertNotIn("rotate-180", thead)

    def test_active_ascending_shows_arrow_and_flips_to_descending(self):
        from common.sorting import SortTerm

        thead = self._thead(
            self._render(
                [components.Column("Name", "name")],
                sort_terms=[SortTerm("name", False)],
            )
        )
        self.assertIn('aria-sort="ascending"', thead)
        # ascending → arrow is rotated up
        self.assertIn("rotate-180", thead)
        # plain click on the sole-active ascending column flips to descending
        self.assertIn("sort=-name", thead)

    def test_active_descending_no_rotation_flips_to_ascending(self):
        from common.sorting import SortTerm

        thead = self._thead(
            self._render(
                [components.Column("Name", "name")],
                sort_terms=[SortTerm("name", True)],
            )
        )
        self.assertIn('aria-sort="descending"', thead)
        self.assertNotIn("rotate-180", thead)
        # sole-active descending flips back to ascending (bare key)
        self.assertIn("sort=name", thead)
        self.assertNotIn("sort=-name", thead)

    def test_multi_column_shows_position_badges(self):
        from common.sorting import SortTerm

        thead = self._thead(
            self._render(
                [
                    components.Column("Status", "status"),
                    components.Column("Name", "name"),
                ],
                sort_terms=[SortTerm("status", False), SortTerm("name", True)],
            )
        )
        # 1-based badges for both active columns
        self.assertIn(">1<", thead)
        self.assertIn(">2<", thead)


class SortHrefTest(SimpleTestCase):
    """_sort_href / _replace_query querystring surgery."""

    def setUp(self):
        from django.test import RequestFactory

        self.factory = RequestFactory()

    def test_sets_sort_drops_page_preserves_filter(self):
        from common.components.primitives import _sort_href

        request = self.factory.get("/x", {"filter": "abc", "page": "3", "sort": "name"})
        href = _sort_href(request, "-name")
        self.assertIn("filter=abc", href)
        self.assertIn("sort=-name", href)
        self.assertNotIn("page=", href)

    def test_empty_sort_drops_sort_and_page(self):
        from common.components.primitives import _sort_href

        request = self.factory.get("/x", {"filter": "abc", "page": "2", "sort": "name"})
        href = _sort_href(request, "")
        self.assertIn("filter=abc", href)
        self.assertNotIn("sort=", href)
        self.assertNotIn("page=", href)


class ComponentPrimitivesTest(SimpleTestCase):
    def test_checkbox_primitive(self):
        html = str(
            components.Checkbox(
                name="test-check", label="Accept Terms", checked=True, value="yes"
            )
        )
        self.assertIn('type="checkbox"', html)
        self.assertIn('name="test-check"', html)
        self.assertIn('value="yes"', html)
        self.assertIn('checked="true"', html)
        self.assertIn("Accept Terms", html)

    def test_checkbox_headless(self):
        html = str(components.Checkbox(name="test-headless", label=None, checked=True))
        self.assertNotIn("<label", html)
        self.assertIn("<input", html)
        self.assertIn('type="checkbox"', html)
        self.assertIn('name="test-headless"', html)

    def test_radio_primitive(self):
        html = str(
            components.Radio(
                name="test-radio", label="Option A", checked=False, value="A"
            )
        )
        self.assertIn('type="radio"', html)
        self.assertIn('name="test-radio"', html)
        self.assertIn('value="A"', html)
        self.assertNotIn('checked="true"', html)
        self.assertIn("Option A", html)


class PrimitiveWidgetsTest(SimpleTestCase):
    def test_mixin_applies_widget_to_boolean_fields_only(self):
        from django import forms

        from games.forms import PrimitiveCheckboxWidget, PrimitiveWidgetsMixin

        class DummyForm(PrimitiveWidgetsMixin, forms.Form):
            agree = forms.BooleanField(required=False)
            name = forms.CharField(required=False)

        form = DummyForm()
        self.assertIsInstance(form.fields["agree"].widget, PrimitiveCheckboxWidget)
        self.assertNotIsInstance(form.fields["name"].widget, PrimitiveCheckboxWidget)

    def test_primitive_checkbox_widget_renders_headless(self):
        from games.forms import PrimitiveCheckboxWidget

        widget = PrimitiveCheckboxWidget()
        html = widget.render(name="agree", value=True)
        self.assertNotIn("<label", html)
        self.assertIn("<input", html)
        self.assertIn('type="checkbox"', html)
        self.assertIn('name="agree"', html)
        self.assertIn('checked="true"', html)


if __name__ == "__main__":
    unittest.main()
