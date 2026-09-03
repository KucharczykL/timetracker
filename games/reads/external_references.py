"""The live references of a batch of rows.

One query per kind present, so no list pays per row.
"""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from games.external_references import CatalogTarget
from games.models import ExternalReference

#: Every live reference a batch holds, under the row it names.
type ReferenceMap = dict[UUID, list[ExternalReference]]


def references_for(rows: Sequence[CatalogTarget]) -> ReferenceMap:
    """Every live reference of these rows, under the row's own id.

    `CatalogTarget` rather than `Model`, because the lookup below
    reads a table of the four kinds that may hold a reference. A
    Device would leave it as a bare `KeyError` where the rest of
    this app refuses a wrong target in a sentence; the checker
    refuses it instead, before anything runs.
    """
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


def held_by(references: ReferenceMap, row_id: UUID) -> list[ExternalReference]:
    """What one row of the batch states, or nothing.

    A row with no reference is absent from the map, so every
    reader needs the same empty answer. Two of them wrote their
    own and disagreed about its type; this is the one place that
    knows the map promises a list.

    A copy, because Game detail gathers an Edition's references
    and its Releases' into one list. Extending what it was handed
    would write the Releases into the Edition's own entry.
    """
    return list(references.get(row_id, ()))
