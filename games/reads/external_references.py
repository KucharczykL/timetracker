"""The live references of a batch of rows.

One query per kind present, so no list pays per row.
"""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from django.db.models import Model

from games.models import ExternalReference

#: Every live reference a batch holds, under the row it names.
type ReferenceMap = dict[UUID, list[ExternalReference]]


def references_for(rows: Sequence[Model]) -> ReferenceMap:
    """Every live reference of these rows, under the row's own id."""
    by_column: dict[str, list[UUID]] = defaultdict(list)
    for row in rows:
        by_column[ExternalReference.TARGET_FIELDS_BY_MODEL[type(row)]].append(row.pk)
    found: ReferenceMap = defaultdict(list)
    for column, ids in by_column.items():
        held = ExternalReference.objects.filter(
            removed_at__isnull=True, **{f"{column}__in": ids}
        ).order_by("provider")
        for reference in held:
            found[getattr(reference, column)].append(reference)
    return dict(found)
