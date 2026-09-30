"""What acts on the Games list share; declares no act."""

from django.db.models import QuerySet

from games.bulk_narrowing import narrowed
from games.bulk_parts import FilterJson
from games.filters import parse_game_filter
from games.models import Game, UserLibrary

GAME_GONE = "One of the games is no longer available, so it was left as it is."


def game_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Game]:
    """The list's own read: shared catalog games it tracks included."""
    return narrowed(
        Game.objects.tracked_by(library), library, filter_json, parse_game_filter
    )
