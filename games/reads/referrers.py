"""The projections that name a projection row.

A registry, not a rule: removal reads it to refuse taking a
row other rows still name, and the placeholder read asks it
whether anybody has recorded against a run. It lives beside
the reads because a command that reads it would make the
read modules import the command modules back.
"""

from __future__ import annotations

import uuid
from typing import Any, NamedTuple, Protocol, cast

from django.db import models
from django.db.models import QuerySet

from games.models import (
    HistoricalPlaytimeRun,
    LibraryEntry,
    PlayerSession,
    Playthrough,
    ProjectionModel,
    Purchase,
)
from games.projections import FieldName


class RemovableReads(Protocol):
    """A manager whose reads skip a removed row."""

    def alive(self) -> QuerySet[Any]: ...


def _skips_removed_rows(model: type[ProjectionModel]) -> bool:
    """Whether the model's manager states `alive()`."""
    return hasattr(model._default_manager, "alive")


def _checked(
    model: type[ProjectionModel], field_name: FieldName, target: type[ProjectionModel]
) -> None:
    """Refuse a member the query cannot run.

    A malformed member would raise a FieldError inside build(),
    which answers every removal with a 500. Refusing it here
    states it at import.
    """
    field = model._meta.get_field(field_name)
    if not isinstance(field, models.ForeignKey):
        raise TypeError(f"{model.__name__}.{field_name} is not a foreign key.")
    if field.related_model is not target:
        raise TypeError(
            f"{model.__name__}.{field_name} names "
            f"{field.related_model.__name__}, not a {target.__name__.lower()}."
        )
    if not _skips_removed_rows(model):
        raise TypeError(
            f"{model.__name__} states no alive(), so a removed row of it "
            f"would keep a {target.__name__.lower()} in place forever."
        )


class BlockingReferrer(NamedTuple):
    """A way to name a row that blocks its removal."""

    #: A projection: ProjectionModel gives it library.
    model: type[ProjectionModel]
    #: Field name alias from games/projections.py.
    field_name: FieldName
    #: The model the field names.
    target: type[ProjectionModel]
    #: What a person is shown.
    sentence: str

    @classmethod
    def on(
        cls,
        model: type[ProjectionModel],
        field_name: FieldName,
        *,
        target: type[ProjectionModel],
        sentence: str,
    ) -> BlockingReferrer:
        """The one construction path."""
        _checked(model, field_name, target)
        return cls(model, field_name, target, sentence)


class CascadingReferrer(NamedTuple):
    """A way to name a row its removal takes."""

    model: type[ProjectionModel]
    field_name: FieldName
    target: type[ProjectionModel]

    @classmethod
    def on(
        cls,
        model: type[ProjectionModel],
        field_name: FieldName,
        *,
        target: type[ProjectionModel],
    ) -> CascadingReferrer:
        """The one construction path."""
        _checked(model, field_name, target)
        return cls(model, field_name, target)


type Referrer = BlockingReferrer | CascadingReferrer


HISTORICAL_PLAYTIME_RECORDED = (
    "Historical playtime is recorded on this playthrough. Restate it onto "
    "another playthrough, or remove it, before removing this one."
)

#: Every sentence names a remedy that exists.
BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = (
    BlockingReferrer.on(
        PlayerSession,
        "playthrough",
        target=Playthrough,
        sentence=(
            "Sessions are recorded on this playthrough. Move them to "
            "another playthrough before removing it."
        ),
    ),
    BlockingReferrer.on(
        HistoricalPlaytimeRun,
        "playthrough",
        target=Playthrough,
        sentence=HISTORICAL_PLAYTIME_RECORDED,
    ),
)

#: The target's remove and restore take these.
CASCADING_REFERRERS: tuple[CascadingReferrer, ...] = (
    CascadingReferrer.on(Purchase, "entry", target=LibraryEntry),
)


def referrers_of(target: type[ProjectionModel]) -> tuple[BlockingReferrer, ...]:
    """Registered members naming `target`, read per call."""
    return tuple(
        referrer for referrer in BLOCKING_REFERRERS if referrer.target is target
    )


def _named(referrer: Referrer, row: ProjectionModel) -> ProjectionModel:
    if type(row) is not referrer.target:
        raise TypeError(
            f"{referrer.model.__name__}.{referrer.field_name} names a "
            f"{referrer.target.__name__}, not a {type(row).__name__}."
        )
    return row


def _live_rows_naming(referrer: Referrer, row: ProjectionModel) -> QuerySet[Any]:
    """Every live row of the referrer naming the row."""
    #: `on()` refuses a manager without it. The annotation on
    #: `_default_manager` names the base, which cannot say so.
    reads = cast(RemovableReads, referrer.model._default_manager)
    return reads.alive().filter(**{referrer.field_name: _named(referrer, row)})


def rows_naming(referrer: BlockingReferrer, row: ProjectionModel) -> QuerySet[Any]:
    """Every row naming `row`, removed ones included.

    Unscoped by the library as well. An act that takes a row
    away on its own asks whether anything at all still names
    it: a removed row is restorable and a foreign row is
    drift, and either is a reason to leave the row alone.
    """
    return referrer.model._default_manager.filter(
        **{referrer.field_name: _named(referrer, row)}
    )


def blocking_referrer(row: ProjectionModel) -> BlockingReferrer | None:
    """The first member a live row of this library answers.

    Scoped on the library, as `_other_live_ordinary_runs` is: a
    person cannot act on advice about rows their library does not
    hold, so a foreign row is `foreign_referrer`'s to refuse.
    """
    for referrer in referrers_of(type(row)):
        if _live_rows_naming(referrer, row).filter(library=row.library).exists():
            return referrer
    return None


class ForeignReferrer(NamedTuple):
    """Rows of other libraries naming a row."""

    referrer: Referrer
    library_ids: tuple[uuid.UUID, ...]


def foreign_referrer(row: ProjectionModel) -> ForeignReferrer | None:
    """The first member a row of another library answers.

    Such a row is the drift `audit_library_ownership` reports.
    Removing the row would leave it live under a removed row,
    where no read finds it and no restore reaches it.
    """
    target = type(row)
    members: tuple[Referrer, ...] = (
        *referrers_of(target),
        *(member for member in CASCADING_REFERRERS if member.target is target),
    )
    for referrer in members:
        library_ids = tuple(
            _live_rows_naming(referrer, row)
            .exclude(library=row.library)
            .order_by("library_id")
            .values_list("library_id", flat=True)
            .distinct()
        )
        if library_ids:
            return ForeignReferrer(referrer, library_ids)
    return None
