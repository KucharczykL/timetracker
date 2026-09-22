"""Every list reads the person's choice, and offers the control that states it."""

import re

import pytest
from django.urls import reverse

from games.list_columns import state_hidden_columns
from games.views.list_columns import LIST_COLUMNS

pytestmark = pytest.mark.django_db

MODES = sorted(LIST_COLUMNS)

#: A key every mode declares and every mode lets a person hide.
HIDEABLE = "created"


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _body(logged_in, mode: str) -> str:
    return logged_in.get(reverse(LIST_COLUMNS[mode].route)).content.decode()


def _headers(body: str) -> list[str]:
    """The header cells, less the picker's panel, which names every column."""
    without_panel = re.sub(
        r'<form method="post" action="[^"]*/columns/.*?</form>',
        "",
        body,
        flags=re.DOTALL,
    )
    heads = re.findall(r"<thead.*?</thead>", without_panel, re.DOTALL)
    return re.findall(r"<th.*?</th>", "".join(heads), re.DOTALL)


def _panel_boxes(body: str) -> dict[str, str]:
    boxes = re.findall(r'<input[^>]*name="shown"[^>]*>', body)
    return {key: box for box in boxes for key in re.findall(r'value="([^"]+)"', box)}


@pytest.mark.parametrize("mode", MODES)
def test_a_person_with_no_row_sees_every_declared_column(logged_in, mode):
    headers = "".join(_headers(_body(logged_in, mode)))

    assert [
        column.label
        for column in LIST_COLUMNS[mode].columns
        if column.label not in headers
    ] == []


@pytest.mark.parametrize("mode", MODES)
def test_a_hidden_column_leaves_the_table(logged_in, owned_user, mode):
    state_hidden_columns(owned_user, mode, [HIDEABLE])
    body = _body(logged_in, mode)

    assert "Created" not in "".join(_headers(body))


@pytest.mark.parametrize("mode", MODES)
def test_the_panel_states_a_box_for_every_column(logged_in, mode):
    boxes = _panel_boxes(_body(logged_in, mode))

    assert set(boxes) == {column.key for column in LIST_COLUMNS[mode].columns}


@pytest.mark.parametrize("mode", MODES)
def test_a_hidden_columns_box_reads_unchecked(logged_in, owned_user, mode):
    state_hidden_columns(owned_user, mode, [HIDEABLE])

    assert "checked" not in _panel_boxes(_body(logged_in, mode))[HIDEABLE]


@pytest.mark.parametrize("mode", MODES)
def test_a_key_that_refuses_to_hide_changes_nothing(logged_in, owned_user, mode):
    """A rename may leave one behind; the list owes the column anyway."""
    pinned = LIST_COLUMNS[mode].columns[0]
    state_hidden_columns(owned_user, mode, [pinned.key])
    body = _body(logged_in, mode)

    assert pinned.label in "".join(_headers(body))
    assert "checked" in _panel_boxes(body)[pinned.key]


@pytest.mark.parametrize("mode", MODES)
def test_the_choice_is_one_persons(logged_in, owned_user, django_user_model, mode):
    other = django_user_model.objects.create_user(
        username=f"other-{mode}", password="p"
    )
    state_hidden_columns(other, mode, [HIDEABLE])

    assert "Created" in "".join(_headers(_body(logged_in, mode)))


@pytest.mark.parametrize("mode", MODES)
def test_the_picker_posts_to_this_mode_and_carries_its_origin(logged_in, mode):
    body = _body(logged_in, mode)
    route = reverse("games:state_list_columns", args=[mode])

    assert f'action="{route}?origin=' in body


def test_a_sort_naming_a_hidden_column_still_orders_the_rows(logged_in, owned_user):
    state_hidden_columns(owned_user, "games", ["created"])

    answer = logged_in.get(reverse("games:list_games"), {"sort": "created"})

    assert answer.status_code == 200
    assert "Unknown sort" not in answer.content.decode()
