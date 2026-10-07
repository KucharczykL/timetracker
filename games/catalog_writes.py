"""Write a private Game's Editions and Releases.

One call states one Game's whole graph. Nothing here destroys a
row: a removal is a stamp.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, Q

from common.naming import NameKey, name_key
from games.events.dispatch import RowNotHeld
from games.ids import EditionId, PlatformId, ReleaseId
from games.models import Edition, EditionKind, Game, Platform, Release, UserLibrary
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
REMOVED_PLATFORM = "This platform is removed. Put it back, or choose another one."
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
    #: None keeps it; new rows are full.
    kind: EditionKind | None = None
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


@dataclass(frozen=True, slots=True)
class GraphRows:
    """One Game's rows, removed included; written in place.

    An absent pk is another Game's row or none. The
    instances are the ones the write stamps and saves:
    `removed_at` stays current, `is_default` does not
    once the old defaults step down.
    """

    editions: Mapping[EditionId, Edition]
    releases: Mapping[ReleaseId, Release]

    @classmethod
    def of(cls, owner: Game) -> GraphRows:
        """Two reads; relations wired for `clean()`."""
        editions = {row.pk: row for row in Edition.objects.filter(game_id=owner.pk)}
        for edition in editions.values():
            edition.game = owner
        #: A kept mark's save validates its Platform.
        releases = {
            row.pk: row
            for row in Release.objects.filter(edition__game_id=owner.pk).select_related(
                "platform"
            )
        }
        for release in releases.values():
            release.edition = editions[release.edition_id]
        return cls(editions=editions, releases=releases)

    def live_editions(self) -> list[Edition]:
        """Own mark: the constraints read it."""
        return [row for row in self.editions.values() if row.removed_at is None]

    def live_releases(self, edition: Edition) -> list[Release]:
        return [
            row
            for row in self.releases.values()
            if row.edition_id == edition.pk and row.removed_at is None
        ]


def _first_by_pk[Row: Model](rows: Sequence[Row]) -> Row | None:
    return min(rows, key=lambda row: row.pk, default=None)


def _newly_named(row: ReleaseState, stored: Release | None) -> PlatformId | None:
    """None when absent, unsaved or already stored."""
    platform = row.platform
    if platform is None or platform.pk is None:
        return None
    #: A stored removed Platform stays editable.
    if stored is not None and stored.platform_id == platform.pk:
        return None
    return platform.pk


@dataclass(frozen=True, slots=True)
class PlatformLocks:
    """Newly named Platforms, and the live ones locked."""

    wanted: frozenset[PlatformId]
    locked: frozenset[PlatformId]

    @classmethod
    def of(
        cls,
        library: UserLibrary,
        editions: Sequence[EditionState],
        stored_releases: StoredReleases,
    ) -> PlatformLocks:
        """One read, locked by pk.

        The pk order gives writers on different Games one
        lock order; the lock makes a removal in flight wait.
        """
        wanted = frozenset(
            platform
            for state in editions
            if not state.removed
            for row in state.releases
            if not row.removed
            and (platform := _newly_named(row, stored_releases[row.key])) is not None
        )
        if not wanted:
            return cls(wanted=wanted, locked=frozenset())
        locked = (
            Platform.objects.select_for_update(no_key=True)
            .filter(Q(library__isnull=True) | Q(library=library))
            .filter(pk__in=wanted, removed_at__isnull=True)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        return cls(wanted=wanted, locked=frozenset(locked))

    def holds(self, platform: PlatformId) -> bool:
        """Whether the read locked it."""
        if platform not in self.wanted:
            raise LookupError(f"Platform {platform} was never asked for.")
        return platform in self.locked


def _refuse_platform(
    library: UserLibrary,
    row: ReleaseState,
    stored: Release | None,
    locks: PlatformLocks,
) -> None:
    """Shared or own; live unless already stored."""
    platform = row.platform
    if platform is None:
        return
    if platform.library_id not in (None, library.pk):
        raise GraphRefused(FOREIGN_PLATFORM, key=row.key)
    if platform.pk is None:
        raise GraphRefused(REMOVED_PLATFORM, key=row.key)
    #: Not locked: missing, removed or foreign.
    newly = _newly_named(row, stored)
    if newly is not None and not locks.holds(newly):
        raise GraphRefused(REMOVED_PLATFORM, key=row.key)


def _writable_game(game_id, library: UserLibrary) -> Game:
    """The Game this library may write, locked."""
    game = Game.objects.select_for_update().filter(pk=game_id).first()
    if game is None:
        raise RowNotHeld(f"Game {game_id} is gone before library {library.pk}'s lock.")
    #: `GraphRefused` with no key: the sentence belongs to the whole
    #: statement, and a caller shows it rather than raising a page.
    if game.library_id is None:
        raise GraphRefused(SHARED_GAME)
    if game.library_id != library.pk:
        raise GraphRefused(FOREIGN_GAME)
    if game.removed_at is not None:
        raise GraphRefused(REMOVED_GAME)
    return game


def _resolved_edition(rows: GraphRows, state: EditionState) -> Edition | None:
    """The stored row a state names."""
    if state.edition is None:
        return None
    #: Missing or another Game's: not mapped.
    stored = rows.editions.get(state.edition.pk)
    if stored is None:
        raise GraphRefused(FOREIGN_ROW, key=state.key)
    #: A stated removal of a row already gone states what is true.
    if stored.removed_at is not None and not state.removed:
        raise GraphRefused(REMOVED_EDITION, key=state.key)
    return stored


def _resolved_release(
    rows: GraphRows, parent: Edition | None, state: ReleaseState
) -> Release | None:
    """The stored Release a state names."""
    if state.release is None:
        return None
    stored = rows.releases.get(state.release.pk)
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
    taken: set[NameKey] = {name_key(edition.name) for edition in untouched} - {""}
    for state in surviving:
        wanted = name_key(state.name)
        if not wanted:
            continue
        if wanted in taken:
            raise GraphRefused(DUPLICATE_EDITION_NAME, key=state.key)
        taken.add(wanted)


def _refuse_the_set(
    rows: GraphRows,
    library: UserLibrary,
    editions: Sequence[EditionState],
    stored_editions: StoredEditions,
    stored_releases: StoredReleases,
    locks: PlatformLocks,
) -> None:
    """Everything the statement can be wrong about."""
    surviving = [state for state in editions if not state.removed]
    named = {stored.pk for stored in stored_editions.values() if stored is not None}
    untouched = [row for row in rows.live_editions() if row.pk not in named]
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
        stated = [row for row in state.releases if not row.removed]
        marked_rows = [row for row in stated if row.is_default]
        if len(marked_rows) > 1:
            raise GraphRefused(TWO_DEFAULT_RELEASES, key=marked_rows[1].key)
        for row in stated:
            _refuse_platform(library, row, stored_releases[row.key], locks)


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
    """Creates or updates it, then its Releases."""
    name = state.name.strip()
    if stored is None:
        edition = Edition.objects.create(
            game=owner,
            name=name,
            kind=state.kind or EditionKind.FULL,
            is_default=False,
        )
    else:
        edition = stored
        edition.name = name
        edition.kind = state.kind or stored.kind
        edition.is_default = False
        edition.save(update_fields=("name", "kind", "is_default"))
    written_releases = tuple(
        WrittenRelease(
            row.key, _written_release(edition, row, stored_releases[row.key])
        )
        for row in state.releases
        if not row.removed
    )
    return WrittenEdition(key=state.key, edition=edition, releases=written_releases)


def _edition_to_mark(
    rows: GraphRows,
    surviving: Sequence[EditionState],
    written: Sequence[WrittenEdition],
    standing: Edition | None,
) -> Edition | None:
    """The stated mark, else standing, else first."""
    for state, entry in zip(surviving, written, strict=True):
        if state.is_default:
            return entry.edition
    #: `remove()` stamped the map's own instance.
    if standing is not None and standing.removed_at is None:
        return standing
    if written:
        return written[0].edition
    return _first_by_pk(rows.live_editions())


def _release_to_mark(
    rows: GraphRows,
    state: EditionState,
    entry: WrittenEdition,
    standing: Release | None,
) -> Release | None:
    """The same rule, one level down."""
    stated = [row for row in state.releases if not row.removed]
    for row, written in zip(stated, entry.releases, strict=True):
        if row.is_default:
            return written.release
    if standing is not None and standing.removed_at is None:
        return standing
    if entry.releases:
        return entry.releases[0].release
    return _first_by_pk(rows.live_releases(entry.edition))


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
    if game._state.adding:
        raise ValueError(f"state_catalog_graph takes a saved Game; {game} is unsaved.")
    owner = _writable_game(game.pk, library)
    rows = GraphRows.of(owner)
    stored_editions: StoredEditions = {
        state.key: _resolved_edition(rows, state) for state in editions
    }
    stored_releases: StoredReleases = {
        row.key: _resolved_release(rows, stored_editions[state.key], row)
        for state in editions
        for row in state.releases
    }
    _refuse_repeated_rows(stored_editions)
    _refuse_repeated_rows(stored_releases)
    locks = PlatformLocks.of(library, editions, stored_releases)
    _refuse_the_set(rows, library, editions, stored_editions, stored_releases, locks)

    surviving = [state for state in editions if not state.removed]
    standing_edition = next(
        (row for row in rows.live_editions() if row.is_default), None
    )
    standing_releases: dict[RowKey, Release | None] = {}
    surviving_stored: list[Edition] = []
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None:
            surviving_stored.append(stored)
            standing_releases[state.key] = next(
                (row for row in rows.live_releases(stored) if row.is_default), None
            )

    #: 1. Every live default steps down first. Both constraints
    #: permit at most one, thus zero is legal and the rest is free.
    Edition.objects.filter(
        game_id=owner.pk, removed_at__isnull=True, is_default=True
    ).update(is_default=False)
    if surviving_stored:
        Release.objects.filter(
            edition_id__in=[stored.pk for stored in surviving_stored],
            removed_at__isnull=True,
            is_default=True,
        ).update(is_default=False)

    #: 2. A removal stamps each stated row alone.
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
    renamed = [
        stored.pk
        for state in surviving
        if (stored := stored_editions[state.key]) is not None
        and stored.name.strip() != state.name.strip()
    ]
    if renamed:
        Edition.objects.filter(pk__in=renamed).update(name="")

    #: 4 and 5. Each surviving row, in statement order.
    written = [
        _written_edition(owner, state, stored_editions[state.key], stored_releases)
        for state in surviving
    ]

    #: 6. One mark at each level, once everything else stands.
    winner = _edition_to_mark(rows, surviving, written, standing_edition)
    if winner is not None:
        winner.is_default = True
        winner.save(update_fields=("is_default",))
    for state, entry in zip(surviving, written, strict=True):
        marked_row = _release_to_mark(
            rows, state, entry, standing_releases.get(state.key)
        )
        if marked_row is not None:
            marked_row.is_default = True
            marked_row.save(update_fields=("is_default",))

    return WrittenGraph(game=owner, editions=tuple(written))
