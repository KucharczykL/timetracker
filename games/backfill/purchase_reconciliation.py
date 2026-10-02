"""What the purchase conversion moved, checked."""

# conversion-tooling

import dataclasses
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple, TypedDict, cast

from django.db.models import (
    Exists,
    ManyToManyField,
    Max,
    Model,
    OuterRef,
    Q,
    QuerySet,
    Sum,
)
from django.utils import timezone

from games.backfill.purchase import LibraryConversion
from games.backfill.purchase_plan import (
    AccessAndFormat,
    CurrencyCode,
    LegacyRow,
    exact_amount,
    quantized_amount,
)
from games.conversion_review import ORIGIN, Category
from games.models import (
    LibraryEntry,
    LibraryEvent,
    Purchase,
    PurchaseValuation,
    UserLibrary,
)
from games.reads.playtime import played_years
from games.views.stats_data import StatsKey, compute_stats

SNAPSHOT_FORMAT = 2
ALL_TIME = "all-time"

type LegacyKeyText = str  # a legacy purchase's key
type ReviewLists = dict[Category, list[LegacyKeyText]]


@dataclasses.dataclass(frozen=True, slots=True)
class CurrencyTotal:
    """One currency's legacy and converted sums."""

    currency: CurrencyCode
    legacy: Decimal
    converted: Decimal
    #: Quantized amounts less exact ones.
    quantization: Decimal
    #: Amounts of copies the pass skipped.
    skipped: Decimal

    @property
    def unexplained(self) -> Decimal:
        return self.legacy + self.quantization - self.skipped - self.converted


class Tally(NamedTuple):
    """A count the legacy rows predict."""

    expected: int
    actual: int

    @property
    def differs(self) -> bool:
        return self.expected != self.actual


class ValuationTotal(NamedTuple):
    """Rated shares beside their seeded sum."""

    legacy: Decimal
    seeded: Decimal

    @property
    def differs(self) -> bool:
        return self.legacy != self.seeded


@dataclasses.dataclass(frozen=True, slots=True)
class Reconciliation:
    """Legacy rows beside what the pass stated."""

    planned_copies: int
    own_copies: int
    purchases: int
    skipped: int
    unvalued: int
    totals: tuple[CurrencyTotal, ...]
    refunded_purchases: Tally
    refund_ended_copies: Tally
    copies_by_access: Mapping[AccessAndFormat, int]
    valuations: Mapping[CurrencyCode, ValuationTotal]

    def failures(self) -> list[str]:
        """Differences no rule explains."""
        failures = [
            f"{total.currency}: legacy {total.legacy} + quantization "
            f"{total.quantization} - skipped {total.skipped} is not the "
            f"converted {total.converted}"
            for total in self.totals
            if total.unexplained != 0
        ]
        if self.refunded_purchases.differs:
            failures.append(
                f"{self.refunded_purchases.actual} refunded purchases, expected "
                f"{self.refunded_purchases.expected}"
            )
        if self.refund_ended_copies.differs:
            failures.append(
                f"{self.refund_ended_copies.actual} copies ended as refunded, "
                f"expected {self.refund_ended_copies.expected}"
            )
        failures += [
            f"{target}: seeded {total.seeded}, legacy shares {total.legacy}"
            for target, total in self.valuations.items()
            if total.differs
        ]
        return failures


def reconcile(
    rows: Sequence[LegacyRow], conversion: LibraryConversion
) -> Reconciliation:
    """Read the projections against the legacy rows."""
    copies = conversion.copies
    purchase_ids = [copy.purchase_id for copy in copies if copy.purchase_id is not None]
    own_copies = [copy.entry_id for copy in copies if copy.own_copy]
    planned = [
        *(copy.planned for copy in copies),
        *(skip.planned for skip in conversion.skipped),
    ]

    legacy: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    quantization: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    skipped: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    #: Per row: a bundle's price counts once.
    priced = {
        copy.row.id: (copy.row.price, copy.purchase.price.currency)
        for copy in planned
        if copy.purchase is not None and copy.purchase.price.amount is not None
    }
    #: A row holds one currency.
    for row_price, currency in priced.values():
        exact = exact_amount(row_price)
        legacy[currency] += exact
        quantization[currency] += quantized_amount(row_price) - exact
    for skip in conversion.skipped:
        purchase = skip.planned.purchase
        if purchase is not None and purchase.price.amount is not None:
            skipped[purchase.price.currency] += purchase.price.amount
    converted = dict(
        Purchase.objects.filter(pk__in=purchase_ids, amount__isnull=False)
        .values("currency")
        .annotate(total=Sum("amount"))
        .values_list("currency", "total")
    )
    totals = tuple(
        CurrencyTotal(
            currency,
            legacy[currency],
            converted.get(currency, Decimal(0)),
            quantization[currency],
            skipped[currency],
        )
        for currency in sorted(set(legacy) | set(converted))
    )

    refunded = [copy for copy in copies if copy.planned.refunded is not None]
    entries = LibraryEntry.objects.filter(pk__in=own_copies)

    #: Only shares seeded at a rate compare.
    rated = set(conversion.rated)
    valued = dict(
        PurchaseValuation.objects.filter(purchase_id__in=rated)
        .values("target_currency")
        .annotate(total=Sum("amount"))
        .values_list("target_currency", "total")
    )
    legacy_converted: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    for stated in copies:
        purchase = stated.planned.purchase
        if (
            stated.purchase_id in rated
            and purchase is not None
            and purchase.converted is not None
        ):
            legacy_converted[purchase.converted.currency] += purchase.converted.amount

    return Reconciliation(
        planned_copies=len(planned),
        own_copies=len(own_copies),
        purchases=len(purchase_ids),
        skipped=len(conversion.skipped),
        unvalued=len(conversion.unvalued),
        totals=totals,
        refunded_purchases=Tally(
            expected=sum(1 for copy in refunded if copy.purchase_id is not None),
            actual=Purchase.objects.filter(
                pk__in=purchase_ids, refund_recorded_at__isnull=False
            ).count(),
        ),
        refund_ended_copies=Tally(
            expected=sum(1 for copy in refunded if copy.own_copy),
            actual=entries.filter(access_end_way="refunded").count(),
        ),
        copies_by_access=dict(
            sorted(
                Counter(
                    cast(
                        list[AccessAndFormat],
                        list(entries.values_list("access", "format")),
                    )
                ).items()
            )
        ),
        valuations={
            target: ValuationTotal(
                legacy=legacy_converted.get(target, Decimal(0)),
                seeded=valued.get(target, Decimal(0)),
            )
            for target in sorted(set(valued) | set(legacy_converted))
        },
    )


def review_lists(library: UserLibrary, conversion: LibraryConversion) -> ReviewLists:
    """Legacy keys per review category."""
    listed: defaultdict[Category, set[LegacyKeyText]] = defaultdict(set)
    for metadata in LibraryEvent.objects.filter(
        library=library, source_metadata__origin=ORIGIN
    ).values_list("source_metadata", flat=True):
        for category in metadata.get("review", []):
            listed[Category(category)].update(metadata.get("legacy_purchases", []))
    for skip in conversion.skipped:
        listed[Category.SKIPPED_REMOVED_GAME].add(str(skip.legacy_id))
    return {category: sorted(listed[category]) for category in sorted(listed)}


def snapshot_value(value: object) -> Any:
    """JSON for one statistics value."""
    match value:
        case None | bool() | int() | float() | str():
            return value
        case Decimal() | uuid.UUID():
            return str(value)
        case datetime() | date():
            return value.isoformat()
        case timedelta():
            return int(value.total_seconds())
        case QuerySet():
            return [str(key) for key in value.values_list("pk", flat=True)]
        case Model():
            return str(value.pk)
        case tuple() if hasattr(value, "_fields"):
            return {
                name: snapshot_value(getattr(value, name))
                for name in value._fields  # type: ignore[attr-defined]
            }
        case Mapping():
            return {str(key): snapshot_value(item) for key, item in value.items()}
        case set() | frozenset():
            return sorted((snapshot_value(item) for item in value), key=str)
        case list() | tuple() | range():
            return [snapshot_value(item) for item in value]
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: snapshot_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
    raise TypeError(f"No snapshot spelling for {type(value).__name__}.")


def snapshot_scopes(
    library: UserLibrary, rows: Sequence[LegacyRow]
) -> list[int | None]:
    """All-time, then played, purchase and refund years."""
    years = set(played_years(library))
    for row in rows:
        years.add(row.date_purchased.year)
        if row.date_refunded is not None:
            years.add(row.date_refunded.year)
    return [None, *sorted(years)]


# ── Legacy figures, any legacy model ──────────────────────────────────────

type RowsKey = str  # a RowSets field, e.g. "unfinished"


class RowSets[Rows](NamedTuple):
    """Every row set behind a figure or ratio."""

    purchases: Rows
    refunded: Rows
    unrefunded: Rows
    valued: Rows
    unfinished: Rows
    unfinished_base: Rows
    dropped: Rows
    dropped_base: Rows
    backlog_decrease: Rows
    finished: Rows
    finished_released: Rows
    bought_and_finished: Rows
    played: Rows


ROWS_KEYS: tuple[RowsKey, ...] = RowSets._fields

#: Literal: the model may be historical.
DONE: tuple[str, ...] = ("completed", "retired")
ABANDONED = "abandoned"


type LegacyRows = frozenset[LegacyKeyText]


class LegacyFigures(NamedTuple):
    """The figures, their rows, the valued shares."""

    values: Mapping[StatsKey, object]
    rows: RowSets[LegacyRows]
    #: A valued row's converted price, quantized.
    amounts: Mapping[LegacyKeyText, Decimal]


def _percent(part: int, whole: int) -> int:
    return int(part / whole * 100) if whole else 0


def legacy_figures(
    model: type[Model], library: UserLibrary, year: int | None
) -> LegacyFigures:
    """The legacy purchase figures of one scope.

    The model may be historical: every other model comes
    from its registry, the alive rule is stated here, and
    games are reached through the link table alone.
    """
    registry = model._meta.apps
    #: Key only: historical models refuse instances.
    library_id = library.pk
    player_game = registry.get_model("games", "PlayerGame")
    run = registry.get_model("games", "Playthrough")
    session = registry.get_model("games", "PlayerSession")
    record = registry.get_model("games", "HistoricalPlaytime")
    conversion_state = registry.get_model("games", "PurchaseConversionState")
    games = model._meta.get_field("games")
    assert isinstance(games, ManyToManyField)
    through = games.remote_field.through
    assert through is not None
    own, other = games.m2m_field_name(), games.m2m_reverse_field_name()
    links = through._base_manager

    def holding(game_ids: QuerySet) -> Q:
        """A row naming one of these games."""
        return Q(pk__in=links.filter(**{f"{other}_id__in": game_ids}).values(own))

    def tracked(**facts: object) -> QuerySet:
        return player_game._base_manager.filter(
            library_id=library_id,
            removed_at__isnull=True,
            game__removed_at__isnull=True,
            **facts,
        ).values("game_id")

    linked = links.filter(**{own: OuterRef("pk")})
    alive = model._base_manager.filter(
        library_id=library_id, removed_at__isnull=True
    ).filter(
        ~Exists(linked)
        | Exists(linked.filter(**{f"{other}__removed_at__isnull": True}))
    )

    runs = run._base_manager.filter(
        library_id=library_id,
        player_game__library_id=library_id,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
        kind="ordinary",
    )
    if year is None:
        runs = runs.filter(completion_recorded_at__isnull=False)
    else:
        first, last = date(year, 1, 1), date(year, 12, 31)
        runs = runs.filter(
            Q(completed__isnull=False)
            & (Q(completed_lower__isnull=True) | Q(completed_lower__lte=last))
            & (Q(completed_upper__isnull=True) | Q(completed_upper__gte=first))
        )
    completed = holding(runs.values("player_game__game_id"))
    done = holding(tracked(status__in=DONE))
    abandoned = holding(tracked(status=ABANDONED))
    not_finished = ~done & ~completed
    games_and_dlc = Q(type__in=("game", "dlc"))

    if year is None:
        purchases = alive
    else:
        purchases = alive.filter(date_purchased__year=year)
    unrefunded = purchases.filter(date_refunded__isnull=True)
    refunded = purchases.filter(date_refunded__isnull=False)
    valued = unrefunded.filter(converted_price__isnull=False)
    unfinished = (
        unrefunded.filter(not_finished)
        .filter(infinite=False)
        .exclude(holding(tracked(excluded_from_unfinished=True)))
        .filter(games_and_dlc)
        .exclude(abandoned)
    )
    dropped = (
        purchases.filter(not_finished)
        .filter(abandoned | Q(date_refunded__isnull=False))
        .filter(infinite=False)
        .exclude(holding(tracked(excluded_from_dropped=True)))
        .filter(games_and_dlc)
    )
    sessions = session._base_manager.filter(
        library_id=library_id,
        playthrough__library_id=library_id,
        playthrough__player_game__library_id=library_id,
        removed_at__isnull=True,
        playthrough__removed_at__isnull=True,
        playthrough__player_game__removed_at__isnull=True,
        playthrough__player_game__game__removed_at__isnull=True,
    )
    records = record._base_manager.filter(
        library_id=library_id,
        player_game__library_id=library_id,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
    )
    released = Q()
    if year is None:
        finished = alive.filter(done | completed)
        finished_released = finished
        backlog_decrease = finished
        bought_and_finished = alive.none()
    else:
        sessions = sessions.filter(effective_day__year=year)
        records = records.filter(
            when_lower__gte=date(year, 1, 1), when_upper__lte=date(year, 12, 31)
        )
        released = Q(
            pk__in=links.filter(**{f"{other}__year_released": year}).values(own)
        )
        finished = alive.filter(completed)
        finished_released = finished.filter(released)
        backlog_decrease = (
            alive.filter(date_purchased__year__lt=year).filter(done).filter(completed)
        )
        bought_and_finished = unrefunded.filter(completed)
    played = alive.filter(
        holding(sessions.values("playthrough__player_game__game_id"))
        | holding(records.values("player_game__game_id"))
    ).filter(released)

    def keys(rows: QuerySet) -> frozenset[LegacyKeyText]:
        return frozenset(str(key) for key in rows.values_list("pk", flat=True))

    rows = RowSets(
        purchases=keys(purchases),
        refunded=keys(refunded),
        unrefunded=keys(unrefunded),
        valued=keys(valued),
        unfinished=keys(unfinished),
        unfinished_base=keys(unrefunded),
        dropped=keys(dropped),
        dropped_base=keys(purchases),
        backlog_decrease=keys(backlog_decrease),
        finished=keys(finished),
        finished_released=keys(finished_released),
        bought_and_finished=keys(bought_and_finished),
        played=keys(played),
    )
    amounts = {
        str(key): quantized_amount(price)
        for key, price in valued.values_list("pk", "converted_price")
    }
    spending = unrefunded.aggregate(
        total=Sum("converted_price"),
        currency=Max("converted_currency", filter=Q(converted_price__isnull=False)),
    )
    total_spent = spending["total"] or 0
    currency = (
        spending["currency"]
        or conversion_state._base_manager.get(library_id=library_id).published_currency
    )
    counts = {key: len(found) for key, found in rows._asdict().items()}
    values: dict[StatsKey, object] = {
        "all_purchased_this_year_count": counts["purchases"],
        "all_purchased_refunded_this_year_count": counts["refunded"],
        "refunded_percent": _percent(counts["refunded"], counts["purchases"]),
        "total_spent": total_spent,
        "total_spent_currency": currency,
        "spent_per_game": int(total_spent / counts["unrefunded"])
        if counts["unrefunded"]
        else 0,
        "dropped_count": counts["dropped"],
        "dropped_percentage": _percent(counts["dropped"], counts["purchases"]),
        "purchased_unfinished_count": counts["unfinished"],
        "unfinished_purchases_percent": _percent(
            counts["unfinished"], counts["unrefunded"]
        ),
        "backlog_decrease_count": counts["backlog_decrease"],
        "this_year_finished_this_year_count": counts["finished_released"],
        "total_year_games": counts["played"],
    }
    if year is not None:
        values["all_finished_this_year_count"] = counts["finished"]
    return LegacyFigures(values, rows, amounts)


#: Keys the legacy rows answer.
LEGACY_KEYS: frozenset[StatsKey] = frozenset(
    {
        "all_purchased_this_year_count",
        "all_purchased_refunded_this_year_count",
        "refunded_percent",
        "total_spent",
        "total_spent_currency",
        "spent_per_game",
        "dropped_count",
        "dropped_percentage",
        "purchased_unfinished_count",
        "unfinished_purchases_percent",
        "backlog_decrease_count",
        "this_year_finished_this_year_count",
        "total_year_games",
        "all_finished_this_year_count",
        "all_purchased_refunded_this_year",
        "all_finished_this_year",
        "this_year_finished_this_year",
        "purchased_this_year_finished_this_year",
        "purchased_unfinished",
        "all_purchased_this_year",
    }
)


#: Figures the legacy pages lacked.
NEW_KEYS: frozenset[StatsKey] = frozenset(
    {"total_spent_unpriced", "total_spent_unvalued"}
)


class SnapshotScope(TypedDict):
    """One scope of a format-2 snapshot."""

    figures: dict[StatsKey, Any]
    rows: dict[RowsKey, list[LegacyKeyText]]
    amounts: dict[LegacyKeyText, str]


def legacy_scope(
    model: type[Model], library: UserLibrary, year: int | None
) -> SnapshotScope:
    """One snapshot scope: figures, rows, shares."""
    legacy = legacy_figures(model, library, year)
    stats = {
        key: value
        for key, value in compute_stats(library, year).items()
        if key not in LEGACY_KEYS | NEW_KEYS
    }
    return {
        "figures": {**snapshot_value(stats), **snapshot_value(legacy.values)},
        "rows": {key: sorted(found) for key, found in legacy.rows._asdict().items()},
        "amounts": {key: str(amount) for key, amount in legacy.amounts.items()},
    }


def legacy_statistics(
    model: type[Model], library: UserLibrary, rows: Sequence[LegacyRow]
) -> dict[str, Any]:
    """Every scope, before the cutover."""
    return {
        "format": SNAPSHOT_FORMAT,
        "library": str(library.pk),
        "taken_at": timezone.now().isoformat(),
        "scopes": {
            ALL_TIME if scope is None else str(scope): legacy_scope(
                model, library, scope
            )
            for scope in snapshot_scopes(library, rows)
        },
    }
