"""The groups a library's platforms hold."""

from games.models import Platform, UserLibrary


def platform_groups(library: UserLibrary) -> list[str]:
    """Every group a live platform the library sees holds."""
    return sorted(
        set(
            Platform.objects.visible_to(library)
            .exclude(group="")
            .values_list("group", flat=True)
        ),
        key=str.casefold,
    )
