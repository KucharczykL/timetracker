"""What one session row offers, behind its trigger.

Not in `common/components/`: reading `games.bulk_actions` there
closes a cycle through that table's foot imports.
"""

from common.components import (
    BrowserTimeZoneInput,
    DropdownLinkItem,
    DropdownPostItem,
    RowActionMenu,
)
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_move import MOVE
from games.bulk_reclassification import RECLASSIFY
from games.bulk_removal import REMOVE_SESSION
from games.bulk_tray import one_row_statement
from games.models import PlayerSession, PlayerSessionTimingMode

#: Three dots: the act asks first, not opens a page.
#: See docs/visual-conventions.md, "Row acts".
_ASKS_FIRST = "\u2026"


def session_row_menu(
    session: PlayerSession, csrf_token: str, origin: OriginUrl | None
) -> Node:
    """Every act this session admits, gated as before."""
    #: Only a Timed row runs; Corrected states its end.
    running = (
        session.timing_mode == PlayerSessionTimingMode.TIMED
        and session.ended_at is None
    )
    items: list[Node] = []
    if running:
        items += [
            DropdownPostItem(
                action_url("games:finish_session", session.pk, origin=origin),
                "Finish",
                csrf_token=csrf_token,
                hidden_fields=BrowserTimeZoneInput(),
                icon="end",
            ),
            DropdownLinkItem(
                action_url("games:reset_session", session.pk, origin=origin),
                "Reset start to now",
                icon="reset",
            ),
        ]
    items += [
        DropdownLinkItem(
            action_url("games:edit_session", session.pk, origin=origin),
            "Edit",
            icon="edit",
        ),
        DropdownPostItem(
            action_url("games:run_bulk_action", MOVE.name, origin=origin),
            MOVE.label,
            csrf_token=csrf_token,
            hidden_fields=one_row_statement(session.pk),
            icon="move",
        ),
    ]
    if session.timing_mode == PlayerSessionTimingMode.DURATION_ONLY:
        items.append(
            DropdownLinkItem(
                action_url("games:reclassify_session", session.pk, origin=origin),
                f"{RECLASSIFY.label}{_ASKS_FIRST}",
                icon="history",
            )
        )
    items.append(
        DropdownLinkItem(
            action_url("games:remove_session", session.pk, origin=origin),
            REMOVE_SESSION.label,
            icon="delete",
            danger=True,
        )
    )
    return RowActionMenu(
        items,
        #: The day as well as the game: the organized list states one game
        #: for every row, so the game alone names each trigger the same.
        label=(
            f"{session.playthrough.player_game.game.name}, "
            f"{session.effective_day} actions"
        ),
        id=f"session-menu-{session.pk}",
    )
