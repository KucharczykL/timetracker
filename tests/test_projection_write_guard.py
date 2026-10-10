"""The projection write guard refuses writes, and its doors hold."""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from django.db import connection, connections, transaction
from django.db.models import F, Model
from projection_doors import (
    _frame_permits_seeding,
    _seed_from_tests,
    classify,
)

from games.models import PurchaseValuation
from games.projection_writers import (
    ProjectionWriter,
    ProjectionWriteRefused,
    open_writer,
    projection_writes,
    refuse_unpermitted_writes,
)
from games.projections import projection_models

GUARDED_MODELS: tuple[type[Model], ...] = (*projection_models(), PurchaseValuation)


def noop(execute: Callable[..., Any], sql, params, many, context):
    return execute(sql, params, many, context)


def _pk_name(model: type[Model]) -> str:
    return model._meta.pk.attname


def _table_count(model: type[Model]) -> int:
    return model._base_manager.count()


def _raw(sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _in_fresh_connection(action: Callable[[Any], Any]) -> Any:
    """Run `action` on a connection its own thread opens; re-raise its failure."""

    def target() -> Any:
        thread_connection = connections["default"]
        try:
            return action(thread_connection)
        finally:
            thread_connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(target).result()


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_update_is_refused_strictly(
    model, owned_library, projection_guard_strict
):
    before = _table_count(model)
    if any(field.attname == "library_id" for field in model._meta.concrete_fields):
        changes = {"library_id": F("library_id")}
    else:
        changes = {_pk_name(model): F(_pk_name(model))}
    with pytest.raises(ProjectionWriteRefused), transaction.atomic():
        #: The savepoint keeps the test transaction usable after a refusal.
        model._base_manager.filter(pk=uuid.uuid7()).update(**changes)
    assert _table_count(model) == before


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_bulk_create_is_refused_strictly(
    model, owned_library, projection_guard_strict
):
    before = _table_count(model)
    row = model(**{_pk_name(model): uuid.uuid7(), "library_id": owned_library.pk})
    with pytest.raises(ProjectionWriteRefused):
        model._base_manager.bulk_create([row])
    assert _table_count(model) == before


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_raw_delete_is_refused_strictly(
    model, owned_library, projection_guard_strict
):
    before = _table_count(model)
    with pytest.raises(ProjectionWriteRefused):
        _raw(f'DELETE FROM "{model._meta.db_table}"')
    assert _table_count(model) == before


@pytest.mark.django_db
def test_a_valuation_door_cannot_write_a_projection(projection_guard_strict):
    projection = next(model for model in projection_models())
    with (
        projection_writes(ProjectionWriter.VALUATION_PUBLISHER),
        pytest.raises(ProjectionWriteRefused),
    ):
        _raw(f'DELETE FROM "{projection._meta.db_table}"')


@pytest.mark.django_db
def test_a_projector_door_cannot_write_the_valuation(projection_guard_strict):
    with (
        projection_writes(ProjectionWriter.PROJECTOR),
        pytest.raises(ProjectionWriteRefused),
    ):
        _raw(f'DELETE FROM "{PurchaseValuation._meta.db_table}"')


@pytest.mark.django_db
def test_a_permitted_door_runs_its_write(projection_guard_strict):
    projection = next(model for model in projection_models())
    with projection_writes(ProjectionWriter.PROJECTOR):
        _raw(f'DELETE FROM "{projection._meta.db_table}" WHERE false')


@pytest.mark.django_db
def test_a_test_frame_seeds_without_strict():
    projection = next(model for model in projection_models())
    _raw(f'DELETE FROM "{projection._meta.db_table}" WHERE false')


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("tests", "x.py"), "test"),
        (("e2e", "x.py"), "test"),
        (("games", "x.py"), "app"),
        (("common", "x.py"), "app"),
        (("timetracker", "x.py"), "app"),
        (("contrib", "x.py"), "app"),
        (("scripts", "x.py"), "app"),
        ((".venv", "lib"), None),
        ((), None),
    ],
)
def test_classify_names_the_source_tree(parts, expected):
    assert classify(parts) == expected


def test_the_seeding_frame_check_permits_a_test_file():
    assert _frame_permits_seeding() is True


@pytest.mark.django_db(transaction=True)
def test_the_guard_survives_a_connection_opened_inside_a_wrapper():
    def action(thread_connection):
        with thread_connection.execute_wrapper(noop):
            thread_connection.ensure_connection()
        return list(thread_connection.execute_wrappers)

    wrappers = _in_fresh_connection(action)
    assert refuse_unpermitted_writes in wrappers
    assert noop not in wrappers


@pytest.mark.django_db(transaction=True)
def test_a_reconnect_does_not_duplicate_the_guard():
    def action(thread_connection):
        thread_connection.ensure_connection()
        thread_connection.close()
        thread_connection.ensure_connection()
        return list(thread_connection.execute_wrappers)

    wrappers = _in_fresh_connection(action)
    assert wrappers.count(refuse_unpermitted_writes) == 1
    assert wrappers.count(_seed_from_tests) == 1
    seed_index = wrappers.index(_seed_from_tests)
    assert wrappers[seed_index + 1] is refuse_unpermitted_writes


def test_the_migrate_door_opens_on_pre_migrate_and_closes_on_post_migrate():
    from games import apps

    assert open_writer() is None
    try:
        apps._open_migrate_door(sender=None)
        assert open_writer() is ProjectionWriter.MIGRATE
        apps._close_migrate_door(sender=None)
        assert open_writer() is None
    finally:
        apps._close_migrate_door(sender=None)
    apps._close_migrate_door(sender=None)
    assert open_writer() is None
