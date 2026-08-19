import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from games.identity_audit import (
    RESIDUAL_INTEGER_PRIMARY_KEYS,
    RESIDUAL_INTEGER_RELATIONS,
    actual_column_types,
    check_residual_inventory,
    check_type_agreement,
    primary_key_types,
    relation_columns,
)

pytestmark = pytest.mark.django_db

# Pinned rather than re-derived: a test that recomputes the expectation the same
# way the code does cannot fail when the derivation itself is wrong.
EXPECTED_RELATION_COLUMNS = {
    ("games_device", "library_id"),
    ("games_filterpreset", "library_id"),
    ("games_game", "library_id"),
    ("games_game", "platform_id"),
    ("games_gamestatuschange", "game_id"),
    ("games_platform", "library_id"),
    ("games_playevent", "game_id"),
    ("games_purchase", "library_id"),
    ("games_purchase", "platform_id"),
    ("games_purchase", "related_game_id"),
    ("games_purchase_games", "game_id"),
    ("games_purchase_games", "purchase_id"),
    ("games_purchaseconversionstate", "library_id"),
    ("games_session", "device_id"),
    ("games_session", "game_id"),
    ("games_userlibrary", "user_id"),
    ("games_userlibrarypreferences", "default_device_id"),
    ("games_userlibrarypreferences", "library_id"),
    ("games_userpreferences", "user_id"),
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
    monkeypatch.delitem(RESIDUAL_INTEGER_PRIMARY_KEYS, "games_game")

    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )

    assert [violation.subject for violation in report.violations] == ["games_game"]


def test_residual_inventory_notes_name_the_owning_slice(actual_types):
    report = check_residual_inventory(
        relation_columns(), actual_types, primary_key_types(actual_types)
    )

    through_notes = [
        note for note in report.notes if note.subject == "games_purchase_games.game_id"
    ]
    assert len(through_notes) == 1
    assert "ID-11 (#646)" in through_notes[0].detail


def test_command_succeeds_on_a_migrated_database():
    call_command("audit_uuid_identity")


def test_command_fails_when_the_inventory_drifts(monkeypatch):
    monkeypatch.delitem(RESIDUAL_INTEGER_RELATIONS, ("games_userlibrary", "user_id"))

    with pytest.raises(CommandError, match="1 identity violation"):
        call_command("audit_uuid_identity")
