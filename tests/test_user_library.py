from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from games.models import UserLibrary, UserLibraryPreferences, UserPreferences

BEFORE_LIBRARY = ("games", "0002_uuid_v7_domain")
WITH_LIBRARY = ("games", "0003_userlibrary")


def create_user_without_signals(username: str) -> User:
    return User.objects.bulk_create([User(username=username)])[0]


@pytest.mark.django_db
def test_user_library_uses_uuid7_and_preserves_explicit_created_at():
    owner = create_user_without_signals("owner")
    library = UserLibrary.objects.create(user=owner)
    assert isinstance(library.pk, UUID)
    assert library.pk.version == 7

    restored_at = datetime(
        2022,
        12,
        31,
        14,
        18,
        27,
        tzinfo=ZoneInfo("Europe/Prague"),
    )
    restored_owner = create_user_without_signals("restored")
    restored = UserLibrary.objects.create(
        user=restored_owner,
        created_at=restored_at,
    )
    restored.refresh_from_db()
    assert restored.created_at == restored_at


@pytest.mark.django_db
def test_user_library_is_one_to_one_and_cascades_with_user():
    user = create_user_without_signals("one-to-one")
    library_id = UserLibrary.objects.create(user=user).pk

    with pytest.raises(IntegrityError), transaction.atomic():
        UserLibrary.objects.create(user=user)

    user.delete()
    assert not UserLibrary.objects.filter(pk=library_id).exists()


@pytest.mark.django_db
def test_new_user_eagerly_gets_complete_library_structure():
    user = User.objects.create_user("new-user")
    library = UserLibrary.objects.get(user=user)
    assert UserPreferences.objects.filter(user=user).count() == 1
    assert UserLibraryPreferences.objects.filter(library=library).count() == 1


@pytest.mark.django_db
def test_saving_existing_user_does_not_replace_provisioned_records():
    user = User.objects.create_user("existing")
    library = UserLibrary.objects.get(user=user)
    library_id = library.pk
    preferences_id = UserPreferences.objects.get(user=user).pk
    library_preferences_id = UserLibraryPreferences.objects.get(library=library).pk

    user.email = "new@example.com"
    user.save(update_fields=["email"])

    assert UserLibrary.objects.get(user=user).pk == library_id
    assert UserLibrary.objects.filter(user=user).count() == 1
    assert UserPreferences.objects.get(user=user).pk == preferences_id
    assert UserPreferences.objects.filter(user=user).count() == 1
    assert (
        UserLibraryPreferences.objects.get(library_id=library_id).pk
        == library_preferences_id
    )
    assert UserLibraryPreferences.objects.filter(library_id=library_id).count() == 1


@pytest.mark.django_db
def test_bulk_created_user_has_no_implicit_library():
    user = User.objects.bulk_create([User(username="bulk")])[0]
    assert not UserLibrary.objects.filter(user=user).exists()


@pytest.mark.django_db(transaction=True)
def test_user_library_migration_does_not_backfill_existing_users():
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE_LIBRARY])
        old_apps = executor.loader.project_state([BEFORE_LIBRARY]).apps
        LegacyUser = old_apps.get_model("auth", "User")
        legacy_user = LegacyUser.objects.create(username="legacy")
        legacy_user_id = legacy_user.pk

        executor = MigrationExecutor(connection)
        executor.migrate([WITH_LIBRARY])
        new_apps = executor.loader.project_state([WITH_LIBRARY]).apps
        HistoricalUserLibrary = new_apps.get_model("games", "UserLibrary")
        assert not HistoricalUserLibrary.objects.filter(user_id=legacy_user_id).exists()
    finally:
        MigrationExecutor(connection).migrate([WITH_LIBRARY])
