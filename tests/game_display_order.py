"""Games created out of their display order."""

from games.models import Game, Platform, UserLibrary


def tied_games(library: UserLibrary) -> list[Game]:
    """Games in display order, created in another.

    Neither creation, name nor case-blind order matches. Two
    tie on `sort_name` alone, two on `sort_name` and `name`.

    The full tie's ids follow creation, so only a read that
    orders another model by the game can show `id` decides.
    """
    first_platform = Platform.objects.create(
        library=library, name="Order One", icon="steam"
    )
    second_platform = Platform.objects.create(
        library=library, name="Order Two", icon="nintendo-switch"
    )
    created = {
        key: Game.objects.create(
            library=library, name=name, sort_name=sort_name, platform=platform
        )
        for key, name, sort_name, platform in [
            ("aardvark", "Aardvark", "zz", first_platform),
            ("chapter", "Tell Me Why: Chapter 2", "tell me why", first_platform),
            ("doom_first", "Doom", "doom", second_platform),
            ("doom_second", "Doom", "doom", first_platform),
            ("tell", "Tell Me Why", "tell me why", first_platform),
            ("alpha", "alpha", "alpha", first_platform),
            ("zeta", "Zeta Prime", "Beta", first_platform),
        ]
    }
    return [
        created[key]
        for key in [
            "zeta",
            "alpha",
            "doom_first",
            "doom_second",
            "tell",
            "chapter",
            "aardvark",
        ]
    ]
