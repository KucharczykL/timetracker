"""The projection tables, and every row outside a library they can name."""

from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q

from games.models import PlayerGame, Playthrough, ProjectionModel

type FieldName = str  # e.g. "player_game"

#: The column every library-scoped model carries.
LIBRARY_FIELD: FieldName = "library"


class ProjectionReference(NamedTuple):
    """One foreign key out of a projection table."""

    model: type[ProjectionModel]
    field: models.ForeignKey[Any, Any]

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
    """Whether a row of `model` belongs to one library."""
    try:
        model._meta.get_field(LIBRARY_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]:
    """Every foreign key out of a projection into a library-scoped row.

    Keyed on the referenced model carrying a library, not on it being a
    projection: that is the condition the cost follows. `UserLibrary` has
    no library of its own, so the `library` column excludes itself and
    needs no case. `on_delete` does not narrow the walk either --
    `RESTRICT` stops the referenced library from ever being purged, and
    `CASCADE` would take rows out of it.
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


#: Every reference the ownership audit reads. `games.E009` refuses a walk
#: that finds one this list does not.
AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...] = (
    ProjectionReference(PlayerGame, PlayerGame._meta.get_field("game")),
    ProjectionReference(Playthrough, Playthrough._meta.get_field("player_game")),
)


def unaudited_projection_references(
    apps: Apps = global_apps,
) -> tuple[ProjectionReference, ...]:
    """Every reference the walk finds and the registry omits."""
    audited = {
        (reference.model._meta.label, reference.field.name)
        for reference in AUDITED_PROJECTION_REFERENCES
    }
    return tuple(
        reference
        for reference in projection_references(apps)
        if (reference.model._meta.label, reference.field.name) not in audited
    )


def cross_library_violations(
    references: Iterable[ProjectionReference],
    library_ids: Sequence[Any],
) -> list[str]:
    """Every row that names a row in another library.

    The `isnull` clause is on the referenced row's library, and it is
    load-bearing. Django compiles `exclude()` to mean "not equal, nulls
    included": it puts `IS NOT NULL` inside the negation, so a null on
    either side would be answered as a violation. A null foreign key
    joins no row, and a joined row with no library is shared.
    """
    violations: list[str] = []
    for reference in references:
        name = reference.field.name
        rows = (
            reference.model._default_manager.filter(
                Q(library_id__in=library_ids)
                | Q(**{f"{name}__library_id__in": library_ids}),
                **{f"{name}__library__isnull": False},
            )
            .exclude(**{f"{name}__library_id": F("library_id")})
            .values_list("pk", reference.field.attname)
        )
        referenced = reference.field.related_model.__name__
        for row_id, referenced_id in rows:
            violations.append(
                f"{reference}: {row_id} names {referenced} {referenced_id}"
            )
    return violations
