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
    "SortResult",
    "apply_sort",
    "parse_find_filter",
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


def parse_find_filter(request: HttpRequest) -> FindFilter:
    return FindFilter(
        sort=request.GET.get("sort") or None
    )  # FindFilter.sort holds a SortString
