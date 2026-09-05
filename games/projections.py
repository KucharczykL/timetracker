"""Projection tables, and what they name outside."""

import uuid
from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q

from games.models import PlayerGame, Playthrough, ProjectionModel

type FieldName = str  # e.g. "player_game"
type ModelLabel = str  # e.g. "games.PlayerGame"
type ReferenceKey = tuple[ModelLabel, FieldName]
type ViolationSentence = str  # e.g. "PlayerGame.game: <id> names Game <id>"

#: The field every library-scoped model carries.
LIBRARY_FIELD: FieldName = "library"

#: The column that field writes.
_LIBRARY_ID = f"{LIBRARY_FIELD}_id"


class ProjectionReference(NamedTuple):
    """One foreign key out of a projection."""

    model: type[ProjectionModel]
    field: models.ForeignKey[Any, Any]

    @classmethod
    def on(
        cls, model: type[ProjectionModel], field_name: FieldName
    ) -> ProjectionReference:
        """The one construction path; refuses unauditable pairs."""
        field = model._meta.get_field(field_name)
        if not isinstance(field, models.ForeignKey):
            raise TypeError(f"{model.__name__}.{field_name} is not a foreign key.")
        if not _is_library_scoped(field.related_model):
            raise TypeError(
                f"{model.__name__}.{field_name} names "
                f"{field.related_model.__name__}, which holds no library."
            )
        return cls(model, field)

    @property
    def key(self) -> ReferenceKey:
        """What makes two references the same pair."""
        return (self.model._meta.label, self.field.name)

    def __str__(self) -> str:
        return f"{self.model.__name__}.{self.field.name}"


def projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]:
    """Every projection table in `apps`, sorted."""
    found = [
        model
        for model in apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    ]
    #: `managed` is what excludes the manufactured twins.
    return tuple(sorted(found, key=lambda model: model._meta.db_table))


def _is_library_scoped(model: type[models.Model]) -> bool:
    """Whether `model` rows carry a library column.

    Concrete, because `get_field` answers for a reverse relation too:
    `UserLibrary.user` is `related_name="library"`, which would make the
    user model read as scoped and every lookup built below a FieldError.
    """
    try:
        field = model._meta.get_field(LIBRARY_FIELD)
    except FieldDoesNotExist:
        return False
    return field.concrete


def projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]:
    """Every foreign key out of a projection.

    Keyed on the referenced model carrying a library, not on it being a
    projection: that is the condition the cost follows. `on_delete` does
    not narrow the walk -- `RESTRICT` stops the referenced library from
    ever being purged, and `CASCADE` would take rows out of it.
    """
    found = [
        ProjectionReference(model, field)
        for model in projection_models(apps)
        for field in model._meta.concrete_fields
        if isinstance(field, models.ForeignKey)
        and _is_library_scoped(field.related_model)
    ]
    return tuple(
        sorted(
            found,
            key=lambda reference: (
                reference.model._meta.db_table,
                reference.field.column,
            ),
        )
    )


#: Every reference the ownership audit reads.
AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...] = (
    ProjectionReference.on(PlayerGame, "game"),
    ProjectionReference.on(Playthrough, "player_game"),
)


def unaudited_projection_references(
    apps: Apps = global_apps,
) -> tuple[ProjectionReference, ...]:
    """Walked references the registry omits."""
    audited = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}
    return tuple(
        reference
        for reference in projection_references(apps)
        if reference.key not in audited
    )


def stale_projection_references(
    apps: Apps = global_apps,
) -> tuple[ProjectionReference, ...]:
    """Registered references the walk no longer finds.

    A stale entry passes the completeness check and fails later, inside
    the query the audit builds from it. A registry `apps` does not hold
    the model of is another registry's, not a stale entry.
    """
    walked = {reference.key for reference in projection_references(apps)}
    present = {model._meta.label for model in projection_models(apps)}
    return tuple(
        reference
        for reference in AUDITED_PROJECTION_REFERENCES
        if reference.model._meta.label in present and reference.key not in walked
    )


def cross_library_violations(
    library_ids: Sequence[uuid.UUID],
    *,
    references: Iterable[ProjectionReference] = AUDITED_PROJECTION_REFERENCES,
) -> list[ViolationSentence]:
    """Rows naming a row in another library.

    The `isnull` clause is on the referenced row's library, and it is
    load-bearing wherever that library is nullable -- a shared catalog
    row. Django compiles `exclude()` to mean "not equal, nulls
    included": it puts `IS NOT NULL` inside the negation, so a
    referenced row with no library would read as a violation.
    """
    violations: list[ViolationSentence] = []
    for reference in references:
        name = reference.field.name
        #: The base manager: a removed row keeps its key.
        rows = (
            reference.model._base_manager.filter(
                Q(**{f"{_LIBRARY_ID}__in": library_ids})
                | Q(**{f"{name}__{_LIBRARY_ID}__in": library_ids}),
                **{f"{name}__{LIBRARY_FIELD}__isnull": False},
            )
            .exclude(**{f"{name}__{_LIBRARY_ID}": F(_LIBRARY_ID)})
            .values_list("pk", reference.field.attname)
        )
        referenced = reference.field.related_model.__name__
        for row_id, referenced_id in rows:
            violations.append(
                f"{reference}: {row_id} names {referenced} {referenced_id}"
            )
    return violations
