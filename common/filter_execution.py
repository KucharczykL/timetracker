"""Execution safeguards for user-controlled regex filters."""

import json
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate

from django.contrib import messages
from django.db import OperationalError, connection, transaction
from django.db.models import Model, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

if TYPE_CHECKING:
    from common.criteria import FilterQueryContext, OperatorFilter

FILTER_STATEMENT_TIMEOUT_MS = 1000


def execute_filter[M: Model](
    filter_object: OperatorFilter,
    queryset: QuerySet[M],
    context: FilterQueryContext,
) -> QuerySet[M]:
    return filter_object.apply(queryset, context)


class FilterQueryTimeout(Exception):
    pass


def contains_regex_modifier(filter_json: str) -> bool:
    try:
        parsed = json.loads(filter_json)
    except json.JSONDecodeError:
        return False

    def visit(value: Any) -> bool:
        if isinstance(value, dict):
            return value.get("modifier") in {
                "MATCHES_REGEX",
                "NOT_MATCHES_REGEX",
            } or any(visit(item) for item in value.values())
        return isinstance(value, list) and any(visit(item) for item in value)

    return visit(parsed)


def _is_statement_timeout(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if getattr(current, "sqlstate", None) == "57014":
            return True
        current = current.__cause__
    return False


def run_with_statement_timeout[R](callback: Callable[[], R]) -> R:
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    [str(FILTER_STATEMENT_TIMEOUT_MS)],
                )
            return callback()
    except OperationalError as exc:
        if _is_statement_timeout(exc):
            raise FilterQueryTimeout from exc
        raise


def run_with_regex_timeout[R](filter_json: str, callback: Callable[[], R]) -> R:
    if not contains_regex_modifier(filter_json):
        return callback()
    return run_with_statement_timeout(callback)


def regex_timeout_view[**P](
    view: Callable[Concatenate[HttpRequest, P], HttpResponse],
) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
    @wraps(view)
    def wrapped(
        request: HttpRequest, *args: P.args, **kwargs: P.kwargs
    ) -> HttpResponse:
        filter_json = request.GET.get("filter", "")
        try:
            return run_with_regex_timeout(
                filter_json, lambda: view(request, *args, **kwargs)
            )
        except FilterQueryTimeout:
            messages.warning(
                request, "Filter took too long to evaluate. Simplify it and try again."
            )
            query = request.GET.copy()
            query.pop("filter", None)
            query.pop("page", None)
            url = request.path
            if query:
                url = f"{url}?{query.urlencode()}"
            return redirect(url)

    return wrapped


def regex_timeout_api[**P, R](
    view: Callable[Concatenate[HttpRequest, P], R],
) -> Callable[Concatenate[HttpRequest, P], R]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> R:
        from ninja.errors import HttpError

        try:
            return run_with_regex_timeout(
                request.GET.get("filter", ""), lambda: view(request, *args, **kwargs)
            )
        except FilterQueryTimeout as exc:
            raise HttpError(
                400, "Invalid filter: filter took too long to evaluate."
            ) from exc

    return wrapped
