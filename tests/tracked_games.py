"""A game with the facts a test states on its projection row.

The autouse hook seeds every created game an UNPLAYED, unmastered
row and one run; this states the words the test wants on that row.
Under ``untracked_games`` there is no row, and the factory says so.
"""

from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary


def create_tracked_game(
    library: UserLibrary,
    name: str,
    *,
    status: PlayerGameStatus = PlayerGameStatus.UNPLAYED,
    mastered: bool = False,
    **game_fields,
) -> Game:
    game = Game.objects.create(library=library, name=name, **game_fields)
    stated = PlayerGame.objects.filter(library=library, game=game).update(
        status=status, mastered=mastered
    )
    if stated != 1:
        raise RuntimeError(
            "No PlayerGame row to state facts on: is this test marked untracked_games?"
        )
    return game
