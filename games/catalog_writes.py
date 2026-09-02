"""Write a private Game's Editions and Releases.

One call states one Game's whole graph. Nothing here destroys a
row: a removal is a stamp.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet

from games.models import Edition, Game, Platform, Release, UserLibrary
from games.removal import remove
from timetracker.temporal import TemporalValue

#: The words an Edition presents under.
type EditionName = str

SHARED_GAME = "This is a shared game, and a shared game is read-only."
FOREIGN_GAME = "This game belongs to another library."
REMOVED_GAME = "This game is removed. Put it back before you change it."
REMOVED_EDITION = "This edition is removed. Put it back before you change it."
REMOVED_RELEASE = "This release is removed. Put it back before you change it."
FOREIGN_PLATFORM = "Platform belongs to another library."
DUPLICATE_EDITION_NAME = "Another edition of this game already has that name."
LAST_EDITION = "A game keeps one edition. Add another one before you remove this."
TWO_DEFAULT_EDITIONS = "A game keeps one default edition, and this states two."
TWO_DEFAULT_RELEASES = "An edition keeps one default release, and this states two."
FOREIGN_ROW = "This row belongs to another game."
REPEATED_ROW = "Two rows of this statement name the same stored row."

#: The caller's own name for one row, handed back on a refusal.
type RowKey = str

#: Each stated row's stored counterpart. None states a new row.
type StoredEditions = dict[RowKey, Edition | None]
type StoredReleases = dict[RowKey, Release | None]


class GraphRefused(ValidationError):
    """A refusal that names its row.

    `key` is opaque here. The form passes the prefix it already
    has, thus a sentence reaches the row a person typed into.
    """

    def __init__(self, sentence: str, *, key: RowKey | None = None) -> None:
        super().__init__(sentence)
        self.key = key


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """One Release the caller wants.

    `release` is identity only, resolved under the lock. None
    states a row that does not exist yet.
    """

    key: RowKey
    release: Release | None = None
    platform: Platform | None = None
    release_date: TemporalValue | None = None
    removed: bool = False
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class EditionState:
    """One Edition the caller wants."""

    key: RowKey
    edition: Edition | None = None
    name: EditionName = ""
    removed: bool = False
    is_default: bool = False
    releases: tuple[ReleaseState, ...] = ()


class WrittenRelease(NamedTuple):
    """One written Release, under the caller's own name for it."""

    key: RowKey
    release: Release


@dataclass(frozen=True, slots=True)
class WrittenEdition:
    """One written Edition and its surviving Releases."""

    key: RowKey
    edition: Edition
    releases: tuple[WrittenRelease, ...]


@dataclass(frozen=True, slots=True)
class WrittenGraph:
    """What one statement left, row by row.

    `editions` runs parallel to the surviving input.
    """

    game: Game
    editions: tuple[WrittenEdition, ...]


def _refuse_foreign_platform(
    library_id, platform: Platform | None, key: RowKey | None
) -> None:
    """A Platform is shared or this library's."""
    if platform is not None and platform.library_id not in (None, library_id):
        raise GraphRefused(FOREIGN_PLATFORM, key=key)


def _writable_game(game_id, library: UserLibrary) -> Game:
    """The Game this library may write, locked."""
    game = Game.objects.select_for_update().get(pk=game_id)
    #: `GraphRefused` with no key: the sentence belongs to the whole
    #: statement, and a caller shows it rather than raising a page.
    if game.library_id is None:
        raise GraphRefused(SHARED_GAME)
    if game.library_id != library.pk:
        raise GraphRefused(FOREIGN_GAME)
    if game.removed_at is not None:
        raise GraphRefused(REMOVED_GAME)
    return game


def _live_editions(game_id) -> QuerySet[Edition]:
    """One Game's Editions, by their own mark.

    The row's own mark, not `alive()`: the constraints here are
    conditional on it.
    """
    return Edition.objects.filter(game_id=game_id, removed_at__isnull=True)


def _clear_default_edition(game_id) -> None:
    """The old default steps down before the new one stands."""
    _live_editions(game_id).filter(is_default=True).update(is_default=False)


def _live_releases(edition_id) -> QuerySet[Release]:
    """One Edition's Releases, by their own mark."""
    return Release.objects.filter(edition_id=edition_id, removed_at__isnull=True)


def _clear_default_release(edition_id) -> None:
    """The old default steps down before the new one stands."""
    _live_releases(edition_id).filter(is_default=True).update(is_default=False)


def _resolved_edition(owner: Game, state: EditionState) -> Edition | None:
    """The stored row a state names."""
    if state.edition is None:
        return None
    stored = Edition.objects.filter(pk=state.edition.pk).first()
    if stored is None or stored.game_id != owner.pk:
        raise GraphRefused(FOREIGN_ROW, key=state.key)
    #: A stated removal of a row already gone states what is true.
    if stored.removed_at is not None and not state.removed:
        raise GraphRefused(REMOVED_EDITION, key=state.key)
    return stored


def _resolved_release(parent: Edition | None, state: ReleaseState) -> Release | None:
    """The stored Release a state names."""
    if state.release is None:
        return None
    stored = Release.objects.filter(pk=state.release.pk).first()
    if stored is None or parent is None or stored.edition_id != parent.pk:
        raise GraphRefused(FOREIGN_ROW, key=state.key)
    if stored.removed_at is not None and not state.removed:
        raise GraphRefused(REMOVED_RELEASE, key=state.key)
    return stored


def _refuse_repeated_rows(stored: Mapping[RowKey, Model | None]) -> None:
    """One stored row answers to one stated row."""
    seen: set[object] = set()
    for key, row in stored.items():
        if row is None:
            continue
        if row.pk in seen:
            raise GraphRefused(REPEATED_ROW, key=key)
        seen.add(row.pk)


def _refuse_taken_names(
    surviving: list[EditionState], untouched: list[Edition]
) -> None:
    """One live name per Game."""
    taken = {edition.name.strip().casefold() for edition in untouched} - {""}
    for state in surviving:
        wanted = state.name.strip().casefold()
        if not wanted:
            continue
        if wanted in taken:
            raise GraphRefused(DUPLICATE_EDITION_NAME, key=state.key)
        taken.add(wanted)


def _refuse_the_set(
    owner: Game,
    library: UserLibrary,
    editions: Sequence[EditionState],
    stored_editions: StoredEditions,
) -> None:
    """Everything the statement can be wrong about."""
    surviving = [state for state in editions if not state.removed]
    named = [stored.pk for stored in stored_editions.values() if stored is not None]
    untouched = list(_live_editions(owner.pk).exclude(pk__in=named))
    #: No key: every stated row is one this refusal is about, and a
    #: sentence on a row the caller is removing is a sentence nobody
    #: sees.
    if not surviving and not untouched:
        raise GraphRefused(LAST_EDITION)
    marked = [state for state in surviving if state.is_default]
    if len(marked) > 1:
        raise GraphRefused(TWO_DEFAULT_EDITIONS, key=marked[1].key)
    _refuse_taken_names(surviving, untouched)
    for state in surviving:
        rows = [row for row in state.releases if not row.removed]
        marked_rows = [row for row in rows if row.is_default]
        if len(marked_rows) > 1:
            raise GraphRefused(TWO_DEFAULT_RELEASES, key=marked_rows[1].key)
        for row in rows:
            _refuse_foreign_platform(library.pk, row.platform, row.key)


def _written_release(
    edition: Edition, state: ReleaseState, stored: Release | None
) -> Release:
    """One Release's whole Platform and date."""
    if stored is None:
        return Release.objects.create(
            edition=edition,
            platform=state.platform,
            release_date=state.release_date,
            is_default=False,
        )
    stored.platform = state.platform
    stored.release_date = state.release_date
    stored.is_default = False
    stored.save(update_fields=("platform", "release_date", "is_default"))
    return stored


def _written_edition(
    owner: Game,
    state: EditionState,
    stored: Edition | None,
    stored_releases: StoredReleases,
) -> WrittenEdition:
    """One Edition's name and its surviving Releases."""
    name = state.name.strip()
    if stored is None:
        edition = Edition.objects.create(game=owner, name=name, is_default=False)
    else:
        edition = stored
        edition.name = name
        edition.is_default = False
        edition.save(update_fields=("name", "is_default"))
    rows = tuple(
        WrittenRelease(
            row.key, _written_release(edition, row, stored_releases[row.key])
        )
        for row in state.releases
        if not row.removed
    )
    return WrittenEdition(key=state.key, edition=edition, releases=rows)


def _edition_to_mark(
    owner: Game,
    surviving: Sequence[EditionState],
    written: Sequence[WrittenEdition],
    standing: Edition | None,
) -> Edition | None:
    """The stated mark, else standing, else first."""
    for state, entry in zip(surviving, written, strict=True):
        if state.is_default:
            return entry.edition
    if standing is not None:
        kept = _live_editions(owner.pk).filter(pk=standing.pk).first()
        if kept is not None:
            return kept
    if written:
        return written[0].edition
    return _live_editions(owner.pk).order_by("pk").first()


def _release_to_mark(
    state: EditionState, entry: WrittenEdition, standing: Release | None
) -> Release | None:
    """The same rule, one level down."""
    stated = [row for row in state.releases if not row.removed]
    for row, written in zip(stated, entry.releases, strict=True):
        if row.is_default:
            return written.release
    if standing is not None:
        kept = _live_releases(entry.edition.pk).filter(pk=standing.pk).first()
        if kept is not None:
            return kept
    if entry.releases:
        return entry.releases[0].release
    return _live_releases(entry.edition.pk).order_by("pk").first()


@transaction.atomic
def state_catalog_graph(
    *,
    game: Game,
    library: UserLibrary,
    editions: Sequence[EditionState],
) -> WrittenGraph:
    """State one Game's whole graph.

    A row the caller does not mention is left alone: removal is
    stated by `removed`, thus one partial writer cannot take a
    catalog somebody built by hand.
    """
    owner = _writable_game(game.pk, library)
    stored_editions: StoredEditions = {
        state.key: _resolved_edition(owner, state) for state in editions
    }
    stored_releases: StoredReleases = {
        row.key: _resolved_release(stored_editions[state.key], row)
        for state in editions
        for row in state.releases
    }
    _refuse_repeated_rows(stored_editions)
    _refuse_repeated_rows(stored_releases)
    _refuse_the_set(owner, library, editions, stored_editions)

    surviving = [state for state in editions if not state.removed]
    standing_edition = _live_editions(owner.pk).filter(is_default=True).first()
    standing_releases: dict[RowKey, Release | None] = {}
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None:
            standing_releases[state.key] = (
                _live_releases(stored.pk).filter(is_default=True).first()
            )

    #: 1. Every live default steps down first. Both constraints
    #: permit at most one, thus zero is legal and the rest is free.
    _clear_default_edition(owner.pk)
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None:
            _clear_default_release(stored.pk)

    #: 2. A removal is a stamp, and every stated row is read,
    #: removed Editions too, thus putting one back brings back
    #: exactly the rows nobody removed.
    for state in editions:
        for row in state.releases:
            stored_release = stored_releases[row.key]
            #: A row already gone keeps the stamp it went out under.
            if row.removed and stored_release and not stored_release.removed_at:
                remove(stored_release)
    for state in editions:
        stored = stored_editions[state.key]
        if state.removed and stored and not stored.removed_at:
            remove(stored)

    #: 3. A name being given up is freed before it is taken. The
    #: empty name claims no slot, thus two Editions can exchange.
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None and stored.name.strip() != state.name.strip():
            Edition.objects.filter(pk=stored.pk).update(name="")

    #: 4 and 5. The stored rows, then the new ones.
    written = [
        _written_edition(owner, state, stored_editions[state.key], stored_releases)
        for state in surviving
    ]

    #: 6. One mark at each level, once everything else stands.
    winner = _edition_to_mark(owner, surviving, written, standing_edition)
    if winner is not None:
        winner.is_default = True
        winner.save(update_fields=("is_default",))
    for state, entry in zip(surviving, written, strict=True):
        marked_row = _release_to_mark(state, entry, standing_releases.get(state.key))
        if marked_row is not None:
            marked_row.is_default = True
            marked_row.save(update_fields=("is_default",))

    return WrittenGraph(game=owner, editions=tuple(written))
