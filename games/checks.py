"""Startup checks over the projection tables."""

import datetime
import time
import uuid
from collections.abc import Collection, Sequence
from typing import Any

from django.apps import AppConfig
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register
from django.db import models
from django.utils import timezone

from common.components.icons_generated import ICON_NODES
from common.criteria import FilterError, declared_through_paths, resolve_through_path
from common.platform_icons import PLATFORM_ICONS, PlatformIcon
from games.endpoint_fields import (
    EndpointColumns,
    OpeningEndpointColumns,
    endpoint_constraints,
)
from games.endpoints import ENDPOINTS
from games.models import ProjectionModel
from games.projections import (
    stale_projection_references,
    unaudited_projection_references,
)
from timetracker.temporal import TemporalLowerBound, TemporalUpperBound

#: A new UUID every call, so never a projection key.
_UUID_FACTORIES = frozenset(
    factory
    for name in ("uuid1", "uuid4", "uuid6", "uuid7", "uuid8")
    if callable(factory := getattr(uuid, name, None))
)

#: The clock decides these, so a rebuild moves them.
_CLOCK_FACTORIES = frozenset(
    {
        timezone.now,
        timezone.localtime,
        timezone.localdate,
        datetime.datetime.now,
        datetime.datetime.today,
        datetime.date.today,
        time.time,
    }
)

#: Argless builtins returning one value every call.
_CONSTANT_FACTORIES = frozenset({dict, list, set, tuple, frozenset, str, int, float})


def unsnipped_platform_icons(
    listed: Collection[PlatformIcon], drawn: Collection[str]
) -> list[CheckMessage]:
    """A listed icon no snippet draws."""
    missing = sorted(set(listed) - set(drawn))
    if not missing:
        return []
    return [
        Error(
            f"Platform icons no snippet draws: {missing}.",
            hint="Add games/templates/icons/<slug>.html and run make gen-icons.",
            id="games.E013",
        )
    ]


@register()
def check_platform_icons(**kwargs: Any) -> list[CheckMessage]:
    """Every listed platform icon has a snippet."""
    return unsnipped_platform_icons(PLATFORM_ICONS, ICON_NODES)


@register(Tags.models)
def check_projection_models(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    apps: Apps = global_apps,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a field the events cannot determine."""
    labels = None if app_configs is None else {config.label for config in app_configs}
    errors: list[CheckMessage] = []
    for model in apps.get_models():
        if not issubclass(model, ProjectionModel):
            continue
        #: A twin repeats its live model's fields.
        if not model._meta.managed:
            continue
        if labels is not None and model._meta.app_label not in labels:
            continue
        errors.extend(_check_one(model))
    return errors


def _check_one(model: type[ProjectionModel]) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    primary_key = model._meta.pk
    if isinstance(primary_key, models.AutoField):
        errors.append(
            Error(
                "A projection model may not have an auto-increment primary key.",
                hint=(
                    "The shadow copy gets an identity sequence of its own, "
                    "starting at 1, so every unchanged row would diff as a "
                    "deletion and an insertion. Declare an explicit primary key "
                    "carrying a value the events determine."
                ),
                obj=model,
                id="games.E003",
            )
        )
    if not _carries_library_pair(model):
        errors.append(
            Error(
                "A projection model carries no unique constraint over its "
                "primary key and library.",
                hint=(
                    "The projector's upsert conflicts on that pair, so a "
                    "creation under an identity another library holds is "
                    "refused by the primary key instead of rewriting the row. "
                    "Name library_identity_constraint() in Meta.constraints."
                ),
                obj=model,
                id="games.E012",
            )
        )
    for field in model._meta.local_fields:
        errors.extend(_check_field(model, field))
    return errors


def _carries_library_pair(model: type[ProjectionModel]) -> bool:
    """Whether the upsert's arbiter exists.

    A conditional constraint is a partial index. It arbitrates only a
    statement that repeats its predicate. A deferrable one is never an
    arbiter. Neither counts.
    """
    pair = {model._meta.pk.name, "library"}
    return any(
        isinstance(constraint, models.UniqueConstraint)
        and constraint.condition is None
        and constraint.deferrable is None
        and set(constraint.fields) == pair
        for constraint in model._meta.constraints
    )


def _check_field(
    model: type[ProjectionModel], field: models.Field
) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    where = f"{model._meta.label}.{field.name}"
    if getattr(field, "auto_now", False):
        errors.append(
            Error(
                f"{where} uses auto_now.",
                hint=(
                    "A projected timestamp comes from the event — recorded_at "
                    "or effective_time — not from the clock at rebuild time."
                ),
                obj=model,
                id="games.E001",
            )
        )
    if getattr(field, "auto_now_add", False):
        errors.append(
            Error(
                f"{where} uses auto_now_add.",
                hint=(
                    "A projected timestamp comes from the event — recorded_at "
                    "or effective_time — not from the clock at rebuild time."
                ),
                obj=model,
                id="games.E002",
            )
        )
    if field.db_default is not models.NOT_PROVIDED:
        errors.append(
            Error(
                f"{where} has a database default.",
                hint=(
                    "PostgreSQL copies the default onto the shadow table and "
                    "evaluates it there independently, so the rebuilt row "
                    "differs from the live one by construction."
                ),
                obj=model,
                id="games.E004",
            )
        )
    #: has_default() first: NOT_PROVIDED is callable.
    if field.has_default() and callable(field.default):
        unreproducible = _check_callable_default(model, field, where)
        if unreproducible is not None:
            errors.append(unreproducible)
    return errors


def _check_callable_default(
    model: type[ProjectionModel], field: models.Field, where: str
) -> CheckMessage | None:
    """How a callable default fails a rebuild."""
    if field.default in _UUID_FACTORIES:
        return Error(
            f"{where} defaults to a freshly minted UUID.",
            hint=(
                "A projection key comes from the event — its aggregate_id "
                "or correlation_id, or a uuid5 over them — so that a "
                "rebuild produces the identity it produced last time."
            ),
            obj=model,
            id="games.E005",
        )
    if field.default in _CLOCK_FACTORIES:
        return Error(
            f"{where} defaults to the clock.",
            hint=(
                "A rebuild evaluates the default again, at rebuild time, so "
                "every row differs from the live one. A projected timestamp "
                "comes from the event — recorded_at or effective_time."
            ),
            obj=model,
            id="games.E006",
        )
    if field.default in _CONSTANT_FACTORIES:
        return None
    return Error(
        f"{where} defaults to a callable.",
        hint=(
            "A rebuild evaluates the default again, so only a constant "
            "reproduces the live row. E005 and E006 name two factory "
            "families; this refuses every other callable, including a "
            "wrapper around one of them. An argless builtin constructor is the "
            "exception, because it returns one value every call and Django "
            "wants a callable for a mutable default."
        ),
        obj=model,
        id="games.E007",
    )


@register(Tags.models)
def check_projection_references(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    apps: Apps = global_apps,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a reference the ownership audit does not read."""
    labels = None if app_configs is None else {config.label for config in app_configs}
    errors: list[CheckMessage] = []
    for reference in unaudited_projection_references(apps):
        if labels is not None and reference.model._meta.app_label not in labels:
            continue
        #: A ForeignKey always states one; the base relation types it optional.
        on_delete = getattr(
            reference.field.remote_field.on_delete, "__name__", "unstated"
        )
        errors.append(
            Error(
                f"{reference} is an unaudited {on_delete} reference out of a "
                "projection table.",
                hint=(
                    "A value naming another library's row is invisible to "
                    "every query a rebuild runs: a shadow table copies no "
                    "foreign key, and the diff is scoped to one library. It "
                    "is found when the swap refuses at commit, or never. Add "
                    "the pair to AUDITED_PROJECTION_REFERENCES in "
                    "games/projections.py, which is what "
                    "audit_library_ownership reads."
                ),
                obj=reference.model,
                id="games.E009",
            )
        )
    for reference in stale_projection_references(apps):
        if labels is not None and reference.model._meta.app_label not in labels:
            continue
        errors.append(
            Error(
                f"{reference} is registered and is no longer a reference out "
                "of a projection table.",
                hint=(
                    "The ownership audit and the swap's refusal both build a "
                    "query from this pair, so a stale entry raises a "
                    "FieldError -- and the worst place for that is the "
                    "handler explaining a refused swap. Take the pair out of "
                    "AUDITED_PROJECTION_REFERENCES in games/projections.py."
                ),
                obj=reference.model,
                id="games.E010",
            )
        )
    return errors


@register(Tags.models)
def check_comparison_through(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    apps: Apps = global_apps,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a declared comparison path that is not to-one at every hop."""
    labels = None if app_configs is None else {config.label for config in app_configs}
    errors: list[CheckMessage] = []
    for model in apps.get_models():
        if not issubclass(model, ProjectionModel):
            continue
        if labels is not None and model._meta.app_label not in labels:
            continue
        for path, _label in declared_through_paths(model):
            try:
                resolve_through_path(model, path)
            except FilterError as error:
                errors.append(
                    Error(
                        str(error),
                        hint=(
                            "comparison_through offers a path as one hop of a "
                            "comparison operand, so an F() across it must reach "
                            "one row. Declare a to-one path, or leave the "
                            "relation to the multi-valued grammar."
                        ),
                        obj=model,
                        id="games.E011",
                    )
                )
    return errors


@register()
def check_atomic_requests(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a transaction dispatches cannot nest in.

    Untagged, because a database tag would skip it: it reads only
    settings, and a tagged check runs only when a database is asked for.
    """
    wrapped = sorted(
        alias
        for alias, config in settings.DATABASES.items()
        if config.get("ATOMIC_REQUESTS")
    )
    if not wrapped:
        return []
    return [
        Error(
            f"ATOMIC_REQUESTS is on for {', '.join(wrapped)}.",
            hint=(
                "run_in_transaction opens the transaction it retries, so it "
                "refuses to run inside one: every view that dispatches a "
                "command would raise NestedTransactionNotSupported at request "
                "time. Wrap the work that needs a transaction, not the request."
            ),
            id="games.E008",
        )
    ]


def endpoint_errors(
    endpoint: EndpointColumns, model: type[models.Model]
) -> list[CheckMessage]:
    """Where a model departs from the endpoint it registers."""
    problems: list[str] = []
    if not issubclass(model, ProjectionModel):
        problems.append("its model is no projection")
    declared = {field.name: field for field in model._meta.get_fields()}
    named = [endpoint.when, endpoint.lower, endpoint.upper, endpoint.marker]
    named.append(endpoint.note)
    if endpoint.way is not None:
        named.append(endpoint.way.column)
    problems.extend(
        f"it declares no column {name!r}" for name in named if name not in declared
    )
    for bound, expression in (
        (endpoint.lower, TemporalLowerBound),
        (endpoint.upper, TemporalUpperBound),
    ):
        field = declared.get(bound)
        if field is None:
            continue
        #: django-stubs declares no `expression` on GeneratedField.
        computed = getattr(field, "expression", None)
        if not (
            isinstance(field, models.GeneratedField)
            and isinstance(computed, expression)
            and computed.source_expressions == [models.F(endpoint.when)]
        ):
            problems.append(
                f"{bound!r} is not the {expression.__name__} of {endpoint.when!r}"
            )
    held = {constraint.name: constraint for constraint in model._meta.constraints}
    problems.extend(
        f"its Meta.constraints lack {constraint.name!r}"
        for constraint in endpoint_constraints(endpoint)
        if held.get(constraint.name) != constraint
    )
    marker = declared.get(endpoint.marker)
    if isinstance(endpoint, OpeningEndpointColumns) and getattr(marker, "null", True):
        problems.append("its marker admits null")
    return [_endpoint_error(endpoint, problem, model) for problem in problems]


def _endpoint_error(
    endpoint: EndpointColumns, problem: str, model: type[models.Model] | None = None
) -> Error:
    return Error(
        f"Endpoint {endpoint.name!r} on {endpoint.model_label}: {problem}.",
        hint=(
            "Declare the endpoint's columns through the factories in "
            "games/endpoint_fields.py, and spread endpoint_constraints() "
            "into the model's own Meta.constraints."
        ),
        obj=model,
        id="games.E014",
    )


@register(Tags.models)
def check_endpoints(**kwargs: Any) -> list[CheckMessage]:
    """Every registered endpoint names what its model holds."""
    errors: list[CheckMessage] = []
    seen: set[tuple[str, str]] = set()
    for endpoint in ENDPOINTS:
        key = (endpoint.model_label, endpoint.name)
        if key in seen:
            errors.append(_endpoint_error(endpoint, "another endpoint has its name"))
        seen.add(key)
        try:
            model = endpoint.model
        except LookupError:
            errors.append(_endpoint_error(endpoint, "its model label names no model"))
            continue
        errors.extend(endpoint_errors(endpoint, model))
    return errors
