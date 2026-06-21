"""The filter bar must render a filter whose choice/multi values are bare
(no embedded {id, label}) — e.g. a programmatically built filter from
stats_links — without crashing (#65)."""

from common.components.filters import _extract_labeled


def test_extract_labeled_handles_labeled_dicts():
    assert _extract_labeled([{"id": "game", "label": "Game"}]) == [("game", "Game")]


def test_extract_labeled_handles_bare_values():
    # bare scalars (ids/choices) fall back to using the value as its own label
    assert _extract_labeled(["game", "dlc"]) == [("game", "game"), ("dlc", "dlc")]


def test_extract_labeled_handles_bare_ints():
    assert _extract_labeled([3, 7]) == [("3", "3"), ("7", "7")]
