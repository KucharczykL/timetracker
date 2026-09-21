"""The projections that name a run.

A registry, not a rule: removal reads it to refuse taking a
run rows still name, and the placeholder read asks it
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
    PlayerSession,
    Playthrough,
    ProjectionModel,
)
from games.projections import FieldName


class RemovableReads(Protocol):
    """A manager whose reads skip a removed row."""

    def alive(self) -> QuerySet[Any]: ...


def _skips_removed_rows(model: type[ProjectionModel]) -> bool:
    """Whether the model's manager states `alive()`."""
    return hasattr(model._default_manager, "alive")


class BlockingReferrer(NamedTuple):
    """One registered way to name a run."""

    #: A projection: ProjectionModel gives it library.
    model: type[ProjectionModel]
    #: Field name alias from games/projections.py.
    field_name: FieldName
    #: What a person is shown.
    sentence: str

    @classmethod
    def on(
        cls, model: type[ProjectionModel], field_name: FieldName, *, sentence: str
    ) -> BlockingReferrer:
        """The one construction path; refuses an entry the query cannot run.

        A malformed entry would raise a FieldError inside build(),
        which answers every removal with a 500. Refusing it here
        states it at import.
        """
        field = model._meta.get_field(field_name)
        if not isinstance(field, models.ForeignKey):
            raise TypeError(f"{model.__name__}.{field_name} is not a foreign key.")
        if field.related_model is not Playthrough:
            raise TypeError(
                f"{model.__name__}.{field_name} names "
                f"{field.related_model.__name__}, not a playthrough."
            )
        if not _skips_removed_rows(model):
            raise TypeError(
                f"{model.__name__} states no alive(), so a removed row of it "
                "would keep a run in place forever."
            )
        return cls(model, field_name, sentence)


HISTORICAL_PLAYTIME_RECORDED = (
    "Historical playtime is recorded on this playthrough. Restate it onto "
    "another playthrough, or remove it, before removing this one."
)

#: Every sentence names a remedy that exists.
BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = (
    BlockingReferrer.on(
        PlayerSession,
        "playthrough",
        sentence=(
            "Sessions are recorded on this playthrough. Move them to "
            "another playthrough before removing it."
        ),
    ),
    BlockingReferrer.on(
        HistoricalPlaytimeRun,
        "playthrough",
        sentence=HISTORICAL_PLAYTIME_RECORDED,
    ),
)


def _live_rows_naming(referrer: BlockingReferrer, run: Playthrough) -> QuerySet[Any]:
    """Every live row of the referrer naming the run."""
    #: `on()` refuses a manager without it. The annotation on
    #: `_default_manager` names the base, which cannot say so.
    reads = cast(RemovableReads, referrer.model._default_manager)
    return reads.alive().filter(**{referrer.field_name: run})


def rows_naming(referrer: BlockingReferrer, run: Playthrough) -> QuerySet[Any]:
    """Every row of the referrer naming the run, removed ones included.

    Unscoped by the library as well. What this answers is
    whether anything at all still points at the run, which
    is what an act asks before it takes one away on its own:
    a removed row is restorable and a foreign row is drift,
    and either is a reason to leave the run alone.
    """
    return referrer.model._default_manager.filter(**{referrer.field_name: run})


def blocking_referrer(run: Playthrough) -> BlockingReferrer | None:
    """The first registered entry a live row of this library answers.

    Scoped on the library, as `_other_live_ordinary_runs` is: a
    person cannot act on advice about rows their library does not
    hold, so a foreign row is `foreign_referrer`'s to refuse.
    """
    for referrer in BLOCKING_REFERRERS:
        if _live_rows_naming(referrer, run).filter(library=run.library).exists():
            return referrer
    return None


class ForeignReferrer(NamedTuple):
    """Rows of other libraries naming a run."""

    referrer: BlockingReferrer
    library_ids: tuple[uuid.UUID, ...]


def foreign_referrer(run: Playthrough) -> ForeignReferrer | None:
    """The first registered entry a row of another library answers.

    Such a row is the drift `audit_library_ownership` reports.
    Removing the run would leave it live under a removed run,
    where no read finds it and no restore reaches it.
    """
    for referrer in BLOCKING_REFERRERS:
        library_ids = tuple(
            _live_rows_naming(referrer, run)
            .exclude(library=run.library)
            .order_by("library_id")
            .values_list("library_id", flat=True)
            .distinct()
        )
        if library_ids:
            return ForeignReferrer(referrer, library_ids)
    return None
