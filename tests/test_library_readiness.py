import builtins
import importlib
import os
import sys

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured

from games.models import UserLibrary, UserLibraryPreferences, UserPreferences


def create_user_without_signals(username: str) -> User:
    return User.objects.bulk_create([User(username=username)])[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("missing", "expected_relation"),
    [
        ("library", "UserLibrary"),
        ("user_preferences", "UserPreferences"),
        ("library_preferences", "UserLibraryPreferences"),
    ],
)
def test_readiness_rejects_each_missing_companion_record(
    missing, expected_relation, capture_games_logger
):
    from games.readiness import assert_library_structure

    user = create_user_without_signals(f"missing-{missing}")
    library = None
    if missing != "library":
        library = UserLibrary.objects.create(user=user)
    if missing == "library_preferences":
        UserPreferences.objects.create(user=user)
    if missing == "user_preferences":
        UserLibraryPreferences.objects.create(library=library)

    with (
        capture_games_logger() as caplog,
        pytest.raises(ImproperlyConfigured, match=expected_relation) as error,
    ):
        assert_library_structure()

    affected_id = library.pk if missing == "library_preferences" else user.pk
    assert str(affected_id) in str(error.value)
    records = [record for record in caplog.records if record.name == "games"]
    assert len(records) == 1


def test_qcluster_command_module_import_does_not_run_readiness(monkeypatch):
    import games.readiness

    def fail_if_called():
        raise AssertionError("readiness must not run while loading the command")

    monkeypatch.setattr(games.readiness, "assert_library_structure", fail_if_called)
    module = importlib.import_module("games.management.commands.qcluster")

    assert module.Command


@pytest.mark.django_db
@pytest.mark.parametrize("entrypoint", ["timetracker.asgi", "timetracker.wsgi"])
def test_entrypoint_sets_django_settings_before_importing_readiness(
    monkeypatch, entrypoint
):
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    sys.modules.pop(entrypoint, None)
    original_import = builtins.__import__

    def import_with_settings_check(name, *args, **kwargs):
        if name == "games.readiness":
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "timetracker.settings"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_settings_check)

    importlib.import_module(entrypoint)
