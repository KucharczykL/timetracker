import pytest

from common.components import Column
from games.list_columns import (
    hidden_columns,
    reset_columns,
    state_shown_columns,
)
from games.models import ListColumnChoice

pytestmark = pytest.mark.django_db

COLUMNS = [
    Column("Name", key="name", hideable=False),
    Column("Device", key="device"),
    Column("Note", key="note"),
    Column("Created", key="created", hidden_by_default=True),
]

EVERY_KEY = [column.key for column in COLUMNS]


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="other-reader", password="p")


def test_a_person_with_no_row_reads_the_declared_defaults(owned_user):
    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset({"created"})


def test_a_stated_choice_reads_back(owned_user):
    state_shown_columns(owned_user, "sessions", ["name", "note"], COLUMNS)

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset(
        {"device", "created"}
    )


def test_a_column_shown_against_its_default_is_written_down(owned_user):
    state_shown_columns(owned_user, "sessions", EVERY_KEY, COLUMNS)

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset()
    assert ListColumnChoice.objects.get().shown == {"created": True}


def test_a_choice_that_states_the_defaults_back_keeps_no_row(owned_user):
    """The row would say what the declaration already says."""
    state_shown_columns(owned_user, "sessions", ["name", "device", "note"], COLUMNS)

    assert ListColumnChoice.objects.count() == 0
    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset({"created"})


def test_only_a_column_away_from_its_default_is_written_down(owned_user):
    state_shown_columns(owned_user, "sessions", ["name", "device"], COLUMNS)

    assert ListColumnChoice.objects.get().shown == {"note": False}


def test_a_second_statement_replaces_the_first(owned_user):
    state_shown_columns(owned_user, "sessions", ["name"], COLUMNS)
    state_shown_columns(owned_user, "sessions", ["name", "device"], COLUMNS)

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset(
        {"note", "created"}
    )
    assert ListColumnChoice.objects.count() == 1


def test_a_column_the_row_says_nothing_about_reads_its_own_default(owned_user):
    """A column added after the choice was stated starts where it says."""
    state_shown_columns(owned_user, "sessions", ["name", "device"], COLUMNS)
    later = [*COLUMNS, Column("Platform", key="platform", hidden_by_default=True)]

    assert hidden_columns(owned_user, "sessions", later) == frozenset(
        {"note", "created", "platform"}
    )


def test_a_reset_takes_the_row_away(owned_user):
    state_shown_columns(owned_user, "sessions", EVERY_KEY, COLUMNS)
    reset_columns(owned_user, "sessions")

    assert ListColumnChoice.objects.count() == 0
    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset({"created"})


def test_a_mode_the_project_does_not_state_is_refused(owned_user):
    with pytest.raises(ValueError):
        state_shown_columns(owned_user, "sittings", ["name"], COLUMNS)

    with pytest.raises(ValueError):
        hidden_columns(owned_user, "sittings", COLUMNS)

    with pytest.raises(ValueError):
        reset_columns(owned_user, "sittings")


def test_one_mode_does_not_read_another(owned_user):
    state_shown_columns(owned_user, "sessions", ["name"], COLUMNS)

    assert hidden_columns(owned_user, "games", COLUMNS) == frozenset({"created"})


def test_two_people_state_their_own(owned_user, other_user):
    state_shown_columns(owned_user, "sessions", ["name"], COLUMNS)
    state_shown_columns(other_user, "sessions", EVERY_KEY, COLUMNS)

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset(
        {"device", "note", "created"}
    )
    assert hidden_columns(other_user, "sessions", COLUMNS) == frozenset()


@pytest.mark.parametrize(
    "foreign", [["name"], "name", 3, {"device": "false"}, {"device": 1}]
)
def test_a_foreign_row_reads_the_declared_defaults(
    owned_user, foreign, capture_games_logger
):
    """The control that repairs the row is on the page that would not render."""
    ListColumnChoice.objects.create(user=owned_user, mode="sessions", shown=foreign)

    with capture_games_logger() as caplog:
        hidden = hidden_columns(owned_user, "sessions", COLUMNS)

    assert hidden == frozenset({"created"})
    assert "states no map" in caplog.text


def test_a_true_value_shows_a_column_that_starts_hidden(owned_user):
    ListColumnChoice.objects.create(
        user=owned_user, mode="sessions", shown={"created": True}
    )

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset()


def test_a_key_no_column_claims_hides_nothing(owned_user):
    """JSON keys are text, so a number reads back as a key nothing claims."""
    ListColumnChoice.objects.create(
        user=owned_user, mode="sessions", shown={"3": True, "gone": False}
    )

    assert hidden_columns(owned_user, "sessions", COLUMNS) == frozenset({"created"})
