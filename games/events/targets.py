"""Where a projector family writes its rows.

A family never imports its projection model. It writes
`self.target.model(Shelf).objects...`, and what a rebuild redirects is the class
the family is handed rather than the statement it writes. `LIVE_TARGET` hands
back the live model; `ShadowTarget` hands back a manufactured twin naming the
temp table the rebuild created beside it.

This is a module of its own rather than part of `projection.py`, which holds no
ORM reference by design -- a registry of families over a value. Importing
`ProjectionModel` there for a protocol bound would contradict it, so the import
below is under `TYPE_CHECKING`: PEP 695 evaluates a type parameter's bound
lazily, so the name is never looked up at runtime.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast
from weakref import WeakKeyDictionary

from django.apps.registry import Apps
from django.db import models

if TYPE_CHECKING:
    from games.models import ProjectionModel

#: What a twin's table is called: the live table, plus this.
SHADOW_SUFFIX = "__shadow"

type ModelNamespace = dict[str, Any]


class ProjectionTarget(Protocol):
    """The tables one fold writes.

    The signature says `type[M]` and `ShadowTarget` returns a class that is not
    an `M`. The cast is deliberate, and is stated here so nobody removes it as a
    mistake: the twin carries the same fields under the same names, which is
    what every caller uses it for, and a protocol describing "a model with these
    fields" cannot be written for fields known only at runtime.
    """

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...


class LiveTarget:
    """The tables the application serves."""

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]:
        return model


LIVE_TARGET: ProjectionTarget = LiveTarget()


#: Manufactured twins, one per live model, keyed by the registry the live model
#: was declared in. Per-registry rather than one flat dict because an
#: `isolate_apps` registry dies with the test that made it, and a twin of one of
#: its models must die with it -- a twin pointing at a dead registry would
#: otherwise be handed to the next caller.
_TWINS: WeakKeyDictionary[Apps, dict[type[models.Model], type[models.Model]]] = (
    WeakKeyDictionary()
)


class ShadowTarget:
    """The temp tables one rebuild attempt writes.

    A twin is cached per live model per process, because manufacturing a second
    one would register a second model under the same name and displace the
    first in the registry -- with a warning, and with the two classes no longer
    comparable.
    """

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]:
        twins = _TWINS.setdefault(model._meta.apps, {})
        twin = twins.get(model)
        if twin is None:
            twin = _manufacture(model)
            twins[model] = twin
        return cast("type[M]", twin)


def _manufacture(model: type[models.Model]) -> type[models.Model]:
    namespace: ModelNamespace = {
        "__module__": __name__,
        "__qualname__": f"{model.__name__}Shadow",
        "Meta": _shadow_meta(model),
    }
    for field in model._meta.local_fields:
        name, _path, args, kwargs = field.deconstruct()
        namespace[name] = _rebuilt(field, args, kwargs)
    return type(f"{model.__name__}Shadow", (models.Model,), namespace)


def _shadow_meta(model: type[models.Model]) -> type:
    return type(
        "Meta",
        (),
        {
            "app_label": model._meta.app_label,
            #: The table is a temp table the rebuild created with LIKE, so
            #: Django owns none of its schema.
            "managed": False,
            "db_table": f"{model._meta.db_table}{SHADOW_SUFFIX}",
            #: A twin belongs to the registry its live model came from, so a
            #: twin of an isolated model lands in the isolated registry.
            "apps": model._meta.apps,
        },
    )


def _rebuilt(
    field: models.Field, args: Sequence[Any], kwargs: dict[str, Any]
) -> models.Field:
    """One field again, built from its own `deconstruct()`.

    Deep-copying the field and setting `related_name = "+"` on the copy looks
    equivalent and is not: `ForeignObjectRel.hidden` is a `cached_property` and
    `Field.__deepcopy__` shallow-copies `remote_field`, so the copy carries the
    cached `False` across. The reverse accessor stays visible, clashes with the
    live model's, and `fields.E304` is then reported against the **live** model
    as well -- permanently, because the twin is cached for the process.
    """
    if field.remote_field is not None:
        kwargs = {**kwargs, "related_name": "+"}
    return field.__class__(*args, **kwargs)
