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
from common.criteria import OperatorFilter, resolve_path_kind
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


# Each filter bar paired with the dataclass its widget paths resolve against.
class _BarCase(NamedTuple):
    name: str
    bar_factory: type
    filter_cls: type[OperatorFilter]


_BAR_CASES = [
    _BarCase("game", FilterBar, GameFilter),
    _BarCase("session", SessionFilterBar, SessionFilter),
    _BarCase("purchase", PurchaseFilterBar, PurchaseFilter),
    _BarCase("device", DeviceFilterBar, DeviceFilter),
    _BarCase("platform", PlatformFilterBar, PlatformFilter),
    _BarCase("playevent", PlayEventFilterBar, PlayEventFilter),
]


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.name)
def test_every_widget_path_resolves_to_its_kind(case: _BarCase) -> None:
    """Every rendered widget's path resolves to a criterion whose kind matches."""
    html = str(case.bar_factory(""))
    widgets = _collect_widgets(html)
    assert widgets, f"{case.name} bar rendered no filter widgets"
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
