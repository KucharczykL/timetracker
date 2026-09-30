"""States facts on the hook's seeded row."""

from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary


def create_tracked_game(
    library: UserLibrary,
    name: str,
    *,
    status: PlayerGameStatus = PlayerGameStatus.UNPLAYED,
    mastered: bool = False,
    excluded_from_unfinished: bool = False,
    excluded_from_dropped: bool = False,
    **game_fields,
) -> Game:
    game = Game.objects.create(library=library, name=name, **game_fields)
    stated = PlayerGame.objects.filter(library=library, game=game).update(
        status=status,
        mastered=mastered,
        excluded_from_unfinished=excluded_from_unfinished,
        excluded_from_dropped=excluded_from_dropped,
    )
    if stated != 1:
        raise RuntimeError(
            "No PlayerGame row to state facts on: is this test marked untracked_games?"
        )
    return game
