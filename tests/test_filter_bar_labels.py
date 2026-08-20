"""Filter set-criterion labels must survive round-trips whose choice/multi
values are bare (no embedded {id, label}) — e.g. a programmatically built
filter from stats_links."""

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
    from uuid import UUID

    from common.components.filters import _choice_from_raw
    from common.criteria import UUIDMultiCriterion
    from games.filters import SessionFilter

    game_id = UUID("018f5e66-e800-7000-8000-000000000001")
    link = SessionFilter(
        game=UUIDMultiCriterion(value=[game_id], labels={game_id: "Hollow Knight"})
    )
    existing = json.loads(json.dumps(link.to_json()))
    choice = _choice_from_raw(existing.get("game") or {})
    assert choice.selected == [(str(game_id), "Hollow Knight")]
