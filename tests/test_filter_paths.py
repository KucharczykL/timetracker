"""Guard the server↔client filter-widget contract at test time.

Every filter widget advertises a ``data-path`` (its filter-JSON key chain, as
a JSON array) and a ``data-kind`` (string/number/date/bool/set). This module
renders each mode's quick filter bar, extracts those attributes from the real
HTML, and asserts that every path resolves through the Python filter dataclass
tree (``resolve_path_kind``) to a criterion whose kind matches the widget. A
widget pointing at a non-existent path or the wrong kind fails here — the
rendered-widget analogue of ``gen_icons --check``.
"""

import json
from html.parser import HTMLParser
from typing import NamedTuple

import pytest

from common.components import QUICK_FACETS, QuickFilterBar
from common.criteria import (
    OperatorFilter,
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
    """Collect every ``[data-filter-widget]`` start tag's contract attributes.

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


# Each mode's quick bar paired with the dataclass its widget paths resolve
# against. The widget count is pinned to the facet inventory: a forgotten
# ``path=`` silently drops a widget (it stops emitting ``data-filter-widget``),
# which the per-path checks below cannot catch — only an exact count does.
class _BarCase(NamedTuple):
    mode: str
    filter_cls: type[OperatorFilter]


_BAR_CASES = [
    _BarCase("games", GameFilter),
    _BarCase("sessions", SessionFilter),
    _BarCase("purchases", PurchaseFilter),
    _BarCase("devices", DeviceFilter),
    _BarCase("platforms", PlatformFilter),
    _BarCase("playevents", PlayEventFilter),
]


@pytest.mark.parametrize("case", _BAR_CASES, ids=lambda case: case.mode)
def test_every_widget_path_resolves_to_its_kind(case: _BarCase) -> None:
    """Every rendered facet widget's path resolves to a matching-kind criterion."""
    html = str(QuickFilterBar(mode=case.mode, apply_url="/synthetic"))
    widgets = _collect_widgets(html)
    assert len(widgets) == len(QUICK_FACETS[case.mode]), (
        f"{case.mode} bar rendered {len(widgets)} filter widgets, expected one "
        f"per facet (a forgotten path= silently drops a widget)"
    )
    for widget in widgets:
        assert len(widget.path) == 1, (
            f"{case.mode} facet {widget.path} is not a flat own-model leaf"
        )
        resolved = resolve_path_kind(case.filter_cls, widget.path)
        assert resolved == widget.kind, (
            f"{case.mode} widget {widget.path} declares kind {widget.kind!r} "
            f"but resolves to {resolved!r}"
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
    with pytest.raises(ValueError):
        resolve_path_kind(GameFilter, ["name", "emulated"])
