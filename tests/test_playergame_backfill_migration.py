"""Migration 0033 turns a held catalog into a tracked one, once."""

import json

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

#: The migration is reached through MigrationExecutor, never imported: a
#: module whose name starts with a digit is not an importable identifier.
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]

BEFORE_BASELINE = ("games", "0032_playergame_archived_at")
WITH_BASELINE = ("games", "0033_playergame_baseline_backfill")


@pytest.fixture
def baseline_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_BASELINE])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_BASELINE]).apps
    yield old_apps
    #: Emptied before the graph is replayed: a test that deliberately leaves an
    #: unmapped letter behind would fail this backfill a second time, in
    #: teardown, where the failure belongs to no test.
    call_command("flush", interactive=False, verbosity=0)
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_baseline():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_BASELINE])
    return executor.loader.project_state([WITH_BASELINE]).apps


def reconciliation_payload(captured):
    for line in captured.out.splitlines():
        if line.startswith("PLAYERGAME_BASELINE_RECONCILIATION_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise AssertionError(f"No machine reconciliation line in:\n{captured.out}")


def seed(old_apps, *, status="u", mastered=False):
    """A user, its library, and one game, in the pre-migration state."""
    User = old_apps.get_model("auth", "User")
    UserLibrary = old_apps.get_model("games", "UserLibrary")
    Game = old_apps.get_model("games", "Game")
    user = User.objects.create(username="owner")
    library = UserLibrary.objects.create(user=user)
    game = Game.objects.create(
        library=library, name="Outer Wilds", status=status, mastered=mastered
    )
    return library, game


def test_the_migration_tracks_every_game_and_reports_it(
    baseline_migration_harness, capsys
):
    library, game = seed(baseline_migration_harness, status="f")

    new_apps = migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["mismatches"] == []
    assert payload["summary"]["tracked"] == 1
    assert payload["summary"]["created_events"] == 1
    assert payload["summary"]["corrective_events"] == 1
    assert payload["summary"]["unknown_effective_times"] == 1
    PlayerGame = new_apps.get_model("games", "PlayerGame")
    row = PlayerGame.objects.get()
    assert (row.game_id, row.library_id, row.status) == (
        game.pk,
        library.pk,
        "completed",
    )


def test_the_second_pass_appends_nothing(baseline_migration_harness, capsys):
    seed(baseline_migration_harness, status="p")

    new_apps = migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["summary"]["mismatches"] == 0
    LibraryEvent = new_apps.get_model("games", "LibraryEvent")
    #: Creation plus one corrective status, and nothing from the second pass.
    assert LibraryEvent.objects.count() == 2


def test_an_unmapped_letter_fails_the_migration(baseline_migration_harness, capsys):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(status="z")

    with pytest.raises(RuntimeError, match="baseline backfill failed"):
        migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert [entry["code"] for entry in payload["mismatches"]] == [
        "unmapped_legacy_status"
    ]


def test_a_failed_migration_leaves_no_event_behind(baseline_migration_harness):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(status="z")

    with pytest.raises(RuntimeError):
        migrate_to_baseline()

    #: The migration's transaction rolled back, records and all.
    LibraryEvent = old_apps.get_model("games", "LibraryEvent")
    assert LibraryEvent.objects.count() == 0


def test_a_tombstoned_game_is_reported_as_skipped(baseline_migration_harness, capsys):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["summary"]["skipped_tombstoned"] == 1
    assert payload["summary"]["tracked"] == 0
