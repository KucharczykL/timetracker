"""Pure sort-string core for list views (no Django).

The generic half of the sorting feature: the URL ``?sort=`` format and the
term model. A ``?sort=`` value is a signed comma-list of public keys
(e.g. ``"-playtime,name"``) — bare key = ascending, leading ``-`` = descending
(Django ``order_by`` semantics). This module both *parses* that string into
terms and *builds* it back from terms (the clickable-header targets).

The ORM binding (``SortSpec``, the per-model ``*_SORTS`` maps, ``apply_sort``)
lives in ``games/sorting.py`` and imports from here — same split as
``common/criteria.py`` (generic) ↔ ``games/filters.py`` (app-specific). See
docs/superpowers/specs/2026-06-21-list-view-sort-param-design.md.
"""

from collections.abc import Container, Sequence
from typing import NamedTuple

type SortKey = (
    str  # public column key in a *_SORTS map and in a URL term ("playtime", "name")
)
type SortString = str  # comma-list of signed SortKeys: the URL ?sort= value and *_DEFAULT_SORT ("-date,created")


class SortTerm(NamedTuple):
    key: SortKey
    descending: bool  # True = "-key" (desc), False = bare key (asc)


class ParsedSort(NamedTuple):
    terms: list[SortTerm]
    unknown: list[SortKey]  # keys not in the map — the view turns these into warnings


def parse_sort_terms(raw: SortString, valid_keys: Container[SortKey]) -> ParsedSort:
    """Parse a signed comma-list into terms, splitting out unknown keys.

    ``valid_keys`` only needs ``in`` support — a ``*_SORTS`` dict (keyed by
    SortKey) satisfies it, so the ORM-side SortMap need not be imported here.
    """
    terms: list[SortTerm] = []
    unknown: list[SortKey] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        descending = token.startswith("-")
        key = token.lstrip("-")
        if key in valid_keys:
            terms.append(SortTerm(key, descending))
        else:
            unknown.append(key)
    return ParsedSort(terms, unknown)


def _format(terms: Sequence[SortTerm]) -> SortString:
    return ",".join(("-" if term.descending else "") + term.key for term in terms)


def collapse_sort(active: Sequence[SortTerm], key: SortKey) -> SortString:
    """Plain-click target: collapse the sort to a single column, asc-first.

    If ``key`` is the *sole* active term, flip its direction; any other case
    (inactive, or active only as a secondary term) → ``key`` ascending.
    """
    if len(active) == 1 and active[0].key == key:
        return _format([SortTerm(key, not active[0].descending)])
    return _format([SortTerm(key, False)])


def cycle_sort(active: Sequence[SortTerm], key: SortKey) -> SortString:
    """Shift-click target: cycle ``key`` within the ordered term list.

    Absent → append ``(key, asc)`` at the end; ascending → flip to descending
    in place; descending → remove. Removing the last term yields ``""`` (the
    caller drops ``?sort=`` so the view default applies).
    """
    terms = list(active)
    index = next((i for i, term in enumerate(terms) if term.key == key), None)
    if index is None:
        terms.append(SortTerm(key, False))
    elif not terms[index].descending:
        terms[index] = SortTerm(key, True)
    else:
        del terms[index]
    return _format(terms)
