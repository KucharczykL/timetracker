"""How every act reads the statement's filter."""

from collections.abc import Callable

from django.db.models import Model, QuerySet

from common.criteria import OperatorFilter
from games.bulk_actions import FilterJson
from games.filters import filter_query_context_for_library
from games.models import UserLibrary

#: One mode's `?filter=` reader, e.g. `parse_session_filter`.
type ParseFilter = Callable[[FilterJson], OperatorFilter | None]


def narrowed[RowT: Model](
    rows: QuerySet[RowT],
    library: UserLibrary,
    filter_json: FilterJson,
    parse: ParseFilter,
) -> QuerySet[RowT]:
    """The act's base, narrowed by the statement's filter.

    Never `apply_structured_filter`, which drops a filter it cannot
    read: on a list that widens a page, and here it would widen the
    act to every row the base holds. The library's query context
    compiles it, so a statement naming a related entity narrows the
    act as it narrowed the list.
    """
    if not filter_json:
        return rows
    parsed = parse(filter_json)
    if parsed is None:
        return rows
    return parsed.apply(rows, filter_query_context_for_library(library))
