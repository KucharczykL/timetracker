"""Convert legacy purchases into copies and purchases."""

# conversion-tooling

import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import partial
from typing import Any, Literal, NamedTuple, TypedDict

from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, connection, models, transaction
from django.db.models import Case, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from games.api_creation import RowRefused
from games.backfill.purchase_plan import (
    ConvertedShare,
    CopyShape,
    CurrencyCode,
    GameId,
    LegacyId,
    LegacyRow,
    LibraryId,
    PlannedCopy,
    PurchaseId,
    RowNotConvertible,
    legacy_refusals,
    plan,
)
from games.catalog_addons import state_addon
from games.catalog_compat import identity_taken, write_and_mirror
from games.catalog_release import release_on
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    EndEntryAccess,
    EntryStatement,
    RecordEntry,
    RemoveEntry,
)
from games.commands.playergame import RecordPlayerGameFacts
from games.commands.purchase import (
    RefundPurchase,
    RemovePurchase,
    purchase_creation_events,
)
from games.conversion import request_revaluation
from games.conversion_review import ORIGIN, RECONCILIATION_ONLY, Category
from games.end_ways import EndWay
from games.events.append import LockedStream
from games.events.conflicts import CommandConflict
from games.events.dispatch import (
    CommandContext,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
)
from games.events.idempotency import (
    FINGERPRINT_VERSION,
    IdempotencyKey,
    IdempotencyKeyMismatch,
    ReplayedAppend,
    UnchangedAppend,
    fingerprint_command_input,
    idempotent_append,
)
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.purchase import PURCHASE_CREATED
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.vocabulary import NewEvent, Unchanged
from games.models import (
    Edition,
    EditionKind,
    ExchangeRate,
    Game,
    GameKind,
    LibraryEntry,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    Platform,
    PlayerGame,
    Purchase,
    PurchaseConversionState,
    PurchaseValuation,
    Release,
    UserLibrary,
)
from games.projections import projection_models
from games.reads.entries import EntryId, library_entries
from games.reads.purchases import valuation_inputs
from games.valuations import ValuationInput, needs_rate, publish_valuations, seeded
from timetracker.temporal import TemporalValue

logger = logging.getLogger("games")

ISSUE = 723
DEMO_EDITION = "Demo"

type ConversionAct = Literal[
    "created", "entry", "refunded", "ended", "removed", "removed_copy"
]
type CommandInput = dict[str, Any]
type Build = Callable[[], Sequence[NewEvent] | Unchanged]
type PlannedRows = list[tuple[LegacyRow, list[PlannedCopy]]]


class ConversionMetadata(TypedDict):
    """What a converted event names."""

    origin: Literal["conversion"]
    issue: int
    legacy_purchases: list[str]
    review: list[str]


class ConversionDefect(Exception):
    """A state the pass cannot read."""


#: A row's refusal; the person restates it.
REFUSALS = (CommandRejected, RowRefused, ValidationError, RowNotConvertible)
#: A row's defect; data or code wrong.
DEFECTS = (
    CommandConflict,
    RowUnreadable,
    RowNotHeld,
    IntegrityError,
    DataError,
    ConversionDefect,
)


class RefusalKind(StrEnum):
    """Whether a person or a repair answers."""

    REFUSED = "refused"
    DEFECT = "defect"


class Refusal(NamedTuple):
    """One legacy row the pass cannot state."""

    #: None: the library's own state.
    legacy_id: LegacyId | None
    game_id: GameId | None
    reason: str
    kind: RefusalKind = RefusalKind.REFUSED

    def __str__(self) -> str:
        subject = (
            "library state" if self.legacy_id is None else f"purchase {self.legacy_id}"
        )
        game = "" if self.game_id is None else f", game {self.game_id}"
        return f"{subject}{game} {self.kind}: {self.reason}"


class PurchaseConversionRefused(Exception):
    """Rows the pass cannot state; nothing written."""

    def __init__(self, refusals: Iterable[Refusal]) -> None:
        self.refusals = tuple(refusals)
        named = "\n".join(f"- {refusal}" for refusal in self.refusals)
        super().__init__(
            f"{len(self.refusals)} legacy purchase refusal(s); nothing was "
            f"converted:\n{named}"
        )


class PurchaseConversionDrift(Exception):
    """Schema or replay drift; nothing written."""


class ConvertedCopy(NamedTuple):
    """A planned copy, as stated."""

    planned: PlannedCopy
    entry_id: EntryId
    purchase_id: PurchaseId | None
    #: Its own copy; else the base game's.
    own_copy: bool
    categories: tuple[Category, ...]


class SkippedCopy(NamedTuple):
    """A copy whose game the library removed."""

    planned: PlannedCopy

    @property
    def legacy_id(self) -> LegacyId:
        return self.planned.row.id

    @property
    def game_id(self) -> GameId:
        return self.planned.game_id


class UnvaluedPurchase(NamedTuple):
    """A purchase the pass did not value."""

    purchase_id: PurchaseId
    legacy_id: LegacyId
    reason: str


@dataclass(frozen=True, slots=True)
class LibraryConversion:
    """What the pass did in one library."""

    library: UserLibrary
    appended: int
    copies: tuple[ConvertedCopy, ...]
    skipped: tuple[SkippedCopy, ...]
    unvalued: tuple[UnvaluedPurchase, ...]
    #: Seeded from a legacy share and rate.
    rated: tuple[PurchaseId, ...]


class PurchaseConversion(NamedTuple):
    """What one pass did."""

    libraries: tuple[LibraryConversion, ...]

    @property
    def appended(self) -> int:
        return sum(library.appended for library in self.libraries)

    @property
    def nothing_awaited(self) -> bool:
        """Every key replayed; nothing appended."""
        return self.appended == 0


def _key(act: ConversionAct, legacy_id: LegacyId, game_id: GameId) -> IdempotencyKey:
    return f"conversion:{ISSUE}:{act}:{legacy_id}:{game_id}"


def _exclusion_key(game_id: GameId) -> IdempotencyKey:
    return f"conversion:{ISSUE}:excluded:{game_id}"


def legacy_rows(
    model: type[models.Model], library_id: LibraryId | None = None
) -> list[LegacyRow]:
    """Legacy rows; the model may be historical."""
    rows = model._base_manager.all()
    if library_id is not None:
        rows = rows.filter(library_id=library_id)
    games = model._meta.get_field("games")
    assert isinstance(games, models.ManyToManyField)
    through = games.remote_field.through
    assert through is not None
    own, other = games.m2m_field_name(), games.m2m_reverse_field_name()
    linked: defaultdict[LegacyId, list[GameId]] = defaultdict(list)
    for purchase_id, game_id in through._base_manager.filter(
        **{f"{own}__in": rows.values("pk")}
    ).values_list(f"{own}_id", f"{other}_id"):
        linked[purchase_id].append(game_id)
    columns = rows.order_by("date_purchased", "pk").values(
        "id",
        "library_id",
        "platform_id",
        "date_purchased",
        "date_refunded",
        "infinite",
        "price",
        "price_currency",
        "converted_price",
        "converted_currency",
        "ownership_type",
        "type",
        "name",
        "related_game_id",
        "removed_at",
        platform_name=Coalesce("platform__name", Value("")),
    )
    return [
        LegacyRow(**values, game_ids=tuple(sorted(linked[values["id"]])))
        for values in columns
    ]


def _removed_games(library_id: LibraryId, game_ids: set[GameId]) -> set[GameId]:
    """Games the catalog or the library removed."""
    marked = Game.objects.filter(pk__in=game_ids, removed_at__isnull=False)
    untracked = PlayerGame.objects.filter(
        library_id=library_id, game_id__in=game_ids, removed_at__isnull=False
    )
    return set(marked.values_list("pk", flat=True)) | set(
        untracked.values_list("game_id", flat=True)
    )


def _by_library(planned: PlannedRows) -> dict[LibraryId, PlannedRows]:
    by_library: defaultdict[LibraryId, PlannedRows] = defaultdict(list)
    for row, copies in planned:
        by_library[row.library_id].append((row, copies))
    return by_library


def convert_purchases(
    rows: Sequence[LegacyRow], *, recorded_at: datetime | None = None
) -> PurchaseConversion:
    """State every legacy row; all or nothing."""
    refusals = [
        Refusal(row.id, None, reason) for row in rows for reason in legacy_refusals(row)
    ]
    if refusals:
        raise PurchaseConversionRefused(refusals)
    #: A fresh database holds no rows.
    if not rows:
        return PurchaseConversion(())
    _require_the_schema_this_pass_was_written_for()
    instant = timezone.now() if recorded_at is None else recorded_at
    by_library = _by_library([(row, plan(row)) for row in rows])
    libraries = UserLibrary.objects.select_related("user").in_bulk(by_library)
    with transaction.atomic():
        passes = [
            _LibraryPass(libraries[library_id], planned, instant)
            for library_id, planned in by_library.items()
        ]
        done = tuple(library_pass.run() for library_pass in passes)
        refused = [
            refusal for library_pass in passes for refusal in library_pass.refusals
        ]
        if refused:
            raise PurchaseConversionRefused(refused)
        appended = [library.library for library in done if library.appended]
        if appended:
            _analyze()
            require_replay_parity(appended)
    return PurchaseConversion(done)


def _one[T](found: T | None, what: str) -> T:
    """The row the pass relies on."""
    if found is None:
        raise ConversionDefect(f"No {what}.")
    return found


class _Appender:
    """Appends under the pass's own keys."""

    def __init__(self, library: UserLibrary, recorded_at: datetime) -> None:
        self.library = library
        self.recorded_at = recorded_at
        self.correlation_id = uuid.uuid7()
        self.appended = 0

    def _events(self, first: int, last: int) -> tuple[LibraryEvent, ...]:
        return tuple(
            LibraryEvent.objects.filter(
                library=self.library, sequence__range=(first, last)
            ).order_by("sequence")
        )

    def held(self, keys: Iterable[IdempotencyKey]) -> set[IdempotencyKey]:
        """The keys this library already answered."""
        return set(
            LibraryIdempotencyRecord.objects.filter(
                library=self.library, idempotency_key__in=list(keys)
            ).values_list("idempotency_key", flat=True)
        )

    def replayed(
        self, key: IdempotencyKey, command_input: CommandInput
    ) -> tuple[LibraryEvent, ...] | None:
        """The key's events; None if never answered."""
        record = LibraryIdempotencyRecord.objects.filter(
            library=self.library, idempotency_key=key
        ).first()
        if record is None:
            return None
        if record.fingerprint_version != FINGERPRINT_VERSION:
            raise ConversionDefect(
                f"Key {key!r} holds fingerprint version "
                f"{record.fingerprint_version}, not {FINGERPRINT_VERSION}; its "
                "legacy facts cannot be compared."
            )
        if record.request_fingerprint != fingerprint_command_input(command_input):
            raise IdempotencyKeyMismatch(
                f"Key {key!r} recorded other legacy facts; the legacy row "
                "changed after its conversion."
            )
        if record.first_sequence is None or record.last_sequence is None:
            return ()
        return self._events(record.first_sequence, record.last_sequence)

    def append(
        self,
        key: IdempotencyKey,
        command_input: CommandInput,
        build: Build,
        metadata: ConversionMetadata,
    ) -> tuple[LibraryEvent, ...]:
        """Append once; a repeat reads back."""
        replayed = self.replayed(key, command_input)
        if replayed is not None:
            return replayed

        def built(stream: LockedStream) -> Sequence[NewEvent] | Unchanged:
            return build()

        result = idempotent_append(
            self.library,
            idempotency_key=key,
            command_input=command_input,
            build=built,
            actor=self.library.user,
            correlation_id=self.correlation_id,
            source_metadata=dict(metadata),
            recorded_at=self.recorded_at,
        )
        if isinstance(result, ReplayedAppend):
            return self._events(result.first_sequence, result.last_sequence)
        if isinstance(result, UnchangedAppend):
            logger.info(
                "[purchase conversion]: %s answered unchanged: %s", key, result.reason
            )
            return ()
        self.appended += len(result.events)
        return result.events


def _created(events: Iterable[LibraryEvent], event_type: str) -> uuid.UUID | None:
    for event in events:
        if event.event_type == event_type:
            return event.aggregate_id
    return None


def _default_release(game: Game) -> Release:
    """Default Edition's default Release, else first live."""
    release = (
        Release.objects.filter(edition__game=game)
        .alive()
        .order_by("-edition__is_default", "-is_default", "edition_id", "id")
        .select_related("platform")
        .first()
    )
    if release is None:
        raise RowRefused(f"{game.name} has no release to hold a copy.")
    return release


class _LibraryPass:
    """One library's rows; attached rows last."""

    def __init__(
        self, library: UserLibrary, planned: PlannedRows, recorded_at: datetime
    ) -> None:
        self.library = library
        #: Attached copies ride copies stated first.
        self.planned = sorted(planned, key=lambda pair: _is_attached(pair[1]))
        self.context = CommandContext(library=library, actor=library.user)
        self.appender = _Appender(library, recorded_at)
        self.copies: list[ConvertedCopy] = []
        self.skipped: list[SkippedCopy] = []
        self.unvalued: list[UnvaluedPurchase] = []
        self.rated: list[PurchaseId] = []
        self.refusals: list[Refusal] = []
        rows = [row for row, _ in planned]
        self.removed = _removed_games(
            library.pk, {game for row in rows for game in row.game_ids}
        )
        self.hand_recorded = self._hand_recorded_games()
        #: A DLC row's games are its base's.
        live = [row for row in rows if row.removed_at is None and row.type != "dlc"]
        infinite = {game for row in live if row.infinite for game in row.game_ids}
        finite = {game for row in live if not row.infinite for game in row.game_ids}
        self.mixed = infinite & finite
        #: Game key to its live infinite rows.
        self.infinite: defaultdict[GameId, list[LegacyId]] = defaultdict(list)
        #: Every game a converted copy names.
        self.excludable: set[GameId] = set()

    def _hand_recorded_games(self) -> set[GameId]:
        converted = LibraryEvent.objects.filter(
            library=self.library,
            event_type=LIBRARYENTRY_CREATED.event_type,
            source_metadata__origin=ORIGIN,
        ).values("aggregate_id")
        return set(
            LibraryEntry.objects.filter(library=self.library)
            .exclude(pk__in=converted)
            .values_list("player_game__game_id", flat=True)
        )

    def run(self) -> LibraryConversion:
        for row, copies in self.planned:
            self._row(row, copies)
        self._exclusions()
        if self.appender.appended and not self.refusals:
            try:
                self._valuations()
            except ConversionDefect as error:
                logger.exception("[purchase conversion]: valuation defect")
                self.refusals.append(
                    Refusal(None, None, str(error), kind=RefusalKind.DEFECT)
                )
        return LibraryConversion(
            library=self.library,
            appended=self.appender.appended,
            copies=tuple(self.copies),
            skipped=tuple(self.skipped),
            unvalued=tuple(self.unvalued),
            rated=tuple(self.rated),
        )

    def _row(self, row: LegacyRow, copies: Sequence[PlannedCopy]) -> None:
        game_id: GameId | None = None
        try:
            with transaction.atomic():
                for copy in copies:
                    game_id = copy.game_id
                    self._copy(copy)
        except REFUSALS as error:
            self.refusals.append(Refusal(row.id, game_id, _reason(error)))
        except DEFECTS as error:
            logger.exception(
                "[purchase conversion]: defect on legacy purchase %s, game %s",
                row.id,
                game_id,
            )
            self.refusals.append(
                Refusal(row.id, game_id, _defect_reason(error), kind=RefusalKind.DEFECT)
            )

    def _refuse_withdrawn_acts(self, copy: PlannedCopy) -> None:
        """Acts the legacy row no longer states."""
        row, game = copy.row, copy.game_id
        withdrawn: dict[ConversionAct, str] = {
            "entry" if copy.purchase is not None else "created": "its price changed",
        }
        if copy.refunded is None:
            withdrawn |= {"refunded": "its refund", "ended": "its refund"}
        if row.removed_at is None:
            withdrawn |= {"removed": "its removal", "removed_copy": "its removal"}
        keys = {_key(act, row.id, game): reason for act, reason in withdrawn.items()}
        held = self.appender.held(keys)
        if held:
            reasons = sorted({keys[key] for key in held})
            raise ConversionDefect(
                f"Legacy purchase {row.id}, game {game}: {', '.join(reasons)} "
                "changed after its conversion."
            )

    def _copy(self, copy: PlannedCopy) -> None:
        row = copy.row
        if copy.game_id in self.removed:
            logger.warning(
                "[purchase conversion]: skipped legacy purchase %s, game %s "
                "the library removed; its price %s is not converted",
                row.id,
                copy.game_id,
                None if copy.purchase is None else copy.purchase.price.amount,
            )
            self.skipped.append(SkippedCopy(copy))
            return
        self._refuse_withdrawn_acts(copy)
        categories = list(copy.categories)
        if copy.game_id in self.mixed:
            categories.append(Category.MIXED_INFINITE)
        act: ConversionAct = "created" if copy.purchase is not None else "entry"
        facts = _creation_input(copy)
        key = _key(act, row.id, copy.game_id)
        events = self.appender.replayed(key, facts)
        if events is None:
            events = self._create(copy, key, facts, categories)
        purchase_id = _created(events, PURCHASE_CREATED.event_type)
        entry_id = _created(events, LIBRARYENTRY_CREATED.event_type)
        own_copy = entry_id is not None
        if entry_id is None:
            if purchase_id is None:
                raise ConversionDefect(
                    f"Key {key!r} answered no creation for legacy purchase "
                    f"{row.id}, game {copy.game_id}."
                )
            entry_id = _one(
                Purchase.objects.filter(pk=purchase_id)
                .values_list("entry_id", flat=True)
                .first(),
                f"purchase {purchase_id} of key {key!r}",
            )
        converted = ConvertedCopy(
            copy, entry_id, purchase_id, own_copy, tuple(categories)
        )
        metadata = _metadata([row.id], categories)
        if copy.refunded is not None:
            self._refund(converted, copy.refunded, metadata)
        if row.removed_at is not None:
            self._remove(converted, metadata)
        #: An infinite DLC excludes its own Game.
        excluded = (
            self._game_of(entry_id)
            if copy.shape == CopyShape.ADDON_GAME
            else copy.game_id
        )
        self.excludable.add(excluded)
        if row.infinite and row.removed_at is None:
            self.infinite[excluded].append(row.id)
        self.copies.append(converted)

    def _create(
        self,
        copy: PlannedCopy,
        key: IdempotencyKey,
        facts: CommandInput,
        categories: list[Category],
    ) -> tuple[LibraryEvent, ...]:
        held = (
            self._base_copy(copy)
            if copy.shape == CopyShape.ATTACHED and copy.purchase is not None
            else None
        )
        if copy.shape == CopyShape.ATTACHED and held is None:
            categories.append(Category.OWN_COPY_FALLBACK)
        if (
            held is None
            and copy.shape != CopyShape.ADDON_GAME
            and copy.game_id in self.hand_recorded
        ):
            categories.append(Category.HAND_RECORDED_COPY)
        statement: EntryId | EntryStatement
        if held is not None:
            statement = held
        else:
            statement = EntryStatement(
                release_id=self._release_for(copy, categories).pk,
                access=copy.access,
                format=copy.format,
                acquired=ActStatement(copy.purchased, ""),
            )
        build: Build
        if copy.purchase is None:
            assert isinstance(statement, EntryStatement)
            record = RecordEntry(
                release_id=statement.release_id,
                access=statement.access,
                format=statement.format,
                acquired=statement.acquired,
            )
            build = partial(record.build, self.context)
        else:
            build = partial(
                purchase_creation_events,
                self.context,
                copy=statement,
                kind=copy.purchase.kind,
                name=copy.purchase.name,
                price=copy.purchase.price,
                purchased=ActStatement(copy.purchased, ""),
                purchase_id=copy.purchase.key or uuid.uuid7(),
            )

        return self.appender.append(
            key, facts, build, _metadata([copy.row.id], categories)
        )

    def _refund(
        self,
        copy: ConvertedCopy,
        refunded: TemporalValue,
        metadata: ConversionMetadata,
    ) -> None:
        planned = copy.planned
        row = planned.row
        facts: CommandInput = {**_act_input(planned), "refunded": refunded.serialize()}
        if copy.purchase_id is not None:
            refund = RefundPurchase(
                purchase_id=copy.purchase_id,
                statement=ActStatement(refunded, ""),
            )
            self.appender.append(
                _key("refunded", row.id, planned.game_id),
                facts,
                partial(refund.build, self.context),
                metadata,
            )
        if copy.own_copy and not planned.refund_ends_it:
            end = EndEntryAccess(
                entry_id=copy.entry_id,
                statement=WayActStatement(refunded, EndWay.REFUNDED),
            )
            self.appender.append(
                _key("ended", row.id, planned.game_id),
                facts,
                partial(end.build, self.context),
                metadata,
            )

    def _remove(self, copy: ConvertedCopy, metadata: ConversionMetadata) -> None:
        planned = copy.planned
        row = planned.row
        facts = _act_input(planned)
        if copy.purchase_id is not None:
            removal = RemovePurchase(purchase_id=copy.purchase_id)
            self.appender.append(
                _key("removed", row.id, planned.game_id),
                facts,
                partial(removal.build, self.context),
                metadata,
            )
        if copy.own_copy:
            copy_removal = RemoveEntry(entry_id=copy.entry_id)
            self.appender.append(
                _key("removed_copy", row.id, planned.game_id),
                facts,
                partial(copy_removal.build, self.context),
                metadata,
            )

    def _game_of(self, entry_id: EntryId) -> GameId:
        return _one(
            LibraryEntry.objects.filter(pk=entry_id)
            .values_list("player_game__game_id", flat=True)
            .first(),
            f"copy {entry_id}",
        )

    def _base_copy(self, copy: PlannedCopy) -> EntryId | None:
        """Base's live Owned copy, platform first."""
        platform = copy.row.platform_id
        candidates = (
            library_entries(self.library)
            .filter(
                player_game__game_id=copy.game_id,
                access="owned",
                access_end_recorded_at__isnull=True,
            )
            .annotate(
                elsewhere=Case(
                    When(release__platform_id=platform, then=Value(0)),
                    default=Value(1),
                )
                if platform is not None
                else Value(0)
            )
            .order_by("elsewhere", "acquired_lower", "pk")
        )
        return candidates.values_list("pk", flat=True).first()

    def _release_for(self, copy: PlannedCopy, categories: list[Category]) -> Release:
        """The copy's Release, tagged where made."""
        row = copy.row
        game = _one(
            Game.objects.filter(pk=copy.game_id).first(), f"game {copy.game_id}"
        )
        platform = (
            None
            if row.platform_id is None
            else _one(
                Platform.objects.filter(pk=row.platform_id).first(),
                f"platform {row.platform_id}",
            )
        )
        if copy.shape == CopyShape.ADDON_GAME:
            game = self._dlc_game(
                row, base=game, platform=platform, categories=categories
            )
        default = _default_release(game)
        platform = default.platform if platform is None else platform
        if row.ownership_type == "de":
            release, made = self._demo_release(game, platform)
        elif platform is None or platform.pk == default.platform_id:
            release, made = default, False
        else:
            reached = release_on(self.library, game, platform)
            release, made = reached.release, reached.created
        if made:
            categories.append(Category.CREATED_RELEASE)
        return release

    def _dlc_game(
        self,
        row: LegacyRow,
        *,
        base: Game,
        platform: Platform | None,
        categories: list[Category],
    ) -> Game:
        """The DLC's own Game, row's platform."""
        name = row.name.strip()
        #: A name another live Game holds.
        renamed = f"{base.name}: {name}"
        standing = (
            Game.objects.filter(
                library=self.library,
                parent=base,
                name__in=[name, renamed],
                kind=GameKind.DLC,
            )
            .alive()
            .order_by("pk")
            .first()
        )
        if standing is not None:
            return standing
        if platform is None:
            platform = _default_release(base).platform
        if identity_taken(self.library.pk, name, platform, None):
            name = renamed
            categories.append(Category.RENAMED_ADDON)
        game = Game(library=self.library, name=name, sort_name=name)
        state_addon(game, kind=GameKind.DLC, parent=base, library=self.library)
        game.save()
        write_and_mirror(
            game,
            partial(
                state_catalog_graph,
                game=game,
                library=self.library,
                editions=[
                    EditionState(
                        key="edition",
                        is_default=True,
                        releases=(
                            ReleaseState(
                                key="release", platform=platform, is_default=True
                            ),
                        ),
                    )
                ],
            ),
        )
        return game

    def _demo_release(
        self, game: Game, platform: Platform | None
    ) -> tuple[Release, bool]:
        edition = (
            Edition.objects.filter(
                game=game, name=DEMO_EDITION, kind=EditionKind.PRERELEASE
            )
            .alive()
            .order_by("pk")
            .first()
        )
        if edition is not None:
            standing = (
                Release.objects.filter(edition=edition, platform=platform)
                .alive()
                .order_by("-is_default", "pk")
                .first()
            )
            if standing is not None:
                return standing, False
        statement = EditionState(
            key="demo",
            edition=edition,
            name=DEMO_EDITION,
            kind=EditionKind.PRERELEASE,
            releases=(
                ReleaseState(
                    key="release", platform=platform, is_default=edition is None
                ),
            ),
        )
        written = write_and_mirror(
            game,
            partial(
                state_catalog_graph,
                game=game,
                library=self.library,
                editions=[statement],
            ),
        )
        made = next(
            (
                written_release.release
                for written_release in written.editions[0].releases
                if written_release.key == "release"
            ),
            None,
        )
        return _one(made, f"Demo release of {game.pk}"), True

    def _exclusions(self) -> None:
        withdrawn = self.appender.held(
            _exclusion_key(game) for game in self.excludable - set(self.infinite)
        )
        self.refusals += [
            Refusal(
                None,
                None,
                f"{key!r} excluded a game no live infinite row names now",
                kind=RefusalKind.DEFECT,
            )
            for key in sorted(withdrawn)
        ]
        tracked = set(
            PlayerGame.objects.filter(
                library=self.library,
                game_id__in=self.infinite,
                removed_at__isnull=True,
            ).values_list("game_id", flat=True)
        )
        for game_id, legacy_ids in self.infinite.items():
            named = ", ".join(str(legacy_id) for legacy_id in legacy_ids)
            if game_id not in tracked:
                self.refusals.append(
                    Refusal(
                        legacy_ids[0],
                        game_id,
                        f"the infinite rows {named} name a game no copy tracked",
                        kind=RefusalKind.DEFECT,
                    )
                )
                continue
            facts = RecordPlayerGameFacts(
                game_id=game_id,
                excluded_from_unfinished=True,
                excluded_from_dropped=True,
            )
            try:
                with transaction.atomic():
                    self.appender.append(
                        _exclusion_key(game_id),
                        {"act": "excluded", "game": str(game_id)},
                        partial(facts.build, self.context),
                        _metadata(legacy_ids, []),
                    )
            except REFUSALS as error:
                self.refusals.append(
                    Refusal(legacy_ids[0], game_id, f"{_reason(error)} (rows {named})")
                )
            except DEFECTS as error:
                logger.exception(
                    "[purchase conversion]: defect excluding game %s", game_id
                )
                self.refusals.append(
                    Refusal(
                        legacy_ids[0],
                        game_id,
                        f"{_defect_reason(error)} (rows {named})",
                        kind=RefusalKind.DEFECT,
                    )
                )

    def _unvalued(
        self, copy: ConvertedCopy, purchase_id: PurchaseId, reason: str
    ) -> None:
        logger.warning(
            "[purchase conversion]: purchase %s of legacy purchase %s is not "
            "valued: %s",
            purchase_id,
            copy.planned.row.id,
            reason,
        )
        self.unvalued.append(UnvaluedPurchase(purchase_id, copy.planned.row.id, reason))

    def _valuations(self) -> None:
        state = _one(
            PurchaseConversionState.objects.select_for_update()
            .filter(library=self.library)
            .first(),
            f"conversion state of library {self.library.pk}",
        )
        converted = {
            copy.purchase_id: copy
            for copy in self.copies
            if copy.purchase_id is not None
        }
        inputs = [
            facts
            for facts in valuation_inputs(self.library)
            if facts.purchase_id in converted
        ]
        if state.published_version and state.published_currency:
            self._seed(state, converted, inputs)
        else:
            for facts in inputs:
                self._unvalued(
                    converted[facts.purchase_id],
                    facts.purchase_id,
                    "the library has published no target currency",
                )
        if state.requested_currency.strip():
            request_revaluation(self.library)

    def _seed(
        self,
        state: PurchaseConversionState,
        converted: dict[PurchaseId, ConvertedCopy],
        inputs: Sequence[ValuationInput],
    ) -> None:
        """Value converted purchases at the legacy amounts."""
        target = state.published_currency
        rows = list(PurchaseValuation.objects.filter(library=self.library))
        valued = {row.purchase_id for row in rows}
        for facts in inputs:
            if facts.purchase_id in valued:
                continue
            copy = converted[facts.purchase_id]
            rate: Decimal | None = None
            amount = facts.amount
            if needs_rate(facts, target):
                rate = (
                    ExchangeRate.objects.filter(
                        currency_from=facts.currency,
                        currency_to=target,
                        year=facts.rate_year,
                    )
                    .values_list("rate", flat=True)
                    .first()
                )
                purchase = copy.planned.purchase
                share = None if purchase is None else purchase.converted
                reason = _unvalued_reason(facts, target, rate, share)
                if reason is not None:
                    self._unvalued(copy, facts.purchase_id, reason)
                    continue
                assert share is not None
                amount = share.amount
                self.rated.append(facts.purchase_id)
            rows.append(
                seeded(
                    facts,
                    target,
                    rate,
                    amount,
                    library=self.library,
                    version=state.published_version,
                    calculated_at=self.appender.recorded_at,
                )
            )
        publish_valuations(self.library, rows)


def _is_attached(copies: Sequence[PlannedCopy]) -> bool:
    return copies[0].shape == CopyShape.ATTACHED


def _unvalued_reason(
    facts: ValuationInput,
    target: CurrencyCode,
    rate: Decimal | None,
    share: ConvertedShare | None,
) -> str | None:
    """Why a rated purchase cannot seed."""
    if rate is None:
        return f"no stored {facts.currency}->{target} rate for {facts.rate_year}"
    if share is None:
        return "the legacy row holds no converted amount"
    if share.currency != target:
        return f"the legacy converted currency {share.currency} is not {target}"
    return None


def _reason(error: Exception) -> str:
    if isinstance(error, CommandRejected) and error.sentence:
        return f"{error.sentence} ({error})"
    if isinstance(error, ValidationError):
        if hasattr(error, "error_dict"):
            return "; ".join(
                f"{field}: {' '.join(messages)}"
                for field, messages in error.message_dict.items()
            )
        return " ".join(error.messages)
    return str(error) or type(error).__name__


def _defect_reason(error: Exception) -> str:
    cause = error.__cause__
    detail = f" ({type(cause).__name__}: {cause})" if cause is not None else ""
    return f"{type(error).__name__}: {error}{detail}"


def _creation_input(copy: PlannedCopy) -> CommandInput:
    """Legacy-derived facts; never a minted key."""
    purchase = copy.purchase
    return {
        **_act_input(copy),
        "access": copy.access,
        "format": copy.format,
        "platform": None if copy.row.platform_id is None else str(copy.row.platform_id),
        "kind": None if purchase is None else purchase.kind,
        "name": "" if purchase is None else purchase.name,
        "amount": (
            None
            if purchase is None or purchase.price.amount is None
            else str(purchase.price.amount)
        ),
        "currency": "" if purchase is None else purchase.price.currency,
        "purchased": copy.purchased.serialize(),
    }


def _act_input(copy: PlannedCopy) -> CommandInput:
    return {"legacy": str(copy.row.id), "game": str(copy.game_id)}


def _metadata(
    legacy_ids: Sequence[LegacyId], categories: Sequence[Category]
) -> ConversionMetadata:
    untaggable = RECONCILIATION_ONLY.intersection(categories)
    if untaggable:
        raise ConversionDefect(f"{sorted(untaggable)} are never tagged on an event.")
    return {
        "origin": ORIGIN,
        "issue": ISSUE,
        "legacy_purchases": [str(legacy_id) for legacy_id in legacy_ids],
        "review": [str(category) for category in categories],
    }


def _analyze() -> None:
    """Fresh statistics before the replay reads."""
    analyzed: tuple[type[models.Model], ...] = (
        LibraryEvent,
        LibraryEventReference,
        *projection_models(),
    )
    tables = [model._meta.db_table for model in analyzed]
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f'ANALYZE "{table}"')


def _require_the_schema_this_pass_was_written_for() -> None:
    """Refuse when code outruns the schema."""
    touched: tuple[type[models.Model], ...] = (
        LibraryEvent,
        LibraryEventReference,
        LibraryEventStreamHead,
        LibraryIdempotencyRecord,
        *projection_models(),
        Game,
        Edition,
        Release,
        Platform,
        PurchaseConversionState,
        PurchaseValuation,
        ExchangeRate,
        UserLibrary,
    )
    missing: list[str] = []
    with connection.cursor() as cursor:
        for model in touched:
            table = model._meta.db_table
            held = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, table
                )
            }
            missing += [
                f"{table}.{column.column}"
                for column in model._meta.concrete_fields
                if column.column not in held
            ]
    if missing:
        raise PurchaseConversionDrift(
            "The purchase conversion runs today's code, which declares "
            f"columns this database does not hold yet: {', '.join(missing)}. "
            "Deploy the release that carries this migration, migrate, and "
            "move on from there."
        )


def require_replay_parity(libraries: Sequence[UserLibrary]) -> None:
    """Refuse unless replay reproduces the tables."""
    for library in libraries:
        report = rebuild_projections(
            library, mode=RebuildMode.CHECK, models=projection_models()
        )
        drifted = [
            f"{table.table}: {table.only_live} only live, {table.only_rebuilt} "
            f"only rebuilt, {table.differing} differing ({', '.join(table.sample)})"
            for table in report.tables
            if table.only_live or table.only_rebuilt or table.differing
        ]
        if drifted:
            raise PurchaseConversionDrift(
                f"Library {library.pk} does not replay to its own tables after "
                f"the purchase conversion: {'; '.join(drifted)}."
            )
