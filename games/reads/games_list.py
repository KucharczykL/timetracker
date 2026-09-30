"""The rows the Games list reads before a filter narrows them."""

from typing import TYPE_CHECKING

from django.db.models import QuerySet

from games.models import Game, GameKind, UserLibrary

if TYPE_CHECKING:
    from games.filters import GameFilter


def games_list_base(
    library: UserLibrary, game_filter: GameFilter | None
) -> QuerySet[Game]:
    """Main games, unless the filter names a kind or a parent.

    The list, its bulk scope and the builder's count read this one
    base, so the three agree on which rows a filter narrows.
    """
    games = Game.objects.tracked_by(library)
    if game_filter is not None and game_filter.names_addon_fields():
        return games
    return games.filter(kind=GameKind.MAIN)
