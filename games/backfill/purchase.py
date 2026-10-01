"""Convert legacy purchases into copies and purchases."""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any, NamedTuple

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, models, transaction
from django.db.models import Case, Value, When
from django.utils import timezone

from games.api_creation import RowRefused
from games.backfill.purchase_plan import (
    Category,
    LegacyRow,
    PlannedCopy,
    legacy_refusals,
    plan,
)
from games.catalog_addons import state_addon
from games.catalog_compat import write_and_mirror
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
    StatedPrice,
    purchase_creation_events,
)
from games.conversion import request_revaluation
from games.end_ways import EndWay
from games.events.append import AppendResult, LockedStream
from games.events.conflicts import CommandConflict
from games.events.dispatch import (
    CommandContext,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
)
from games.events.idempotency import IdempotencyKey, idempotent_append
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
from games.reads.entries import library_entries
from games.reads.purchases import valuation_inputs
from games.valuations import needs_rate, publish_valuations, seeded

ISSUE = 723
ORIGIN = "conversion"
DEMO_EDITION = "Demo"

#: A row's refusal; the person restates it.
REFUSALS = (
    CommandRejected,
    RowUnreadable,
    RowNotHeld,
    RowRefused,
    ValidationError,
)
#: A row's defect; the pass is wrong.
DEFECTS = (CommandConflict, DatabaseError)

type Build = Callable[[], Sequence[NewEvent] | Unchanged]


class Refusal(NamedTuple):
    """One legacy row the pass cannot state."""

    legacy_id: uuid.UUID
    game_id: uuid.UUID | None
    reason: str
    defect: bool = False

    def __str__(self) -> str:
        game = "" if self.game_id is None else f", game {self.game_id}"
        kind = "defect" if self.defect else "refused"
        return f"purchase {self.legacy_id}{game} {kind}: {self.reason}"


class PurchaseConversionRefused(Exception):
    """Rows no rule converts, or a differing replay."""

    def __init__(self, refusals: Iterable[Refusal | str]) -> None:
        self.refusals = tuple(refusals)
        named = "\n".join(f"- {refusal}" for refusal in self.refusals)
        super().__init__(
            f"{len(self.refusals)} legacy purchase refusal(s); nothing was "
            f"converted:\n{named}"
        )


class ConvertedCopy(NamedTuple):
    """A planned copy, as the pass stated it."""

    planned: PlannedCopy
    entry_id: uuid.UUID
    purchase_id: uuid.UUID | None
    #: Its own copy; else the base game's.
    own_copy: bool


class SkippedCopy(NamedTuple):
    legacy_id: uuid.UUID
    game_id: uuid.UUID


@dataclass
class LibraryConversion:
    """What the pass did in one library."""

    library: UserLibrary
    appended: int = 0
    copies: list[ConvertedCopy] = field(default_factory=list)
    skipped: list[SkippedCopy] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)


class PurchaseConversion(NamedTuple):
    """What one pass did."""

    libraries: tuple[LibraryConversion, ...]

    @property
    def appended(self) -> int:
        return sum(library.appended for library in self.libraries)


def _key(act: str, legacy_id: uuid.UUID, game_id: uuid.UUID) -> IdempotencyKey:
    return f"conversion:{ISSUE}:{act}:{legacy_id}:{game_id}"


def _exclusion_key(game_id: uuid.UUID) -> IdempotencyKey:
    return f"conversion:{ISSUE}:excluded:{game_id}"


def legacy_rows(
    model: type[models.Model], library_id: uuid.UUID | None = None
) -> list[LegacyRow]:
    """Every legacy row; the model may be historical."""
    rows = model._base_manager.all()
    if library_id is not None:
        rows = rows.filter(library_id=library_id)
    games = model._meta.get_field("games")
    assert isinstance(games, models.ManyToManyField)
    through = games.remote_field.through
    assert through is not None
    own, other = games.m2m_field_name(), games.m2m_reverse_field_name()
    linked: defaultdict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for purchase_id, game_id in through._base_manager.filter(
        **{f"{own}__in": rows.values("pk")}
    ).values_list(f"{own}_id", f"{other}_id"):
        linked[purchase_id].append(game_id)
    columns = rows.order_by("date_purchased", "pk").values_list(
        "pk",
        "library_id",
        "platform_id",
        "platform__name",
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
    )
    return [
        LegacyRow(
            id=pk,
            library_id=library,
            game_ids=tuple(sorted(linked[pk])),
            platform_id=platform_id,
            platform_name=platform_name or "",
            date_purchased=purchased,
            date_refunded=refunded,
            infinite=infinite,
            price=price,
            price_currency=currency,
            converted_price=converted,
            converted_currency=converted_currency,
            ownership_type=ownership,
            type=kind,
            name=name,
            related_game_id=related,
            removed_at=removed_at,
        )
        for (
            pk,
            library,
            platform_id,
            platform_name,
            purchased,
            refunded,
            infinite,
            price,
            currency,
            converted,
            converted_currency,
            ownership,
            kind,
            name,
            related,
            removed_at,
        ) in columns
    ]


def _removed_games(library_id: uuid.UUID, game_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Games the catalog or the library removed."""
    marked = Game.objects.filter(pk__in=game_ids, removed_at__isnull=False)
    untracked = PlayerGame.objects.filter(
        library_id=library_id, game_id__in=game_ids, removed_at__isnull=False
    )
    return set(marked.values_list("pk", flat=True)) | set(
        untracked.values_list("game_id", flat=True)
    )


def _unconverted(rows: Sequence[LegacyRow]) -> bool:
    """Any live copy lacking its creation key."""
    by_library: defaultdict[uuid.UUID, list[LegacyRow]] = defaultdict(list)
    for row in rows:
        by_library[row.library_id].append(row)
    for library_id, held_rows in by_library.items():
        game_ids = {game for row in held_rows for game in row.game_ids}
        removed = _removed_games(library_id, game_ids)
        wanted = {
            (row.id, game): (_key("created", row.id, game), _key("entry", row.id, game))
            for row in held_rows
            for game in row.game_ids
            if game not in removed
        }
        keys = {key for pair in wanted.values() for key in pair}
        held = set(
            LibraryIdempotencyRecord.objects.filter(
                library_id=library_id, idempotency_key__in=keys
            ).values_list("idempotency_key", flat=True)
        )
        if any(not (set(pair) & held) for pair in wanted.values()):
            return True
    return False


def convert_purchases(
    rows: Sequence[LegacyRow], *, recorded_at: datetime | None = None
) -> PurchaseConversion:
    """State every legacy row; all or nothing."""
    refusals = [
        Refusal(row.id, None, reason) for row in rows for reason in legacy_refusals(row)
    ]
    if refusals:
        raise PurchaseConversionRefused(refusals)
    if not _unconverted(rows):
        return PurchaseConversion(())
    _require_the_schema_this_pass_was_written_for()
    instant = timezone.now() if recorded_at is None else recorded_at
    by_library: defaultdict[uuid.UUID, list[LegacyRow]] = defaultdict(list)
    for row in rows:
        by_library[row.library_id].append(row)
    libraries = UserLibrary.objects.select_related("user").in_bulk(by_library)
    with transaction.atomic():
        done = tuple(
            _LibraryPass(libraries[library_id], held, instant).run()
            for library_id, held in by_library.items()
        )
        refused = [refusal for library in done for refusal in library.refusals]
        if refused:
            raise PurchaseConversionRefused(refused)
        _analyze()
        require_replay_parity([library.library for library in done])
    return PurchaseConversion(done)


class _Appender:
    """Appends under the pass's own keys."""

    def __init__(self, library: UserLibrary, recorded_at: datetime) -> None:
        self.library = library
        self.recorded_at = recorded_at
        self.correlation_id = uuid.uuid7()
        self.appended = 0

    def replayed(self, key: IdempotencyKey) -> tuple[LibraryEvent, ...] | None:
        """The key's events; None if never answered."""
        record = LibraryIdempotencyRecord.objects.filter(
            library=self.library, idempotency_key=key
        ).first()
        if record is None:
            return None
        if record.first_sequence is None:
            return ()
        return tuple(
            LibraryEvent.objects.filter(
                library=self.library,
                sequence__range=(record.first_sequence, record.last_sequence),
            ).order_by("sequence")
        )

    def append(
        self,
        key: IdempotencyKey,
        command_input: dict[str, Any],
        build: Build,
        metadata: dict[str, Any],
    ) -> tuple[LibraryEvent, ...]:
        """Append once; a repeat reads back."""
        replayed = self.replayed(key)
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
            source_metadata={"origin": ORIGIN, "issue": ISSUE, **metadata},
            recorded_at=self.recorded_at,
        )
        if not isinstance(result, AppendResult):
            return ()
        self.appended += len(result.events)
        return result.events


def _created(events: Iterable[LibraryEvent], event_type: str) -> uuid.UUID | None:
    for event in events:
        if event.event_type == event_type:
            return event.aggregate_id
    return None


def _default_release(game: Game) -> Release:
    """The default Edition's default Release."""
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
    """One library's rows, in the spec's order."""

    def __init__(
        self, library: UserLibrary, rows: Sequence[LegacyRow], recorded_at: datetime
    ) -> None:
        self.library = library
        self.rows = rows
        self.context = CommandContext(library=library, actor=library.user)
        self.appender = _Appender(library, recorded_at)
        self.result = LibraryConversion(library)
        game_ids = {game for row in rows for game in row.game_ids}
        self.removed = _removed_games(library.pk, game_ids)
        self.hand_recorded = self._hand_recorded_games()
        infinite = {game for row in rows if row.infinite for game in row.game_ids}
        finite = {game for row in rows if not row.infinite for game in row.game_ids}
        self.mixed = infinite & finite
        #: Game key to the infinite rows naming it.
        self.infinite: defaultdict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)

    def _hand_recorded_games(self) -> set[uuid.UUID]:
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
        planned = [(row, plan(row, minted=uuid.uuid7)) for row in self.rows]
        first = [pair for pair in planned if not pair[1][0].is_attached]
        attached = [pair for pair in planned if pair[1][0].is_attached]
        for row, copies in [*first, *attached]:
            self._row(row, copies)
        self._exclusions()
        if self.appender.appended and not self.result.refusals:
            self._valuations()
        self.result.appended = self.appender.appended
        return self.result

    def _row(self, row: LegacyRow, copies: Sequence[PlannedCopy]) -> None:
        current: list[uuid.UUID | None] = [None]
        try:
            with transaction.atomic():
                for copy in copies:
                    current[0] = copy.game_id
                    self._copy(copy)
        except REFUSALS as error:
            self.result.refusals.append(Refusal(row.id, current[0], _reason(error)))
        except DEFECTS as error:
            self.result.refusals.append(
                Refusal(
                    row.id, current[0], f"{type(error).__name__}: {error}", defect=True
                )
            )

    def _copy(self, copy: PlannedCopy) -> None:
        row = copy.row
        if copy.game_id in self.removed:
            self.result.skipped.append(SkippedCopy(row.id, copy.game_id))
            return
        categories = list(copy.categories)
        if copy.game_id in self.mixed:
            categories.append(Category.MIXED_INFINITE)
        if not copy.is_addon_game and copy.game_id in self.hand_recorded:
            categories.append(Category.HAND_RECORDED_COPY)
        facts = _command_input(copy)
        act = "entry" if copy.purchase_id is None else "created"
        key = _key(act, row.id, copy.game_id)
        events = self.appender.replayed(key)
        if events is None:
            events = self._create(copy, act, key, facts, categories)
        purchase_id = _created(events, PURCHASE_CREATED.event_type)
        entry_id = _created(events, LIBRARYENTRY_CREATED.event_type)
        own_copy = entry_id is not None
        if entry_id is None:
            assert purchase_id is not None
            entry_id = Purchase.objects.get(pk=purchase_id).entry_id
        converted = ConvertedCopy(copy, entry_id, purchase_id, own_copy)
        metadata = _metadata([row.id], categories)
        if copy.refunded is not None:
            self._refund(converted, facts, metadata)
        if row.removed_at is not None:
            self._remove(converted, facts, metadata)
        if row.infinite:
            self.infinite[copy.game_id].append(row.id)
            if copy.is_addon_game:
                self.infinite[self._game_of(entry_id)].append(row.id)
        self.result.copies.append(converted)

    def _create(
        self,
        copy: PlannedCopy,
        act: str,
        key: IdempotencyKey,
        facts: dict[str, Any],
        categories: list[Category],
    ) -> tuple[LibraryEvent, ...]:
        held = self._base_copy(copy) if copy.is_attached else None
        statement: uuid.UUID | EntryStatement
        if held is not None:
            statement = held
        else:
            release, made = self._release_for(copy)
            if made:
                categories.append(Category.CREATED_RELEASE)
            statement = EntryStatement(
                release_id=release.pk,
                access=copy.access,
                format=copy.format,
                acquired=ActStatement(copy.purchased, ""),
            )
        build: Build
        if copy.purchase_id is None:
            assert isinstance(statement, EntryStatement)
            record = RecordEntry(
                release_id=statement.release_id,
                access=statement.access,
                format=statement.format,
                acquired=statement.acquired,
            )
            build = lambda: record.build(self.context)
        else:
            purchase_id = copy.purchase_id

            def build() -> Sequence[NewEvent]:
                return purchase_creation_events(
                    self.context,
                    copy=statement,
                    kind=copy.kind,
                    name=copy.name,
                    price=StatedPrice(copy.amount, copy.currency),
                    purchased=ActStatement(copy.purchased, ""),
                    purchase_id=purchase_id,
                )

        return self.appender.append(
            key, {**facts, "act": act}, build, _metadata([copy.row.id], categories)
        )

    def _refund(
        self, copy: ConvertedCopy, facts: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        planned = copy.planned
        row = planned.row
        if copy.purchase_id is not None:
            refund = RefundPurchase(
                purchase_id=copy.purchase_id,
                statement=ActStatement(planned.refunded, ""),
            )
            self.appender.append(
                _key("refunded", row.id, planned.game_id),
                {**facts, "act": "refunded"},
                lambda: refund.build(self.context),
                metadata,
            )
        if copy.own_copy and planned.access != "owned":
            end = EndEntryAccess(
                entry_id=copy.entry_id,
                statement=WayActStatement(planned.refunded, EndWay.REFUNDED),
            )
            self.appender.append(
                _key("ended", row.id, planned.game_id),
                {**facts, "act": "ended"},
                lambda: end.build(self.context),
                metadata,
            )

    def _remove(
        self, copy: ConvertedCopy, facts: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        row = copy.planned.row
        if copy.purchase_id is not None:
            removal = RemovePurchase(purchase_id=copy.purchase_id)
            self.appender.append(
                _key("removed", row.id, copy.planned.game_id),
                {**facts, "act": "removed"},
                lambda: removal.build(self.context),
                metadata,
            )
        if copy.own_copy:
            copy_removal = RemoveEntry(entry_id=copy.entry_id)
            self.appender.append(
                _key("removed_copy", row.id, copy.planned.game_id),
                {**facts, "act": "removed_copy"},
                lambda: copy_removal.build(self.context),
                metadata,
            )

    def _game_of(self, entry_id: uuid.UUID) -> uuid.UUID:
        return LibraryEntry.objects.values_list("player_game__game_id", flat=True).get(
            pk=entry_id
        )

    def _base_copy(self, copy: PlannedCopy) -> uuid.UUID | None:
        """The base game's held, Owned copy."""
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

    def _release_for(self, copy: PlannedCopy) -> tuple[Release, bool]:
        """The copy's Release; whether the pass made it."""
        row = copy.row
        game = Game.objects.get(pk=copy.game_id)
        if copy.is_addon_game:
            game = self._dlc_game(row, base=game)
        default = _default_release(game)
        platform = (
            default.platform
            if row.platform_id is None
            else Platform.objects.get(pk=row.platform_id)
        )
        if row.ownership_type == "de":
            return self._demo_release(game, platform)
        if platform is None or platform.pk == default.platform_id:
            return default, False
        reached = release_on(self.library, game, platform)
        return reached.release, reached.created

    def _dlc_game(self, row: LegacyRow, *, base: Game) -> Game:
        name = row.name.strip()
        standing = (
            Game.objects.filter(
                library=self.library, parent=base, name=name, kind=GameKind.DLC
            )
            .alive()
            .order_by("pk")
            .first()
        )
        if standing is not None:
            return standing
        game = Game(library=self.library, name=name, sort_name=name)
        state_addon(game, kind=GameKind.DLC, parent=base, library=self.library)
        game.save()
        platform = _default_release(base).platform
        write_and_mirror(
            game,
            lambda: state_catalog_graph(
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
            releases=(ReleaseState(key="release", platform=platform, is_default=True),),
        )
        written = write_and_mirror(
            game,
            lambda: state_catalog_graph(
                game=game, library=self.library, editions=[statement]
            ),
        )
        return written.editions[0].releases[0].release, True

    def _exclusions(self) -> None:
        tracked = set(
            PlayerGame.objects.filter(
                library=self.library,
                game_id__in=self.infinite,
                removed_at__isnull=True,
            ).values_list("game_id", flat=True)
        )
        for game_id, legacy_ids in self.infinite.items():
            #: No backlog counts an untracked game.
            if game_id not in tracked:
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
                self.result.refusals.append(
                    Refusal(legacy_ids[0], game_id, _reason(error))
                )

    def _valuations(self) -> None:
        state = PurchaseConversionState.objects.select_for_update().get(
            library=self.library
        )
        target = state.published_currency
        if state.published_version and target:
            shares = {
                copy.purchase_id: copy.planned
                for copy in self.result.copies
                if copy.purchase_id is not None
            }
            standing = list(PurchaseValuation.objects.filter(library=self.library))
            valued = {row.purchase_id for row in standing}
            calculated_at = self.appender.recorded_at
            rows = list(standing)
            for facts in valuation_inputs(self.library):
                planned = shares.get(facts.purchase_id)
                if planned is None or facts.purchase_id in valued:
                    continue
                rate = None
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
                    converted = planned.row.converted_currency.strip().upper()
                    if (
                        rate is None
                        or planned.converted_share is None
                        or converted != target
                    ):
                        continue
                    amount = planned.converted_share
                rows.append(
                    seeded(
                        facts,
                        target,
                        rate,
                        amount,
                        library=self.library,
                        version=state.published_version,
                        calculated_at=calculated_at,
                    )
                )
            publish_valuations(self.library, rows)
        if state.requested_currency.strip():
            request_revaluation(self.library)


def _reason(error: Exception) -> str:
    if isinstance(error, CommandRejected) and error.sentence:
        return f"{error.sentence} ({error})"
    if isinstance(error, ValidationError):
        return " ".join(error.messages)
    return str(error) or type(error).__name__


def _command_input(copy: PlannedCopy) -> dict[str, Any]:
    """Legacy-derived facts; never a minted key."""
    return {
        "legacy": str(copy.row.id),
        "game": str(copy.game_id),
        "access": copy.access,
        "format": copy.format,
        "kind": copy.kind,
        "name": copy.name,
        "amount": None if copy.amount is None else str(copy.amount),
        "currency": copy.currency,
        "purchased": copy.purchased.serialize(),
        "refunded": None if copy.refunded is None else copy.refunded.serialize(),
        "removed": copy.row.removed_at is not None,
    }


def _metadata(
    legacy_ids: Sequence[uuid.UUID], categories: Sequence[Category]
) -> dict[str, Any]:
    return {
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
        message = (
            "The purchase conversion runs today's code, which declares "
            f"columns this database does not hold yet: {', '.join(missing)}. "
            "Deploy the release that carries this migration, migrate, and "
            "move on from there."
        )
        raise PurchaseConversionRefused([message])


def require_replay_parity(libraries: Sequence[UserLibrary]) -> None:
    """Refuse unless replay reproduces the tables."""
    for library in libraries:
        report = rebuild_projections(
            library, mode=RebuildMode.CHECK, models=projection_models()
        )
        drifted = [
            table
            for table in report.tables
            if table.only_live or table.only_rebuilt or table.differing
        ]
        if drifted:
            raise PurchaseConversionRefused(
                [
                    f"Library {library.pk} does not replay to its own tables "
                    f"after the purchase conversion: {table.table}: "
                    f"{table.only_live} only live, {table.only_rebuilt} only "
                    f"rebuilt, {table.differing} differing "
                    f"({', '.join(table.sample)})"
                    for table in drifted
                ]
            )
