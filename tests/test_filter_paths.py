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
    OperatorFilter,
    _Criterion,
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


class _FilterWidgetCollector(HTMLParser):
    """Collect ``(path, kind)`` from every ``[data-filter-widget]`` start tag.

    Pairs ``data-path``/``data-kind`` within a single element by reading the
    start tag's own attribute list — no regex pairing across the document.
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
        self.widgets.append(WidgetDescriptor(json.loads(raw_path), kind))


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
_BAR_CASES = [
    _BarCase("game", FilterBar, GameFilter, 23),
    _BarCase("session", SessionFilterBar, SessionFilter, 8),
    _BarCase("purchase", PurchaseFilterBar, PurchaseFilter, 14),
    _BarCase("device", DeviceFilterBar, DeviceFilter, 1),
    _BarCase("platform", PlatformFilterBar, PlatformFilter, 2),
    _BarCase("playevent", PlayEventFilterBar, PlayEventFilter, 4),
]


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.name)
def test_every_widget_path_resolves_to_its_kind(case: _BarCase) -> None:
    """Every rendered widget's path resolves to a criterion whose kind matches."""
    html = str(case.bar_factory(""))
    widgets = _collect_widgets(html)
    assert len(widgets) == case.widget_count, (
        f"{case.name} bar rendered {len(widgets)} filter widgets, "
        f"expected {case.widget_count} (a forgotten path= silently drops a widget)"
    )
    for widget in widgets:
        resolved = resolve_path_kind(case.filter_cls, widget.path)
        assert resolved == widget.kind, (
            f"{case.name} widget {widget.path} declares kind {widget.kind!r} "
            f"but resolves to {resolved!r}"
        )


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.name)
def test_no_widget_path_is_a_prefix_of_another(case: _BarCase) -> None:
    """No declared path may be a strict prefix of another within a bar.

    A leaf/branch collision (one widget targeting a sub-filter another widget
    steps through) would make the contract ambiguous; forbid it up front."""
    html = str(case.bar_factory(""))
    paths = [widget.path for widget in _collect_widgets(html)]
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
    """Spot-check each kind on a top-level GameFilter field."""
    assert resolve_path_kind(GameFilter, ["name"]) == "string"
    assert resolve_path_kind(GameFilter, ["year_released"]) == "number"
    assert resolve_path_kind(GameFilter, ["finished"]) == "date"
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
