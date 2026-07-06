"""Filter set-criterion labels must survive round-trips whose choice/multi
values are bare (no embedded {id, label}) — e.g. a programmatically built
filter from stats_links (#65)."""

from common.components.filters import _extract_labeled


def test_extract_labeled_handles_labeled_dicts():
    assert _extract_labeled([{"id": "game", "label": "Game"}]) == [("game", "Game")]


def test_extract_labeled_handles_bare_values():
    # bare scalars (ids/choices) fall back to using the value as its own label
    assert _extract_labeled(["game", "dlc"]) == [("game", "game"), ("dlc", "dlc")]


def test_extract_labeled_handles_bare_ints():
    assert _extract_labeled([3, 7]) == [("3", "3"), ("7", "7")]


def test_stats_link_prefills_labelled_choice():
    """End-to-end (#224): a server-built stats-link that embeds an id's label
    serializes it into the ``?filter=`` JSON, so the quick bar prefills a
    labelled pill rather than a bare id."""
    import json

    from common.components.filters import _choice_from_raw
    from common.criteria import MultiCriterion
    from games.filters import SessionFilter

    link = SessionFilter(game=MultiCriterion(value=[5], labels={5: "Hollow Knight"}))
    existing = json.loads(json.dumps(link.to_json()))
    choice = _choice_from_raw(existing.get("game") or {})
    assert choice.selected == [("5", "Hollow Knight")]
