"""What a batch changed on conventional rows.

A conventional row writes no event, so its batch Undo reads here the
value each field held before the batch.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime

from django.db.models import Min, Model
from django.utils.dateparse import parse_datetime

from games.models import BatchChange, UserLibrary
from games.reads.fact_change import FactChange

#: A row's field, as the ledger names it.
type FieldName = str  # "group"

#: `app_label.model_name` of a row.
type ModelLabel = str  # "games.platform"

#: An act's declared name, or its Undo's.
type ActName = str  # "platform.edit"

#: A field's JSON value back to what the row holds.
type Decoder = Callable[[object], object]


def _datetime(value: object) -> object:
    return None if value is None else parse_datetime(str(value))


def _text(value: object) -> object:
    return "" if value is None else str(value)


#: Each recorded field's reading.
FIELD_DECODERS: Mapping[FieldName, Decoder] = {
    "removed_at": _datetime,
    "group": _text,
    "icon": _text,
}


def _stored(value: object) -> object:
    """Full precision: the JSON encoder drops microseconds."""
    return value.isoformat() if isinstance(value, datetime) else value


def label_of(model: type[Model]) -> ModelLabel:
    return model._meta.label_lower


def record(
    library: UserLibrary,
    *,
    batch: uuid.UUID,
    act: ActName,
    row: Model,
    field: FieldName,
    earlier: object,
    stated: object,
) -> None:
    """One field's change; a repeat records nothing."""
    if field not in FIELD_DECODERS:
        raise ValueError(f"The ledger reads no {field!r}; add its decoder.")
    BatchChange.objects.get_or_create(
        batch=batch,
        model_label=label_of(type(row)),
        row_id=row.pk,
        field=field,
        defaults={
            "library": library,
            "act": act,
            "earlier": _stored(earlier),
            "stated": _stored(stated),
        },
    )


def recorded(
    library: UserLibrary, *, batch: uuid.UUID, row: Model, field: FieldName
) -> bool:
    """Whether this batch changed that field."""
    return BatchChange.objects.filter(
        library=library,
        batch=batch,
        model_label=label_of(type(row)),
        row_id=row.pk,
        field=field,
    ).exists()


def batch_rows(
    library: UserLibrary, batch: uuid.UUID, model: type[Model]
) -> list[uuid.UUID]:
    """The rows one batch changed, in the order it reached them."""
    return list(
        BatchChange.objects.filter(
            library=library, batch=batch, model_label=label_of(model)
        )
        .values("row_id")
        .annotate(first=Min("created_at"))
        .order_by("first", "row_id")
        .values_list("row_id", flat=True)
    )


def batch_act(library: UserLibrary, batch: uuid.UUID) -> ActName | None:
    """The act that wrote a batch, or none."""
    return (
        BatchChange.objects.filter(library=library, batch=batch)
        .order_by("created_at", "id")
        .values_list("act", flat=True)
        .first()
    )


def row_changes(
    library: UserLibrary, batch: uuid.UUID, row: Model
) -> dict[FieldName, FactChange[object]]:
    """Each field one batch changed on one row."""
    changes: dict[FieldName, FactChange[object]] = {}
    for field, earlier, stated in BatchChange.objects.filter(
        library=library, batch=batch, model_label=label_of(type(row)), row_id=row.pk
    ).values_list("field", "earlier", "stated"):
        decode = FIELD_DECODERS[field]
        changes[field] = FactChange(decode(earlier), decode(stated))
    return changes
