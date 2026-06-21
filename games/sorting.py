"""Structured sorting for list views (Stash-inspired, paired with games/filters.py).

A list view maps a public sort key to a SortSpec; the URL ?sort= param is a
signed comma-list of those keys (e.g. "-playtime,name"). See
docs/superpowers/specs/2026-06-21-list-view-sort-param-design.md.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Aggregate

type SortKey = str         # public column key in a *_SORTS map and in a URL term ("playtime", "name")
type SortString = str      # comma-list of signed SortKeys: the URL ?sort= value and *_DEFAULT_SORT ("-date,created")
type AnnotationName = str  # an alias added via .annotate(), then referenced by SortSpec.expression
type OrderField = str      # SortSpec.expression: a real model field path OR an AnnotationName

# alias name -> the ORM aggregate that computes it, applied via queryset.annotate()
# e.g. {"total_playtime": Sum("sessions__duration_total")}
type Annotations = dict[AnnotationName, Aggregate]


@dataclass(frozen=True)
class SortSpec:
    expression: OrderField           # unsigned; a real column path or an AnnotationName
    annotate: Annotations | None = None


class SortTerm(NamedTuple):
    key: SortKey
    descending: bool      # True = "-key" (desc), False = bare key (asc)


type SortMap = dict[SortKey, SortSpec]


class ParsedSort(NamedTuple):
    terms: list[SortTerm]
    unknown: list[SortKey]   # keys not in the map — the view turns these into warnings


def parse_sort_terms(raw: SortString, sort_map: SortMap) -> ParsedSort:
    terms: list[SortTerm] = []
    unknown: list[SortKey] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        descending = token.startswith("-")
        key = token.lstrip("-")
        if key in sort_map:
            terms.append(SortTerm(key, descending))
        else:
            unknown.append(key)
    return ParsedSort(terms, unknown)
