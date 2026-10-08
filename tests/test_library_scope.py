from uuid import uuid7

import pytest
from django.core.management.base import CommandError

from games.management.library_scope import (
    library_by_id,
    library_of_user,
    scoped_libraries,
    user_named,
)
from games.models import UserLibrary


def scope(*, user=None, library_id=None, all_libraries=False):
    return {"user": user, "library_id": library_id, "all_libraries": all_libraries}


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="scope-owner")


@pytest.mark.django_db
def test_all_libraries_reads_every_library_in_key_order(owner, django_user_model):
    second = django_user_model.objects.create_user(username="scope-second")

    found = scoped_libraries(scope(all_libraries=True))

    assert found == sorted([owner.library, second.library], key=lambda row: row.pk)


@pytest.mark.django_db
def test_all_libraries_finding_none_is_refused():
    UserLibrary.objects.all().delete()

    with pytest.raises(CommandError, match="found no library"):
        scoped_libraries(scope(all_libraries=True))


@pytest.mark.django_db
def test_an_empty_username_is_a_username(owner):
    with pytest.raises(CommandError, match="No user is named ''"):
        scoped_libraries(scope(user=""))


@pytest.mark.django_db
def test_no_scope_member_is_refused():
    """call_command can pass the group unset."""
    with pytest.raises(CommandError, match="Name --user, --library"):
        scoped_libraries(scope())


@pytest.mark.django_db
def test_a_user_names_their_library(owner):
    assert scoped_libraries(scope(user=owner.username)) == [owner.library]


@pytest.mark.django_db
def test_an_unknown_user_is_named():
    with pytest.raises(CommandError, match="No user is named 'nobody'"):
        user_named("nobody")


@pytest.mark.django_db
def test_a_user_owning_no_library_is_its_own_sentence(owner):
    owner.library.delete()

    with pytest.raises(CommandError, match="'scope-owner' owns no library"):
        library_of_user(owner.username)


@pytest.mark.django_db
def test_a_library_id_resolves_as_text_or_uuid(owner):
    assert library_by_id(str(owner.library.pk)) == owner.library
    assert library_by_id(owner.library.pk) == owner.library


@pytest.mark.django_db
@pytest.mark.parametrize("raw_id", ["nope", "6f1c2e2a-5b8d-4c1e-9a3f-2d7b8e9c0a11"])
def test_a_malformed_library_id_is_named(raw_id):
    """A version-4 UUID is no library key."""
    with pytest.raises(CommandError, match="is not a library id"):
        library_by_id(raw_id)


@pytest.mark.django_db
def test_an_unheld_library_id_is_named():
    unheld = uuid7()

    with pytest.raises(CommandError, match=f"No library {unheld}"):
        library_by_id(str(unheld))
