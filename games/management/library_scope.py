"""Which libraries a maintenance command reads."""

from argparse import ArgumentParser
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db.models import QuerySet

from games.models import UserLibrary

type UserRows = QuerySet[User, User]
type Username = str
type CommandOptions = Mapping[str, Any]


def add_scope_arguments(parser: ArgumentParser, *, verb: str) -> None:
    """Add the required --user/--library/--all-libraries group."""
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user", help=f"{verb} the library owned by USERNAME.")
    scope.add_argument("--library", dest="library_id", help=f"{verb} one library UUID.")
    scope.add_argument(
        "--all-libraries",
        action="store_true",
        help=f"Explicitly {verb.lower()} every library, in key order.",
    )


def scoped_libraries(options: CommandOptions) -> list[UserLibrary]:
    """The libraries the scope group names."""
    if options["all_libraries"]:
        found = list(_libraries())
        if not found:
            raise CommandError(
                "--all-libraries found no library, so there was nothing to act on."
            )
        return found
    #: Not truthiness: --user "" is a username.
    if options["user"] is not None:
        return [library_of_user(options["user"])]
    #: call_command can leave every member unset.
    if options["library_id"] is None:
        raise CommandError("Name --user, --library or --all-libraries.")
    return [library_by_id(options["library_id"])]


def user_named(username: Username, *, users: UserRows | None = None) -> User:
    rows = User.objects.all() if users is None else users
    try:
        return rows.get(username=username)
    except rows.model.DoesNotExist as error:
        raise CommandError(f"No user is named {username!r}.") from error


def library_of_user(username: Username) -> UserLibrary:
    """Two errors: no user, or no library."""
    user = user_named(username)
    try:
        return _libraries().get(user=user)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"User {username!r} owns no library.") from error


def library_by_id(raw_id: str | UUID) -> UserLibrary:
    if isinstance(raw_id, UUID):
        library_id = raw_id
    else:
        try:
            library_id = UUID(raw_id)
        except ValueError as error:
            raise CommandError(f"{raw_id!r} is not a library id.") from error
    try:
        return _libraries().get(pk=library_id)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"No library {library_id}.") from error
    #: Library keys are UUIDv7; others are refused.
    except ValidationError as error:
        raise CommandError(f"{raw_id!r} is not a library id.") from error


def _libraries() -> QuerySet[UserLibrary, UserLibrary]:
    return UserLibrary.objects.select_related("user").order_by("pk")
