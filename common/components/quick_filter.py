"""GitHub-style quick filter bar — the ONE filter tier above every list view
(issues #197, #315).

A row of compact ghost "Label ▾" dropdown facets directly above the table.
Each facet is a :func:`ComboboxDropdown` whose dialog hosts the field's
panel-layout widget (set → panel ``FilterSelect``, date → ``DateRangePanel``,
number/string/bool → the stacked widget embedded as-is). The facets are a
form: Apply (or Enter in a facet input) serializes them and navigates
(``ts/elements/quick-filter-bar.ts``); anything richer belongs to the nested
builder, reachable from the action group's "Advanced filter…" segment.

Row anatomy: facets (collapsible), the "⋯" priority-plus overflow menu, the
Load-preset picker, and the Apply | Clear [| Advanced filter…] ButtonGroup.
Everything after the overflow host is non-collapsible row furniture — the
bar's ResizeObserver layout reserves its width and moves only facets.

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
    FILTER_MODE_MODELS,
    Dropdown,
    FilterMode,
    _QuickFilterBarElement,
    dropdown_combobox_panel_class,
    list_url_for,
)
from common.components.filters import (
    _field_meta,
    field_widget,
    parse_filter_dict,
)
from common.components.primitives import (
    A,
    ButtonGroup,
    ButtonGroupMember,
    ControlButton,
    Div,
    Form,
    Span,
)
from common.components.search_select import ComboboxDropdown, LoadPresetDropdown
from common.criteria import AttrName


class QuickFacet(NamedTuple):
    field: AttrName  # own-model leaf field == the top-level ?filter= key
    label: str = ""  # compact display override; "" = the FieldMeta-derived label
    placeholder: str = ""  # value-input hint (number/string kinds)
    placeholder2: str = ""  # second-input hint (BETWEEN)
    step: str = "1"  # number-input step, e.g. "0.01" for prices


# The leaf kinds a quick facet may have — the kinds the bar's serializer
# (ts/elements/quick-filter-bar.ts, via the shared readLeafWidget) can read back. Relations
# are excluded by construction (a cross-entity facet would serialize a relation
# sub-filter, which the predicate below rejects).
QUICK_FACET_KINDS = frozenset({"set", "number", "date", "string", "bool"})


# One facet row per list mode: a few own-model leaf fields mirroring the
# list's displayed columns, each rendered via field_widget (set → FilterSelect,
# number → NumberFilter, date → DateRangePicker, …). Contract-tested in
# tests/test_quick_filter_bar.py.
QUICK_FACETS: dict[FilterMode, list[QuickFacet]] = {
    "games": [
        QuickFacet("status"),
        QuickFacet("platform"),
        QuickFacet("name", placeholder="e.g. Zelda"),
        QuickFacet(
            "year_released", "Year", placeholder="e.g. 2020", placeholder2="e.g. 2024"
        ),
        QuickFacet(
            "playtime_hours",
            "Playtime (hrs)",
            placeholder="e.g. 1",
            placeholder2="e.g. 100",
        ),
        QuickFacet("mastered"),
        QuickFacet(
            "session_count", "Sessions", placeholder="e.g. 1", placeholder2="e.g. 50"
        ),
        QuickFacet(
            "purchase_count", "Purchases", placeholder="e.g. 1", placeholder2="e.g. 5"
        ),
        QuickFacet(
            "purchase_price_total",
            "Total price",
            placeholder="0",
            placeholder2="e.g. 100",
            step="0.01",
        ),
    ],
    "sessions": [
        QuickFacet("game"),
        QuickFacet("device"),
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
        QuickFacet("type"),
        QuickFacet("ownership_type", "Ownership"),
        QuickFacet("name", placeholder="e.g. Humble Bundle"),
        QuickFacet(
            "converted_price",
            "Price",
            placeholder="0",
            placeholder2="e.g. 100",
            step="0.01",
        ),
        QuickFacet("infinite"),
        QuickFacet("date_purchased", "Purchased"),
        QuickFacet("is_refunded", "Refunded"),
        QuickFacet("created_at", "Created"),
    ],
    "playevents": [
        QuickFacet("game"),
        QuickFacet("started"),
        QuickFacet("ended"),
        QuickFacet(
            "days_to_finish",
            "Days to finish",
            placeholder="e.g. 1",
            placeholder2="e.g. 30",
        ),
        QuickFacet("note", placeholder="e.g. Completed, Started"),
        QuickFacet("created_at", "Created"),
    ],
    "devices": [
        QuickFacet("name", placeholder="e.g. Steam Deck"),
        QuickFacet("type"),
        QuickFacet("created_at", "Created"),
    ],
    "platforms": [
        QuickFacet("name", placeholder="e.g. Switch"),
        QuickFacet("group", placeholder="e.g. Nintendo"),
        QuickFacet("created_at", "Created"),
    ],
}


def is_quick_editable(parsed: dict, facet_fields: Collection[AttrName]) -> bool:
    """Whether the quick bar may edit ``parsed`` — THE pinned predicate (#197).

    True iff ``parsed`` is empty or every top-level key is one of
    ``facet_fields`` with a dict (criterion) value. Everything else degrades
    the bar to the read-only pill: operator keys (``AND``/``OR``/``NOT``),
    relation keys (``*_filter``), ``field_comparisons``, ``search``, any
    non-facet flat leaf (e.g. ``year_released``), or a facet key whose value
    is not a dict. Unparseable / absent filter JSON parses to ``{}`` (see
    ``parse_filter_dict``) and is therefore editable.

    Round-trip guarantee: the bar's serializer emits only ``{facet: criterion
    dict}`` entries, so a filter the quick bar itself produced always passes —
    it can never lock itself out (pinned by the round-trip test).
    """
    return all(
        key in facet_fields and isinstance(value, dict) for key, value in parsed.items()
    )


_QUICK_BAR_ROW_CLASS = "flex flex-wrap items-center gap-x-4 gap-y-2 mb-3"

_QUICK_PILL_CLASS = (
    "mb-3 flex flex-wrap items-center gap-3 rounded-base border "
    "border-default-medium bg-neutral-secondary-medium/50 px-3 py-2 text-sm"
)


class QuickFilterBar(BaseComponent):
    """The quick facet bar for one list mode (#197, #315).

    Renders either the editable ``<quick-filter-bar>`` element (a form of
    dropdown facets built via ``field_widget`` — prefilled from the filter
    JSON — plus the preset picker and the action ButtonGroup) or, when
    :func:`is_quick_editable` rejects the current filter, the degraded pill —
    plain links, no custom element, so no bar JS is loaded.

    ``builder_url`` is the fully-formed nested-builder URL (already carrying
    ``?filter=`` when one is set); when non-empty the action group grows the
    "Advanced filter…" segment and the degraded pill an Edit link.
    ``preset_api_url`` enables the Load-preset picker (issue #297's dropdown,
    load-only — saving stays on the builder page).
    ``apply_url`` overrides every derived list URL (the element's apply
    target, the Clear link, the degraded pill's Clear) — the #304 override
    for synthetic e2e harnesses rendered under a stripped ROOT_URLCONF,
    where ``list_url_for``'s ``reverse()`` would crash.
    """

    def __init__(
        self,
        *,
        mode: FilterMode,
        filter_json: str = "",
        builder_url: str = "",
        existing: dict | None = None,
        apply_url: str = "",
        preset_api_url: str = "",
    ) -> None:
        self.mode = mode
        self.builder_url = builder_url
        self.apply_url = apply_url
        self.preset_api_url = preset_api_url
        # ``existing`` lets the view share one parse with other consumers
        # (both only read it); otherwise the bar parses its own copy.
        self.existing = (
            existing if existing is not None else parse_filter_dict(filter_json)
        )

    def _list_url(self) -> str:
        return self.apply_url or list_url_for(self.mode)

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

        filter_cls = filter_for_model(FILTER_MODE_MODELS[self.mode])
        row_children: list[Node] = [
            *[self._facet(filter_cls, facet) for facet in facets],
            self._overflow_dropdown(),
        ]
        # Everything from the overflow host on is non-collapsible row
        # furniture (the TS reserve calc walks the host's following
        # siblings): the preset picker, then the action group.
        if self.preset_api_url:
            row_children.append(
                LoadPresetDropdown(
                    api_url=self.preset_api_url,
                    mode=self.mode,
                    id=f"quick-{self.mode}-preset-picker",
                    ghost=True,
                )
            )
        # One segmented group so the bar-level actions read as a single unit
        # and can't be separated by row wrapping (#315). Apply is a bare
        # submit button; Clear is a plain link, not JS — radios and modifier
        # selects have no per-widget "unset", so the bar needs a one-click
        # reset.
        row_children.append(ButtonGroup(self._action_group_members()))
        return _QuickFilterBarElement(apply_url=self._list_url())[
            # A real <form> so Enter in any facet input applies; the element
            # intercepts submit and navigates.
            Form()[Div(class_=_QUICK_BAR_ROW_CLASS, data_quick_row="")[row_children]]
        ]

    def _facet(self, filter_cls: type, facet: QuickFacet) -> Node:
        """A GitHub-style compact facet (#315): a ghost "Label ▾" trigger
        whose combobox dialog hosts the panel-layout widget — the FilterSelect
        panel personality for set facets, the static-calendar DateRangePanel
        for date facets, the stacked Number/String/bool widget embedded as-is
        (their select-above-inputs layout is the natural shape inside a
        vertical dialog). No ``Label:`` span — the trigger is the label."""
        # Label defaults to the FieldMeta-derived one, so a filter-layer rename
        # propagates here; QuickFacet.label overrides only for compact wording.
        label = facet.label or _field_meta(filter_cls, facet.field)["label"]
        kind = _field_meta(filter_cls, facet.field)["kind"]
        return ComboboxDropdown(
            label=label,
            content=field_widget(
                filter_cls,
                facet.field,
                value=self.existing.get(facet.field),
                # The quick- name prefix keeps scalar-widget input names (and
                # the date picker's hidden-input DOM ids) unique and stable.
                name_prefix=f"quick-{facet.field}",
                label=label,
                placeholder=facet.placeholder,
                placeholder2=facet.placeholder2,
                step=facet.step,
                layout="panel",
            ),
            id=f"quick-{facet.field}-dropdown",
            ghost=True,
            # The calendar has an intrinsic width; list panels keep w-72.
            panel_width="w-auto" if kind == "date" else "w-72",
            # The priority-plus hook: the bar's TS moves overfull facets
            # (whole <drop-down> nodes, widget state intact) into the "⋯"
            # overflow menu as the row narrows.
            config={"data_quick_facet": ""},
        )

    def _action_group_members(self) -> list[ButtonGroupMember]:
        members: list[ButtonGroupMember] = [
            {
                "slot": "Apply",
                "color": "blue",
                "button_attributes": [],
                "type": "submit",
            },
            {"slot": "Clear", "href": self._list_url()},
        ]
        # The builder entry point rides in the group whenever the mode has a
        # builder page (devices/platforms don't — no builder_url).
        if self.builder_url:
            members.append({"slot": "Advanced filter…", "href": self.builder_url})
        return members

    def _overflow_dropdown(self) -> Node:
        """The "⋯" priority-plus overflow menu: a ghost trigger whose panel
        receives the facet dropdowns that don't fit the row
        (``ts/elements/quick-filter-bar.ts``). Server-rendered hidden; the
        bar's ResizeObserver layout unhides it while any facet is spilled.
        Facets keep working inside it — the moved nodes are the same
        elements, and the single-open coordination keeps this menu open when
        a facet dropdown inside it opens (ancestor check)."""
        trigger = ControlButton(
            color="gray",
            variant="ghost",
            aria_label="More filters",
            aria_haspopup="true",
        )["⋯"].as_element()
        panel = Div(
            role="dialog",
            aria_label="More filters",
            # The shared dialog surface + a vertical stack for the moved
            # facet triggers (their own dropdowns open position:fixed, so
            # the surface's overflow-hidden never clips them).
            class_=(
                f"{dropdown_combobox_panel_class('w-auto')} "
                "flex flex-col items-stretch gap-1"
            ),
            data_quick_overflow_items="",
        )
        return Div(class_="hidden", data_quick_overflow="")[
            Dropdown(
                trigger_element=trigger,
                target_element=panel,
                id=f"quick-{self.mode}-overflow",
            )
        ]

    def _degraded(self) -> Node:
        children: list[Node] = [Span(class_="text-body")["Advanced filter active"]]
        # Modes without a nested-builder page (devices/platforms) pass no
        # builder_url; their pill offers only Clear — an Edit link would 404.
        if self.builder_url:
            children.append(
                A(href=self.builder_url, class_="text-brand hover:underline")[
                    "Edit in builder"
                ]
            )
        children.append(
            A(href=self._list_url(), class_="text-body hover:underline")["Clear"]
        )
        return Div(class_=_QUICK_PILL_CLASS)[children]
