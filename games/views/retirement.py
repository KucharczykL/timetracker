"""The delete affordance for a referenceable row.

A sibling of `confirm_and_delete`. It asks the policy what the
POST will do, so the page can say so.
"""

from collections.abc import Sequence
from functools import partial
from typing import Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from common.components.core import Children
from common.returns import UrlName
from games.retention import reference_count, tombstone_or_delete
from games.views.deletion import confirm_and_apply


def retention_message(noun: str, label: str, count: int) -> str:
    """What the page says when a row leaves a tombstone."""
    return (
        f"{count} recorded event(s) reference {label}, and their history has to "
        f"stay readable. The {noun} will be removed from your library along "
        "with everything below, but the record itself is kept out of sight "
        "rather than deleted:"
    )


def confirm_and_retire(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    noun: str,
    label: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
) -> HttpResponse:
    """Confirm on GET, retire on POST.

    `message` is the copy for a real delete. `noun` and `label`
    name the row in the replacement copy.
    """
    referencing = reference_count(instance)
    return confirm_and_apply(
        request,
        action=partial(tombstone_or_delete, instance),
        title=title,
        message=(
            retention_message(noun, label, referencing) if referencing else message
        ),
        confirm_label="Delete",
        fallback=fallback,
        fallback_args=fallback_args,
        details=details,
        reject=detail_url,
    )
