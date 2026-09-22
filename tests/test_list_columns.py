import pytest

from games.list_columns import hidden_columns, state_hidden_columns
from games.models import ListColumnChoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="other-reader", password="p")


def test_a_person_with_no_row_hides_nothing(owned_user):
    assert hidden_columns(owned_user, "sessions") == frozenset()


def test_a_stated_choice_reads_back(owned_user):
    state_hidden_columns(owned_user, "sessions", ["device", "note"])

    assert hidden_columns(owned_user, "sessions") == frozenset({"device", "note"})


def test_a_second_statement_replaces_the_first(owned_user):
    state_hidden_columns(owned_user, "sessions", ["device", "note"])
    state_hidden_columns(owned_user, "sessions", ["duration"])

    assert hidden_columns(owned_user, "sessions") == frozenset({"duration"})
    assert ListColumnChoice.objects.count() == 1


def test_an_empty_statement_takes_the_row_away(owned_user):
    state_hidden_columns(owned_user, "sessions", ["device"])
    state_hidden_columns(owned_user, "sessions", [])

    assert ListColumnChoice.objects.count() == 0
    assert hidden_columns(owned_user, "sessions") == frozenset()


def test_an_empty_statement_on_no_row_is_no_act(owned_user):
    state_hidden_columns(owned_user, "sessions", [])

    assert ListColumnChoice.objects.count() == 0


def test_a_mode_the_project_does_not_state_is_refused(owned_user):
    with pytest.raises(ValueError):
        state_hidden_columns(owned_user, "sittings", ["device"])

    with pytest.raises(ValueError):
        hidden_columns(owned_user, "sittings")


def test_one_mode_does_not_read_another(owned_user):
    state_hidden_columns(owned_user, "sessions", ["device"])

    assert hidden_columns(owned_user, "games") == frozenset()


def test_two_people_state_their_own(owned_user, other_user):
    state_hidden_columns(owned_user, "sessions", ["device"])
    state_hidden_columns(other_user, "sessions", ["note"])

    assert hidden_columns(owned_user, "sessions") == frozenset({"device"})
    assert hidden_columns(other_user, "sessions") == frozenset({"note"})
