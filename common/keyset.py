"""Reading a large queryset one page at a time, without a server-side cursor.

`QuerySet.iterator()` opens a cursor, and a cursor belongs to one connection: a
pooler in transaction or statement pooling mode hands the next FETCH a different
connection and the read fails. A keyset read runs one ordinary query per page,
each carrying its own WHERE, so it depends on no connection state at all.

The key names the order. Its last field must be unique, or a page boundary can
skip a row or yield one twice. Every field of the key must lie in one index,
ascending: PostgreSQL scans a btree in either direction, so one ascending index
serves both directions of the same key. A key without an index re-sorts the
whole table on every page, which costs more than the single sort it replaces.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from django.db.models import F, Model, QuerySet
from django.db.models.fields.tuple_lookups import (
    Tuple,
    TupleGreaterThan,
    TupleLessThan,
)

#: A concrete local field of the model, named as `order_by` would name it.
type FieldName = str

#: Matches REPLAY_CHUNK_SIZE: a memory decision rather than a speed one.
DEFAULT_PAGE_SIZE = 500


def keyset_pages[ModelT: Model](
    queryset: QuerySet[ModelT],
    *,
    key: Sequence[FieldName],
    descending: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[ModelT]:
    """Yield every row of `queryset` in `key` order, one query per page.

    Any ordering already on the queryset is replaced: the order and the key are
    the same thing here, and a mismatch between them skips rows silently.
    """
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
    """Everything strictly past `last` in the key's order.

    A composite key compares as a row value. Written as
    `Q(a__lt=x) | Q(a=x, b__lt=y)` it is the same logic and the wrong SQL:
    PostgreSQL cannot read an OR as an index range condition, so each page would
    scan from the start of the index and the whole walk would be quadratic.
    """
    if len(key) == 1:
        return queryset.filter(**{f"{key[0]}__{'lt' if descending else 'gt'}": last[0]})
    comparison = TupleLessThan if descending else TupleGreaterThan
    return queryset.filter(comparison(Tuple(*(F(field) for field in key)), last))
