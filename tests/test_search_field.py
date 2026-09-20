"""The quick bar's free-text field: the control ``search`` never had."""

from django.test import SimpleTestCase

from common.components import render
from common.components.quick_filter import QUICK_FACETS
from common.components.search_field import (
    MATCH_MODE_TOKENS,
    MATCH_MODES,
    SEARCH_PLACEHOLDERS,
    SearchField,
)
from common.criteria import SEARCH_LOOKUPS


class MatchModeVocabularyTest(SimpleTestCase):
    def test_the_field_states_six_modes(self):
        self.assertEqual(len(MATCH_MODES), 6)
        self.assertEqual(
            [mode.token for mode in MATCH_MODES],
            [
                "INCLUDES",
                "EXCLUDES",
                "EQUALS",
                "NOT_EQUALS",
                "MATCHES_REGEX",
                "NOT_MATCHES_REGEX",
            ],
        )

    def test_the_presence_pair_is_absent(self):
        # "Is null" across an OR of several columns means nothing.
        self.assertNotIn("IS_NULL", MATCH_MODE_TOKENS)
        self.assertNotIn("NOT_NULL", MATCH_MODE_TOKENS)

    def test_every_mode_the_field_states_is_one_search_q_reads(self):
        self.assertEqual(
            MATCH_MODE_TOKENS,
            {modifier.value for modifier in SEARCH_LOOKUPS},
        )

    def test_every_mark_is_a_snippet_the_codegen_holds(self):
        # get_icon_node falls back silently on a typo.
        from common.components.icons_generated import ICON_NODES

        for mode in MATCH_MODES:
            self.assertIn(mode.mark, ICON_NODES, mode.token)

    def test_every_list_names_what_its_search_reads(self):
        self.assertEqual(set(SEARCH_PLACEHOLDERS), set(QUICK_FACETS))


class SearchFieldMarkupTest(SimpleTestCase):
    def test_the_root_describes_itself_to_the_serializer(self):
        html = render(SearchField())
        self.assertIn("data-filter-widget", html)
        self.assertIn('data-path="[&quot;search&quot;]"', html)
        self.assertIn('data-kind="string"', html)

    def test_the_root_states_the_mode_it_holds(self):
        # No modifier select, so the root is where the mode lives.
        self.assertIn(
            'data-modifier="EXCLUDES"', render(SearchField(modifier="EXCLUDES"))
        )

    def test_it_renders_no_modifier_select(self):
        # One would reach setupModifierToggles, whose
        # toggleStringFilterInput walks closest(".flex-col") and would then
        # disable an unrelated input in the row.
        self.assertNotIn("data-string-modifier-select", render(SearchField()))

    def test_a_mode_it_cannot_state_is_refused(self):
        # One place may degrade a filter: the gate.
        #
        # Coercing here would show one mode over a filter the server reads as
        # another, and Apply would write the shown one back.
        with self.assertRaises(ValueError):
            SearchField(modifier="IS_NULL")  # type: ignore[arg-type]

    def test_the_trigger_speaks_the_mode_it_holds(self):
        html = render(SearchField(modifier="EXCLUDES"))
        self.assertIn('aria-label="Match mode: excludes"', html)
        self.assertIn('title="Match mode: excludes"', html)

    def test_the_menu_lists_every_mode_in_words_and_marks_the_current_one(self):
        html = render(SearchField(modifier="MATCHES_REGEX"))
        for mode in MATCH_MODES:
            self.assertIn(f'data-match-mode="{mode.token}"', html)
            self.assertIn(f">{mode.words}<", html)
        # One row is marked: the mode the field holds.
        self.assertEqual(html.count('aria-checked="true"'), 1)
        marked = html.index('aria-checked="true"')
        self.assertLess(marked, html.index('data-match-mode="NOT_MATCHES_REGEX"'))

    def test_a_prefilled_value_renders(self):
        self.assertIn('value="zelda"', render(SearchField(value="zelda")))

    def test_it_names_what_the_mode_reads_on_this_list(self):
        html = render(SearchField(placeholder=SEARCH_PLACEHOLDERS["sessions"]))
        self.assertIn('placeholder="Search game, platform, device"', html)

    def test_the_box_states_an_accessible_name(self):
        # No visible label: the placeholder names it.
        html = render(SearchField(placeholder=SEARCH_PLACEHOLDERS["games"]))
        self.assertIn('aria-label="Search name, platform"', html)
        self.assertIn('aria-label="Search"', render(SearchField()))

    def test_it_carries_its_own_script(self):
        from common.components import collect_media

        self.assertIn("dist/elements/search-field.js", collect_media(SearchField()).js)

    def test_the_members_are_joined_by_the_segmented_field(self):
        from common.components.primitives import SEGMENTED_FIELD_CLASS

        html = render(SearchField())
        self.assertIn(SEGMENTED_FIELD_CLASS.split()[0], html)
        self.assertIn("[&amp;&gt;*+*]:-ms-px", html)

    def test_the_box_states_no_rounding_of_its_own(self):
        # The field decides it; one here wins only by stylesheet order.
        from common.components.search_field import _INPUT_CLASS

        self.assertNotIn("rounded", _INPUT_CLASS)
        self.assertNotIn("shadow", _INPUT_CLASS)
        self.assertIn("min-h-control", _INPUT_CLASS)
