"""Projection tables, and what they name outside."""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q

from games.models import (
    Edition,
    HistoricalPlaytime,
    HistoricalPlaytimeRun,
    LibraryEntry,
    PlayerGame,
    PlayerSession,
    Playthrough,
    ProjectionModel,
    Release,
)

type FieldName = str  # e.g. "player_game"
type ModelLabel = str  # e.g. "games.PlayerGame"
type ReferenceKey = tuple[ModelLabel, FieldName]
type ViolationSentence = str  # e.g. "PlayerGame.game: <id> names Game <id>"

#: The field every library-scoped model carries.
LIBRARY_FIELD: FieldName = "library"

#: The column that field writes.
_LIBRARY_ID = f"{LIBRARY_FIELD}_id"

type LibraryPath = str  # e.g. "edition__game__library"

#: How a catalog row without a library column reaches one.
LIBRARY_PATHS: Mapping[type[models.Model], LibraryPath] = {
    Release: "edition__game__library",
    Edition: "game__library",
}


class ProjectionReference(NamedTuple):
    """One foreign key out of a projection."""

    model: type[ProjectionModel]
    field: models.ForeignKey[Any, Any]
    #: From the named row to its library.
    library_path: LibraryPath = LIBRARY_FIELD

    @classmethod
    def on(
        cls, model: type[ProjectionModel], field_name: FieldName
    ) -> ProjectionReference:
        """The one construction path; refuses unauditable pairs."""
        field = model._meta.get_field(field_name)
        if not isinstance(field, models.ForeignKey):
            raise TypeError(f"{model.__name__}.{field_name} is not a foreign key.")
        path = library_path_of(field.related_model)
        if path is None:
            raise TypeError(
                f"{model.__name__}.{field_name} names "
                f"{field.related_model.__name__}, which holds no library."
            )
        return cls(model, field, path)

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


def library_path_of(model: type[models.Model]) -> LibraryPath | None:
    """How `model` rows reach a library, or None.

    The concrete column first, then the map, so a throwaway
    registry's twin of a catalog model answers from its own
    column. Concrete, because `get_field` answers for a reverse
    relation too: `UserLibrary.user` is `related_name="library"`,
    which would make the user model read as scoped and every
    lookup built below a FieldError.
    """
    try:
        field = model._meta.get_field(LIBRARY_FIELD)
    except FieldDoesNotExist:
        return LIBRARY_PATHS.get(model)
    return LIBRARY_FIELD if field.concrete else LIBRARY_PATHS.get(model)


def _is_library_scoped(model: type[models.Model]) -> bool:
    return library_path_of(model) is not None


def projection_references(apps: Apps = global_apps) -> tuple[ProjectionReference, ...]:
    """Every foreign key out of a projection.

    Keyed on the referenced model carrying a library, not on it being a
    projection: that is the condition the cost follows. `on_delete` does
    not narrow the walk -- `RESTRICT` stops the referenced library from
    ever being purged, and `CASCADE` would take rows out of it.
    """
    found = [
        ProjectionReference(model, field, path)
        for model in projection_models(apps)
        for field in model._meta.concrete_fields
        if isinstance(field, models.ForeignKey)
        and (path := library_path_of(field.related_model)) is not None
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
    ProjectionReference.on(HistoricalPlaytime, "device"),
    ProjectionReference.on(HistoricalPlaytime, "player_game"),
    ProjectionReference.on(HistoricalPlaytime, "reclassified_from"),
    ProjectionReference.on(HistoricalPlaytimeRun, "playthrough"),
    ProjectionReference.on(HistoricalPlaytimeRun, "record"),
    ProjectionReference.on(LibraryEntry, "player_game"),
    ProjectionReference.on(LibraryEntry, "release"),
    ProjectionReference.on(PlayerGame, "game"),
    ProjectionReference.on(PlayerSession, "device"),
    ProjectionReference.on(PlayerSession, "playthrough"),
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
        named_library = f"{reference.field.name}__{reference.library_path}"
        named_library_id = f"{named_library}_id"
        #: The base manager: a removed row keeps its key.
        rows = (
            reference.model._base_manager.filter(
                Q(**{f"{_LIBRARY_ID}__in": library_ids})
                | Q(**{f"{named_library_id}__in": library_ids}),
                **{f"{named_library}__isnull": False},
            )
            .exclude(**{named_library_id: F(_LIBRARY_ID)})
            .values_list("pk", reference.field.attname)
        )
        referenced = reference.field.related_model.__name__
        for row_id, referenced_id in rows:
            violations.append(
                f"{reference}: {row_id} names {referenced} {referenced_id}"
            )
    return violations
