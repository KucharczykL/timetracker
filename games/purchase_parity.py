"""Judge the purchase figures across the conversion.

A snapshot holds the legacy figures and the legacy keys
behind each. A converted row names its legacy key in its
creation event; every key that leaves or joins a figure
carries a reason read from what the pass wrote.
"""

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, NamedTuple

from django.db.models import QuerySet

from games.backfill.purchase import ORIGIN
from games.backfill.purchase_plan import Category
from games.backfill.purchase_reconciliation import (
    ROWS_KEYS,
    SNAPSHOT_FORMAT,
    LegacyKeyText,
    RowsKey,
    snapshot_value,
)
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.purchase import PURCHASE_CREATED
from games.filters import PurchaseFilter
from games.models import (
    EditionKind,
    EntryAccess,
    LibraryEntry,
    LibraryEvent,
    PurchaseConversionState,
    PurchaseKind,
    UserLibrary,
)
from games.reads import copy_figures, purchase_figures
from games.reads.days import YearScope
from games.stats_parity import UNCHANGED, FigureChange, comparable
from games.views.stats_data import STATS_SOURCES, StatsData, StatsKey

type RowKey = str  # a new row's key


class SnapshotRefused(ValueError):
    """A snapshot this gate cannot read."""


class Reason(StrEnum):
    """Why a legacy key moved."""

    NO_PURCHASE = "a non-owned row at 0 is a copy and no purchase"
    BUNDLE_SPLIT = "a bundle became one row per game"
    NOT_OWNED = "not Owned"
    PRERELEASE = "a prerelease copy"
    ADDON_GAME = "an add-on counts through its own game"
    EXCLUSION_MOVED = "an exclusion moved"
    RIDES_BASE = "a pass or upgrade rides the base copy"
    OWN_COPY = "a pass or upgrade recorded its own copy"
    UNKNOWN_PRICE = "a price nobody knows"
    NO_VALUATION = "no valuation"
    RECORDED_SINCE = "recorded since the conversion"


#: Reasons a purchase figure admits.
PURCHASE_REASONS: frozenset[Reason] = frozenset(
    {Reason.NO_PURCHASE, Reason.BUNDLE_SPLIT, Reason.RECORDED_SINCE}
)
VALUED_REASONS = PURCHASE_REASONS | {Reason.UNKNOWN_PRICE, Reason.NO_VALUATION}
COPY_REASONS: frozenset[Reason] = frozenset(
    {
        Reason.NO_PURCHASE,
        Reason.BUNDLE_SPLIT,
        Reason.NOT_OWNED,
        Reason.PRERELEASE,
        Reason.ADDON_GAME,
        Reason.EXCLUSION_MOVED,
        Reason.RIDES_BASE,
        Reason.OWN_COPY,
        Reason.RECORDED_SINCE,
    }
)


class KeyFacts(NamedTuple):
    """What the pass wrote per key."""

    purchases: frozenset[RowKey]
    entries: frozenset[RowKey]
    review: frozenset[str]
    kinds: frozenset[str]
    accesses: frozenset[str]
    edition_kinds: frozenset[str]
    unknown_price: bool
    unvalued: bool


class ConversionMap(NamedTuple):
    """New rows to legacy keys, with facts."""

    keys: Mapping[RowKey, LegacyKeyText]
    facts: Mapping[LegacyKeyText, KeyFacts]

    @classmethod
    def read(cls, library: UserLibrary) -> ConversionMap:
        created = LibraryEvent.objects.filter(
            library=library,
            source_metadata__origin=ORIGIN,
            event_type__in=(
                PURCHASE_CREATED.event_type,
                LIBRARYENTRY_CREATED.event_type,
            ),
        ).values_list("aggregate_id", "event_type", "source_metadata")
        keys: dict[RowKey, LegacyKeyText] = {}
        purchases: defaultdict[LegacyKeyText, set[RowKey]] = defaultdict(set)
        entries: defaultdict[LegacyKeyText, set[RowKey]] = defaultdict(set)
        review: defaultdict[LegacyKeyText, set[str]] = defaultdict(set)
        for aggregate_id, event_type, metadata in created:
            legacy = metadata["legacy_purchases"][0]
            keys[str(aggregate_id)] = legacy
            review[legacy].update(metadata.get("review", []))
            found = purchases if event_type == PURCHASE_CREATED.event_type else entries
            found[legacy].add(str(aggregate_id))

        def keys_of(purchase_filter: PurchaseFilter) -> set[RowKey]:
            return {
                str(key)
                for key in purchase_figures.purchases_matching(
                    library, purchase_filter
                ).values_list("pk", flat=True)
            }

        kinds = {
            str(key): kind
            for key, kind in purchase_figures.purchases_matching(
                library, purchase_figures.purchases_in_scope(None)
            ).values_list("pk", "kind")
        }
        unknown = keys_of(PurchaseFilter.where(price_state=["unknown"]))
        unvalued = keys_of(
            PurchaseFilter.where(amount__notnull=True, valuation__isnull=True)
        )
        copies = {
            str(row["pk"]): row
            for row in LibraryEntry.objects.filter(library=library).values(
                "pk", "access", "release__edition__kind"
            )
        }
        facts = {}
        for legacy in set(purchases) | set(entries):
            stated = purchases[legacy] & set(kinds)
            copied = [copies[key] for key in entries[legacy] if key in copies]
            facts[legacy] = KeyFacts(
                purchases=frozenset(purchases[legacy]),
                entries=frozenset(entries[legacy]),
                review=frozenset(review[legacy]),
                kinds=frozenset(kinds[key] for key in stated),
                accesses=frozenset(row["access"] for row in copied),
                edition_kinds=frozenset(
                    row["release__edition__kind"] for row in copied
                ),
                unknown_price=bool(stated & unknown),
                unvalued=bool(stated & unvalued),
            )
        return cls(keys, facts)

    def reasons(
        self, legacy: LegacyKeyText, admitted: frozenset[Reason]
    ) -> list[Reason]:
        """The admitted reasons this key's facts hold."""
        facts = self.facts.get(legacy)
        if facts is None:
            return []
        passes = {
            PurchaseKind.SEASON_PASS,
            PurchaseKind.BATTLE_PASS,
            PurchaseKind.UPGRADE,
        }
        holds = {
            Reason.NO_PURCHASE: bool(facts.entries) and not facts.purchases,
            Reason.BUNDLE_SPLIT: len(facts.purchases) > 1 or len(facts.entries) > 1,
            Reason.NOT_OWNED: bool(facts.accesses - {EntryAccess.OWNED}),
            Reason.PRERELEASE: EditionKind.PRERELEASE in facts.edition_kinds,
            Reason.ADDON_GAME: Category.ADDON_GAME in facts.review,
            Reason.EXCLUSION_MOVED: Category.MIXED_INFINITE in facts.review,
            Reason.RIDES_BASE: bool(facts.kinds & passes) and not facts.entries,
            Reason.OWN_COPY: Category.OWN_COPY_FALLBACK in facts.review,
            Reason.UNKNOWN_PRICE: facts.unknown_price,
            Reason.NO_VALUATION: facts.unvalued,
        }
        return [reason for reason in Reason if reason in admitted and holds.get(reason)]


class RowsJudgement(NamedTuple):
    """One row set, before and after."""

    rows_key: RowsKey
    explained: Mapping[LegacyKeyText, tuple[Reason, ...]]
    unexplained: tuple[LegacyKeyText, ...]
    #: New rows no conversion wrote.
    recorded_since: int

    @property
    def clean(self) -> bool:
        return not self.unexplained


#: The new rows each row set holds.
def _new_rows(library: UserLibrary, year: YearScope) -> dict[RowsKey, QuerySet]:
    purchases = purchase_figures.purchases_matching
    copies = copy_figures.copies_matching
    unrefunded = purchases(library, purchase_figures.unrefunded_in_scope(year))
    return {
        "purchases": purchases(library, purchase_figures.purchases_in_scope(year)),
        "refunded": purchases(library, purchase_figures.refunded_in_scope(year)),
        "unrefunded": unrefunded,
        "valued": purchases(library, purchase_figures.valued_in_scope(year)),
        "unfinished": copies(library, copy_figures.unfinished_copies(year)),
        "unfinished_base": copies(library, copy_figures.owned_held(year)),
        "dropped": copies(library, copy_figures.dropped_copies(year)),
        "dropped_base": copies(library, copy_figures.owned(year)),
        "backlog_decrease": copies(library, copy_figures.backlog_decrease_copies(year)),
        "finished": copies(library, copy_figures.finished_copies(year)),
        "finished_released": copies(
            library, copy_figures.finished_released_copies(year)
        ),
        "bought_and_finished": (
            copies(library, copy_figures.bought_and_finished_copies(year))
            if year is not None
            else LibraryEntry.objects.none()
        ),
        "played": copies(library, copy_figures.played_copies(year)),
    }


_PURCHASE_ROWS = {"purchases", "refunded", "unrefunded"}


def _admitted(rows_key: RowsKey) -> frozenset[Reason]:
    if rows_key == "valued":
        return VALUED_REASONS
    if rows_key in _PURCHASE_ROWS:
        return PURCHASE_REASONS
    return COPY_REASONS


def judge_rows(
    rows_key: RowsKey,
    before: frozenset[LegacyKeyText],
    after: QuerySet,
    mapping: ConversionMap,
) -> RowsJudgement:
    """Each moved key, with its reasons."""
    after_keys: defaultdict[LegacyKeyText, int] = defaultdict(int)
    recorded_since = 0
    for row_key in after.values_list("pk", flat=True):
        legacy = mapping.keys.get(str(row_key))
        if legacy is None:
            recorded_since += 1
        else:
            after_keys[legacy] += 1
    admitted = _admitted(rows_key)
    moved = (before ^ set(after_keys)) | {
        legacy for legacy, count in after_keys.items() if count > 1
    }
    explained: dict[LegacyKeyText, tuple[Reason, ...]] = {}
    unexplained: list[LegacyKeyText] = []
    for legacy in sorted(moved):
        reasons = mapping.reasons(legacy, admitted)
        if reasons:
            explained[legacy] = tuple(reasons)
        else:
            unexplained.append(legacy)
    return RowsJudgement(rows_key, explained, tuple(unexplained), recorded_since)


#: The row set a figure counts.
FIGURE_ROWS: Mapping[StatsKey, RowsKey] = {
    "all_purchased_this_year_count": "purchases",
    "all_purchased_this_year": "purchases",
    "all_purchased_refunded_this_year_count": "refunded",
    "all_purchased_refunded_this_year": "refunded",
    "purchased_unfinished_count": "unfinished",
    "purchased_unfinished": "unfinished",
    "dropped_count": "dropped",
    "backlog_decrease_count": "backlog_decrease",
    "all_finished_this_year_count": "finished",
    "all_finished_this_year": "finished",
    "this_year_finished_this_year_count": "finished_released",
    "this_year_finished_this_year": "finished_released",
    "purchased_this_year_finished_this_year": "bought_and_finished",
    "total_year_games": "played",
}
#: A ratio's numerator and denominator.
FIGURE_RATIOS: Mapping[StatsKey, tuple[RowsKey, RowsKey]] = {
    "refunded_percent": ("refunded", "purchases"),
    "dropped_percentage": ("dropped", "dropped_base"),
    "unfinished_purchases_percent": ("unfinished", "unfinished_base"),
    "spent_per_game": ("valued", "valued"),
}


def _attribution(judgement: RowsJudgement) -> str | None:
    if not judgement.clean:
        return None
    named = {reason for reasons in judgement.explained.values() for reason in reasons}
    parts = [str(reason) for reason in sorted(named)]
    if judgement.recorded_since:
        parts.append(f"{judgement.recorded_since} {Reason.RECORDED_SINCE}")
    return "; ".join(parts) or UNCHANGED


def _spent(
    before: Mapping[LegacyKeyText, Decimal],
    after: QuerySet,
    mapping: ConversionMap,
) -> str | None:
    """Valued keys sum alike, to the cent."""
    totals: defaultdict[LegacyKeyText, Decimal] = defaultdict(Decimal)
    for row_key, amount in after.values_list("pk", "valuation_amount"):
        legacy = mapping.keys.get(str(row_key))
        if legacy is not None:
            totals[legacy] += amount
    both = set(before) & set(totals)
    legacy_sum = sum((before[key] for key in both), Decimal(0))
    seeded_sum = sum((totals[key] for key in both), Decimal(0))
    if legacy_sum != seeded_sum:
        return None
    return f"{seeded_sum} over {len(both)} key(s) valued on both sides"


class PurchaseScope(NamedTuple):
    changes: tuple[FigureChange, ...]
    judgements: tuple[RowsJudgement, ...]


def judge_purchase_scope(
    snapshot: Mapping[str, Any],
    after: StatsData,
    library: UserLibrary,
    year: YearScope,
    mapping: ConversionMap,
) -> PurchaseScope:
    """Every figure of one scope, judged."""
    rows_before = {key: frozenset(snapshot["rows"][key]) for key in ROWS_KEYS}
    new_rows = _new_rows(library, year)
    judgements = {
        key: judge_rows(key, rows_before[key], new_rows[key], mapping)
        for key in ROWS_KEYS
    }
    amounts = {key: Decimal(amount) for key, amount in snapshot["amounts"].items()}
    now: Mapping[StatsKey, object] = after
    changes: list[FigureChange] = []
    for key in STATS_SOURCES:
        if key not in snapshot and key not in now:
            continue
        if key not in now:
            changes.append(FigureChange(key, snapshot[key], None, None))
            continue
        value = now[key]
        if key in FIGURE_ROWS:
            rows_key = FIGURE_ROWS[key]
            #: A list compares as its count.
            was = snapshot.get(key, len(rows_before[rows_key]))
            current = value.count() if isinstance(value, QuerySet) else value
            attribution = _attribution(judgements[rows_key])
        elif key not in snapshot:
            was, current, attribution = None, value, "a new figure"
        elif key in FIGURE_RATIOS:
            numerator, denominator = FIGURE_RATIOS[key]
            was, current = snapshot[key], value
            clean = judgements[numerator].clean and judgements[denominator].clean
            attribution = "recomputed" if clean else None
        elif key == "total_spent_currency":
            was, current = snapshot[key], value
            attribution = (
                UNCHANGED
                if was == current
                else "the published currency"
                if current == _published(library)
                else None
            )
        elif key == "total_spent":
            was, current = snapshot[key], value
            attribution = (
                _spent(amounts, new_rows["valued"], mapping)
                if judgements["valued"].clean
                else None
            )
        else:
            was, current = snapshot[key], _plain(value)
            attribution = UNCHANGED if was == current else None
        if was != current or attribution is None:
            changes.append(FigureChange(key, was, current, attribution))
    return PurchaseScope(tuple(changes), tuple(judgements.values()))


def _published(library: UserLibrary) -> str:
    return (
        PurchaseConversionState.objects.only("published_currency")
        .get(library=library)
        .published_currency
    )


def _plain(value: object) -> object:
    """The snapshot's spelling of a value."""
    return snapshot_value(comparable(value))


def read_snapshot(snapshot: Mapping[str, Any], library: UserLibrary) -> Mapping:
    """The scopes, or a refusal."""
    if snapshot.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotRefused(
            f"Snapshot format {snapshot.get('format')!r}; this gate reads "
            f"format {SNAPSHOT_FORMAT}. Write it again with --snapshot."
        )
    if snapshot.get("library") != str(library.pk):
        raise SnapshotRefused(
            f"Snapshot of library {snapshot.get('library')}, not {library.pk}."
        )
    return snapshot["scopes"]
