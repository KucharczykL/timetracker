"""Which tables a SQL statement writes."""

import pytest

from games.sql_writes import write_targets


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ('INSERT INTO "games_playergame" (id) VALUES (%s)', ("games_playergame",)),
        (
            '/* a comment */ INSERT INTO "games_playergame" (id) VALUES (%s)',
            ("games_playergame",),
        ),
        (
            (
                'WITH moved AS (DELETE FROM "old" RETURNING *) '
                'INSERT INTO "new" SELECT * FROM moved'
            ),
            ("old", "new"),
        ),
        ('SELECT 1 FROM "games_playergame"', ()),
        ("SAVEPOINT s1", ()),
        (
            'UPDATE ONLY pg_temp."games_playergame__shadow" SET id = id',
            ("games_playergame__shadow",),
        ),
        (
            'TRUNCATE "games_a", games_b, "Games_C"',
            ("games_a", "games_b", "games_c"),
        ),
        (
            'TRUNCATE TABLE ONLY "games_a", pg_temp."games_b" RESTRICT;',
            ("games_a", "games_b"),
        ),
        ('TRUNCATE "games_a" *, games_b', ("games_a", "games_b")),
        ('TRUNCATE "games_a", "games_b" CASCADE', ("",)),
        ('truncate table "games_a" cascade;', ("",)),
        ('-- clear\n/* first */ DELETE FROM "Games_Y"', ("games_y",)),
    ],
)
def test_write_targets_names_every_table_a_statement_writes(statement, expected):
    assert write_targets(statement) == expected


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO (broken",
        "TRUNCATE",
        'TRUNCATE "games_a" games_b',
        'TRUNCATE "games_a"; DELETE FROM "games_b"',
    ],
)
def test_write_targets_refuses_a_write_it_cannot_parse(statement):
    assert write_targets(statement) == ("",)
