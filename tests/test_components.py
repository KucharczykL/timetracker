import re
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

    def test_host_stays_content_width_in_flex(self):
        # self-start keeps the <pop-over> host at trigger width in a flex parent;
        # a stretched host mis-anchors the fixed panel (#446).
        html = str(components.Popover("c", wrapped_content="c"))
        self.assertIn("self-start", html[: html.index("data-pop-over-trigger")])

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


class TooltipDefinitionListTest(unittest.TestCase):
    def test_shared_semantic_term_and_value_treatment(self):
        html = str(
            components.TooltipDefinitionList(
                [
                    components.TooltipDefinition("Name", "The Display Name"),
                    components.TooltipDefinition(
                        "Sort name",
                        "Display Name, The",
                        {"data-example-detail": ""},
                    ),
                ],
                class_="max-w-sm",
            )
        )

        self.assertIn("<dl", html)
        self.assertIn('data-tooltip-definition-list=""', html)
        self.assertIn("flex flex-col gap-2 max-w-sm", html)
        self.assertEqual(html.count('<dt class="text-type-micro text-body">'), 2)
        self.assertEqual(html.count('<dd class="font-medium">'), 2)
        self.assertIn(">Name</dt>", html)
        self.assertIn(">The Display Name</dd>", html)
        self.assertIn('data-example-detail=""', html)


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
        result = str(components.Div([("class", "x")])["hello"])
        self.assertIsInstance(result, SafeText)

    def test_div_deterministic(self):
        r1 = str(components.Div([("class", "x")])["hello"])
        r2 = str(components.Div([("class", "x")])["hello"])
        self.assertEqual(r1, r2)
        self.assertIn('<div class="x">hello</div>', r1)

    def test_div_no_args(self):
        result = str(components.Div()["test"])
        self.assertIsInstance(result, SafeText)
        self.assertIn("<div>test</div>", result)

    def test_a_returns_safe_text(self):
        result = str(components.A()["link"])
        self.assertIsInstance(result, SafeText)

    def test_a_literal_href(self):
        result = str(components.A(href="/literal/path")["x"])
        self.assertIn('href="/literal/path"', result)

    def test_a_no_url_or_href(self):
        result = str(components.A()["link"])
        self.assertIn("<a>link</a>", result)
        self.assertNotIn("href=", result)

    def test_button_returns_safe_text(self):
        result = str(components.ControlButton()["click"])
        self.assertIsInstance(result, SafeText)
        self.assertIn("<button", result)

    def test_button_default_colors(self):
        result = str(components.ControlButton()["click"])
        self.assertIn("solid-brand", result)

    def test_name_with_icon_no_link(self):
        result = str(components.NameWithIcon(name="Game", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Game", result)
        self.assertNotIn("<a ", result)

    def test_name_with_icon_no_trailing_comma(self):
        result = str(components.NameWithIcon(name="Test", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertNotIsInstance(result, tuple)


class SessionActionsTest(unittest.TestCase):
    """The <session-actions> custom element: finish/reset only for an open
    session, plus the hidden reset-confirm modal. Edit/Delete always present."""

    def _session(self, *, pk=7, timestamp_end=None, game_name="Hades"):
        from types import SimpleNamespace

        return SimpleNamespace(
            pk=pk,
            timestamp_end=timestamp_end,
            game=SimpleNamespace(name=game_name),
        )

    def test_open_session_renders_finish_reset_csrf_and_modal(self):
        from common.components.domain import SessionActions

        html = str(SessionActions(self._session(), "tok123"))
        self.assertIn("<session-actions", html)
        self.assertIn('api-url="/api/session/7"', html)
        self.assertIn('csrf="tok123"', html)
        self.assertIn("data-finish", html)
        self.assertIn("data-reset", html)
        self.assertIn("data-reset-modal", html)
        self.assertIn("Hades", html)  # modal copy names the game

    def test_closed_session_hides_finish_reset_and_modal(self):
        import datetime

        from common.components.domain import SessionActions

        ended = self._session(
            timestamp_end=datetime.datetime(
                2026, 6, 24, 19, 0, tzinfo=datetime.timezone.utc
            )
        )
        html = str(SessionActions(ended, "tok123"))
        self.assertIn("<session-actions", html)
        self.assertNotIn("data-finish", html)
        self.assertNotIn("data-reset", html)
        self.assertNotIn("data-reset-modal", html)
        self.assertIn("/session/7/edit", html)  # edit link still present


class ComponentOutputIsNotEscapedTest(unittest.TestCase):
    """Smoke test: every component that generates HTML must not double-escape."""

    def test_component_output_starts_with_tag(self):
        for label, html in [
            ("A", str(components.A(href="/foo")["link"])),
            ("Button", str(components.ControlButton()["click"])),
            ("Div", str(components.Div()["hello"])),
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
            ("PriceConverted", str(components.PriceConverted(["27 CZK"]))),
            ("PageHeading", str(components.PageHeading(["Title"]))),
            (
                "PageHeading with badge",
                str(components.PageHeading(["Title"], badge="3")),
            ),
        ]:
            with self.subTest(component=label):
                self.assertTrue(
                    str(html).startswith("<"),
                    f"{label} output should start with '<', got: {str(html)[:80]}",
                )

    def test_button_with_icon_children_not_escaped(self):
        result = str(components.ControlButton()[components.Icon("play"), "LOG"])
        self.assertTrue(str(result).startswith("<button"))

    def test_popover_with_button_children_not_escaped(self):
        result = str(
            components.Popover(
                popover_content="test tooltip",
                children=[
                    components.ControlButton(color="gray")[
                        components.Icon("play"), "test"
                    ],
                ],
            )
        )
        self.assertTrue(str(result).startswith("<pop-over"))

    def test_name_with_icon_output_not_escaped(self):
        result = str(components.NameWithIcon(name="Test", linkify=False))
        self.assertTrue(str(result).startswith("<truncated-text"))


class ComponentEdgeCasesTest(unittest.TestCase):
    """Test Element() edge cases and error handling."""

    def test_no_tag_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            str(components.Element("", children="hello"))
        self.assertIn("tag_name", str(ctx.exception))

    def test_duplicate_element_ids_are_rejected_by_document_walk(self):
        tree = components.Div()[components.Span(id="same"), components.Span(id="same")]
        with self.assertRaisesRegex(ValueError, "Duplicate element id"):
            components.assert_unique_element_ids(tree)

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

    def test_raw_text_element_body_is_not_escaped(self):
        # <script>/<style> are HTML raw-text elements: their body is character
        # data, so it must be emitted verbatim (escaping would corrupt JS/CSS).
        js = "if (a < b && c) f('x');"
        result = str(components.Element(tag_name="script", children=[js]))
        self.assertIn(js, result)
        self.assertNotIn("&lt;", result)
        self.assertNotIn("&#x27;", result)
        self.assertNotIn("&amp;", result)

        css = "a > b { content: '\"'; }"
        result = str(components.Element(tag_name="style", children=[css]))
        self.assertIn(css, result)
        self.assertNotIn("&gt;", result)

    def test_void_element_has_no_closing_tag(self):
        # HTML void elements get no closing tag and no self-closing slash.
        result = str(components.Element(tag_name="img", attributes=[("src", "x")]))
        self.assertEqual(result, '<img src="x">')
        self.assertNotIn("</img>", result)
        self.assertEqual(str(components.Element(tag_name="br")), "<br>")

    def test_void_element_with_children_raises(self):
        with self.assertRaises(ValueError):
            str(components.Element(tag_name="img", children=["nope"]))

    def test_non_void_element_keeps_closing_tag(self):
        result = str(components.Element(tag_name="div", children=["hi"]))
        self.assertEqual(result, "<div>hi</div>")

    def test_document_node_renders_doctype_and_bubbles_media(self):
        # A whole document is the <!DOCTYPE html> preamble + an <html> subtree,
        # as a single node; media still bubbles from the subtree.
        body_child = components.Element(tag_name="div").with_media(
            components.Media(js=("widget.js",))
        )
        html = components.Element(tag_name="html", children=[body_child])
        document = components.Document(html)
        self.assertTrue(str(document).startswith("<!DOCTYPE html><html>"))
        self.assertIn("widget.js", components.collect_media(document).js)

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

    def test_icon_overrides_snippet_class_and_keeps_viewbox(self):
        # The snippet's baked class is replaced by the central icon classes (so
        # all icons restyle in one place); a passed class appends as an override.
        # viewBox must survive — dropping it clips the paths to a sliver.
        from common.components.primitives import ICON_SIZE_CLASS

        result = str(components.Icon("arrowdownlong", [("class", "rotate-180")]))
        self.assertIn(f'class="{ICON_SIZE_CLASS} rotate-180"', result)
        self.assertNotIn("w-3 h-3 rotate-180", result)  # snippet size dropped
        self.assertIn("viewBox=", result)

    def test_icon_size_override_replaces_default(self):
        # `size=` swaps the default size wholesale; the default size tokens are
        # gone. ICON_BASE_CLASS is colourless, so the icon inherits currentColor.
        result = str(components.Icon("play", size="w-6 h-6"))
        self.assertIn('class="w-6 h-6"', result)
        self.assertNotIn("w-2", result)  # default size replaced
        self.assertNotIn("text-black", result)  # no pinned colour

    def test_icon_escapes_title_text(self):
        result = str(components.Icon("play", [("title", 'a"<&b')]))
        self.assertIn("&lt;", result)
        self.assertIn("&amp;", result)
        self.assertNotIn("<&", result)

    def test_icon_without_attributes_still_overrides_class(self):
        # Even with no attributes every icon is restyled by the central classes
        # (overriding the snippet's baked class); viewBox is kept.
        from common.components.primitives import ICON_SIZE_CLASS

        result = str(components.Icon("arrowdownlong"))
        self.assertIn(f'class="{ICON_SIZE_CLASS}"', result)
        self.assertIn("viewBox=", result)

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
            components.Input([("id", "email"), ("class", "form-input")], type="email")
        )
        self.assertIn('type="email"', result)
        self.assertIn('id="email"', result)
        self.assertIn('class="form-input"', result)


class NormalizeAttributesTest(unittest.TestCase):
    """The node-layer attribute algebra: class/style accumulate, scalars first-wins."""

    def test_duplicate_class_accumulates(self):
        result = components.normalize_attributes(
            [("class", "a"), ("class", "b"), ("class", "c")]
        )
        self.assertEqual(result, [("class", "a b c")])

    def test_duplicate_scalar_first_wins(self):
        result = components.normalize_attributes([("id", "first"), ("id", "second")])
        self.assertEqual(result, [("id", "first")])

    def test_style_accumulates_with_semicolon(self):
        result = components.normalize_attributes(
            [("style", "color: red"), ("style", "margin: 0")]
        )
        self.assertEqual(result, [("style", "color: red; margin: 0")])

    def test_empty_class_contribution_dropped(self):
        result = components.normalize_attributes(
            [("class", ""), ("class", "real"), ("class", "")]
        )
        self.assertEqual(result, [("class", "real")])

    def test_all_empty_class_omits_attribute(self):
        result = components.normalize_attributes([("class", "")])
        self.assertEqual(result, [])

    def test_class_emitted_at_first_position(self):
        result = components.normalize_attributes(
            [("class", "a"), ("id", "x"), ("class", "b")]
        )
        self.assertEqual(result, [("class", "a b"), ("id", "x")])

    def test_order_preserved_for_scalars(self):
        result = components.normalize_attributes(
            [("name", "n"), ("value", "v"), ("type", "text")]
        )
        self.assertEqual(result, [("name", "n"), ("value", "v"), ("type", "text")])

    def test_non_string_scalar_value_preserved(self):
        result = components.normalize_attributes([("tabindex", 0), ("checked", True)])
        self.assertEqual(result, [("tabindex", 0), ("checked", True)])

    def test_idempotent(self):
        once = components.normalize_attributes(
            [("class", "a"), ("class", "b"), ("id", "x"), ("id", "y")]
        )
        twice = components.normalize_attributes(once)
        self.assertEqual(once, twice)

    def test_no_duplicate_input_unchanged(self):
        attrs = [("class", "btn"), ("id", "x"), ("name", "n")]
        self.assertEqual(components.normalize_attributes(attrs), attrs)

    def test_element_collapses_duplicate_class_in_render(self):
        # The root-fix regression guard: duplicate-attribute HTML is impossible.
        result = str(components.Element("div", [("class", "a"), ("class", "b")], "hi"))
        self.assertEqual(result, '<div class="a b">hi</div>')

    def test_element_duplicate_scalar_collapsed_in_render(self):
        result = str(components.Element("div", [("id", "a"), ("id", "b")]))
        self.assertEqual(result, '<div id="a"></div>')


class GenericBuilderContractTest(SimpleTestCase):
    """The generic builder contract: positional attrs (list or Mapping), htpy
    kwargs, and `[]` children only. Legacy attributes=/children= are rejected."""

    def test_positional_attrs_list(self):
        result = str(components.Div([("id", "x")]))
        self.assertEqual(result, '<div id="x"></div>')

    def test_positional_attrs_mapping(self):
        result = str(components.Div({"data-x": "y"}))
        self.assertEqual(result, '<div data-x="y"></div>')

    def test_kwargs_static(self):
        result = str(components.Div(class_="a", data_foo="b"))
        self.assertEqual(result, '<div class="a" data-foo="b"></div>')

    def test_mixed_dynamic_and_static_class_accumulates(self):
        result = str(components.Div([("class", "dyn")], class_="static"))
        self.assertEqual(result, '<div class="dyn static"></div>')

    def test_legacy_attributes_keyword_rejected(self):
        with self.assertRaises(TypeError):
            components.Div(attributes=[("id", "x")])

    def test_legacy_children_keyword_rejected(self):
        with self.assertRaises(TypeError):
            components.Div(children=["hi"])

    def test_getitem_children(self):
        result = str(components.Div(class_="x")["hi"])
        self.assertEqual(result, '<div class="x">hi</div>')

    def test_reserved_attributes_kwarg_raises(self):
        # The footgun guard: 'attributes'/'children' as htpy kwargs are rejected
        # rather than silently rendered as bogus HTML attributes.
        from common.components.primitives import _attrs_from_kwargs

        with self.assertRaises(TypeError) as ctx:
            _attrs_from_kwargs({"attributes": "oops"})
        self.assertIn("htpy", str(ctx.exception))

    def test_reserved_children_kwarg_raises(self):
        from common.components.primitives import _attrs_from_kwargs

        with self.assertRaises(TypeError):
            _attrs_from_kwargs({"children": "oops"})

    def test_styled_builders_reject_legacy_attributes_kwarg(self):
        # The guard fires on the styled builders too — they no longer have an
        # `attributes=` param, so it lands in **kwargs and is rejected.
        with self.assertRaises(TypeError):
            components.ControlButton(attributes=[("data-x", "y")])
        with self.assertRaises(TypeError):
            components.Input(attributes=[("data-x", "y")])
        with self.assertRaises(TypeError):
            components.Pill(label="x", attributes=[("data-x", "y")])

    def test_no_class_token_dedup(self):
        # class accumulation joins verbatim — it does NOT de-duplicate tokens
        # (JS-cloned pills rely on byte-for-byte class strings).
        result = components.normalize_attributes([("class", "a"), ("class", "a")])
        self.assertEqual(result, [("class", "a a")])

    def test_mapping_attrs_class_accumulates_through_builder(self):
        result = str(components.Div({"class": "dyn"}, class_="static"))
        self.assertEqual(result, '<div class="dyn static"></div>')


class StyledBuilderContractTest(SimpleTestCase):
    """The six styled builders accept htpy kwargs, positional attrs, and merge
    class via the node algebra (caller class appends; baked semantic attrs win)."""

    def test_input_htpy_kwargs(self):
        result = str(components.Input(type="hidden", name="n", value="v"))
        self.assertIn('type="hidden"', result)
        self.assertIn('name="n"', result)
        self.assertIn('value="v"', result)

    def test_input_positional_dynamic_attrs(self):
        result = str(components.Input([("name", "n"), ("value", "v")]))
        self.assertIn('name="n"', result)
        self.assertIn('value="v"', result)
        self.assertIn('type="text"', result)

    def test_input_explicit_type_in_attrs_wins_over_default(self):
        result = str(components.Input([("type", "date")]))
        self.assertIn('type="date"', result)
        self.assertNotIn('type="text"', result)

    def test_checkbox_class_appends_to_baked(self):
        result = str(components.Checkbox(name="x", class_="ml-2"))
        self.assertIn("ml-2", result)
        self.assertIn("rounded", result)  # baked class still present
        # single class attribute, not two
        self.assertEqual(result.count("class="), 1)

    def test_checkbox_extra_attr_via_kwargs(self):
        result = str(components.Checkbox(name="x", data_foo="bar"))
        self.assertIn('data-foo="bar"', result)

    def test_radio_class_appends(self):
        result = str(components.Radio(name="x", class_="mr-1"))
        self.assertIn("mr-1", result)
        self.assertIn("rounded-full", result)

    def test_pill_class_appends_to_base(self):
        result = str(components.Pill(label="hi", class_="ring-1"))
        self.assertIn("ring-1", result)
        self.assertIn("inline-flex", result)  # base pill class

    def test_pill_extra_class(self):
        result = str(components.Pill(label="hi", extra_class="opacity-50"))
        self.assertIn("opacity-50", result)

    def test_controlbutton_class_appends_and_kwargs_passthrough(self):
        result = str(
            components.ControlButton(class_="w-full", aria_label="Go", color="red")[
                "Go"
            ]
        )
        self.assertIn("w-full", result)
        self.assertIn('aria-label="Go"', result)
        self.assertEqual(result.count("class="), 1)

    def test_controlbutton_type_param_sets_submit(self):
        self.assertIn(
            'type="submit"', str(components.ControlButton(type="submit")["x"])
        )

    def test_controlbutton_baked_type_wins_over_caller_attrs(self):
        # baked attrs come first -> first-wins -> a caller can't override `type`
        result = str(components.ControlButton([("type", "reset")])["x"])
        self.assertIn('type="button"', result)
        self.assertNotIn('type="reset"', result)

    def test_checkbox_baked_name_wins_over_caller_attrs(self):
        result = str(components.Checkbox(name="real", attrs=[("name", "spoof")]))
        self.assertIn('name="real"', result)
        self.assertNotIn('name="spoof"', result)
        self.assertEqual(result.count("name="), 1)


class ContentContainerTest(SimpleTestCase):
    """The page-body width container (issue #313): baked classes, caller class
    merge, htpy children slot."""

    def test_baked_classes_and_children(self):
        result = str(components.ContentContainer()["body"])
        self.assertEqual(result, '<div class="w-full max-w-7xl self-center">body</div>')

    def test_caller_class_appends_to_baked(self):
        result = str(components.ContentContainer(class_="dark:text-white px-2")["x"])
        self.assertIn(
            'class="w-full max-w-7xl self-center dark:text-white px-2"', result
        )
        self.assertEqual(result.count("class="), 1)


class ControlButtonTest(SimpleTestCase):
    """The polymorphic ControlButton: one styling source, three rendered shapes
    (<button>, <a href>, <form method=post> + submit)."""

    def test_default_mode_is_button_with_filled_classes(self):
        html = str(components.ControlButton()["Go"])
        self.assertTrue(html.startswith("<button"))
        self.assertIn('type="button"', html)
        self.assertIn("solid-brand", html)
        # shared control-height token present; no fixed-size margins baked
        self.assertIn("min-h-control", html)
        self.assertNotIn("mb-2", html)
        self.assertNotIn("me-2", html)
        # shared disabled appearance is baked in
        self.assertIn("disabled:opacity-50", html)

    def test_href_mode_is_single_anchor(self):
        html = str(components.ControlButton(href="/games/add")["Add game"])
        self.assertTrue(html.startswith("<a "))
        self.assertIn('href="/games/add"', html)
        self.assertIn("solid-brand", html)
        # a link is not a button: no nested interactive element, no type attr
        self.assertNotIn("<button", html)
        self.assertNotIn("type=", html)

    def test_post_mode_wraps_submit_in_form(self):
        html = str(
            components.ControlButton(href="/x/delete", method="post", csrf_token="tok")[
                "Delete"
            ]
        )
        self.assertTrue(html.startswith("<form"))
        self.assertIn('method="post"', html)
        # action defaults to href
        self.assertIn('action="/x/delete"', html)
        self.assertIn('name="csrfmiddlewaretoken" value="tok"', html)
        # classes land on the inner button, not the form
        self.assertIn('<button type="submit"', html)
        submit_index = html.index("<button")
        self.assertIn("bg-brand", html[submit_index:])
        self.assertNotIn("bg-brand", html[:submit_index])

    def test_post_mode_action_overrides_href(self):
        html = str(
            components.ControlButton(href="/fallback", method="post", action="/real")[
                "Save"
            ]
        )
        self.assertIn('action="/real"', html)
        self.assertNotIn("/fallback", html)

    def test_post_mode_forced_submit_wins_over_caller_type(self):
        html = str(components.ControlButton([("type", "reset")], method="post")["Save"])
        self.assertIn('type="submit"', html)
        self.assertNotIn('type="reset"', html)

    def test_getitem_returns_new_instance(self):
        base = components.ControlButton(color="gray")
        first = base["One"]
        second = base["Two"]
        self.assertIsNot(first, base)
        self.assertIn("One", str(first))
        self.assertIn("Two", str(second))
        self.assertNotIn("Two", str(first))

    def test_getitem_after_render_does_not_serve_stale_tree(self):
        base = components.ControlButton()["Old"]
        str(base)  # populate the memoized tree
        self.assertIn("New", str(base["New"]))

    def test_segmented_variant_classes(self):
        html = str(components.ControlButton(variant="segmented", color="gray")["Edit"])
        # shared control-height scale, same as filled
        self.assertIn("min-h-control", html)
        self.assertNotIn("lg:px-4", html)
        self.assertIn("bg-neutral-primary-medium", html)

    def test_color_tables_have_matching_keys(self):
        from common.components.primitives import (
            _FILLED_COLOR_CLASSES,
            _SEGMENTED_COLOR_CLASSES,
        )

        self.assertEqual(set(_FILLED_COLOR_CLASSES), set(_SEGMENTED_COLOR_CLASSES))

    def test_as_element_unwraps_button(self):
        element = components.ControlButton()["Go"].as_element()
        self.assertEqual(element.tag_name, "button")

    def test_outline_variant_is_the_dropdown_toggle_look(self):
        html = str(components.ControlButton(variant="outline")["x"])
        self.assertTrue(html.startswith("<button"))
        self.assertIn("whitespace-nowrap", html)
        self.assertIn("border-default-medium", html)
        # shared control-height scale, same as every other button variant
        self.assertIn("min-h-control", html)
        self.assertNotIn("lg:px-4", html)
        # single-look variant: no color axis, keyboard focus ring
        self.assertNotIn("bg-brand", html)
        self.assertIn("focus:ring-2", html)

    def test_button_variants_share_one_sizing_scale(self):
        # ALL button-shaped variants floor to the one control-height token; only
        # the nav-link plain variant keeps its navbar layout. Height is now
        # container-independent — no @md step, so a button is 42px in every row.
        for variant in ("filled", "segmented", "outline"):
            with self.subTest(variant=variant):
                html = str(components.ControlButton(variant=variant)["x"])
                self.assertIn("min-h-control", html)
                self.assertIn("text-type-body", html)
                self.assertNotIn("@md:", html)  # height no longer container-stepped
                self.assertNotIn("text-xs", html)

    def test_plain_variant_is_the_navbar_nav_link_look(self):
        html = str(components.ControlButton(variant="plain")["x"])
        self.assertIn("md:hover:text-blue-700", html)
        self.assertIn("justify-between", html)
        # the nav-link layout survives untouched: no centering or inline-flex
        # from the filled/segmented base, no color table
        self.assertNotIn("justify-center", html)
        self.assertNotIn("inline-flex", html)
        self.assertNotIn("bg-brand", html)

    def test_toggle_variants_ignore_color(self):
        default = str(components.ControlButton(variant="outline")["x"])
        red = str(components.ControlButton(variant="outline", color="red")["x"])
        self.assertEqual(red, default)

    def test_outline_variant_takes_extra_shape_classes(self):
        html = str(
            components.ControlButton([("class", "rounded-e-lg")], variant="outline")[
                "x"
            ]
        )
        self.assertIn("rounded-e-lg", html)


class ModalContractTest(SimpleTestCase):
    """Modal injects [] children into the inner panel, not the outer backdrop."""

    def test_id_on_backdrop_content_in_panel(self):
        html = str(components.Modal("m1")[components.Div(class_="body-marker")["BODY"]])
        # id sits on the outer backdrop (before the panel's max-w-xl class)
        self.assertIn('id="m1"', html)
        self.assertLess(html.index('id="m1"'), html.index("max-w-xl"))
        # children land after the panel class, i.e. inside the panel
        self.assertLess(html.index("max-w-xl"), html.index("body-marker"))
        self.assertIn("BODY", html)

    def test_getitem_is_immutable_and_bubbles_media(self):
        base = components.Modal("m2")
        filled = base[components.Div().with_media(components.Media(js=("modal-c.js",)))]
        self.assertIsNot(base, filled)
        self.assertIn("modal-c.js", components.collect_media(filled).js)
        # the original, unsubscripted modal has no child media
        self.assertNotIn("modal-c.js", components.collect_media(base).js)

    def test_renders_modal_dialog_element_with_dismiss_contract(self):
        # The overlay is the <modal-dialog> custom element carrying the dialog
        # role/aria + the panel hook the shared dismiss anchors on.
        html = str(components.Modal("m3")[components.Div()["x"]])
        self.assertTrue(html.startswith("<modal-dialog"))
        self.assertIn('role="dialog"', html)
        self.assertIn('aria-modal="true"', html)
        self.assertIn("data-modal-panel", html)
        # Self-managing by default; the element wires Escape/backdrop dismiss.
        self.assertIn('data-manage="true"', html)
        self.assertIn(
            "dist/elements/modal-dialog.js",
            components.collect_media(components.Modal("m3")).js,
        )

    def test_self_dismiss_false_marks_element_inert(self):
        # The session-reset overlay opts out — <session-actions> manages it.
        html = str(components.Modal("m4", self_dismiss=False)[components.Div()["x"]])
        self.assertIn('data-manage="false"', html)


class DropdownActionItemContractTest(SimpleTestCase):
    """DropdownActionItem: label is the [] slot; htpy kwargs are button hooks."""

    def test_label_and_data_hook_on_button(self):
        html = str(components.DropdownActionItem(data_add_play="")["Played +1"])
        self.assertIn("Played +1", html)
        # the data hook and the label both live on the <button>, not the <li>
        button = html[html.index("<button") : html.index("</button>")]
        self.assertIn("data-add-play", button)
        self.assertIn("Played +1", button)
        self.assertNotIn("data-add-play", html[: html.index("<button")])

    def test_disabled_branch(self):
        html = str(components.DropdownActionItem(disabled=True)["x"])
        self.assertIn("disabled", html)
        self.assertIn('aria-disabled="true"', html)

    def test_bubbles_media(self):
        item = components.DropdownActionItem()[
            components.Div().with_media(components.Media(js=("ddi.js",)))
        ]
        self.assertIn("ddi.js", components.collect_media(item).js)


class TruncatedTextTest(unittest.TestCase):
    """The server-side contract for width-based text truncation."""

    def test_default_keeps_full_text_and_is_visual_only_for_at(self):
        html = str(components.TruncatedText("The complete visible value"))
        self.assertTrue(html.startswith("<truncated-text"))
        self.assertIn("max-w-[16rem]", html)
        self.assertIn("The complete visible value", html)
        self.assertIn("data-truncated-clip", html)
        self.assertIn('data-truncated-reveal="ellipsis"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn("aria-describedby", html)
        self.assertNotRegex(html, r'data-pop-over-panel=""[^>]*\sid=')

    def test_default_adds_the_component_script(self):
        node = components.TruncatedText("text")
        self.assertIn(
            "dist/elements/truncated-text.js", components.collect_media(node).js
        )

    def test_leading_content_and_clip_remain_inside_link(self):
        html = str(
            components.TruncatedText(
                "Linked text", leading=components.Span()["icon"], link="/target"
            )
        )
        link = html[html.index("<a ") : html.index("</a>")]
        self.assertIn("icon", link)
        self.assertIn("data-truncated-clip", link)
        self.assertNotIn("<button", link)

    def test_tap_false_has_no_reveal_button(self):
        html = str(components.TruncatedText("menu text", tap=False))
        self.assertNotIn("<button", html)

    def test_differing_tooltip_content_gets_safe_aria_relationship(self):
        html = str(
            components.TruncatedText(
                "Bundle",
                link="/bundle",
                reveal="always",
                tooltip_content=components.Ul()[components.Li()["Game"]],
                instance_key="purchase-list:7",
            )
        )
        panel_id = re.search(r'data-pop-over-panel="" id="([^"]+)"', html)
        self.assertIsNotNone(panel_id)
        assert panel_id is not None
        self.assertRegex(panel_id.group(1), r"^[0-9a-f]{10}$")
        self.assertEqual(html.count(f'aria-describedby="{panel_id.group(1)}"'), 2)
        self.assertIn('data-truncated-reveal="info"', html)
        self.assertIn("[@media(hover:none)]:pe-6", html)
        self.assertIn('role="tooltip"', html)
        self.assertNotIn('aria-hidden="true"', html)

    def test_differing_content_requires_instance_key(self):
        with self.assertRaises(ValueError):
            components.TruncatedText("Bundle", tooltip_content="Game")


class TruncateInfoTest(unittest.TestCase):
    """Test the truncate_info() pure helper."""

    def test_short_string_not_truncated(self):
        truncation = components.truncate_info("hi")
        self.assertEqual(truncation.display, "hi")
        self.assertFalse(truncation.was_truncated)

    def test_long_string_truncated(self):
        truncation = components.truncate_info("a" * 100)
        self.assertEqual(truncation.display, components.truncate("a" * 100))
        self.assertTrue(truncation.display.endswith("…"))
        self.assertTrue(truncation.was_truncated)

    def test_endpart_appended_without_cutting(self):
        truncation = components.truncate_info("short", endpart="!")
        self.assertEqual(truncation.display, "short!")
        self.assertFalse(truncation.was_truncated)

    def test_endpart_with_cutting(self):
        truncation = components.truncate_info("a" * 50, length=10, endpart="x")
        self.assertTrue(truncation.was_truncated)
        self.assertTrue(truncation.display.endswith("x"))


class TruncateBoundaryTest(unittest.TestCase):
    """The cut must never leave a dangling separator before the ellipsis."""

    def test_no_dangling_space_dash_before_ellipsis(self):
        result = components.truncate(
            "The Walking Dead: Michonne - A Telltale Games Series", 30
        )
        self.assertTrue(result.endswith("…"))
        # No space+ellipsis tail, and the char before the ellipsis is alphanumeric.
        self.assertNotIn(" …", result)
        self.assertTrue(result[:-1].isalnum() or result[-2].isalnum())

    def test_trailing_dash_at_cut_is_dropped(self):
        # Cut lands right on the " - " separator.
        result = components.truncate("Portal 2 - Deluxe Edition", 12)
        self.assertEqual(result, "Portal 2…")

    def test_unicode_em_dash_stripped(self):
        result = components.truncate("Portal 2 — Deluxe Edition", 12)
        self.assertEqual(result, "Portal 2…")

    def test_trailing_comma_at_cut_is_dropped(self):
        result = components.truncate("Detective Instinct: Farewell, My Beloved", 30)
        self.assertEqual(result, "Detective Instinct: Farewell…")

    def test_trailing_colon_at_cut_is_dropped(self):
        result = components.truncate("The Secret of Monkey Island: Special Edition", 30)
        self.assertEqual(result, "The Secret of Monkey Island…")


class PopoverIfTest(unittest.TestCase):
    """Test the PopoverIf() conditional wrapper."""

    def test_false_condition_returns_node_untouched(self):
        button = components.ControlButton()["Click"]
        result = components.PopoverIf(False, "full text", button)
        self.assertIs(result, button)
        self.assertNotIn("<pop-over", str(result))

    def test_true_condition_wraps_node_in_popover(self):
        button = components.ControlButton()["Click"]
        result = str(components.PopoverIf(True, "full text", button))
        self.assertIn("<pop-over", result)
        self.assertIn("<button", result)
        self.assertIn("full text", result)

    def test_explicit_id_used(self):
        result = str(components.PopoverIf(True, "content", "wrapped", id="my-popover"))
        self.assertIn('aria-describedby="my-popover"', result)
        self.assertIn('id="my-popover"', result)


class PopOverContractTest(unittest.TestCase):
    """The <pop-over> tooltip element contract."""

    def test_renders_pop_over_element(self):
        html = str(components.Popover("tip", wrapped_content="word", id="pid"))
        # A <pop-over> wrapping a trigger + panel; no data-popover/popper attrs.
        self.assertNotIn("data-popover-target", html)
        self.assertNotIn("data-popper-arrow", html)
        self.assertTrue(html.startswith("<pop-over"))
        self.assertIn("</pop-over>", html)

    def test_trigger_describes_panel(self):
        html = str(components.Popover("tip", wrapped_content="word", id="pid"))
        # Trigger carries the hook + aria-describedby -> the panel id.
        self.assertIn("data-pop-over-trigger", html)
        self.assertIn('aria-describedby="pid"', html)
        # Panel is a role="tooltip" that starts hidden. Assert the hidden
        # ATTRIBUTE on the panel itself — a bare assertIn("hidden") would also
        # match the decoration-dotted JIT-safety span and pass even if the
        # closed-state attribute were dropped (every tooltip rendering open).
        self.assertIn("data-pop-over-panel", html)
        self.assertRegex(html, r'role="tooltip"\s+hidden')
        self.assertIn('id="pid"', html)

    def test_media_auto_attached(self):
        node = components.Popover("tip", wrapped_content="word")
        self.assertIn("dist/elements/pop-over.js", components.collect_media(node).js)

    def test_tap_default_renders_button_trigger(self):
        # Default tap=True: the trigger is a real <button> so a touch tap toggles
        # the panel, and the host advertises tap="true" to the element.
        html = str(components.Popover("tip", wrapped_content="word", id="pid"))
        self.assertIn('tap="true"', html)
        self.assertRegex(html, r'<button[^>]*type="button"')
        self.assertIn("data-pop-over-trigger", html)
        # Toggletip, not disclosure: no aria-expanded (it would contradict the
        # role="tooltip"/aria-describedby pattern).
        self.assertNotIn("aria-expanded", html)

    def test_tap_false_renders_span_trigger(self):
        html = str(
            components.Popover("tip", wrapped_content="word", id="pid", tap=False)
        )
        self.assertIn('tap="false"', html)
        self.assertNotIn("<button", html)
        self.assertRegex(html, r"<span[^>]*data-pop-over-trigger")

    def test_trigger_label_becomes_aria_label(self):
        html = str(
            components.Popover(
                "tip", wrapped_content="ⓘ", trigger_label="Show details", id="pid"
            )
        )
        self.assertIn('aria-label="Show details"', html)

    def test_selectable_text_reenables_selection_on_button(self):
        html = str(
            components.Popover(
                "tip", wrapped_content="19.99", selectable_text=True, id="pid"
            )
        )
        self.assertIn("select-text", html)

    def test_preface_renders_before_trigger_in_host(self):
        # The host-wraps case: a preface node (a link) sits before the glyph
        # <button> trigger, both inside <pop-over> as siblings.
        link = components.A(href="/x")["visible"]
        html = str(
            components.Popover("tip", wrapped_content="ⓘ", preface=link, id="pid")
        )
        self.assertLess(html.index("</a>"), html.index("data-pop-over-trigger"))


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

    _LONG_NAME = "A Very Long Game Name That Exceeds Thirty Characters"

    def _assert_no_button_inside_link(self, html: str) -> None:
        # No <button> may sit between an <a ...> and its </a>. The extraction
        # renders the reveal trigger as a sibling of the link, never a
        # descendant (there are no nested anchors, so non-greedy is safe).
        for match in re.finditer(r"<a\b[^>]*>(.*?)</a>", html, re.DOTALL):
            self.assertNotIn(
                "<button", match.group(1), "reveal <button> nested inside <a>"
            )

    def test_linked_truncated_name_reveal_is_button_beside_link(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform, name=self._LONG_NAME)
        html = str(components.NameWithIcon(game=game, linkify=True))
        self.assertIn("<truncated-text", html)
        self.assertRegex(html, r"<button[^>]*data-truncated-reveal")
        self._assert_no_button_inside_link(html)

    def test_short_linked_name_renders_an_inert_auto_reveal(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform, name="Short Name")
        html = str(components.NameWithIcon(game=game, linkify=True))
        # Overflow is a browser-width decision, so the inert auto-reveal exists
        # in markup and stays hidden until the element measures real overflow.
        self.assertIn('reveal="auto"', html)
        self.assertIn("data-truncated-reveal", html)
        self.assertIn('aria-hidden="true"', html)

    def test_game_list_name_includes_different_sort_name_in_tooltip(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform, name="The Display Name")
        game.sort_name = "Display Name, The"
        game.save(update_fields=["sort_name"])

        html = str(
            components.NameWithIcon(game=game, include_sort_name=True, linkify=True)
        )

        self.assertIn('reveal="always"', html)
        self.assertIn('data-truncated-detail="name"', html)
        self.assertIn("hidden group-data-[overflowing]:block", html)
        self.assertIn('data-truncated-detail="sort-name"', html)
        self.assertIn('data-tooltip-definition-list=""', html)
        self.assertIn("text-type-micro text-body", html)
        self.assertIn(">Name</dt>", html)
        self.assertIn(">Sort name</dt>", html)
        self.assertIn("Display Name, The", html)
        self.assertIn('data-truncated-reveal="info"', html)
        self.assertIn('role="tooltip"', html)
        self.assertIn('aria-describedby="', html)
        self.assertIn("Show full name and sort name", html)

    def test_game_list_name_omits_identical_sort_name_from_tooltip(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform, name="Same Name")
        game.sort_name = game.name
        game.save(update_fields=["sort_name"])

        html = str(components.NameWithIcon(game=game, include_sort_name=True))

        self.assertIn('reveal="auto"', html)
        self.assertNotIn("Sort name", html)
        self.assertNotIn('role="tooltip"', html)
        self.assertIn('aria-hidden="true"', html)

    def test_menu_wrapped_name_keeps_button_out_of_link(self):
        # The navbar recent-resumes case: DropdownLinkItem wraps NameWithIcon in
        # its own <a role=menuitem>, so tap=False keeps a hover-only <span> —
        # no <button> may nest in that caller-supplied link.
        from common.components.custom_elements import DropdownLinkItem

        platform = self._create_platform(name="Steam", icon="steam")
        game = self._create_game(platform, name=self._LONG_NAME)
        html = str(
            DropdownLinkItem(
                "/go", components.NameWithIcon(game=game, linkify=False, tap=False)
            )
        )
        self.assertNotIn("<button", html)
        self._assert_no_button_inside_link(html)

    def test_linked_purchase_bundle_reveal_is_button_beside_link(self):
        platform = self._create_platform(name="Steam", icon="steam")
        game_one = self._create_game(platform, name="Bundle Game One")
        game_two = self._create_game(platform, name="Bundle Game Two")
        purchase = self._create_purchase([game_one, game_two], platform=platform)
        html = str(components.LinkedPurchase(purchase))
        self.assertIn("<truncated-text", html)
        self.assertRegex(html, r"<button[^>]*data-truncated-reveal")
        self._assert_no_button_inside_link(html)

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
        self.assertIn("<pop-over", result)

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

    def test_linked_purchase_named_bundle_shows_games_list(self):
        """A multi-game purchase shows its games-list popover even when the
        purchase name is short enough to display untruncated."""
        platform = self._create_platform(icon="steam")
        game1 = self._create_game(platform, name="Game A")
        game2 = self._create_game(platform, name="Game B")
        purchase = self._create_purchase([game1, game2], price=24.99)
        purchase.name = "Bundle"
        purchase.save()
        result = str(components.LinkedPurchase(purchase))
        self.assertIn("<truncated-text", result)
        self.assertIn("Game A", result)
        self.assertIn("Game B", result)

    def test_linked_purchase_renders_game_names_in_popover(self):
        platform = self._create_platform(icon="steam")
        game1 = self._create_game(platform, name="Alpha")
        game2 = self._create_game(platform, name="Beta")
        purchase = self._create_purchase([game1, game2], price=19.99)
        result = str(components.LinkedPurchase(purchase))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Alpha", result)
        self.assertIn("Beta", result)


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
        # No game context at all: no platform badge, not even the
        # "unspecified" fallback icon.
        result = str(components.NameWithIcon(name="Unknown Game", linkify=False))
        self.assertIsInstance(result, SafeText)
        self.assertIn("Unknown Game", result)
        visible_prefix = result[: result.index("data-truncated-clip")]
        self.assertNotIn("<svg", visible_prefix)

    def test_name_with_icon_null_platform_shows_unspecified_icon(self):
        # A game without a platform (NULL since issue #290) keeps a badge:
        # the "unspecified" fallback icon.
        platformless_game = Game.objects.create(name="Homebrew")
        result = str(components.NameWithIcon(game=platformless_game, linkify=False))
        self.assertIn("<svg", result)
        self.assertIn("Unspecified", result)


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
        resolved = components._resolve_name_with_icon(
            "", self.mock_game, self.mock_session, True
        )
        self.assertEqual(resolved.name, "Test Game")
        self.assertEqual(resolved.badge, components.PlatformBadge("steam", "Steam"))
        self.assertFalse(resolved.emulated)

    def test_session_overrides_game_parameter(self):
        override_game = MagicMock()
        override_game.name = "Override"
        override_game.platform = self.mock_platform
        override_game.pk = 99
        with patch("common.components.domain.reverse", return_value="/game/99"):
            resolved = components._resolve_name_with_icon(
                "", override_game, self.mock_session, True
            )
        self.assertEqual(resolved.name, "Test Game")
        self.assertIsNot(resolved.name, "Override")

    def test_game_only_provides_platform(self):
        with patch("common.components.domain.reverse", return_value="/game/1"):
            resolved = components._resolve_name_with_icon(
                "", self.mock_game, None, True
            )
        self.assertEqual(resolved.name, "Test Game")
        self.assertEqual(resolved.badge, components.PlatformBadge("steam", "Steam"))
        self.assertEqual(resolved.link, "/game/1")

    def test_game_without_platform_gets_unspecified_badge(self):
        platformless_game = MagicMock()
        platformless_game.name = "Homebrew"
        platformless_game.pk = 7
        platformless_game.platform = None
        resolved = components._resolve_name_with_icon(
            "", platformless_game, None, False
        )
        self.assertEqual(
            resolved.badge, components.PlatformBadge("unspecified", "Unspecified")
        )

    def test_custom_name_overrides_game_name(self):
        resolved = components._resolve_name_with_icon(
            "Custom", self.mock_game, None, False
        )
        self.assertEqual(resolved.name, "Custom")

    def test_empty_name_falls_back_to_game_name(self):
        resolved = components._resolve_name_with_icon("", self.mock_game, None, False)
        self.assertEqual(resolved.name, "Test Game")

    def test_no_game_no_session_returns_empty_name(self):
        resolved = components._resolve_name_with_icon("", None, None, False)
        self.assertEqual(resolved.name, "")
        self.assertIsNone(resolved.badge)
        self.assertIsNone(resolved.link)

    def test_linkify_false_no_link_created(self):
        resolved = components._resolve_name_with_icon("", self.mock_game, None, False)
        self.assertIsNone(resolved.link)

    def test_linkify_true_creates_link(self):
        with patch("common.components.domain.reverse", return_value="/game/42"):
            resolved = components._resolve_name_with_icon(
                "", self.mock_game, None, True
            )
        self.assertEqual(resolved.link, "/game/42")

    def test_session_emulated_flag_preserved(self):
        emulated_session = MagicMock()
        emulated_session.game = self.mock_game
        emulated_session.emulated = True
        emulated_session.pk = 1
        resolved = components._resolve_name_with_icon(
            "", self.mock_game, emulated_session, False
        )
        self.assertTrue(resolved.emulated)

    def test_game_emulated_default_false(self):
        resolved = components._resolve_name_with_icon("", self.mock_game, None, False)
        self.assertFalse(resolved.emulated)


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

    def test_show_header_false_omits_thead(self):
        """show_header=False renders the <tbody> but no <thead> (headerless
        key-value stats tables); columns still drive the cell-count guard."""
        result = str(
            components.StyledTable(
                columns=[components.Column(""), components.Column("")],
                rows=[components.make_row("Hours", "312")],
                show_header=False,
            )
        )
        self.assertNotIn("<thead", result)
        self.assertIn("<tbody", result)
        self.assertIn("Hours", result)
        self.assertIn('th scope="row"', result)

    def test_show_header_true_by_default_renders_thead(self):
        """The default keeps the <thead>."""
        result = str(
            components.StyledTable(
                columns=[components.Column("Game"), components.Column("Started")],
                rows=[components.make_row("GameA", "2025-01-01")],
            )
        )
        self.assertIn("<thead", result)

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

    def test_first_column_class_reaches_header_and_body_cell(self):
        result = str(
            components.StyledTable(
                columns=[
                    components.Column("Name", class_="w-full max-w-0"),
                    components.Column("Actions"),
                ],
                rows=[components.make_row("Game", "Edit")],
            )
        )
        self.assertIn('class="px-2 sm:px-3 lg:px-6 py-3 w-full max-w-0"', result)
        tbody = self._tbody(result)
        self.assertIn("w-full max-w-0", tbody)

    def test_direct_table_row_keeps_columns_optional(self):
        result = str(components.TableRow(components.make_row("Game", "Edit")))
        self.assertIn('th scope="row"', result)
        self.assertNotIn("w-full max-w-0", result)

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
        media, so TimetrackerDocument() still emits its JS. StyledTable returns a
        node tree, so
        this now happens via automatic bubbling rather than manual collection."""
        cell = components.Div()["x"].with_media(components.Media(js=("test-cell.js",)))
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


class StyledTableRoundingTest(SimpleTestCase):
    """The shell owns intrinsic symmetric rounding + the general footer slot;
    the scroll wrapper and pagination nav no longer supply piecemeal radii."""

    @staticmethod
    def _plain():
        return str(
            components.StyledTable(
                columns=[components.Column("N")],
                rows=[components.make_row("x")],
            )
        )

    @staticmethod
    def _paginated():
        from django.core.paginator import Paginator

        paginator = Paginator(list(range(1, 51)), 10)
        return str(
            components.StyledTable(
                columns=[components.Column("N")],
                rows=[components.make_row("x")],
                page_obj=paginator.page(2),
                elided_page_range=list(paginator.get_elided_page_range(2)),
                request=None,
            )
        )

    def test_shell_owns_symmetric_rounding_without_pagination(self):
        """A footerless table still gets the shell's rounded clip, no piecemeal
        top/bottom radii."""
        result = self._plain()
        self.assertIn("sm:rounded-base overflow-hidden", result)
        self.assertNotIn("rounded-t-base", result)
        self.assertNotIn("rounded-b-base", result)

    def test_shell_owns_symmetric_rounding_with_pagination(self):
        """The pagination nav no longer re-supplies the bottom radius; the shell
        still owns it."""
        result = self._paginated()
        self.assertIn("sm:rounded-base overflow-hidden", result)
        self.assertNotIn("rounded-t-base", result)
        self.assertNotIn("rounded-b-base", result)

    def test_scroll_and_clip_live_on_separate_elements(self):
        """The rounded clip (overflow-hidden) and horizontal scroll (overflow-x-auto)
        cannot share an element — assert each on its own wrapper."""
        result = self._plain()
        self.assertIn("shadow-md sm:rounded-base overflow-hidden", result)
        self.assertIn("relative overflow-x-auto", result)
        # The scroll wrapper carries no rounding of its own.
        self.assertNotIn("overflow-x-auto sm:rounded", result)

    def test_footer_slot_renders_inside_shell_after_table(self):
        """An explicit footer lands as the shell's last child, after the table."""
        result = str(
            components.StyledTable(
                columns=[components.Column("N")],
                rows=[components.make_row("x")],
                footer=components.Div(id="my-footer")["total"],
            )
        )
        self.assertIn('id="my-footer"', result)
        self.assertIn("total", result)
        # Footer follows the table wrapper (rendered after </table>).
        self.assertLess(result.index("</table>"), result.index('id="my-footer"'))

    def test_footer_plus_pagination_raises(self):
        """The footer slot holds one region — an explicit footer alongside
        pagination args is a contradiction."""
        from django.core.paginator import Paginator

        paginator = Paginator(list(range(1, 51)), 10)
        with self.assertRaises(ValueError):
            components.StyledTable(
                columns=[components.Column("N")],
                rows=[components.make_row("x")],
                page_obj=paginator.page(2),
                elided_page_range=list(paginator.get_elided_page_range(2)),
                request=None,
                footer=components.Div()["x"],
            )


class PageSizeSelectTest(SimpleTestCase):
    """The rows-per-page picker: a current-value trigger over ?per_page= links."""

    @staticmethod
    def _render(current, query=None):
        from django.test import RequestFactory

        request = RequestFactory().get("/games", query or {})
        return str(components.PageSizeSelect(request, current))

    def test_one_link_per_preset(self):
        result = self._render(25)
        for size in components.PAGE_SIZE_PRESETS:
            self.assertIn(f"per_page={size}", result)

    def test_trigger_shows_current_size(self):
        self.assertIn(">100<", self._render(100))

    def test_current_preset_marked(self):
        # The active row carries aria-current="page" (DropdownLinkItem current=).
        result = self._render(50)
        marked = re.findall(r'<a[^>]*aria-current="page"[^>]*>(\d+)</a>', result)
        self.assertEqual(marked, ["50"])

    def test_page_param_dropped_and_others_preserved(self):
        # Switching size resets to page 1 (drops ?page=) but keeps ?sort=.
        result = self._render(25, {"page": "4", "sort": "-name"})
        self.assertNotIn("page=4", result)
        self.assertIn("sort=-name", result)


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


class BadgeTokenTest(SimpleTestCase):
    """Badge size scale uses typography tokens (Task 6)."""

    def test_badge_sizes_use_tokens(self):
        self.assertIn("text-type-micro", str(components.Badge("x", size="sm")))
        self.assertIn("text-type-body", str(components.Badge("x", size="base")))
        self.assertIn("text-type-heading", str(components.Badge("x", size="lg")))
        self.assertIn("font-semibold", str(components.Badge("x")))


if __name__ == "__main__":
    unittest.main()
