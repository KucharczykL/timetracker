"""Judge the purchase figures across the conversion.

A snapshot holds the legacy figures and the legacy keys
behind each. A converted row names its legacy key in its
creation event. A key that leaves, joins or repeats in a
row set needs a reason that can move that set that way.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, NamedTuple

from django.db.models import Model, QuerySet

from common.utils import safe_division
from games.backfill.purchase import ORIGIN
from games.backfill.purchase_plan import Category
from games.backfill.purchase_reconciliation import (
    ROWS_KEYS,
    SNAPSHOT_FORMAT,
    LegacyKeyText,
    RowSets,
    RowsKey,
    SnapshotScope,
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
    PriceState,
    PurchaseKind,
    UserLibrary,
)
from games.reads import copy_figures, purchase_figures
from games.reads.days import YearScope
from games.reads.purchase_figures import spending_currency
from games.stats_parity import UNCHANGED, FigureChange, comparable
from games.views.stats_data import STATS_SOURCES, StatsData, StatsKey

type RowKey = str  # a new row's key
type NewRows = QuerySet[Model]


class GateRefused(ValueError):
    """A snapshot or conversion this gate cannot read."""


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
CENT = Decimal("0.01")


class Move(StrEnum):
    """How a key differs in one row set."""

    LEFT = "left"
    JOINED = "joined"
    #: Several new rows under one key.
    REPEATED = "repeated"


PURCHASE_SETS: frozenset[RowsKey] = frozenset(
    {"purchases", "refunded", "unrefunded", "valued"}
)
COPY_SETS: frozenset[RowsKey] = frozenset(ROWS_KEYS) - PURCHASE_SETS
#: The sets that count Owned copies alone.
OWNED_SETS: frozenset[RowsKey] = frozenset(
    {"unfinished", "unfinished_base", "dropped", "dropped_base", "backlog_decrease"}
)
EVERY_MOVE: frozenset[Move] = frozenset(Move)


class Rule(NamedTuple):
    """The row sets a reason moves, and how."""

    sets: frozenset[RowsKey]
    moves: frozenset[Move]


def _rule(sets: frozenset[RowsKey], *moves: Move) -> Rule:
    return Rule(sets, frozenset(moves) or EVERY_MOVE)


#: Each reason moves only these sets, these ways.
RULES: Mapping[Reason, tuple[Rule, ...]] = {
    Reason.NO_PURCHASE: (_rule(PURCHASE_SETS, Move.LEFT),),
    Reason.BUNDLE_SPLIT: (_rule(PURCHASE_SETS, Move.REPEATED), _rule(COPY_SETS)),
    Reason.NOT_OWNED: (_rule(OWNED_SETS, Move.LEFT),),
    Reason.PRERELEASE: (_rule(COPY_SETS, Move.LEFT),),
    Reason.ADDON_GAME: (_rule(COPY_SETS),),
    Reason.EXCLUSION_MOVED: (
        _rule(frozenset({"unfinished", "dropped"}), Move.LEFT, Move.JOINED),
    ),
    Reason.RIDES_BASE: (_rule(COPY_SETS, Move.LEFT),),
    Reason.OWN_COPY: (_rule(COPY_SETS, Move.JOINED),),
    Reason.UNKNOWN_PRICE: (_rule(frozenset({"valued"}), Move.LEFT),),
    Reason.NO_VALUATION: (_rule(frozenset({"valued"}), Move.LEFT),),
}
assert set(RULES) == set(Reason), "every reason states its rule"

PASSES: frozenset[PurchaseKind] = frozenset(
    {PurchaseKind.SEASON_PASS, PurchaseKind.BATTLE_PASS, PurchaseKind.UPGRADE}
)


def can_move(reason: Reason, rows_key: RowsKey, move: Move) -> bool:
    return any(rows_key in rule.sets and move in rule.moves for rule in RULES[reason])


class KeyFacts(NamedTuple):
    """What the pass wrote per key."""

    purchases: frozenset[RowKey]
    entries: frozenset[RowKey]
    review: frozenset[Category]
    kinds: frozenset[PurchaseKind]
    accesses: frozenset[EntryAccess]
    edition_kinds: frozenset[EditionKind]
    unknown_price: bool
    unvalued: bool


class ConversionMap(NamedTuple):
    """New rows to legacy keys, with facts."""

    legacy_of: Mapping[RowKey, LegacyKeyText]
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
        legacy_of: dict[RowKey, LegacyKeyText] = {}
        purchases: defaultdict[LegacyKeyText, set[RowKey]] = defaultdict(set)
        entries: defaultdict[LegacyKeyText, set[RowKey]] = defaultdict(set)
        review: defaultdict[LegacyKeyText, set[Category]] = defaultdict(set)
        for aggregate_id, event_type, metadata in created:
            named = metadata.get("legacy_purchases") or []
            if len(named) != 1:
                raise GateRefused(
                    f"Conversion event of {aggregate_id} names {len(named)} "
                    "legacy row(s), not one."
                )
            [legacy] = named
            legacy_of[str(aggregate_id)] = legacy
            review[legacy].update(Category(word) for word in metadata.get("review", []))
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
            str(key): PurchaseKind(kind)
            for key, kind in purchase_figures.purchases_matching(
                library, purchase_figures.purchases_in_scope(None)
            ).values_list("pk", "kind")
        }
        unknown = keys_of(PurchaseFilter.where(price_state=[PriceState.UNKNOWN]))
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
                accesses=frozenset(EntryAccess(row["access"]) for row in copied),
                edition_kinds=frozenset(
                    EditionKind(row["release__edition__kind"]) for row in copied
                ),
                unknown_price=bool(stated & unknown),
                unvalued=bool(stated & unvalued),
            )
        return cls(legacy_of, facts)

    def reasons(self, legacy: LegacyKeyText) -> frozenset[Reason]:
        """The reasons this key's facts hold."""
        facts = self.facts.get(legacy)
        if facts is None:
            return frozenset()
        holds = {
            Reason.NO_PURCHASE: bool(facts.entries) and not facts.purchases,
            Reason.BUNDLE_SPLIT: len(facts.purchases) > 1 or len(facts.entries) > 1,
            Reason.NOT_OWNED: bool(facts.accesses - {EntryAccess.OWNED}),
            Reason.PRERELEASE: EditionKind.PRERELEASE in facts.edition_kinds,
            Reason.ADDON_GAME: Category.ADDON_GAME in facts.review,
            Reason.EXCLUSION_MOVED: Category.MIXED_INFINITE in facts.review,
            Reason.RIDES_BASE: bool(facts.kinds & PASSES) and not facts.entries,
            Reason.OWN_COPY: Category.OWN_COPY_FALLBACK in facts.review,
            Reason.UNKNOWN_PRICE: facts.unknown_price,
            Reason.NO_VALUATION: facts.unvalued,
        }
        return frozenset(reason for reason, held in holds.items() if held)


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


def _new_rows(library: UserLibrary, year: YearScope) -> RowSets[NewRows]:
    """The new rows behind each row set."""
    purchases = purchase_figures.purchases_matching
    copies = copy_figures.copies_matching
    return RowSets(
        purchases=purchases(library, purchase_figures.purchases_in_scope(year)),
        refunded=purchases(library, purchase_figures.refunded_in_scope(year)),
        unrefunded=purchases(library, purchase_figures.unrefunded_in_scope(year)),
        valued=purchases(library, purchase_figures.valued_in_scope(year)),
        unfinished=copies(library, copy_figures.unfinished_copies(year)),
        unfinished_base=copies(library, copy_figures.owned_held(year)),
        dropped=copies(library, copy_figures.dropped_copies(year)),
        dropped_base=copies(library, copy_figures.owned(year)),
        backlog_decrease=copies(library, copy_figures.backlog_decrease_copies(year)),
        finished=copies(library, copy_figures.finished_copies(year)),
        finished_released=copies(library, copy_figures.finished_released_copies(year)),
        bought_and_finished=(
            copies(library, copy_figures.bought_and_finished_copies(year))
            if year is not None
            else LibraryEntry.objects.none()
        ),
        played=copies(library, copy_figures.played_copies(year)),
    )


def judge_rows(
    rows_key: RowsKey,
    before: frozenset[LegacyKeyText],
    after: NewRows,
    mapping: ConversionMap,
) -> RowsJudgement:
    """Each moved key, with the reasons moving it."""
    after_keys: defaultdict[LegacyKeyText, int] = defaultdict(int)
    recorded_since = 0
    for row_key in after.values_list("pk", flat=True):
        legacy = mapping.legacy_of.get(str(row_key))
        if legacy is None:
            recorded_since += 1
        else:
            after_keys[legacy] += 1
    moves: defaultdict[LegacyKeyText, set[Move]] = defaultdict(set)
    for legacy in before - set(after_keys):
        moves[legacy].add(Move.LEFT)
    for legacy, count in after_keys.items():
        if legacy not in before:
            moves[legacy].add(Move.JOINED)
        if count > 1:
            moves[legacy].add(Move.REPEATED)
    explained: dict[LegacyKeyText, tuple[Reason, ...]] = {}
    unexplained: list[LegacyKeyText] = []
    for legacy in sorted(moves):
        held = mapping.reasons(legacy)
        named = [
            {reason for reason in held if can_move(reason, rows_key, move)}
            for move in moves[legacy]
        ]
        if all(named):
            moving = set().union(*named)
            explained[legacy] = tuple(reason for reason in Reason if reason in moving)
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
type Counts = Mapping[RowsKey, int]


def _percent(part: RowsKey, whole: RowsKey) -> Callable[[Counts, StatsData], int]:
    def ratio(counts: Counts, after: StatsData) -> int:
        return int(safe_division(counts[part], counts[whole]) * 100)

    return ratio


def _spent_per_game(counts: Counts, after: StatsData) -> int:
    valued = counts["valued"]
    return int(after["total_spent"] / valued) if valued else 0


class Ratio(NamedTuple):
    """A ratio's judged row sets, and its value."""

    sets: tuple[RowsKey, ...]
    expected: Callable[[Counts, StatsData], int]


#: Each ratio, recomputed from the judged rows.
FIGURE_RATIOS: Mapping[StatsKey, Ratio] = {
    "refunded_percent": Ratio(
        ("refunded", "purchases"), _percent("refunded", "purchases")
    ),
    "dropped_percentage": Ratio(
        ("dropped", "dropped_base"), _percent("dropped", "dropped_base")
    ),
    "unfinished_purchases_percent": Ratio(
        ("unfinished", "unfinished_base"), _percent("unfinished", "unfinished_base")
    ),
    #: Legacy divided by unrefunded; now by valued.
    "spent_per_game": Ratio(("valued", "unrefunded"), _spent_per_game),
}


def _attribution(judgement: RowsJudgement) -> str | None:
    if not judgement.clean:
        return None
    named = {reason for reasons in judgement.explained.values() for reason in reasons}
    parts = [str(reason) for reason in Reason if reason in named]
    if judgement.recorded_since:
        parts.append(f"{judgement.recorded_since} {RECORDED_SINCE}")
    return "; ".join(parts) or UNCHANGED


def _spent(
    before: Mapping[LegacyKeyText, Decimal],
    after: NewRows,
    mapping: ConversionMap,
) -> str | None:
    """Each key valued on both sides sums alike."""
    totals: defaultdict[LegacyKeyText, Decimal] = defaultdict(Decimal)
    for row_key, amount in after.values_list("pk", "valuation_amount"):
        legacy = mapping.legacy_of.get(str(row_key))
        if legacy is not None:
            totals[legacy] += amount
    both = set(before) & set(totals)
    if any(before[key] != totals[key] for key in both):
        return None
    seeded_sum = sum((totals[key] for key in both), Decimal(0))
    return f"{seeded_sum} over {len(both)} key(s) valued on both sides"


class PurchaseScope(NamedTuple):
    """One scope's figure changes and row judgements."""

    changes: tuple[FigureChange, ...]
    judgements: tuple[RowsJudgement, ...]


def judge_purchase_scope(
    scope: SnapshotScope,
    after: StatsData,
    library: UserLibrary,
    year: YearScope,
    mapping: ConversionMap,
) -> PurchaseScope:
    """Every figure of one scope, judged."""
    figures = scope["figures"]
    rows_before = {key: frozenset(scope["rows"][key]) for key in ROWS_KEYS}
    new_rows = _new_rows(library, year)._asdict()
    judgements = {
        key: judge_rows(key, rows_before[key], new_rows[key], mapping)
        for key in ROWS_KEYS
    }
    counts = {key: rows.count() for key, rows in new_rows.items()}
    amounts = {key: Decimal(amount) for key, amount in scope["amounts"].items()}
    now: Mapping[StatsKey, object] = after
    changes: list[FigureChange] = []
    for key in STATS_SOURCES:
        if key not in figures and key not in now:
            continue
        if key not in now:
            changes.append(FigureChange(key, figures[key], None, None))
            continue
        value = now[key]
        if key in FIGURE_ROWS:
            rows_key = FIGURE_ROWS[key]
            #: A list compares as its count.
            was = figures.get(key, len(rows_before[rows_key]))
            current = value.count() if isinstance(value, QuerySet) else value
            attribution = _attribution(judgements[rows_key])
        elif key not in figures:
            was, current, attribution = None, value, "a new figure"
        elif key in FIGURE_RATIOS:
            ratio = FIGURE_RATIOS[key]
            was, current = figures[key], value
            clean = all(judgements[rows_key].clean for rows_key in ratio.sets)
            recomputed = clean and ratio.expected(counts, after) == current
            attribution = "recomputed from the judged rows" if recomputed else None
        elif key == "total_spent_currency":
            was, current = figures[key], value
            attribution = _currency_attribution(was, current, library)
        elif key == "total_spent":
            #: The legacy total was a float sum.
            was = Decimal(str(figures[key])).quantize(CENT, ROUND_HALF_UP)
            current = value
            attribution = (
                _spent(amounts, new_rows["valued"], mapping)
                if judgements["valued"].clean
                else None
            )
        else:
            was, current = figures[key], _plain(value)
            attribution = UNCHANGED if was == current else None
        if was != current or attribution is None:
            changes.append(FigureChange(key, was, current, attribution))
    return PurchaseScope(tuple(changes), tuple(judgements.values()))


def _currency_attribution(
    was: object, current: object, library: UserLibrary
) -> str | None:
    if was == current:
        return UNCHANGED
    if current == spending_currency(library, None):
        return "the published currency"
    return None


def _plain(value: object) -> object:
    """The snapshot's spelling of a value."""
    return snapshot_value(comparable(value))


def read_snapshot(
    snapshot: Mapping[str, Any], library: UserLibrary
) -> Mapping[str, SnapshotScope]:
    """The scopes, or a refusal."""
    if snapshot.get("format") != SNAPSHOT_FORMAT:
        raise GateRefused(
            f"Snapshot format {snapshot.get('format')!r}; this gate reads "
            f"format {SNAPSHOT_FORMAT}. Write it again with --snapshot."
        )
    if snapshot.get("library") != str(library.pk):
        raise GateRefused(
            f"Snapshot of library {snapshot.get('library')}, not {library.pk}."
        )
    scopes = snapshot.get("scopes")
    if not scopes:
        raise GateRefused("The snapshot holds no scope.")
    return scopes
