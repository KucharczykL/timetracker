"""A request loads user and library together."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from timetracker.auth_backends import LibraryModelBackend


def _library_statements(captured: CaptureQueriesContext) -> list[str]:
    return [
        query["sql"]
        for query in captured.captured_queries
        if 'FROM "games_userlibrary"' in query["sql"]
    ]


@pytest.mark.django_db
def test_a_request_loads_its_user_and_library_together(client, django_user_model):
    """The library rides along with the user."""
    owner = django_user_model.objects.create_user(username="budget", password="p")
    client.force_login(owner)

    with CaptureQueriesContext(connection) as captured:
        response = client.get("/tracker/library")

    assert response.status_code == 200
    assert _library_statements(captured) == []


@pytest.mark.django_db
def test_the_backend_answers_none_for_an_unknown_id(django_user_model):
    """An id no user holds is nobody."""
    taken = django_user_model.objects.create_user(username="taken", password="p")

    assert LibraryModelBackend().get_user(taken.pk + 1000) is None


@pytest.mark.django_db
def test_a_user_with_no_library_still_loads(django_user_model):
    """A user missing its row still loads."""
    owner = django_user_model.objects.create_user(username="libraryless", password="p")
    owner.library.delete()

    loaded = LibraryModelBackend().get_user(owner.pk)

    assert loaded is not None
    assert loaded.pk == owner.pk
