"""Reading a queryset one page at a time.

A cursor belongs to one connection, and a pooler in transaction or statement
pooling mode hands the next FETCH a different one. A page carries its own WHERE
and holds no connection state.

The key is the order, and any ordering on the queryset is replaced. Its last
field must be unique, or a page boundary skips a row or yields one twice. Every
field of it must lie in one index: PostgreSQL scans a btree either way, so one
ascending index serves both directions.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from django.db.models import F, Model, QuerySet
from django.db.models.fields.tuple_lookups import (
    Tuple,
    TupleGreaterThan,
    TupleLessThan,
)

#: A local field of the model.
type FieldName = str

#: Memory, not speed: matches REPLAY_CHUNK_SIZE.
DEFAULT_PAGE_SIZE = 500


def keyset_pages[ModelT: Model](
    queryset: QuerySet[ModelT],
    *,
    key: Sequence[FieldName],
    descending: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[ModelT]:
    """Yield every row in key order, paging."""
    if not key:
        raise ValueError("A keyset read needs at least one key field.")
    if page_size < 1:
        raise ValueError("A keyset page holds at least one row.")

    prefix = "-" if descending else ""
    ordered = queryset.order_by(*(f"{prefix}{field}" for field in key))
    last: tuple[Any, ...] | None = None
    while True:
        page = ordered if last is None else _after(ordered, key, last, descending)
        rows = list(page[:page_size])
        if not rows:
            return
        yield from rows
        if len(rows) < page_size:
            return
        last = tuple(getattr(rows[-1], field) for field in key)


def _after[ModelT: Model](
    queryset: QuerySet[ModelT],
    key: Sequence[FieldName],
    last: tuple[Any, ...],
    descending: bool,
) -> QuerySet[ModelT]:
    """Everything strictly past `last` in key order.

    A composite key compares as a row value. `Q(a__lt=x) | Q(a=x, b__lt=y)` is
    the same logic and the wrong SQL: PostgreSQL cannot read an OR as an index
    range condition, so every page would scan from the start of the index.
    """
    if len(key) == 1:
        return queryset.filter(**{f"{key[0]}__{'lt' if descending else 'gt'}": last[0]})
    comparison = TupleLessThan if descending else TupleGreaterThan
    return queryset.filter(comparison(Tuple(*(F(field) for field in key)), last))
