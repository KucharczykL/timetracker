"""Tests for the quick filter bar: the pinned degrade predicate, both
render states, and the round-trip guarantee (a filter shaped like the bar's own
serializer output must reload as editable, never flip to "advanced")."""

import json
import re
from collections.abc import Mapping
from html import unescape
from typing import ClassVar
from unittest.mock import patch
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from common.components import (
    QUICK_FACET_KINDS,
    QUICK_FACETS,
    QuickFacet,
    QuickFacetGroup,
    Span,
    is_quick_editable,
    parse_filter_dict,
    quick_facet_fields,
)
from common.components import (
    QuickFilterBar as _QuickFilterBar,
)
from common.components.custom_elements import (
    FILTER_MODE_MODELS,
    DropdownFieldset,
    FilterMode,
    list_url_for,
)
from common.components.primitives import FLOATED_LEGEND_CLASS
from common.components.quick_filter import QUICK_FACET_GROUP_KINDS
from common.criteria import AttrName, field_metadata
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.filters import (
    MODE_PARSERS,
    GameFilter,
    PurchaseFilter,
    filter_for_model,
)
from games.views.filtering import BUILDER_MODES, builder_url_for

_GAME_FACETS = {"status", "platform"}
_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def QuickFilterBar(**kwargs):
    return _QuickFilterBar(presentation=_PRESENTATION, **kwargs)


class IsQuickEditableTest(SimpleTestCase):
    """The pinned degrade predicate: editable iff empty or all top-level keys are
    facet fields with dict (criterion) values."""

    def test_empty_filter_is_editable(self):
        self.assertTrue(is_quick_editable({}, _GAME_FACETS, filter_cls=GameFilter))

    def test_single_facet_is_editable(self):
        parsed = {"status": {"value": [{"id": "f", "label": "Finished"}]}}
        self.assertTrue(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))

    def test_all_facets_are_editable(self):
        parsed = {
            "status": {"value": [{"id": "f", "label": "Finished"}]},
            "platform": {"value": [{"id": "1", "label": "PC"}]},
        }
        self.assertTrue(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))

    def test_presence_modifier_facet_is_editable(self):
        self.assertTrue(
            is_quick_editable(
                {"platform": {"modifier": "IS_NULL"}},
                _GAME_FACETS,
                filter_cls=GameFilter,
            )
        )

    def test_operator_keys_degrade(self):
        criterion = {"status": {"value": ["f"], "modifier": "INCLUDES"}}
        for operator in ("AND", "OR", "NOT"):
            with self.subTest(operator=operator):
                self.assertFalse(
                    is_quick_editable(
                        {operator: [criterion]}, _GAME_FACETS, filter_cls=GameFilter
                    )
                )

    def test_relation_key_degrades(self):
        parsed = {"session_filter": {"device": {"value": [{"id": "1", "label": "PC"}]}}}
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))

    def test_field_comparisons_degrade(self):
        parsed = {"field_comparisons": [{"left": "created_at", "right": "updated_at"}]}
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))

    def test_a_search_in_one_of_the_six_modes_is_editable(self):
        # Six modes the bar can edit without rewriting them.
        for modifier in (
            "INCLUDES",
            "EXCLUDES",
            "EQUALS",
            "NOT_EQUALS",
            "MATCHES_REGEX",
            "NOT_MATCHES_REGEX",
        ):
            with self.subTest(modifier=modifier):
                self.assertTrue(
                    is_quick_editable(
                        {"search": {"value": "mario", "modifier": modifier}},
                        _GAME_FACETS,
                        filter_cls=GameFilter,
                    )
                )

    def test_a_search_the_field_cannot_state_degrades(self):
        # The bar shows no control for a filter it would rewrite.
        for modifier in ("IS_NULL", "NOT_NULL", "GREATER_THAN"):
            with self.subTest(modifier=modifier):
                self.assertFalse(
                    is_quick_editable(
                        {"search": {"value": "mario", "modifier": modifier}},
                        _GAME_FACETS,
                        filter_cls=GameFilter,
                    )
                )

    def test_a_search_that_is_not_a_criterion_degrades(self):
        self.assertFalse(
            is_quick_editable({"search": "mario"}, _GAME_FACETS, filter_cls=GameFilter)
        )

    def test_a_search_whose_value_is_not_text_degrades(self):
        # The value goes into a text box.
        #
        # A dict, list or number reaches it as a repr, and Apply writes that
        # back as the filter.
        for value in ({"id": "mario"}, ["mario"], 7, True):
            with self.subTest(value=value):
                self.assertFalse(
                    is_quick_editable(
                        {"search": {"value": value, "modifier": "INCLUDES"}},
                        _GAME_FACETS,
                        filter_cls=GameFilter,
                    )
                )

    def test_a_search_that_names_no_mode_is_editable_as_exact(self):
        # A stored exact search carries no modifier.
        #
        # to_json drops a default. Reading a fresh field's mode there would show
        # *includes* over a filter the server applies as *is*, and Apply would
        # widen it.
        parsed = {"search": {"value": "mario"}}
        self.assertTrue(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))
        html = str(QuickFilterBar(mode="games", filter_json=json.dumps(parsed)))
        self.assertIn('data-modifier="EQUALS"', html)
        self.assertIn('aria-label="Match mode: is"', html)

    def test_a_bar_with_no_search_opens_on_includes(self):
        # A fresh field's mode is not the criterion's.
        #
        # It is the one people reach for; the criterion's default is read only
        # where a search is already stated.
        html = str(QuickFilterBar(mode="games", filter_json=""))
        self.assertIn('data-modifier="INCLUDES"', html)
        self.assertIn('aria-label="Match mode: includes"', html)

    def test_a_string_facet_in_a_mode_its_widget_lacks_degrades(self):
        # No string column here can be NULL.
        #
        # So no string widget offers the presence pair: "is null" matches no
        # row, and "is empty" tests the empty string. A stored one would render
        # as *is* and Apply would write that back.
        for modifier in ("IS_NULL", "NOT_NULL"):
            with self.subTest(modifier=modifier):
                self.assertFalse(
                    is_quick_editable(
                        {"name": {"modifier": modifier}},
                        {"name"},
                        filter_cls=GameFilter,
                    )
                )
        self.assertTrue(
            is_quick_editable(
                {"name": {"value": "", "modifier": "EQUALS"}},
                {"name"},
                filter_cls=GameFilter,
            )
        )

    def test_a_count_facet_in_a_presence_mode_degrades(self):
        # A count answers 0 over no rows.
        #
        # So its widget offers no presence pair, and a stored one would render
        # as *is* for Apply to write back.
        self.assertFalse(
            is_quick_editable(
                {"session_count": {"modifier": "IS_NULL"}},
                {"session_count"},
                filter_cls=GameFilter,
            )
        )

    def test_an_averaged_facet_in_a_presence_mode_is_editable(self):
        # Avg answers NULL over no rows, so "is null" is a mode it states.
        self.assertTrue(
            is_quick_editable(
                {"session_average": {"modifier": "IS_NULL"}},
                {"session_average"},
                filter_cls=GameFilter,
            )
        )

    def test_a_date_facet_keeps_whatever_modifier_it_holds(self):
        # A date widget returns its modifier untouched.
        #
        # It rides in a hidden input, so the widget rewrites nothing.
        self.assertTrue(
            is_quick_editable(
                {"created_at": {"modifier": "IS_NULL"}},
                {"created_at"},
                filter_cls=GameFilter,
            )
        )

    def test_a_set_facet_keeps_the_modifiers_its_widget_pins(self):
        # A set widget renders more than its metadata names.
        #
        # It pins (Any)/(None) and, for a many-to-many, (All)/(Only), so a check
        # against the metadata would degrade a filter the bar can hold.
        self.assertTrue(
            is_quick_editable(
                {"games": {"value": ["1"], "modifier": "INCLUDES_ALL"}},
                {"games"},
                filter_cls=PurchaseFilter,
            )
        )

    def test_a_search_beside_a_facet_is_editable(self):
        self.assertTrue(
            is_quick_editable(
                {
                    "search": {"value": "mario", "modifier": "INCLUDES"},
                    "status": {"value": ["f"], "modifier": "INCLUDES"},
                },
                _GAME_FACETS,
                filter_cls=GameFilter,
            )
        )

    def test_non_facet_flat_leaf_degrades(self):
        self.assertFalse(
            is_quick_editable(
                {"year_released": {"value": 2020, "modifier": "EQUALS"}},
                _GAME_FACETS,
                filter_cls=GameFilter,
            )
        )

    def test_facet_mixed_with_operator_degrades(self):
        parsed = {
            "status": {"value": ["f"], "modifier": "INCLUDES"},
            "AND": [{"platform": {"value": ["1"]}}],
        }
        self.assertFalse(is_quick_editable(parsed, _GAME_FACETS, filter_cls=GameFilter))

    def test_facet_with_non_dict_value_degrades(self):
        self.assertFalse(
            is_quick_editable({"status": "f"}, _GAME_FACETS, filter_cls=GameFilter)
        )
        self.assertFalse(
            is_quick_editable({"status": ["f"]}, _GAME_FACETS, filter_cls=GameFilter)
        )


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
        # Apply + Clear are one segmented ButtonGroup — a single visual unit
        # that row wrapping can't separate. Order is asserted inside the
        # group's slice, anchored on its own name: the date facets' fields
        # are labelled groups too, and they come earlier.
        group_html = html[html.index('aria-label="Filter actions"') :]
        self.assertIn('aria-label="Clear filter"', group_html)
        self.assertIn(f'href="{list_url_for(mode)}"', group_html)
        self.assertLess(
            group_html.index(">Apply<"), group_html.index('aria-label="Clear filter"')
        )
        derived_labels = {
            meta["name"]: meta["label"]
            for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
        }
        for facet in QUICK_FACETS[mode]:
            expected_label = (
                facet.label
                if isinstance(facet, QuickFacetGroup)
                else facet.label or derived_labels[facet.field]
            )
            # Every facet is a "Label ▾" dropdown trigger opening a combobox
            # dialog — no inline "Label:" span anywhere.
            self.assertNotIn(f"{expected_label}:", html)
            self.assertIn(f">{expected_label}<svg", html)
            self.assertIn(f'id="quick-{facet.key}-dropdown"', html)
            self.assertIn(f'aria-label="{expected_label}"', html)
            # Attribute values are escaped, so the data-path JSON renders with
            # &quot; entities. Present for every facet — the serializer finds
            # dropdown-facet widgets inside the (hidden) dialog panel too.
            for field in facet.fields:
                self.assertIn(f'data-path="[&quot;{field}&quot;]"', html)

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
                    "value": [{"id": "completed", "label": "Completed"}],
                    "modifier": "INCLUDES",
                }
            }
        )
        html = str(
            QuickFilterBar(mode="games", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertIn("Completed", html)

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
                # The serializer emits the field, so this covers it.
                "search": {"value": "mario", "modifier": "EXCLUDES"},
            }
        )
        html = str(
            QuickFilterBar(mode="games", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)

    def test_inclusive_number_modifiers_round_trip(self):
        """`is at least` survives the bar."""
        filter_json = json.dumps(
            {"duration_hours": {"value": 8, "modifier": "GREATER_THAN_OR_EQUAL"}}
        )
        html = str(
            QuickFilterBar(mode="sessions", filter_json=filter_json, builder_url="/x")
        )
        self.assertNotIn("Advanced filter active", html)
        self.assertIn('value="GREATER_THAN_OR_EQUAL" selected', html)
        self.assertIn(">is at least<", html)
        self.assertIn(">is at most<", html)

    def test_scalar_round_trip_serializer_shapes_are_editable(self):
        """The scalar facets' serializer output (number criterion from
        readNumberWidget, date criterion from readDateWidget) must render an
        editable sessions bar with the values prefilled."""
        filter_json = json.dumps(
            {
                "duration_hours": {"value": 2, "modifier": "GREATER_THAN"},
                "day": {
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
                "excluded_from_unfinished": {"value": False, "modifier": "EQUALS"},
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
        # The element hosts the Presets panel; with no row there is no form.
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("data-quick-row", html)
        self.assertNotIn("<form", html)
        self.assertIn("Advanced filter active", html)
        group_html = html[html.index('role="group"') :]
        self.assertIn('aria-label="Advanced filter"', group_html)
        self.assertIn(f'href="{builder_url.replace("&", "&amp;")}"', group_html)
        self.assertIn('aria-label="Clear filter"', group_html)
        self.assertIn(f'href="{list_url_for("games")}"', group_html)
        self.assertNotIn(">Apply<", group_html)

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


class RunFacetsTest(TestCase):
    """The two facets that ask about a session's run."""

    def test_the_sessions_row_carries_both_triggers(self):
        html = str(QuickFilterBar(mode="sessions", builder_url="/x"))
        self.assertIn(">Playthrough<", html)
        self.assertIn(">Outside dates<", html)

    def test_the_runs_kind_alone_stays_editable(self):
        filter_json = json.dumps(
            {
                "playthrough_kind": {
                    "value": [{"id": "imported_history", "label": "Imported history"}],
                    "excludes": [],
                    "modifier": "INCLUDES",
                }
            }
        )
        html = str(
            QuickFilterBar(mode="sessions", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)

    def test_the_dates_question_alone_stays_editable(self):
        filter_json = json.dumps(
            {"outside_playthrough_dates": {"value": True, "modifier": "EQUALS"}}
        )
        html = str(
            QuickFilterBar(mode="sessions", filter_json=filter_json, builder_url="/x")
        )
        self.assertIn("<quick-filter-bar", html)
        self.assertNotIn("Advanced filter active", html)


_DROP_DOWN = re.compile(r"<drop-down\b[^>]*>")
_TRIGGER_ID = re.compile(r'id="quick-(\w+)-dropdownLink"')


def _applied_facets(html: str) -> list[str]:
    """Fields stamped applied, in row order."""
    applied = []
    for match in _DROP_DOWN.finditer(html):
        if "data-quick-facet-applied" not in match.group(0):
            continue
        trigger = _TRIGGER_ID.search(html, match.end())
        assert trigger is not None
        applied.append(trigger.group(1))
    return applied


def _trigger(html: str, field: str) -> str:
    start = html.index(f'id="quick-{field}-dropdownLink"')
    return html[html.rindex("<button", 0, start) : html.index("</button>", start)]


class AppliedFacetMarkTest(TestCase):
    """Applied facets are stamped and marked."""

    def test_a_dropdown_not_applied_renders_as_before(self):
        from common.components.search_select import ComboboxDropdown

        arguments = {"label": "Device", "content": Span()["x"], "id": "d"}
        self.assertEqual(
            str(ComboboxDropdown(**arguments)),
            str(ComboboxDropdown(**arguments, applied=False)),
        )

    def test_an_applied_dropdown_puts_a_dot_in_its_corner(self):
        from common.components.search_select import ComboboxDropdown

        html = str(
            ComboboxDropdown(
                label="Device", content=Span()["x"], id="d", ghost=True, applied=True
            )
        )
        button = html[html.index("<button") : html.index("</button>")]
        button_tag = button[: button.index(">")]
        self.assertIn("relative", button_tag)
        self.assertNotIn("text-fg-brand", button)
        self.assertIn(">Device<span", button)
        dot = re.search(r'<span class="([^"]*bg-brand[^"]*)"', button)
        assert dot is not None
        self.assertIn("absolute", dot.group(1))
        self.assertIn('<span class="sr-only"> (applied)</span>', button)
        # The panel's name stays the bare label.
        self.assertIn('aria-label="Device"', html)

    def test_only_the_stated_keys_are_applied(self):
        html = str(
            QuickFilterBar(
                mode="sessions",
                filter_json=json.dumps(
                    {
                        "device": {"modifier": "IS_NULL"},
                        "day": {"value": "2026-01-01", "modifier": "EQUALS"},
                    }
                ),
            )
        )
        self.assertEqual(sorted(_applied_facets(html)), ["day", "device"])
        self.assertIn("sr-only", _trigger(html, "device"))
        self.assertNotIn("sr-only", _trigger(html, "game"))

    def test_every_kind_is_marked(self):
        cases = {
            "games": {"status": {"value": [{"id": "f", "label": "Finished"}]}},
            "sessions": {"duration_hours": {"value": 2, "modifier": "GREATER_THAN"}},
            "purchases": {
                "date_purchased": {"value": "2026-01-01", "modifier": "EQUALS"}
            },
            "devices": {"name": {"value": "Deck", "modifier": "INCLUDES"}},
            "playthroughs": {"note": {"value": "", "modifier": "EQUALS"}},
        }
        cases_bool = {"purchases": {"infinite": {"value": True}}}
        for mode, stated in [*cases.items(), *cases_bool.items()]:
            with self.subTest(mode=mode, field=next(iter(stated))):
                html = str(QuickFilterBar(mode=mode, filter_json=json.dumps(stated)))
                self.assertEqual(_applied_facets(html), list(stated))

    def test_the_overflow_carries_its_label_and_a_hidden_mark(self):
        html = str(QuickFilterBar(mode="sessions"))
        host = html[html.index("data-quick-overflow") :]
        trigger = re.search(r"<button[^>]*data-quick-overflow-trigger[^>]*>", host)
        assert trigger is not None
        self.assertIn('aria-label="More filters"', trigger.group(0))
        mark = re.search(r"<span[^>]*data-quick-overflow-mark[^>]*>", host)
        assert mark is not None
        self.assertIn("invisible", mark.group(0))
        self.assertIn("bg-brand", mark.group(0))


class FacetOrderTest(SimpleTestCase):
    """Each mode's facets in declared order."""

    ORDERS: ClassVar[Mapping[FilterMode, list[AttrName]]] = {
        "sessions": [
            "game",
            "day",
            "playthrough_kind",
            "outside_playthrough_dates",
            "device",
            "timing_mode",
            "duration_hours",
        ],
        "purchases": [
            "type",
            "date_purchased",
            "is_refunded",
            "ownership_type",
            "converted_price",
            "infinite",
            "created_at",
            "name",
        ],
        "historical_playtime": [
            "game",
            "when",
            "provenance",
            "device",
            "duration_hours",
            "created_at",
        ],
        "games": [
            "status",
            "platform",
            "access",
            "format",
            "kind",
            "year_released",
            "playtime_hours",
            "mastered",
            "session_count",
            "purchase_count",
            "purchase_price_total",
            "name",
            "visibility",
        ],
        "playthroughs": [
            "activity",
            "game",
            "started",
            "completed",
            "days_to_finish",
            "created_at",
            "note",
        ],
        "devices": ["name", "type", "is_owned", "access_end_way", "created_at"],
        "platforms": ["name", "group", "created_at"],
        "entries": [
            "access",
            "format",
            "is_ended",
            "access_end_way",
            "platform",
            "acquired",
            "game",
        ],
    }

    def test_every_mode_states_its_order(self):
        self.assertEqual(set(self.ORDERS), set(QUICK_FACETS))
        for mode, order in self.ORDERS.items():
            with self.subTest(mode=mode):
                self.assertEqual([facet.key for facet in QUICK_FACETS[mode]], order)


class VisibilityFacetTest(SimpleTestCase):
    """One dropdown states both flags."""

    def _dropdown(self, filter_json: str = "") -> str:
        html = str(QuickFilterBar(mode="games", filter_json=filter_json))
        start = html.index('id="quick-visibility-dropdown"')
        return html[
            html.rindex("<drop-down", 0, start) : html.index("</drop-down>", start)
        ]

    def test_each_member_is_a_named_fieldset(self):
        dropdown = self._dropdown()

        for label, field in (
            ("Unfinished lists", "excluded_from_unfinished"),
            ("Dropped figures", "excluded_from_dropped"),
        ):
            fieldset = dropdown.split(f">{label}</legend>", 1)[1].split(
                "</fieldset>", 1
            )[0]
            self.assertIn(f'data-path="[&quot;{field}&quot;]"', fieldset)

    def test_each_legend_floats_inside_its_fieldset(self):
        legends = re.findall(r"<legend[^>]*>", self._dropdown())

        self.assertEqual(len(legends), 2)
        for legend in legends:
            self.assertIn(FLOATED_LEGEND_CLASS, legend)

    def test_one_stated_member_marks_the_group_applied(self):
        stated = json.dumps({"excluded_from_dropped": {"value": True}})

        self.assertIn("data-quick-facet-applied", self._dropdown(stated))
        self.assertNotIn("data-quick-facet-applied", self._dropdown())

    def test_each_member_checks_its_stated_radio(self):
        stated = json.dumps(
            {
                "excluded_from_unfinished": {"value": False},
                "excluded_from_dropped": {"value": True},
            }
        )
        dropdown = self._dropdown(stated)

        for field, value in (
            ("excluded_from_unfinished", "false"),
            ("excluded_from_dropped", "true"),
        ):
            radios = re.findall(rf'<input[^>]*name="quick-{field}"[^>]*>', dropdown)
            checked = [tag for tag in radios if "checked" in tag]
            self.assertEqual(len(checked), 1, field)
            self.assertIn(f'value="{value}"', checked[0])

    def test_both_members_stated_stay_editable(self):
        parsed = {
            "excluded_from_unfinished": {"value": True},
            "excluded_from_dropped": {"value": False},
        }

        self.assertTrue(
            is_quick_editable(
                parsed, quick_facet_fields("games"), filter_cls=GameFilter
            )
        )


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

    def test_a_renamed_key_still_reads_as_its_facet(self):
        """The bar parses a legacy key as the query does."""
        for mode, model in FILTER_MODE_MODELS.items():
            filter_class = filter_for_model(model)
            facets = quick_facet_fields(mode)
            for old, new in filter_class.renamed_fields.items():
                if new not in facets:
                    continue
                with self.subTest(mode=mode, key=old):
                    parsed = parse_filter_dict(
                        json.dumps({old: {"value": "2020", "modifier": "EQUALS"}}),
                        filter_class,
                    )
                    self.assertEqual(set(parsed), {new})
                    self.assertTrue(
                        is_quick_editable(parsed, facets, filter_cls=filter_class)
                    )

    def test_every_facet_is_an_own_model_leaf_field(self):
        for mode in QUICK_FACETS:
            metadata = {
                meta["name"]: meta
                for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
            }
            for field in quick_facet_fields(mode):
                with self.subTest(mode=mode, facet=field):
                    self.assertIn(field, metadata)
                    self.assertIn(metadata[field]["kind"], QUICK_FACET_KINDS)

    def test_every_group_member_is_a_stacking_kind(self):
        for mode, facets in QUICK_FACETS.items():
            metadata = {
                meta["name"]: meta
                for meta in field_metadata(filter_for_model(FILTER_MODE_MODELS[mode]))
            }
            for group in facets:
                if not isinstance(group, QuickFacetGroup):
                    continue
                for field in group.fields:
                    with self.subTest(mode=mode, group=group.key, field=field):
                        self.assertIn(metadata[field]["kind"], QUICK_FACET_GROUP_KINDS)

    def test_facet_keys_are_unique_and_groups_hold_several(self):
        for mode, facets in QUICK_FACETS.items():
            with self.subTest(mode=mode):
                keys = [facet.key for facet in facets]
                self.assertEqual(len(keys), len(set(keys)))
                fields = [field for facet in facets for field in facet.fields]
                self.assertEqual(len(fields), len(set(fields)))
                groups = [
                    facet for facet in facets if isinstance(facet, QuickFacetGroup)
                ]
                for group in groups:
                    self.assertGreaterEqual(len(group.members), 2, group.key)

    def test_an_unlabelled_dropdown_fieldset_is_refused(self):
        with self.assertRaisesRegex(ValueError, "needs a label"):
            DropdownFieldset("")

    def test_a_group_holding_a_set_field_is_refused(self):
        group = QuickFacetGroup("broken", "Broken", (QuickFacet("status"),))
        with (
            patch.dict(QUICK_FACETS, {"games": [group]}),
            self.assertRaisesRegex(ValueError, "'status', a set field"),
        ):
            str(QuickFilterBar(mode="games"))


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
        group_html = html[html.index('aria-label="Filter actions"') :]
        self.assertIn('aria-label="Advanced filter"', group_html)
        self.assertIn('title="Advanced filter"', group_html)
        self.assertIn('href="/builder-url"', group_html)

    def test_no_builder_url_no_advanced_segment(self):
        html = str(QuickFilterBar(mode="devices", filter_json=""))
        self.assertNotIn('aria-label="Advanced filter"', html)

    def test_the_group_is_pushed_to_the_rows_end(self):
        html = str(QuickFilterBar(mode="games", filter_json=""))
        group_tag = html[
            html.rindex("<", 0, html.index('aria-label="Filter actions"')) :
        ]
        self.assertIn("ml-auto", group_tag[: group_tag.index(">")])
        # Apply leads the group and the group follows the overflow host.
        self.assertLess(html.index("data-quick-overflow"), html.index("Filter actions"))
        self.assertIn(">Apply<", group_tag)


class PresetsSegmentTest(TestCase):
    """Presets rides in the acts group when a preset API URL is given."""

    def test_preset_api_url_renders_the_presets_segment_in_the_group(self):
        html = str(
            QuickFilterBar(mode="games", filter_json="", preset_api_url="/api/presets/")
        )
        group_html = html[html.index('aria-label="Filter actions"') :]
        self.assertIn('id="quick-games-presets"', group_html)
        self.assertIn("<preset-panel", group_html)
        self.assertIn('search-url="/api/presets/?mode=games"', group_html)

    def test_the_degraded_pill_offers_presets_and_states_its_filter(self):
        filter_json = json.dumps({"AND": [{"status": {"value": ["f"]}}]})
        html = str(
            QuickFilterBar(
                mode="games", filter_json=filter_json, preset_api_url="/api/presets/"
            )
        )
        self.assertIn("<preset-panel", html)
        stated = re.search(r'<quick-filter-bar[^>]* filter="([^"]*)"', html)
        assert stated is not None
        self.assertEqual(json.loads(unescape(stated.group(1))), json.loads(filter_json))

    def test_the_editable_bar_states_no_filter_prop(self):
        html = str(QuickFilterBar(mode="games", filter_json=""))
        self.assertIn(' filter=""', html)

    def test_no_preset_api_url_no_presets(self):
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
