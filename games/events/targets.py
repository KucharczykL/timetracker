"""Where a projector family writes its rows."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast
from weakref import WeakKeyDictionary

from django.apps.registry import Apps
from django.db import models

if TYPE_CHECKING:
    from games.models import ProjectionModel

#: A twin's table: the live one, suffixed.
SHADOW_SUFFIX = "__shadow"

type ModelNamespace = dict[str, Any]


class ProjectionTarget(Protocol):
    """The tables one handler writes."""

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...


class LiveTarget:
    """The tables the application serves."""

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]:
        return model


LIVE_TARGET: ProjectionTarget = LiveTarget()


#: One twin per live model, per registry.
_TWINS: WeakKeyDictionary[Apps, dict[type[models.Model], type[models.Model]]] = (
    WeakKeyDictionary()
)


class ShadowTarget:
    """The temp tables a rebuild attempt writes."""

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]:
        twins = _TWINS.setdefault(model._meta.apps, {})
        twin = twins.get(model)
        if twin is None:
            twin = _manufacture(model, self)
            twins[model] = twin
        return cast("type[M]", twin)


def _manufacture(
    model: type[models.Model], target: ProjectionTarget
) -> type[models.Model]:
    namespace: ModelNamespace = {
        "__module__": __name__,
        "__qualname__": f"{model.__name__}Shadow",
        "Meta": _shadow_meta(model),
    }
    for field in model._meta.local_fields:
        name, _path, args, kwargs = field.deconstruct()
        namespace[name] = _rebuilt(field, args, kwargs, model, target)
    return type(f"{model.__name__}Shadow", (models.Model,), namespace)


def _shadow_meta(model: type[models.Model]) -> type:
    return type(
        "Meta",
        (),
        {
            "app_label": model._meta.app_label,
            #: The rebuild owns the temp table's schema.
            "managed": False,
            "db_table": f"{model._meta.db_table}{SHADOW_SUFFIX}",
            #: A twin joins its live model's registry.
            "apps": model._meta.apps,
        },
    )


def _rebuilt(
    field: models.Field,
    args: Sequence[Any],
    kwargs: dict[str, Any],
    owner: type[models.Model],
    target: ProjectionTarget,
) -> models.Field:
    """Not a deep copy: `hidden` caches False.

    `ForeignObjectRel.hidden` is a cached property. A deep copy keeps the
    cached value. Django then reports `fields.E304` against the live model.
    The error stays until the process stops.
    """
    if field.remote_field is None:
        return field.__class__(*args, **kwargs)
    #: A live delete must not read twins.
    #:
    #: A twin joins the live registry and stays there; its temp table does not.
    #: `related_name` hides the accessor, but the deletion collector reads
    #: hidden relations too, and skips DO_NOTHING alone. Any other rule makes a
    #: later delete of a referenced live row read a table that is gone.
    kwargs = {**kwargs, "related_name": "+", "on_delete": models.DO_NOTHING}
    related = _projection_referenced_by(field)
    if related is not None:
        #: A twin points at a twin. Live rows are another rebuild's input.
        kwargs["to"] = "self" if related is owner else target.model(related)
    return field.__class__(*args, **kwargs)


def _projection_referenced_by(field: models.Field) -> type[ProjectionModel] | None:
    """The projection this relation points at, if any."""
    from games.models import ProjectionModel

    related = field.remote_field.model if field.remote_field is not None else None
    if isinstance(related, type) and issubclass(related, ProjectionModel):
        return related
    return None
