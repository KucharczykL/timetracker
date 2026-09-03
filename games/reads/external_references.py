"""Live references of a batch of rows."""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from games.external_references import CatalogTarget
from games.models import ExternalReference

#: Live references, under the row they name.
type ReferenceMap = dict[UUID, list[ExternalReference]]


def references_for(rows: Sequence[CatalogTarget]) -> ReferenceMap:
    """Every live reference, under the row's id."""
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
    """What one row states, or nothing.

    A copy, because Game detail gathers an Edition's references
    and its Releases' into one list. Extending what it was handed
    would write the Releases into the Edition's own entry.
    """
    return list(references.get(row_id, ()))
