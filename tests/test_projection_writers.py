"""The door registry: which writes a guard lets through."""

import pytest
from django.db import connection

from games.models import PlayerGame, PurchaseValuation
from games.projection_writers import (
    GuardedKind,
    ProjectionWriter,
    ProjectionWriteRefused,
    guarded_kinds_written,
    guarded_tables,
    install_guard,
    open_writer,
    projection_writes,
    refuse_unpermitted_writes,
)

PLAYER_GAME_DELETE = f'DELETE FROM "{PlayerGame._meta.db_table}"'
VALUATION_DELETE = f'DELETE FROM "{PurchaseValuation._meta.db_table}"'
PLAIN_DELETE = 'DELETE FROM "games_not_guarded_at_all"'


class Recorder:
    """A fake execute that records what it ran."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str, params: object, many: bool, context: object) -> str:
        self.statements.append(sql)
        return "ran"


def test_guarded_tables_hold_every_projection_and_the_valuation():
    tables = guarded_tables()
    assert tables[PlayerGame._meta.db_table] is GuardedKind.PROJECTION
    assert tables[PurchaseValuation._meta.db_table] is GuardedKind.VALUATION
    assert all(name == name.lower() for name in tables)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (PLAYER_GAME_DELETE, frozenset({GuardedKind.PROJECTION})),
        (VALUATION_DELETE, frozenset({GuardedKind.VALUATION})),
        (PLAIN_DELETE, frozenset()),
        ('SELECT 1 FROM "games_playergame"', frozenset()),
        ("INSERT INTO (broken", frozenset(GuardedKind)),
        (
            f'TRUNCATE "games_plain", "{PlayerGame._meta.db_table}"',
            frozenset({GuardedKind.PROJECTION}),
        ),
        ('TRUNCATE "games_plain" CASCADE', frozenset(GuardedKind)),
    ],
)
def test_guarded_kinds_written(sql, expected):
    assert guarded_kinds_written(sql) == expected


def test_projection_writes_nest_and_the_innermost_door_decides():
    assert open_writer() is None
    with projection_writes(ProjectionWriter.PROJECTOR):
        assert open_writer() is ProjectionWriter.PROJECTOR
        with projection_writes(ProjectionWriter.VALUATION_PUBLISHER):
            assert open_writer() is ProjectionWriter.VALUATION_PUBLISHER
        assert open_writer() is ProjectionWriter.PROJECTOR
    assert open_writer() is None


def test_a_permitted_door_lets_the_write_through():
    recorder = Recorder()
    with projection_writes(ProjectionWriter.PROJECTOR):
        result = refuse_unpermitted_writes(
            recorder, PLAYER_GAME_DELETE, None, False, {}
        )
    assert result == "ran"
    assert recorder.statements == [PLAYER_GAME_DELETE]


def test_a_door_of_the_wrong_kind_refuses_before_the_database():
    recorder = Recorder()
    with (
        projection_writes(ProjectionWriter.VALUATION_PUBLISHER),
        pytest.raises(ProjectionWriteRefused, match="games_playergame"),
    ):
        refuse_unpermitted_writes(recorder, PLAYER_GAME_DELETE, None, False, {})
    assert recorder.statements == []


def test_a_write_with_no_door_is_refused_and_names_none():
    recorder = Recorder()
    with pytest.raises(ProjectionWriteRefused, match="open writer is none"):
        refuse_unpermitted_writes(recorder, VALUATION_DELETE, None, False, {})
    assert recorder.statements == []


def test_a_cascade_truncate_needs_a_door_for_both_kinds():
    recorder = Recorder()
    cascade = 'TRUNCATE "games_plain" CASCADE'
    with (
        projection_writes(ProjectionWriter.PROJECTOR),
        pytest.raises(ProjectionWriteRefused, match="cannot read"),
    ):
        refuse_unpermitted_writes(recorder, cascade, None, False, {})
    with projection_writes(ProjectionWriter.LIBRARY_PURGE):
        refuse_unpermitted_writes(recorder, cascade, None, False, {})
    assert recorder.statements == [cascade]


def test_a_statement_outside_the_guarded_tables_passes_with_no_door():
    recorder = Recorder()
    assert refuse_unpermitted_writes(recorder, PLAIN_DELETE, None, False, {}) == "ran"
    select = 'SELECT 1 FROM "games_playergame"'
    assert refuse_unpermitted_writes(recorder, select, None, False, {}) == "ran"
    assert recorder.statements == [PLAIN_DELETE, select]


def test_install_guard_inserts_once_at_the_front(monkeypatch):
    def other(execute, sql, params, many, context):
        return execute(sql, params, many, context)

    monkeypatch.setattr(connection, "execute_wrappers", [other])
    install_guard(connection)
    install_guard(connection)
    assert connection.execute_wrappers == [refuse_unpermitted_writes, other]
