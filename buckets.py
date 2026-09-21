"""Where each game's sessions sit, and whether its bucket survived."""

from django.contrib.auth.models import User

from games.models import PlayerGame, PlayerSession, Playthrough, PlaythroughKind

library = User.objects.get(username="admin").library

for player_game in (
    PlayerGame.objects.filter(library=library)
    .select_related("game")
    .order_by("game__name")
):
    runs = Playthrough.objects.filter(library=library, player_game=player_game)
    bucket = runs.filter(kind=PlaythroughKind.IMPORTED_HISTORY).first()
    print(f"\n{player_game.game.name}")
    if bucket is None:
        print("  no bucket")
    else:
        kept = "still here" if bucket.removed_at is None else "TAKEN AWAY by a move"
        naming = PlayerSession.objects.filter(playthrough=bucket)
        print(
            f"  bucket: {kept}"
            f"  ({naming.alive().count()} sessions in it,"
            f" {naming.filter(removed_at__isnull=False).count()} removed ones"
            " still naming it)"
        )
    print("  this game's sessions sit on:")
    for run in runs.filter(removed_at__isnull=True).order_by("created_at"):
        count = PlayerSession.objects.alive().filter(playthrough=run).count()
        name = run.name or "Playthrough (unnamed)"
        print(f"    {name:<28} {count}")
