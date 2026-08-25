"""Startup checks over the projection tables."""

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.core.checks import CheckMessage, Error, Tags, register
from django.db import models

from games.models import ProjectionModel


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
    if getattr(field.default, "__module__", None) == "uuid":
        errors.append(
            Error(
                f"{where} defaults to a freshly minted UUID.",
                hint=(
                    "A projection key comes from the event — its aggregate_id "
                    "or correlation_id, or a uuid5 over them — so that a "
                    "rebuild produces the identity it produced last time."
                ),
                obj=model,
                id="games.E005",
            )
        )
    return errors
