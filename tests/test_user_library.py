from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from games.models import UserLibrary


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
def test_new_user_eagerly_gets_exactly_one_library():
    user = User.objects.create_user("new-user")
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_saving_existing_user_does_not_replace_library():
    user = User.objects.create_user("existing")
    library_id = UserLibrary.objects.get(user=user).pk

    user.email = "new@example.com"
    user.save(update_fields=["email"])

    assert UserLibrary.objects.get(user=user).pk == library_id
    assert UserLibrary.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_bulk_created_user_has_no_implicit_library():
    user = User.objects.bulk_create([User(username="bulk")])[0]
    assert not UserLibrary.objects.filter(user=user).exists()
