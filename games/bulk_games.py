"""What acts on the Games list share; declares no act."""

from django.db.models import QuerySet

from games.bulk_narrowing import narrowed
from games.bulk_parts import FilterJson
from games.filters import parse_game_filter
from games.models import Game, UserLibrary
from games.reads.games_list import games_list_base

GAME_GONE = "One of the games is no longer available, so it was left as it is."


def game_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Game]:
    """The list's own read: shared catalog games it tracks included."""
    base = games_list_base(
        library, parse_game_filter(filter_json) if filter_json else None
    )
    return narrowed(base, library, filter_json, parse_game_filter)
