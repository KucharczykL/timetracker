"""What one session row offers, behind its own ellipsis trigger.

Here rather than in `common/components/`: the items read the acts' own words
out of `games.bulk_actions`, and a module under `common.components` importing
that table closes a cycle through its foot imports.
"""

import json

from common.components import (
    SELECTION_STATEMENT_FIELD,
    BrowserTimeZoneInput,
    DropdownLinkItem,
    DropdownPostItem,
    Input,
    RowActionMenu,
)
from common.components.core import Node
from common.returns import OriginUrl, action_url
from games.bulk_move import MOVE
from games.bulk_reclassification import RECLASSIFY
from games.bulk_removal import REMOVE_SESSION
from games.models import PlayerSession, PlayerSessionTimingMode


def _one_row(session: PlayerSession) -> Node:
    """The runner's own statement, naming this row alone.

    The act has no per-session route and grows none: the item hands one row to
    the act the tray offers, so the words and the rules are the same in both
    places.
    """
    return Input(
        type="hidden",
        name=SELECTION_STATEMENT_FIELD,
        value=json.dumps({"mode": "some", "keys": [str(session.pk)]}),
    )


def session_row_menu(
    session: PlayerSession, csrf_token: str, origin: OriginUrl | None
) -> Node:
    """Every act this session admits, gated as the buttons were gated.

    A gated act is absent, never disabled: a disabled item promises an act the
    row cannot accept.
    """
    #: Only a Timed row runs; Corrected states its end already.
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
            ),
            DropdownLinkItem(
                action_url("games:reset_session", session.pk, origin=origin),
                "Reset start to now",
            ),
        ]
    items += [
        DropdownLinkItem(
            action_url("games:edit_session", session.pk, origin=origin), "Edit"
        ),
        DropdownPostItem(
            action_url("games:run_bulk_action", MOVE.name, origin=origin),
            MOVE.label,
            csrf_token=csrf_token,
            hidden_fields=_one_row(session),
        ),
    ]
    if session.timing_mode == PlayerSessionTimingMode.DURATION_ONLY:
        items.append(
            DropdownLinkItem(
                action_url("games:reclassify_session", session.pk, origin=origin),
                RECLASSIFY.label,
            )
        )
    items.append(
        DropdownLinkItem(
            action_url("games:remove_session", session.pk, origin=origin),
            REMOVE_SESSION.label,
        )
    )
    return RowActionMenu(
        items,
        label=f"{session.playthrough.player_game.game.name} actions",
        id=f"session-menu-{session.pk}",
    )
