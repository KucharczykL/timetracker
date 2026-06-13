"""Phase 1: the lazy node layer (Node/Element/Safe/Fragment/BaseComponent/Media).

These cover the new machinery directly: rendering, escaping, media bubbling.
"""

import unittest

from django.utils.safestring import mark_safe

from common.components import (
    BaseComponent,
    Element,
    Fragment,
    Media,
    Node,
    Safe,
    collect_media,
    render,
)


class ElementRenderTest(unittest.TestCase):
    def test_renders_tag_attrs_children(self):
        element = Element("div", [("class", "test")], "hello")
        self.assertEqual(render(element), '<div class="test">hello</div>')

    def test_plain_string_children_escaped(self):
        self.assertEqual(
            render(Element("span", children=["<b>"])), "<span>&lt;b&gt;</span>"
        )

    def test_safe_node_child_passes_through(self):
        self.assertEqual(
            render(Element("span", children=[Safe("<b>x</b>")])),
            "<span><b>x</b></span>",
        )

    def test_safetext_child_is_escaped(self):
        # A string child is always escaped — even a mark_safe/SafeText one.
        # Trusted markup must be a Safe node, not a safe string.
        self.assertEqual(
            render(Element("span", children=[mark_safe("<b>x</b>")])),
            "<span>&lt;b&gt;x&lt;/b&gt;</span>",
        )

    def test_node_children_render_safely(self):
        inner = Element("b", children=["x"])
        self.assertEqual(
            render(Element("span", children=[inner])), "<span><b>x</b></span>"
        )


class SafeAndFragmentTest(unittest.TestCase):
    def test_safe_passes_html_through(self):
        self.assertEqual(render(Safe("<i>raw</i>")), "<i>raw</i>")

    def test_fragment_concatenates(self):
        frag = Fragment(
            Element("span", children=["a"]), Element("span", children=["b"])
        )
        self.assertEqual(render(frag), "<span>a</span><span>b</span>")

    def test_fragment_skips_empty_children(self):
        frag = Fragment("", None, Element("span", children=["a"]))
        self.assertEqual(render(frag), "<span>a</span>")

    def test_fragment_escapes_plain_strings(self):
        self.assertEqual(render(Fragment("<x>", Safe("<y>"))), "&lt;x&gt;<y>")


class MediaTest(unittest.TestCase):
    def test_merge_dedups_preserving_order(self):
        merged = Media(js=["a.js", "b.js"]) + Media(js=["b.js", "c.js"])
        self.assertEqual(merged.js, ("a.js", "b.js", "c.js"))

    def test_external_kept_separate(self):
        merged = Media(js=["a.js"]) + Media(js_external=["umd.js"])
        self.assertEqual(merged.js, ("a.js",))
        self.assertEqual(merged.js_external, ("umd.js",))

    def test_sum_with_radd(self):
        merged = sum([Media(js=["a.js"]), Media(js=["b.js"])], Media())
        self.assertEqual(merged.js, ("a.js", "b.js"))

    def test_falsy_when_empty(self):
        self.assertFalse(Media())
        self.assertTrue(Media(js=["a.js"]))


class MediaCollectionTest(unittest.TestCase):
    def test_bubbles_through_element_children(self):
        class Widget(BaseComponent):
            media = Media(js=["widget.js"])

            def render(self) -> Node:
                return Element("div", children=["x"])

        tree = Element("section", children=[Element("div", children=[Widget()])])
        self.assertEqual(collect_media(tree).js, ("widget.js",))

    def test_bubbles_through_fragment(self):
        class Widget(BaseComponent):
            media = Media(js=["w.js"])

            def render(self) -> Node:
                return Element("div")

        self.assertEqual(collect_media(Fragment(Widget(), Element("p"))).js, ("w.js",))

    def test_component_merges_own_and_subtree_media(self):
        class Inner(BaseComponent):
            media = Media(js=["inner.js"])

            def render(self) -> Node:
                return Element("span")

        class Outer(BaseComponent):
            media = Media(js=["outer.js"])

            def render(self) -> Node:
                return Element("div", children=[Inner()])

        self.assertEqual(collect_media(Outer()).js, ("outer.js", "inner.js"))

    def test_bare_string_has_no_media(self):
        self.assertFalse(collect_media("just a string"))


class RealComponentMediaTest(unittest.TestCase):
    """Phase 3: JS-bearing components declare media that bubbles up the tree."""

    def test_search_select_declares_its_script(self):
        from common.components import SearchSelect

        self.assertEqual(
            collect_media(SearchSelect(name="games")).js, ("search_select.js",)
        )

    def test_filter_select_declares_its_script(self):
        from common.components import FilterSelect

        self.assertIn(
            "search_select.js", collect_media(FilterSelect(field_name="type")).js
        )

    def test_date_range_picker_declares_its_script(self):
        from common.components import DateRangePicker

        media = collect_media(
            DateRangePicker(label="Played", input_name_prefix="played")
        )
        self.assertEqual(media.js, ("date_range_picker.js",))

    def test_range_slider_declares_its_script(self):
        from common.components.filters import RangeSlider

        media = collect_media(
            RangeSlider(
                label="Year", input_name_prefix="year", range_min=2000, range_max=2025
            )
        )
        self.assertEqual(media.js, ("range_slider.js",))

    def test_filter_bar_collects_chrome_and_widget_media(self):
        """A FilterBar's media merges its own chrome script with the scripts that
        bubble up from the FilterSelect and RangeSlider widgets it contains —
        exactly the set the view used to thread by hand. (FilterBar wraps its DB
        aggregates in try/except, so it builds without a database.)"""
        from common.components import FilterBar

        media = collect_media(FilterBar())
        self.assertIn("filter_bar.js", media.js)
        self.assertIn("search_select.js", media.js)
        self.assertIn("range_slider.js", media.js)


class HtpyStyleSugarTest(unittest.TestCase):
    def test_getitem_sets_children(self):
        from common.components import Div, Span

        self.assertEqual(
            render(Div(class_="card")[Span()["hi"]]),
            '<div class="card"><span>hi</span></div>',
        )

    def test_getitem_multiple_children(self):
        from common.components import Div

        self.assertEqual(render(Div()["a", "b"]), "<div>a\nb</div>")

    def test_kwargs_class_underscore_becomes_class(self):
        from common.components import Div

        self.assertIn('class="x"', render(Div(class_="x")))

    def test_kwargs_inner_underscore_becomes_hyphen(self):
        from common.components import Div

        self.assertIn('hx-get="/y"', render(Div(hx_get="/y")))

    def test_kwargs_true_renders_bare_attr(self):
        from common.components import Div

        self.assertIn('hidden="hidden"', render(Div(hidden=True)))

    def test_kwargs_false_and_none_omitted(self):
        from common.components import Div

        html = render(Div(hidden=False, title=None))
        self.assertNotIn("hidden", html)
        self.assertNotIn("title", html)

    def test_getitem_preserves_media(self):
        from common.components import Div, Media, collect_media

        node = Div(class_="x").with_media(Media(js=("a.js",)))["child"]
        self.assertEqual(collect_media(node).js, ("a.js",))


if __name__ == "__main__":
    unittest.main()
