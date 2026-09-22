"""The one route a person states a list's columns through."""

from typing import NamedTuple, cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.components import Column
from common.returns import UrlName
from games.list_columns import reset_columns, state_shown_columns
from games.views.device import DEVICE_COLUMNS
from games.views.game import game_list_columns
from games.views.historical_playtime import historical_playtime_columns
from games.views.platform import PLATFORM_COLUMNS
from games.views.playthrough_rows import playthrough_columns
from games.views.purchase import PURCHASE_COLUMNS
from games.views.returns import return_url
from games.views.session import SESSION_COLUMNS

#: What the panel posts the columns it leaves shown as.
SHOWN_FIELD = "shown"
#: The submit button a reset presses, which no other submit posts.
RESET_FIELD = "reset"


class DeclaredList(NamedTuple):
    """Where a mode's list lives, and the columns it declares."""

    route: UrlName
    columns: list[Column]


#: The label is the request's; this route reads keys alone.
LIST_COLUMNS: dict[str, DeclaredList] = {
    "games": DeclaredList("games:list_games", game_list_columns("Playtime")),
    "sessions": DeclaredList("games:list_sessions", SESSION_COLUMNS),
    "purchases": DeclaredList("games:list_purchases", PURCHASE_COLUMNS),
    "playthroughs": DeclaredList(
        "games:list_playthroughs", playthrough_columns(sortable=True)
    ),
    "historical_playtime": DeclaredList(
        "games:list_historical_playtime",
        historical_playtime_columns(sortable=True),
    ),
    "devices": DeclaredList("games:list_devices", DEVICE_COLUMNS),
    "platforms": DeclaredList("games:list_platforms", PLATFORM_COLUMNS),
}


@login_required
@require_POST
def state_list_columns(request: HttpRequest, mode: str) -> HttpResponse:
    """Store what the panel left shown.

    An unchecked box posts nothing, so the posted keys are the whole of what a
    person shows, read against the live column list. A column that refuses to
    hide posts nothing either, and is shown whatever the request carries.
    """
    if mode not in LIST_COLUMNS:
        raise Http404(f"no list states the mode {mode!r}")
    declared = LIST_COLUMNS[mode]
    person = cast(User, request.user)

    if request.POST.get(RESET_FIELD):
        reset_columns(person, mode)
    else:
        posted = set(request.POST.getlist(SHOWN_FIELD))
        shown = {
            column.key
            for column in declared.columns
            if column.key in posted or not column.hideable
        }
        state_shown_columns(person, mode, shown, declared.columns)
    return redirect(return_url(request, fallback=declared.route))
