"""One row per run at a game a library tracks."""

import pytest

from games.checks import check_projection_models
from games.models import Playthrough, PlaythroughKind

pytestmark = pytest.mark.untracked_games


def test_playthrough_is_a_pure_projection():
    """Nothing in the row predates the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is Playthrough
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: The key is the event's aggregate_id.
    assert Playthrough().id is None


def test_a_playthrough_starts_ordinary():
    assert Playthrough().kind == PlaythroughKind.ORDINARY


def test_a_playthrough_starts_unnamed():
    """A blank name is what the display number is for."""
    assert Playthrough().name == ""
    assert Playthrough().note == ""


def test_a_playthrough_starts_with_no_endpoints():
    """#681 states them."""
    assert Playthrough().started is None
    assert Playthrough().completed is None


def test_a_playthrough_starts_live():
    assert Playthrough().removed_at is None


def test_the_bound_columns_are_generated():
    """Never written from application code."""
    generated = {
        field.name for field in Playthrough._meta.concrete_fields if field.generated
    }

    assert generated == {
        "started_lower",
        "started_upper",
        "completed_lower",
        "completed_upper",
    }


def test_the_display_order_index_covers_every_sort_key():
    """The read-time numbering has an index behind it."""
    covering = [
        index
        for index in Playthrough._meta.indexes
        if index.fields
        == [
            "player_game",
            "started_lower",
            "completed_lower",
            "created_at",
            "id",
        ]
    ]

    assert len(covering) == 1
