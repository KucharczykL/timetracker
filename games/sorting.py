"""Structured sorting for list views (Stash-inspired, paired with games/filters.py).

A list view maps a public sort key to a SortSpec; the URL ?sort= param is a
signed comma-list of those keys (e.g. "-playtime,name"). See
docs/superpowers/specs/2026-06-21-list-view-sort-param-design.md.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Aggregate, Max, Min, QuerySet, Sum
from django.http import HttpRequest

# The pure sort-string core lives in common.sorting; this module is the ORM
# binding. Re-exported here so existing `from games.sorting import …` keeps working.
from common.sorting import (
    ParsedSort,
    SortKey,
    SortString,
    SortTerm,
    parse_sort_terms,
)
from games.filters import FindFilter

__all__ = [
    "ParsedSort",
    "SortKey",
    "SortString",
    "SortTerm",
    "parse_sort_terms",
    "SortSpec",
    "SortMap",
    "GAME_SORTS",
    "GAME_DEFAULT_SORT",
    "SESSION_SORTS",
    "SESSION_DEFAULT_SORT",
    "PURCHASE_SORTS",
    "PURCHASE_DEFAULT_SORT",
    "MODE_SORTS",
    "SortResult",
    "apply_sort",
    "parse_find_filter",
    "parse_int_param",
]

type AnnotationName = (
    str  # an alias added via .annotate(), then referenced by SortSpec.expression
)
type OrderField = (
    str  # SortSpec.expression: a real model field path OR an AnnotationName
)

# alias name -> the ORM aggregate that computes it, applied via queryset.annotate()
# e.g. {"total_playtime": Sum("sessions__duration_total")}
type Annotations = dict[AnnotationName, Aggregate]


@dataclass(frozen=True)
class SortSpec:
    expression: OrderField  # unsigned; a real column path or an AnnotationName
    annotate: Annotations | None = None


type SortMap = dict[SortKey, SortSpec]


# ── Per-model sort maps ─────────────────────────────────────────────────────
# Cross-relation sorts use annotated aggregates (group by PK → no row dup).
# To-one relations (game__sort_name, device__name) are ordered directly.

GAME_SORTS: SortMap = {
    "name": SortSpec("name"),
    "sort_name": SortSpec("sort_name"),
    "year": SortSpec("year_released"),
    "status": SortSpec("status"),
    "wikidata": SortSpec("wikidata"),
    "created": SortSpec("created_at"),
    "playtime": SortSpec(
        "total_playtime", {"total_playtime": Sum("sessions__duration_total")}
    ),
    # No annotate dict: list_games pre-annotates `filtered_playtime` (playtime
    # restricted to the active session sub-filter) on the queryset, and this
    # spec just orders by that existing alias.
    "filtered_playtime": SortSpec("filtered_playtime"),
    "finished": SortSpec("last_finished", {"last_finished": Max("playevents__ended")}),
}
GAME_DEFAULT_SORT: SortString = "-created"

SESSION_SORTS: SortMap = {
    "name": SortSpec("game__sort_name"),
    "date": SortSpec("timestamp_start"),
    "duration": SortSpec("duration_total"),
    "device": SortSpec("device__name"),
    "created": SortSpec("created_at"),
}
SESSION_DEFAULT_SORT: SortString = "-date,created"

PURCHASE_SORTS: SortMap = {
    "name": SortSpec("first_game_name", {"first_game_name": Min("games__name")}),
    "type": SortSpec("type"),
    "price": SortSpec("converted_price"),
    "infinite": SortSpec("infinite"),
    "purchased": SortSpec("date_purchased"),
    "refunded": SortSpec("date_refunded"),
    "created": SortSpec("created_at"),
    "finished": SortSpec(
        "last_finished", {"last_finished": Max("games__playevents__ended")}
    ),
}
PURCHASE_DEFAULT_SORT: SortString = "-purchased,-created"


# Maps a FilterPreset.mode to the sort map that mode's list view applies. Only
# the modes with a *_SORTS map appear; playevents/devices/platforms are absent
# (their list views ignore ?sort=), so preset save gates sort on membership here
# and stores nothing for a sort-less mode. Keyset is a subset of MODE_PARSERS /
# FilterPreset.MODE_CHOICES, contract-tested in tests/test_filter_presets.py.
MODE_SORTS: dict[str, SortMap] = {
    "games": GAME_SORTS,
    "sessions": SESSION_SORTS,
    "purchases": PURCHASE_SORTS,
}


# ── Apply ───────────────────────────────────────────────────────────────────


class SortResult(NamedTuple):
    queryset: QuerySet
    terms: list[SortTerm]  # the order actually applied — #73's header UI consumes this
    unknown: list[SortKey]  # rejected keys — the view turns these into warning toasts


def apply_sort(
    queryset: QuerySet, find: FindFilter, sort_map: SortMap, default_sort: SortString
) -> SortResult:
    terms, unknown = parse_sort_terms(find.sort or "", sort_map)
    if not terms:
        # default_sort is trusted developer config — ignore any "unknown" from it
        terms, _ = parse_sort_terms(default_sort, sort_map)
    annotations: Annotations = {}
    order_by: list[OrderField] = []
    for term in terms:
        spec = sort_map[term.key]
        if spec.annotate:
            annotations.update(spec.annotate)
        order_by.append(("-" if term.descending else "") + spec.expression)
    if annotations:
        queryset = queryset.annotate(**annotations)
    return SortResult(queryset.order_by(*order_by), terms, unknown)


def parse_int_param(
    raw: str | None, *, default: int, minimum: int | None = None
) -> int:
    """Parse an optional integer query param, falling back to ``default``.

    Blank, missing, or non-integer input degrades to ``default`` (matching
    ``Paginator.get_page``'s forgiving contract) rather than raising. ``0`` is a
    valid value — it flows through (``per_page=0`` disables pagination).

    ``minimum`` rejects out-of-range integers: a parsed value below it degrades
    to ``default`` too. ``per_page`` passes ``minimum=0`` because Django's
    ``Paginator`` raises on a negative page size (it slices ``[0:-n]``), so a
    negative ``?per_page=`` — hand-typed or restored from a saved preset — would
    otherwise 500 the list (#337). This is the single load-side gate; the preset
    save path reuses it so it can't disagree on which sizes are valid."""
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def parse_find_filter(request: HttpRequest) -> FindFilter:
    """The single list-view request parser: sort + pagination.

    Free-text search is not here — it rides in the ``?filter=`` JSON as a
    ``search`` criterion."""
    return FindFilter(
        sort=request.GET.get("sort") or None,  # FindFilter.sort holds a SortString
        page=parse_int_param(request.GET.get("page"), default=FindFilter.page),
        per_page=parse_int_param(
            request.GET.get("per_page"), default=FindFilter.per_page, minimum=0
        ),
    )
