"""Guard the server↔client filter-widget contract at test time.

Every filter-bar widget advertises a ``data-path`` (its filter-JSON key chain,
as a JSON array) and a ``data-kind`` (string/number/date/bool/set). This module
renders each entity's filter bar, extracts those attributes from the real HTML,
and asserts that every path resolves through the Python filter dataclass tree
(``resolve_path_kind``) to a criterion whose kind matches the widget. A widget
pointing at a non-existent path or the wrong kind fails here — the rendered-widget
analogue of ``gen_icons --check`` (issue #123 Phase 2, slice 2e).
"""

import json
from html.parser import HTMLParser
from typing import NamedTuple

import pytest

from common.components.filters import (
    DeviceFilterBar,
    FilterBar,
    PlatformFilterBar,
    PlayEventFilterBar,
    PurchaseFilterBar,
    SessionFilterBar,
)
from common.criteria import (
    _CRITERION_KINDS,
    _CRITERION_TYPES,
    BoolCriterion,
    OperatorFilter,
    _Criterion,
    _criterion_class_for,
    _filter_class_for,
    criterion_kind,
    resolve_path_kind,
)
from games.filters import (
    DeviceFilter,
    GameFilter,
    PlatformFilter,
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
)


class WidgetDescriptor(NamedTuple):
    """A filter widget's self-described contract, as read off the rendered HTML."""

    path: list[str]
    kind: str
    relation_child: dict | None


class _FilterWidgetCollector(HTMLParser):
    """Collect every ``[data-filter-widget]`` start tag's contract attributes.

    Pairs ``data-path``/``data-kind``/``data-relation-child`` within a single
    element by reading the start tag's own attribute list — no regex pairing
    across the document.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.widgets: list[WidgetDescriptor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "data-filter-widget" not in attributes:
            return
        raw_path = attributes.get("data-path")
        kind = attributes.get("data-kind")
        assert raw_path is not None, f"<{tag}> has data-filter-widget but no data-path"
        assert kind is not None, f"<{tag}> has data-filter-widget but no data-kind"
        raw_child = attributes.get("data-relation-child")
        self.widgets.append(
            WidgetDescriptor(
                json.loads(raw_path),
                kind,
                json.loads(raw_child) if raw_child else None,
            )
        )


def _collect_widgets(html: str) -> list[WidgetDescriptor]:
    collector = _FilterWidgetCollector()
    collector.feed(html)
    return collector.widgets


# Each filter bar paired with the dataclass its widget paths resolve against and
# the exact number of widgets it is expected to render.
class _BarCase(NamedTuple):
    name: str
    bar_factory: type
    filter_cls: type[OperatorFilter]
    widget_count: int


# ``widget_count`` is the intended widget inventory for each bar. A forgotten
# ``path=`` on a FilterSelect/DateRangePicker silently drops that widget (it
# stops emitting ``data-filter-widget``), which the per-path checks below cannot
# catch — only an exact count does. Update these numbers deliberately whenever a
# filter field is added or removed.
# Each count includes the field-comparison widget (#167), present in every bar
# whose model has >=2 columns in one comparison group. Unlike the other widgets
# its ``["field_comparisons"]`` path does NOT resolve through resolve_path_kind
# (it's a list field, serialized by filter-bar.ts's special-case branch), so the
# resolution check below skips kind=="field-comparison".
_BAR_CASES = [
    _BarCase("game", FilterBar, GameFilter, 24),
    _BarCase("session", SessionFilterBar, SessionFilter, 10),
    _BarCase("purchase", PurchaseFilterBar, PurchaseFilter, 15),
    _BarCase("device", DeviceFilterBar, DeviceFilter, 2),
    _BarCase("platform", PlatformFilterBar, PlatformFilter, 3),
    _BarCase("playevent", PlayEventFilterBar, PlayEventFilter, 5),
]


def _resolve_subfilter(
    filter_cls: type[OperatorFilter], path: list[str]
) -> type[OperatorFilter]:
    """Walk a path of sub-filter segments, returning the sub-filter class it ends at."""
    current = filter_cls
    for segment in path:
        sub_filter_cls = _filter_class_for(current, segment)
        assert sub_filter_cls is not None, (
            f"{current.__name__} has no sub-filter field {segment!r} "
            f"(resolving relation path {path})"
        )
        current = sub_filter_cls
    return current


def _assert_relation_bool_resolves(
    filter_cls: type[OperatorFilter], widget: WidgetDescriptor
) -> None:
    """A relation-bool widget's path must resolve to a sub-filter, and every
    fixed child key must be a ``bool`` criterion on that sub-filter."""
    sub_filter_cls = _resolve_subfilter(filter_cls, widget.path)
    assert widget.relation_child, (
        f"relation-bool widget {widget.path} has no data-relation-child"
    )
    for child_key in widget.relation_child:
        criterion_cls = _criterion_class_for(sub_filter_cls, child_key)
        assert criterion_cls is BoolCriterion, (
            f"relation-bool widget {widget.path} child {child_key!r} resolves to "
            f"{criterion_cls} on {sub_filter_cls.__name__}, expected BoolCriterion"
        )


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.name)
def test_every_widget_path_resolves_to_its_kind(case: _BarCase) -> None:
    """Every rendered widget's path resolves to a criterion whose kind matches.

    Relation-bool widgets resolve their path to a *sub-filter* (not a leaf
    criterion) and their fixed child key(s) to a ``bool`` criterion on it."""
    html = str(case.bar_factory(""))
    widgets = _collect_widgets(html)
    assert len(widgets) == case.widget_count, (
        f"{case.name} bar rendered {len(widgets)} filter widgets, "
        f"expected {case.widget_count} (a forgotten path= silently drops a widget)"
    )
    for widget in widgets:
        if widget.kind == "relation-bool":
            _assert_relation_bool_resolves(case.filter_cls, widget)
            continue
        # field_comparisons is a list field handled by filter-bar.ts's
        # special-case branch, not the generic path resolver — resolve_path_kind
        # cannot (and need not) resolve it. See the LeafWidgetKind note in
        # common/criteria.py and the #167 design (§4 path note).
        if widget.kind == "field-comparison":
            assert widget.path == ["field_comparisons"], (
                f"{case.name} field-comparison widget has unexpected path {widget.path}"
            )
            continue
        resolved = resolve_path_kind(case.filter_cls, widget.path)
        assert resolved == widget.kind, (
            f"{case.name} widget {widget.path} declares kind {widget.kind!r} "
            f"but resolves to {resolved!r}"
        )


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.name)
def test_no_widget_path_is_a_prefix_of_another(case: _BarCase) -> None:
    """No top-level (setPath) widget path may be a strict prefix of another.

    A leaf/branch collision among top-level widgets (one targeting a sub-filter
    another steps through) would make the ``setPath`` write ambiguous; forbid it.
    Cross-entity widgets (multi-segment path / relation-bool) are excluded: they
    each build their own AND element (independent EXISTS), so several sharing a
    relation prefix is intended, not a collision."""
    html = str(case.bar_factory(""))
    paths = [
        widget.path
        for widget in _collect_widgets(html)
        if len(widget.path) == 1
        and widget.kind not in ("relation-bool", "field-comparison")
    ]
    for outer in paths:
        for inner in paths:
            if outer is inner:
                continue
            is_strict_prefix = len(outer) < len(inner) and inner[: len(outer)] == outer
            assert not is_strict_prefix, (
                f"{case.name}: path {outer} is a strict prefix of {inner}"
            )


def test_resolve_path_kind_walks_nested_path() -> None:
    """A nested cross-entity path resolves through the sub-filter to its leaf kind."""
    assert resolve_path_kind(GameFilter, ["session_filter", "emulated"]) == "bool"


def test_resolve_path_kind_resolves_leaf_kinds() -> None:
    """Spot-check each kind on a GameFilter field (date via a nested leaf, since
    GameFilter has no top-level DateCriterion field)."""
    assert resolve_path_kind(GameFilter, ["name"]) == "string"
    assert resolve_path_kind(GameFilter, ["year_released"]) == "number"
    assert resolve_path_kind(GameFilter, ["playevent_filter", "ended"]) == "date"
    assert resolve_path_kind(GameFilter, ["mastered"]) == "bool"
    assert resolve_path_kind(GameFilter, ["status"]) == "set"


def test_resolve_path_kind_rejects_unknown_leaf() -> None:
    with pytest.raises(ValueError):
        resolve_path_kind(GameFilter, ["does_not_exist"])


def test_resolve_path_kind_rejects_non_subfilter_step() -> None:
    """A non-leaf segment that isn't a sub-filter (here a criterion) raises."""
    with pytest.raises(ValueError):
        resolve_path_kind(GameFilter, ["name", "emulated"])


def test_resolve_path_kind_rejects_empty_path() -> None:
    with pytest.raises(ValueError):
        resolve_path_kind(GameFilter, [])


def test_every_criterion_type_has_a_kind() -> None:
    """Every criterion registered for from_json/where also has a widget kind.

    Adding a criterion to ``_CRITERION_TYPES`` without giving it a kind in
    ``_CRITERION_KINDS`` would let ``resolve_path_kind`` raise at render time;
    this catches the drift loudly at test time instead."""
    assert set(_CRITERION_KINDS) == set(_CRITERION_TYPES.values())


def test_criterion_kind_rejects_unregistered_class() -> None:
    """A criterion subclass with no registered kind raises ``ValueError``."""

    class _UnregisteredCriterion(_Criterion):
        pass

    with pytest.raises(ValueError):
        criterion_kind(_UnregisteredCriterion)
