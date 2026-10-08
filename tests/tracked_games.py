"""Seeds tracked games; states facts on them."""

import uuid

import pytest
from django.db.models.signals import post_save
from django.utils import timezone

from games.models import (
    Game,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)


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


@pytest.fixture(autouse=True)
def _track_created_games(request):
    """Seed each created game its projection rows.

    Rows, not TrackGame: the command wants an actor and a transaction.
    Both rows: a write path that finds no run creates a second.
    Other words come through ``create_tracked_game``.
    """
    if "untracked_games" in request.keywords:
        yield
        return

    def track(sender, instance, created, raw, **kwargs):
        #: raw is a loaddata row: the library may not exist yet.
        if raw or not created or instance.library_id is None:
            return
        tracked, made = PlayerGame.objects.get_or_create(
            library_id=instance.library_id,
            game=instance,
            defaults={
                "pk": uuid.uuid7(),
                "tracked_at": timezone.now(),
                "status": PlayerGameStatus.UNPLAYED,
                "mastered": False,
            },
        )
        if not made:
            return
        Playthrough.objects.create(
            pk=uuid.uuid7(),
            library_id=instance.library_id,
            player_game=tracked,
            kind=PlaythroughKind.ORDINARY,
            created_at=timezone.now(),
        )

    post_save.connect(track, sender=Game, dispatch_uid="test-track-created-games")
    try:
        yield
    finally:
        post_save.disconnect(sender=Game, dispatch_uid="test-track-created-games")
