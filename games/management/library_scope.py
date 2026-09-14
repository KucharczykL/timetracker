"""The libraries and zone a read-only report reads."""

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError, CommandParser

from games.models import UserLibrary


def add_library_scope(parser: CommandParser) -> None:
    """One of three scopes, always stated."""
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user", help="Report the library owned by USERNAME.")
    scope.add_argument("--library", dest="library_id", help="Report one library UUID.")
    scope.add_argument(
        "--all-libraries",
        action="store_true",
        help="Explicitly report every library.",
    )


def resolve_libraries(options: dict[str, object]) -> list[UserLibrary]:
    libraries = UserLibrary.objects.select_related("user").order_by("pk")
    if options["all_libraries"]:
        return list(libraries)
    if options["user"]:
        return [_library_of_user(str(options["user"]))]
    return [_library_by_id(str(options["library_id"]))]


def resolve_zone(name: str | None) -> ZoneInfo | None:
    if name is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise CommandError(f"{name!r} names no time zone.") from error


def _library_of_user(username: str) -> UserLibrary:
    """A missing user is not a user missing a library."""
    user_model = get_user_model()
    try:
        user = user_model.objects.get(username=username)
    except user_model.DoesNotExist as error:
        raise CommandError(f"No user is named {username!r}.") from error
    try:
        return UserLibrary.objects.select_related("user").get(user=user)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"User {username!r} owns no library.") from error


def _library_by_id(library_id: str) -> UserLibrary:
    """The text is read here, so the query catches one error."""
    try:
        parsed = uuid.UUID(library_id)
    except ValueError as error:
        raise CommandError(f"Library {library_id!r} is no UUID.") from error
    try:
        return UserLibrary.objects.select_related("user").get(pk=parsed)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"Library {parsed} does not exist.") from error
