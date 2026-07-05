"""GitHub-style quick filter bar above list views (issue #197).

A row of compact facet widgets (``status: [▾] platform: [▾] …``) that reads
and writes the same ``?filter=`` JSON as the flat FilterBar it coexists with
(rendered above it) — one source of truth, one backend. The facets are a form:
Apply (or Enter) serializes them and navigates
(``ts/elements/quick-filter-bar.ts``), so the bar covers the common case
without expanding the flat bar; anything richer belongs to the flat bar or
the nested builder.

The bar is editable only when :func:`is_quick_editable` accepts the active
filter; otherwise it degrades to a read-only "Advanced filter active" pill
with Edit-in-builder / Clear links. The strictness is deliberate: the bar
never renders controls that would silently drop part of the filter on the
next apply, and Clear always discards the *whole* filter.
"""

from collections.abc import Collection
from typing import NamedTuple

from common.components.core import BaseComponent, Node
from common.components.custom_elements import (
    FilterMode,
    _QuickFilterBarElement,
    list_url_for,
)
from common.components.filters import _FILTER_LABEL_CLASS, _filter_parse, field_widget
from common.components.primitives import A, ControlButton, Div, Form, Span
from common.criteria import AttrName


class QuickFacet(NamedTuple):
    field: AttrName  # own-model leaf field == the top-level ?filter= key
    label: str  # display label, e.g. "Status"
    placeholder: str = ""  # value-input hint (number/string kinds)
    placeholder2: str = ""  # second-input hint (BETWEEN)


# The leaf kinds a quick facet may have — the kinds the bar's serializer
# (ts/elements/quick-filter-bar.ts readFacetWidget) can read back. Relations
# are excluded by construction (a cross-entity facet would serialize a relation
# sub-filter, which the predicate below rejects).
QUICK_FACET_KINDS = frozenset({"set", "number", "date", "string", "bool"})


# One facet row per list mode: a few own-model leaf fields mirroring the
# list's displayed columns, each rendered via field_widget (set → FilterSelect,
# number → NumberFilter, date → DateRangePicker, …). Contract-tested in
# tests/test_quick_filter_bar.py.
QUICK_FACETS: dict[FilterMode, list[QuickFacet]] = {
    "games": [
        QuickFacet("status", "Status"),
        QuickFacet("platform", "Platform"),
    ],
    "sessions": [
        QuickFacet("game", "Game"),
        QuickFacet("device", "Device"),
        QuickFacet("timestamp_start", "Started"),
        QuickFacet("timestamp_end", "Ended"),
        QuickFacet(
            "duration_total_hours",
            "Duration (hrs)",
            placeholder="e.g. 1",
            placeholder2="e.g. 10",
        ),
    ],
    "purchases": [
        QuickFacet("type", "Type"),
        QuickFacet("ownership_type", "Ownership"),
    ],
    "playevents": [
        QuickFacet("game", "Game"),
    ],
}


# Plural list mode -> root model key for filter_for_model(); mirrors the
# builder-model args the list views pass to games:filter_builder.
_MODE_MODELS: dict[FilterMode, str] = {
    "games": "game",
    "sessions": "session",
    "purchases": "purchase",
    "playevents": "playevent",
}


def is_quick_editable(parsed: dict, facet_fields: Collection[AttrName]) -> bool:
    """Whether the quick bar may edit ``parsed`` — THE pinned predicate (#197).

    True iff ``parsed`` is empty or every top-level key is one of
    ``facet_fields`` with a dict (criterion) value. Everything else degrades
    the bar to the read-only pill: operator keys (``AND``/``OR``/``NOT``),
    relation keys (``*_filter``), ``field_comparisons``, ``search``, any
    non-facet flat leaf (e.g. ``year_released``), or a facet key whose value
    is not a dict. Unparseable / absent filter JSON parses to ``{}`` (see
    ``_filter_parse``) and is therefore editable.

    Round-trip guarantee: the bar's serializer emits only ``{facet: criterion
    dict}`` entries, so a filter the quick bar itself produced always passes —
    it can never lock itself out (pinned by the round-trip test).
    """
    return all(
        key in facet_fields and isinstance(value, dict) for key, value in parsed.items()
    )


_QUICK_BAR_ROW_CLASS = "flex flex-wrap items-center gap-x-4 gap-y-2 mb-3"

_QUICK_FACET_CLASS = "flex items-center gap-1.5"

# min-w so a facet is never cramped but a wider widget (the date range's
# segmented field) can grow to its natural size.
_QUICK_WIDGET_WRAP_CLASS = "min-w-56"

_QUICK_PILL_CLASS = (
    "mb-3 flex flex-wrap items-center gap-3 rounded-base border "
    "border-default-medium bg-neutral-secondary-medium/50 px-3 py-2 text-sm"
)


class QuickFilterBar(BaseComponent):
    """The quick facet bar for one list mode (#197).

    Renders either the editable ``<quick-filter-bar>`` element (a form of
    facet widgets built via ``field_widget`` — prefilled from the filter
    JSON — plus an Apply submit button) or, when :func:`is_quick_editable`
    rejects the current filter, the degraded pill — plain links, no custom
    element, so no bar JS is loaded.
    ``builder_url`` is the fully-formed nested-builder URL (already carrying
    ``?filter=`` when one is set), the same URL the view hands
    ``AdvancedFilterLink``.
    """

    def __init__(
        self,
        *,
        mode: FilterMode,
        filter_json: str = "",
        builder_url: str = "",
    ) -> None:
        self.mode = mode
        self.builder_url = builder_url
        self.existing = _filter_parse(filter_json)

    def render(self) -> Node:
        facets = QUICK_FACETS[self.mode]
        if not is_quick_editable(self.existing, {facet.field for facet in facets}):
            return self._degraded()
        return self._editable(facets)

    def _editable(self, facets: list[QuickFacet]) -> Node:
        # Function-local: games.filters imports common.criteria (and the app
        # layer generally); keep the component library import-light, matching
        # filters.py's own convention.
        from games.filters import filter_for_model

        filter_cls = filter_for_model(_MODE_MODELS[self.mode])
        return _QuickFilterBarElement(apply_url=list_url_for(self.mode))[
            # A real <form> so Enter in any facet input applies, mirroring the
            # flat bar; the element intercepts submit and navigates.
            Form()[
                Div(class_=_QUICK_BAR_ROW_CLASS)[
                    *[self._facet(filter_cls, facet) for facet in facets],
                    ControlButton(color="blue", type="submit")["Apply"],
                ]
            ]
        ]

    def _facet(self, filter_cls: type, facet: QuickFacet) -> Node:
        # The quick- name prefix keeps scalar-widget input names (and the date
        # picker's hidden-input DOM ids) distinct from the flat bar's widgets
        # for the same fields on the same page.
        widget = field_widget(
            filter_cls,
            facet.field,
            value=self.existing.get(facet.field),
            name_prefix=f"quick-{facet.field}",
            label=facet.label,
            placeholder=facet.placeholder,
            placeholder2=facet.placeholder2,
        )
        return Div(class_=_QUICK_FACET_CLASS)[
            Span(class_=_FILTER_LABEL_CLASS)[f"{facet.label}:"],
            Div(class_=_QUICK_WIDGET_WRAP_CLASS)[widget],
        ]

    def _degraded(self) -> Node:
        return Div(class_=_QUICK_PILL_CLASS)[
            Span(class_="text-body")["Advanced filter active"],
            A(href=self.builder_url, class_="text-brand hover:underline")[
                "Edit in builder"
            ],
            A(href=list_url_for(self.mode), class_="text-body hover:underline")[
                "Clear"
            ],
        ]
