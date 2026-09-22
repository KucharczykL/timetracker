"""Show a list's every column, for a test whose subject is not the default."""

from django.contrib.auth.models import User

from games.list_columns import state_shown_columns
from games.views.list_columns import LIST_COLUMNS


def show_every_column(user: User, *modes: str) -> None:
    """State that this person shows every column these lists declare."""
    for mode in modes or tuple(LIST_COLUMNS):
        columns = LIST_COLUMNS[mode].columns
        state_shown_columns(user, mode, [column.key for column in columns], columns)
