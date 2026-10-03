"""Resolving the row a command's UUID names."""

import uuid
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, Q, QuerySet

from games.events.dispatch import (
    CommandContext,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
)
from games.ids import GameId, ReleaseId
from games.models import Device, LibraryEntry, Purchase, Release, UserLibrary
from games.projections import library_path_of
from games.reads.releases import held_releases

RELEASE_REMOVED = (
    "That release was removed from the catalog. Choose another, or restore it."
)
RELEASE_OF_ANOTHER_GAME = (
    "That release belongs to another game. Choose a release of this one."
)
NO_COPY_OF_RELEASE = (
    "Your library holds no copy of that release. Add it first, or choose another."
)


@dataclass(frozen=True, slots=True)
class Refusal:
    """What a caller says when nothing resolves.

    `message` reaches a log and may name an id.
    `sentence` is the only thing a person sees.
    """

    message: str
    #: Only a refusal states one.
    sentence: str | None = None
    #: A rejection refuses; the default answers absent.
    raises: type[RowNotHeld | CommandRejected] = RowNotHeld

    def __post_init__(self) -> None:
        absent = issubclass(self.raises, RowNotHeld)
        if absent and self.sentence is not None:
            raise TypeError(
                f"{self.raises.__name__} shows no sentence. State a "
                "CommandRejected subclass beside it, or take it away."
            )
        if not absent and self.sentence is None:
            raise TypeError(
                f"{self.raises.__name__} reaches a person. State a sentence "
                "naming the remedy, or let `raises` default to RowNotHeld."
            )

    def raised(self) -> RowNotHeld | CommandRejected:
        #: RowNotHeld holds no sentence keyword.
        if issubclass(self.raises, RowNotHeld):
            return self.raises(self.message)
        return self.raises(self.message, sentence=self.sentence)


def library_row[RowT: Model](
    context: CommandContext,
    reads: QuerySet[RowT],
    refusal: Refusal,
    **lookup: object,
) -> RowT:
    """This library's row, or a refusal.

    Returns a removed row: every restore names one.

    The lookup must be unique. MultipleObjectsReturned is not
    caught: a second row is a defect, and its traceback is the
    answer to one.
    """
    try:
        return reads.get(library=context.library, **lookup)
    #: A generic queryset cannot name the class.
    except ObjectDoesNotExist:
        raise refusal.raised() from None


def visible_row[RowT: Model](
    context: CommandContext,
    reads: QuerySet[RowT],
    refusal: Refusal,
    **lookup: object,
) -> RowT:
    """A shared row, or the library's own."""
    return visible_in(context.library, reads, refusal, **lookup)


def visible_in[RowT: Model](
    library: UserLibrary,
    reads: QuerySet[RowT],
    refusal: Refusal,
    **lookup: object,
) -> RowT:
    """`visible_row` for a caller holding no context."""
    path = library_path_of(reads.model)
    if path is None:
        raise TypeError(f"{reads.model.__name__} reaches no library.")
    visible = Q(**{f"{path}__isnull": True}) | Q(**{path: library})
    try:
        return reads.filter(visible, **lookup).get()
    except ObjectDoesNotExist:
        raise refusal.raised() from None


def library_device_row(
    context: CommandContext, device_id: uuid.UUID | None
) -> Device | None:
    """This library's device, removed or not; None unstated."""
    if device_id is None:
        return None
    return library_row(
        context,
        Device.objects.all(),
        Refusal(
            message=(
                f"This library holds no device {device_id}. A stated fact "
                "names a device the library records."
            )
        ),
        pk=device_id,
    )


def library_device(
    context: CommandContext, device_id: uuid.UUID | None
) -> Device | None:
    """This library's live device, or a refusal."""
    device = library_device_row(context, device_id)
    if device is None:
        return None
    #: Under dispatch's lock; mark cannot move.
    if device.removed_at is not None:
        raise CommandRejected(
            f"This library removed device {device_id}, so nothing names it anew.",
            sentence=(
                "That device was removed from your library. Restore it "
                "before choosing it."
            ),
        )
    return device


def library_entry_row(context: CommandContext, entry_id: uuid.UUID) -> LibraryEntry:
    """This library's entry, removed or not.

    A drifted parent is the ownership audit's defect:
    no command states a fact on such a row.
    """
    entry = library_row(
        context,
        #: Every caller reads the parent's mark; restore the Release's.
        LibraryEntry.objects.select_related("player_game", "release__edition__game"),
        Refusal(
            message=(
                f"This library holds no entry {entry_id}. A stated fact names "
                "a copy the library records."
            )
        ),
        pk=entry_id,
    )
    _refuse_a_drifted_entry(context, entry)
    return entry


def _refuse_a_drifted_entry(context: CommandContext, entry: LibraryEntry) -> None:
    """Refuse an entry naming another library's parent."""
    if entry.player_game.library_id != context.library.pk:
        raise RowUnreadable(
            f"Entry {entry.pk} of library {entry.library_id} names player game "
            f"{entry.player_game_id} of library {entry.player_game.library_id}; "
            "the ownership audit reports it, and no command states a fact "
            "about it."
        )
    release_library = entry.release.edition.game.library_id
    if release_library is not None and release_library != context.library.pk:
        raise RowUnreadable(
            f"Entry {entry.pk} of library {entry.library_id} names release "
            f"{entry.release_id} of library {release_library}; the ownership "
            "audit reports it, and no command states a fact about it."
        )


def library_purchase_row(context: CommandContext, purchase_id: uuid.UUID) -> Purchase:
    """This library's purchase, removed or not."""
    purchase = library_row(
        context,
        Purchase.objects.select_related(
            "entry__player_game__game", "entry__release__edition__game"
        ),
        Refusal(
            message=(
                f"This library holds no purchase {purchase_id}. A stated fact "
                "names a purchase the library records."
            )
        ),
        pk=purchase_id,
    )
    if purchase.entry.library_id != context.library.pk:
        raise RowUnreadable(
            f"Purchase {purchase.pk} of library {purchase.library_id} names entry "
            f"{purchase.entry_id} of library {purchase.entry.library_id}; the "
            "ownership audit reports it, and no command states a fact about it."
        )
    _refuse_a_drifted_entry(context, purchase.entry)
    return purchase


def visible_release(context: CommandContext, release_id: ReleaseId) -> Release:
    """A visible Release, removed or not."""
    return _visible_release(context.library, release_id)


def _visible_release(library: UserLibrary, release_id: ReleaseId) -> Release:
    return visible_in(
        library,
        Release.objects.select_related("edition__game"),
        Refusal(
            message=(
                f"No release {release_id} this library can see. A fact names "
                "a release of its own catalog or the shared one."
            )
        ),
        pk=release_id,
    )


def refuse_a_removed_release(release: Release) -> None:
    """Refuse a Release a mark hides."""
    if not Release.objects.alive().filter(pk=release.pk).exists():
        raise CommandRejected(
            f"Release {release.pk} or one of its parents is removed, so no "
            "fact names it anew.",
            sentence=RELEASE_REMOVED,
        )


def stated_release(
    context: CommandContext,
    release_id: ReleaseId | None,
    *,
    game_id: GameId,
    held_id: ReleaseId | None,
) -> Release | None:
    """The stated Release, under the lock."""
    return checked_release(
        context.library, release_id, game_id=game_id, held_id=held_id
    )


def checked_release(
    library: UserLibrary,
    release_id: ReleaseId | None,
    *,
    game_id: GameId,
    held_id: ReleaseId | None,
) -> Release | None:
    """The rule; held skips removal and copy.

    Callers that dispatch several commands run it first, so a
    refusal writes nothing.
    """
    if release_id is None:
        return None
    release = _visible_release(library, release_id)
    held = release_id == held_id
    if not held:
        refuse_a_removed_release(release)
    if release.edition.game_id != game_id:
        raise CommandRejected(
            f"Release {release.pk} is a release of game "
            f"{release.edition.game_id}, not of game {game_id}.",
            sentence=RELEASE_OF_ANOTHER_GAME,
        )
    if not held and not held_releases(library).filter(pk=release.pk).exists():
        raise CommandRejected(
            f"This library holds no live copy of release {release.pk}.",
            sentence=NO_COPY_OF_RELEASE,
        )
    return release
