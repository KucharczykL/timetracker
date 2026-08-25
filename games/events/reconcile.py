"""Which recorded references still name a row."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from django.db.models import Count, Q, QuerySet

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    PayloadKey,
    ReferenceKindName,
    ReferenceKindRegistry,
    Resolution,
)
from games.models import LibraryEventReference, UserLibrary
from games.retention import unresolved_among

#: How many gaps a report describes.
GAP_SAMPLE_LIMIT = 20

#: The label when the payload holds nothing.
NO_SNAPSHOT_RECORDED = "no snapshot recorded"

#: How many gaps a refusal names.
MESSAGE_GAP_LIMIT = 3

#: Retrying repairs nothing, so say what does.
REMEDY = (
    "A REQUIRED reference is retained rather than deleted, so these rows left "
    "outside the retention policy. Restore each one under the same id, or purge "
    "the library, which takes the events with it and leaves nothing to resolve."
)


class GapKey(NamedTuple):
    """The row a gap is about."""

    kind: ReferenceKindName
    referenced_id: uuid.UUID


class Snapshot(NamedTuple):
    """What an event recorded about a row."""

    label: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReferenceGap:
    """One named row that no longer exists."""

    kind: ReferenceKindName
    referenced_id: uuid.UUID
    #: Evidence of what was lost, never a replacement.
    label: str
    detail: str
    payload_key: PayloadKey
    first_sequence: int
    event_count: int


@dataclass(frozen=True, slots=True)
class ReferenceReconciliation:
    """Which recorded references of a library resolve."""

    library_id: uuid.UUID
    #: EVIDENCE_ONLY kinds are not checked.
    kinds_checked: tuple[ReferenceKindName, ...]
    #: Every unresolved row, named below or not.
    unresolved: int
    #: Bounded, ordered by kind and row.
    gaps: tuple[ReferenceGap, ...]

    @property
    def resolves(self) -> bool:
        """Whether every recorded reference names a row."""
        return self.unresolved == 0


class UnresolvedReferences(Exception):
    """A stream naming rows that left."""

    def __init__(self, reconciliation: ReferenceReconciliation) -> None:
        self.reconciliation = reconciliation
        super().__init__(summarise(reconciliation))


def summarise(reconciliation: ReferenceReconciliation) -> str:
    """The refusal, as one paragraph."""
    named = "; ".join(
        f"{gap.kind} {gap.referenced_id} ({gap.label!r}, {gap.detail!r}), first "
        f"named by event #{gap.first_sequence}, named by {gap.event_count} event(s)"
        for gap in reconciliation.gaps[:MESSAGE_GAP_LIMIT]
    )
    remaining = reconciliation.unresolved - min(
        len(reconciliation.gaps), MESSAGE_GAP_LIMIT
    )
    if remaining:
        named = f"{named}; and {remaining} more"
    return (
        f"This library records {reconciliation.unresolved} reference(s) naming "
        f"rows that no longer exist, so a replay cannot resolve them: {named}. "
        f"{REMEDY}"
    )


def require_resolvable_references(
    library: UserLibrary, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> None:
    """Refuse a library whose references name nothing."""
    reconciliation = reconcile_references(library, kinds=kinds)
    if not reconciliation.resolves:
        raise UnresolvedReferences(reconciliation)


def reconcile_references(
    library: UserLibrary, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> ReferenceReconciliation:
    """Reconcile recorded references against the rows."""
    index = LibraryEventReference.objects.for_library(library)
    #: The kinds come from the index, so `kind_for` raises.
    recorded = sorted(index.values_list("kind", flat=True).distinct())

    checked: list[ReferenceKindName] = []
    missing: list[GapKey] = []
    for name in recorded:
        kind = kinds.kind_for(name)
        if kind.resolution is not Resolution.REQUIRED:
            #: EVIDENCE_ONLY: the snapshot promised everything.
            continue
        checked.append(name)
        missing.extend(
            GapKey(name, referenced_id)
            for referenced_id in unresolved_among(kind, index.filter(kind=name))
            .values_list("referenced_id", flat=True)
            .distinct()
        )

    #: Bound the ids, then describe them.
    missing.sort()
    return ReferenceReconciliation(
        library_id=library.pk,
        kinds_checked=tuple(checked),
        unresolved=len(missing),
        gaps=_describe(index, missing[:GAP_SAMPLE_LIMIT]),
    )


def _describe(
    index: QuerySet[LibraryEventReference], sample: Sequence[GapKey]
) -> tuple[ReferenceGap, ...]:
    """The earliest naming event, and the count."""
    if not sample:
        return ()

    named = Q()
    for key in sample:
        named |= Q(kind=key.kind, referenced_id=key.referenced_id)

    #: One payload per gap, whatever names it.
    #:
    #: PostgreSQL makes the DISTINCT ON columns lead the ORDER BY, and Django
    #: emits nothing else. Thus the report is filed under (kind, referenced_id).
    #: Filing it under `first_sequence` needs every gap fetched to sort, which
    #: is the bound above given away.
    earliest = {
        GapKey(row["kind"], row["referenced_id"]): row
        for row in index.filter(named)
        .order_by("kind", "referenced_id", "event__sequence")
        .distinct("kind", "referenced_id")
        .values(
            "kind", "referenced_id", "payload_key", "event__sequence", "event__payload"
        )
    }
    counted = {
        GapKey(row["kind"], row["referenced_id"]): row["naming"]
        for row in index.filter(named)
        .values("kind", "referenced_id")
        .annotate(naming=Count("id"))
    }

    gaps = []
    for key in sample:
        row = earliest[key]
        snapshot = _snapshot_in(
            row["event__payload"], row["payload_key"], key.referenced_id
        )
        gaps.append(
            ReferenceGap(
                kind=key.kind,
                referenced_id=key.referenced_id,
                label=snapshot.label,
                detail=snapshot.detail,
                payload_key=row["payload_key"],
                first_sequence=row["event__sequence"],
                event_count=counted[key],
            )
        )
    return tuple(gaps)


def _snapshot_in(
    payload: Mapping[str, Any], payload_key: PayloadKey, referenced_id: uuid.UUID
) -> Snapshot:
    """What the payload recorded about that row."""
    held = payload.get(payload_key)
    candidates = held if isinstance(held, list) else [held]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate.get("id") == str(referenced_id):
            return Snapshot(
                label=str(candidate.get("label", "")),
                detail=str(candidate.get("detail", "")),
            )
    #: The index and the payload disagree.
    return Snapshot(label=NO_SNAPSHOT_RECORDED, detail="")
