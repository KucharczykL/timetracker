"""Resolves the user or library a command names."""

from argparse import ArgumentParser
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.management.base import CommandError
from django.db.models import QuerySet

from games.models import UserLibrary
from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

type Username = str  # e.g. "lukas"
type LibraryIdText = str  # e.g. "0199a1b2-7c3d-7e4f-8a5b-6c7d8e9f0a1b"
type LibraryIdentifier = LibraryIdText | UUID
type ScopeVerb = str  # e.g. "Rebuild"
type CommandOptions = Mapping[str, Any]  # a command's parsed **options


def add_scope_arguments(parser: ArgumentParser, *, verb: ScopeVerb) -> None:
    """Add the required --user/--library/--all-libraries group."""
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user", help=f"{verb} the library owned by USERNAME.")
    scope.add_argument("--library", dest="library_id", help=f"{verb} one library UUID.")
    scope.add_argument(
        "--all-libraries",
        action="store_true",
        help=f"Explicitly {verb.lower()} every library, in key order.",
    )


@dataclass(frozen=True, slots=True)
class LibraryScope:
    """What the scope group names."""

    user: Username | None = None
    library_id: LibraryIdentifier | None = None
    all_libraries: bool = False

    @classmethod
    def from_options(cls, options: CommandOptions) -> Self:
        return cls(
            user=options["user"],
            library_id=options["library_id"],
            all_libraries=options["all_libraries"],
        )


def scoped_libraries(scope: LibraryScope) -> list[UserLibrary]:
    """Never empty: an empty census is refused."""
    if scope.all_libraries:
        found = list(_libraries())
        if not found:
            lacking = get_user_model().objects.filter(library__isnull=True).count()
            raise CommandError(
                "--all-libraries found no library, so there was nothing to "
                f"act on; {lacking} user(s) hold none."
            )
        return found
    #: Not truthiness: --user "" is a username.
    if scope.user is not None:
        return [library_of_user(scope.user)]
    #: call_command can pass every member None.
    if scope.library_id is None:
        raise CommandError("Name --user, --library or --all-libraries.")
    return [library_by_id(scope.library_id)]


def user_named(username: Username, *, locked: bool = False) -> User:
    users = get_user_model().objects
    rows = users.select_for_update() if locked else users.all()
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


def library_by_id(raw_id: LibraryIdentifier) -> UserLibrary:
    try:
        library_id = parse_uuidv7(raw_id)
    except UUIDv7ParseError as error:
        raise CommandError(f"{str(raw_id)!r} is not a library id. {error}") from error
    try:
        return _libraries().get(pk=library_id)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"No library {library_id}.") from error


def _libraries() -> QuerySet[UserLibrary, UserLibrary]:
    return UserLibrary.objects.select_related("user").order_by("pk")
