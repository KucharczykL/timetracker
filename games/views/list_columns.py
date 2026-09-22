"""The one route a person states a list's columns through."""

from typing import NamedTuple, cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.components import Column
from common.returns import UrlName
from games.list_columns import state_hidden_columns
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
    """Store what the panel left shown, as the keys it left out.

    An unchecked box posts nothing, so the hidden set is the declared keys less
    the posted ones, read from the live column list. A column that refuses to
    hide posts nothing either, which is why it is taken out of the difference
    rather than read out of the request.
    """
    if mode not in LIST_COLUMNS:
        raise Http404(f"no list states the mode {mode!r}")
    declared = LIST_COLUMNS[mode]
    person = cast(User, request.user)

    if request.POST.get(RESET_FIELD):
        state_hidden_columns(person, mode, ())
    else:
        shown = set(request.POST.getlist(SHOWN_FIELD))
        state_hidden_columns(
            person,
            mode,
            [
                column.key
                for column in declared.columns
                if column.hideable and column.key not in shown
            ],
        )
    return redirect(return_url(request, fallback=declared.route))
