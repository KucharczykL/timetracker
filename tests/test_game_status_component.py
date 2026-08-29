"""The status dot and the status selector, on words."""

from types import SimpleNamespace
from uuid import uuid7

from common.components import GameStatus, GameStatusSelector, render
from games.models import PlayerGameStatus


def test_every_status_has_its_own_colour():
    colours = {render(GameStatus(["x"], status=status)) for status in PlayerGameStatus}

    assert len(colours) == len(PlayerGameStatus)


def test_the_selector_marks_the_projection_status_current():
    game = SimpleNamespace(id=uuid7(), status="u", mastered=False)

    html = render(
        GameStatusSelector(
            game,
            PlayerGameStatus.choices,
            "tok",
            current=PlayerGameStatus.COMPLETED,
        )
    )

    assert "Completed" in html
    #: The catalog letter on the instance is not what is shown.
    assert 'data-value="completed"' in html
    #: Every word the projection holds, Shelved included.
    assert html.count("data-value=") == len(PlayerGameStatus)
