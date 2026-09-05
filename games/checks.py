"""Startup checks over the projection tables."""

import datetime
import time
import uuid
from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register
from django.db import models
from django.utils import timezone

from games.models import ProjectionModel
from games.projections import (
    stale_projection_references,
    unaudited_projection_references,
)

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
    for field in model._meta.local_fields:
        errors.extend(_check_field(model, field))
    return errors


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
