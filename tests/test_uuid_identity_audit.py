from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from games.identity_audit import (
    RESIDUAL_INTEGER_PRIMARY_KEYS,
    RESIDUAL_INTEGER_RELATIONS,
    actual_column_types,
    check_identity_columns,
    check_ordering,
    check_referential_agreement,
    check_residual_inventory,
    check_type_agreement,
    identity_models,
    primary_key_types,
    relation_columns,
)
from games.models import Game, GameStatusChange
from timetracker.uuidv7 import uuid7_at

pytestmark = pytest.mark.django_db

# Pinned rather than re-derived: a test that recomputes the expectation the same
# way the code does cannot fail when the derivation itself is wrong.
EXPECTED_RELATION_COLUMNS = {
    ("games_device", "library_id"),
    ("games_edition", "game_id"),
    ("games_externalreference", "edition_id"),
    ("games_externalreference", "game_id"),
    ("games_externalreference", "platform_id"),
    ("games_externalreference", "release_id"),
    ("games_filterpreset", "library_id"),
    ("games_game", "library_id"),
    ("games_game", "platform_id"),
    ("games_gamestatuschange", "game_id"),
    ("games_libraryevent", "actor_id"),
    ("games_libraryevent", "library_id"),
    ("games_libraryevent", "stream_id"),
    ("games_libraryeventstreamhead", "library_id"),
    ("games_platform", "library_id"),
    ("games_playevent", "game_id"),
    ("games_purchase", "library_id"),
    ("games_purchase", "platform_id"),
    ("games_purchase", "related_game_id"),
    ("games_purchase_games", "game_id"),
    ("games_purchase_games", "purchase_id"),
    ("games_purchaseconversionstate", "library_id"),
    ("games_release", "edition_id"),
    ("games_release", "platform_id"),
    ("games_session", "device_id"),
    ("games_session", "game_id"),
    ("games_userlibrary", "user_id"),
    ("games_userlibrarypreferences", "default_device_id"),
    ("games_userlibrarypreferences", "library_id"),
    ("games_userpreferences", "user_id"),
}

EXPECTED_RESIDUAL_INTEGER_PRIMARY_KEYS = {
    "games_purchase_games": "never converts: an auto-created through table keeps its own key",
    "games_exchangerate": "never converts: not part of the UUID identity cutover",
    "games_sitesetting": "never converts: not part of the UUID identity cutover",
    "games_userpreferences": "never converts: not part of the UUID identity cutover",
}


@pytest.fixture
def actual_types():
    with connection.cursor() as cursor:
        return actual_column_types(cursor)


def test_relation_columns_cover_every_games_relation():
    assert {
        relation.key for relation in relation_columns()
    } == EXPECTED_RELATION_COLUMNS


def test_type_agreement_is_clean_on_a_migrated_database(actual_types):
    report = check_type_agreement(relation_columns(), actual_types)
    assert report.violations == []


def test_type_agreement_reports_a_retyped_column(actual_types):
    doctored = actual_types | {("games_session", "game_id"): "bigint"}

    report = check_type_agreement(relation_columns(), doctored)

    assert [violation.subject for violation in report.violations] == [
        "games_session.game_id"
    ]
    assert "expects uuid_v7" in report.violations[0].detail


def test_type_agreement_reports_a_column_postgresql_does_not_have(actual_types):
    doctored = {
        key: value
        for key, value in actual_types.items()
        if key != ("games_playevent", "game_id")
    }

    report = check_type_agreement(relation_columns(), doctored)

    assert [violation.subject for violation in report.violations] == [
        "games_playevent.game_id"
    ]


def test_type_agreement_reports_a_missing_table_once(actual_types):
    """An unmigrated database must name the absent table, not every column in it."""
    doctored = {
        key: value for key, value in actual_types.items() if key[0] != "games_session"
    }

    report = check_type_agreement(relation_columns(), doctored)

    assert [violation.subject for violation in report.violations] == ["games_session"]
    assert "is this database migrated?" in report.violations[0].detail


def test_residual_inventory_matches_the_pinned_constant(actual_types):
    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )
    assert report.violations == []


def test_residual_integer_primary_key_inventory_drops_only_the_promoted_models():
    assert RESIDUAL_INTEGER_PRIMARY_KEYS == EXPECTED_RESIDUAL_INTEGER_PRIMARY_KEYS


def test_residual_inventory_reports_an_unexpected_integer_relation(actual_types):
    doctored = actual_types | {("games_session", "game_id"): "bigint"}

    report = check_residual_inventory(
        relation_columns(), doctored, primary_key_types(doctored)
    )

    assert [violation.subject for violation in report.violations] == [
        "games_session.game_id"
    ]
    assert "not in the residual inventory" in report.violations[0].detail


def test_residual_inventory_reports_a_converted_column_still_listed(
    actual_types, monkeypatch
):
    """A Wave E slice that converts a column must also shrink the inventory."""
    monkeypatch.setitem(
        RESIDUAL_INTEGER_RELATIONS, ("games_session", "game_id"), "ID-99 (#0)"
    )

    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )

    assert [violation.subject for violation in report.violations] == [
        "games_session.game_id"
    ]
    assert "no longer integer" in report.violations[0].detail


def test_residual_inventory_reports_an_unowned_integer_primary_key(
    actual_types, monkeypatch
):
    monkeypatch.delitem(RESIDUAL_INTEGER_PRIMARY_KEYS, "games_exchangerate")

    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )

    assert [violation.subject for violation in report.violations] == [
        "games_exchangerate"
    ]


def test_purchase_relations_are_absent_from_the_residual_inventory(actual_types):
    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )

    through_notes = [
        note
        for note in report.notes
        if note.subject == "games_purchase_games.purchase_id"
    ]
    assert through_notes == []
    assert "games_purchase" not in RESIDUAL_INTEGER_PRIMARY_KEYS


def test_command_succeeds_on_a_migrated_database():
    call_command("audit_uuid_identity")


def test_command_fails_when_the_inventory_drifts(monkeypatch):
    monkeypatch.delitem(RESIDUAL_INTEGER_RELATIONS, ("games_userlibrary", "user_id"))

    with pytest.raises(CommandError, match="1 identity violation"):
        call_command("audit_uuid_identity")


# --- Identity columns, ordering, referential agreement -----------------------

EXPECTED_IDENTITY_TABLES = {
    "games_device",
    "games_edition",
    "games_externalreference",
    "games_filterpreset",
    "games_game",
    "games_gamestatuschange",
    "games_libraryevent",
    "games_libraryeventstreamhead",
    "games_platform",
    "games_playevent",
    "games_purchase",
    "games_purchaseconversionstate",
    "games_release",
    "games_session",
    "games_userlibrary",
    "games_userlibrarypreferences",
}


@pytest.fixture
def cursor():
    with connection.cursor() as db_cursor:
        yield db_cursor


def test_identity_models_cover_every_uuid_carrier():
    assert {entry.table for entry in identity_models()} == EXPECTED_IDENTITY_TABLES


def test_identity_models_use_the_backfilled_order_source():
    sources = {entry.table: entry.order_source for entry in identity_models()}
    assert sources["games_gamestatuschange"] == "timestamp"
    assert sources["games_game"] == "created_at"
    assert sources["games_edition"] is None
    assert sources["games_release"] is None
    assert sources["games_userlibrarypreferences"] is None


def test_identity_columns_are_clean_on_a_migrated_database(cursor):
    assert check_identity_columns(cursor, identity_models()).violations == []


def test_identity_columns_report_a_dropped_not_null(cursor):
    # FilterPreset has no referrers, so its promoted primary key can be replaced
    # by a unique index before making the identity nullable. This isolates the
    # nullable-column violation from the separate unique-index check.
    cursor.execute(
        "ALTER TABLE games_filterpreset DROP CONSTRAINT games_filterpreset_pkey"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX test_filterpreset_identity_unique "
        "ON games_filterpreset (id)"
    )
    cursor.execute("ALTER TABLE games_filterpreset ALTER COLUMN id DROP NOT NULL")

    report = check_identity_columns(cursor, identity_models())

    assert [violation.detail for violation in report.violations] == [
        "column is nullable"
    ]


def test_identity_columns_report_a_dropped_unique_index(cursor):
    """Uses PlayEvent because nothing references its promoted identity.

    games_game.id cannot be used here: it is the primary key, and four foreign
    keys depend on its index - the same coupling that makes a RemoveField on a
    constrained column silently take indexes with it.
    """
    cursor.execute(
        """
        SELECT constraint_.conname FROM pg_constraint AS constraint_
        JOIN pg_class AS class ON class.oid = constraint_.conrelid
        WHERE class.relname = 'games_playevent' AND constraint_.contype = 'p'
        """
    )
    for (name,) in cursor.fetchall():
        cursor.execute(f'ALTER TABLE games_playevent DROP CONSTRAINT "{name}"')

    report = check_identity_columns(cursor, identity_models())

    assert [violation.detail for violation in report.violations] == [
        "no unique index over the column"
    ]


def test_ordering_is_clean_for_rows_created_through_the_orm(owned_library):
    for index in range(5):
        Game.objects.create(library=owned_library, name=f"Ordered {index}")

    assert check_ordering(identity_models()).violations == []


def test_ordering_reports_a_swapped_pair(owned_library):
    first = Game.objects.create(library=owned_library, name="First")
    second = Game.objects.create(library=owned_library, name="Second")
    # Three steps through a scratch value, because uuid is unique. The scratch
    # must itself be version 7: uuid_v7 is a domain with a CHECK, so a uuid4()
    # here would raise a domain violation instead of the ordering violation.
    scratch = uuid7_at(datetime(2030, 1, 1, tzinfo=UTC))
    original_first, original_second = first.pk, second.pk
    Game.objects.filter(pk=original_first).update(id=scratch)
    Game.objects.filter(pk=original_second).update(id=original_first)
    Game.objects.filter(pk=scratch).update(id=original_second)

    report = check_ordering(identity_models())

    assert [violation.subject for violation in report.violations] == ["games_game"]
    assert "diverges" in report.violations[0].detail


def test_ordering_skips_a_model_without_an_order_source():
    report = check_ordering(identity_models())

    skipped = [
        note for note in report.notes if note.subject == "games_userlibrarypreferences"
    ]
    assert len(skipped) == 1
    assert skipped[0].detail.startswith("skipped:")


def test_ordering_excludes_null_source_rows(owned_library):
    """A NULL-timestamp status change is excluded, not required to sort last.

    Migration 0006 stamped those rows with the migration's own clock, which put
    them last only until the next row was written.
    """
    game = Game.objects.create(library=owned_library, name="Audited")
    GameStatusChange.objects.create(
        game=game, new_status=Game.Status.PLAYED, timestamp=timezone.now()
    )
    GameStatusChange.objects.create(
        game=game, new_status=Game.Status.FINISHED, timestamp=None
    )

    report = check_ordering(identity_models())

    assert report.violations == []
    note = next(
        note for note in report.notes if note.subject == "games_gamestatuschange"
    )
    assert "1 excluded for a NULL timestamp" in note.detail


def test_referential_agreement_is_clean_on_a_migrated_database(cursor):
    assert check_referential_agreement(cursor, relation_columns()).violations == []


def test_referential_agreement_reports_an_orphan_row(cursor):
    """Every foreign key here is deferred, so an orphan survives until commit.

    The row names a Game that never existed. Deleting a real one instead would
    not work: Session.game is CASCADE, so the orphan would go with it.
    """
    cursor.execute(
        """
        INSERT INTO games_session
            (game_id, timestamp_start, emulated, note, created_at, modified_at)
        VALUES (%s, now(), false, '', now(), now())
        """,
        [uuid7_at(datetime(2029, 1, 1, tzinfo=UTC))],
    )

    report = check_referential_agreement(cursor, relation_columns())
    # Removed before asserting: Django's fixture teardown runs SET CONSTRAINTS
    # ALL IMMEDIATE, which would surface the deferred violation as a test error.
    cursor.execute("DELETE FROM games_session")

    assert [violation.subject for violation in report.violations] == [
        "games_session.game_id"
    ]
    assert "reference a missing games_game.id" in report.violations[0].detail


def test_referential_agreement_reports_a_not_valid_constraint(cursor):
    cursor.execute(
        """
        SELECT constraint_.conname FROM pg_constraint AS constraint_
        JOIN pg_class AS class ON class.oid = constraint_.conrelid
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_.conrelid
         AND attribute.attnum = ANY(constraint_.conkey)
        WHERE class.relname = 'games_playevent'
          AND attribute.attname = 'game_id'
          AND constraint_.contype = 'f'
        """
    )
    (name,) = cursor.fetchone()
    cursor.execute(f'ALTER TABLE games_playevent DROP CONSTRAINT "{name}"')
    cursor.execute(
        f'ALTER TABLE games_playevent ADD CONSTRAINT "{name}" '
        "FOREIGN KEY (game_id) REFERENCES games_game(id) NOT VALID"
    )

    report = check_referential_agreement(cursor, relation_columns())

    assert [violation.subject for violation in report.violations] == [
        "games_playevent.game_id"
    ]
    assert "NOT VALID" in report.violations[0].detail


def test_the_committed_sample_fixture_passes_the_audit(django_user_model):
    """The blob ships uuids; a regeneration must not reintroduce load-time ones.

    A record with no `uuid` key is minted one at load time, in file order,
    against a `created_at` the anonymizer jittered - which breaks the ordering
    invariant for exactly the models whose uuids the fixture omits.
    """
    owner = django_user_model.objects.create_user(username="sample-owner")

    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    call_command("audit_uuid_identity")
