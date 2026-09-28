"""The groups a library's platforms hold."""

from games.models import Platform, UserLibrary

#: A group a platform names.
type PlatformGroup = str  # "Nintendo"

#: The most characters a group holds.
GROUP_LENGTH = Platform._meta.get_field("group").max_length or 255


def platform_groups(library: UserLibrary) -> list[PlatformGroup]:
    """Every group a live platform the library sees holds."""
    return sorted(
        set(
            Platform.objects.visible_to(library)
            .exclude(group="")
            .values_list("group", flat=True)
        ),
        key=str.casefold,
    )
