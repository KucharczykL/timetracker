"""One status stated on many games, and back."""

import uuid
from collections.abc import Sequence

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict

from common.components.primitives import FormFields
from games.bulk_actions import (
    ActTitle,
    AsksNothing,
    BulkAction,
    BulkChoice,
    ChoiceValue,
    Control,
    FieldName,
    Offered,
    PreviewColumn,
    Resolution,
    RowOutcome,
)
from games.bulk_removal import GAME_GONE, game_scope
from games.bulk_sessions import lost
from games.events.dispatch import CommandRejected, RowNotHeld, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.forms import ChoiceSearchSelectWidget, apply_primitive_widget_classes
from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary
from games.reads.playergame_status import status_before
from games.writes.answers import answered
from games.writes.playergame import record_facts

#: What settling refuses.
CHOOSE_A_STATUS = "Choose a status."

#: What an Undo refuses.
NOT_CHANGED_BY_THIS_BATCH = (
    "That game's status was not changed by this batch, so it was left as it is."
)
GAME_REMOVED = "That game is removed. Restore it first."

#: A placeholder: the word the rows hold.
type Holding = str  # "Now: Played"


def _label(status: str) -> str:
    return PlayerGameStatus(status).label


def status_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Game]:
    """Keys to tracked games, each with its word."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        Game.objects.tracked_by(library)
        .filter(pk__in=wanted)
        .select_related("platform")
        .order_by("sort_name", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, GAME_GONE)))


# ── The question ─────────────────────────────────────────────────────────────


def _holding(rows: Sequence[Game]) -> Holding:
    """What the rows hold; differing, "mixed"."""
    held = {row.tracked_status for row in rows}
    if len(held) != 1:
        return "Now: mixed"
    return f"Now: {_label(held.pop())}"


class StatusForm(forms.Form):
    """One word, under the runner's field name."""

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        field_name: FieldName,
        rows: Sequence[Game] = (),
    ) -> None:
        super().__init__(data)
        self.field_name = field_name
        self.fields[field_name] = forms.ChoiceField(
            label="Status",
            choices=PlayerGameStatus.choices,
            error_messages={
                "required": CHOOSE_A_STATUS,
                "invalid_choice": CHOOSE_A_STATUS,
            },
            widget=ChoiceSearchSelectWidget(
                placeholder=_holding(rows) if rows else None
            ),
        )
        apply_primitive_widget_classes(self.fields)

    def status(self) -> PlayerGameStatus:
        """The valid form's word."""
        return PlayerGameStatus(self.cleaned_data[self.field_name])


def offer_status(
    library: UserLibrary, rows: Sequence[Game], field_name: FieldName
) -> Offered:
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    return Control(FormFields(StatusForm(field_name=field_name, rows=rows)))


def settle_status(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """The posted word, or a refusal."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    form = StatusForm(post, field_name=CHOICE_FIELD)
    if not form.is_valid():
        sentences = [
            str(message) for messages in form.errors.values() for message in messages
        ]
        raise CommandRejected(
            f"the status form refuses: {sentences}", sentence=sentences[0]
        )
    return form.status().value


STATUS_CHOICE: BulkChoice[Game] = BulkChoice(offer=offer_status, settle=settle_status)


# ── Forward ──────────────────────────────────────────────────────────────────


def _source() -> dict[str, object]:
    return {"bulk": {"action": SET_STATUS.name}}


def set_status_one(
    actor: User,
    game: Game,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered("game"):
        if choice not in PlayerGameStatus.values:
            #: Settled this request: ours, not theirs.
            raise RowUnreadable(
                f"{SET_STATUS.name} ran with choice {choice!r} for Game "
                f"{game.pk} of library {actor.library.pk}, which is no status"
            )
    return RowOutcome.of(
        record_facts(
            actor,
            game,
            status=PlayerGameStatus(choice),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


# ── Backward ─────────────────────────────────────────────────────────────────


def set_status_back(
    actor: User,
    player_game_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The earlier word, over any later one."""
    with answered("game"):
        tracked = (
            PlayerGame.objects.select_related("game")
            .filter(library=actor.library, pk=player_game_id)
            .first()
        )
        if tracked is None:
            raise RowNotHeld(
                f"PlayerGame {player_game_id} is not library "
                f"{actor.library.pk}'s, so the batch's inverse has no row to "
                "state a status on."
            )
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"PlayerGame {player_game_id} is removed",
                sentence=GAME_REMOVED,
            )
        before = status_before(actor.library, player_game_id, undoes)
        if before is None:
            raise CommandRejected(
                f"batch {undoes} changed no status of PlayerGame {player_game_id}",
                sentence=NOT_CHANGED_BY_THIS_BATCH,
            )
    return RowOutcome.of(
        record_facts(
            actor,
            tracked.game,
            status=before,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


# ── The confirmation ─────────────────────────────────────────────────────────


STATUS_PREVIEW: tuple[PreviewColumn[Game], ...] = (
    PreviewColumn("Game", lambda row, _: row.name),
    PreviewColumn(
        "Platform",
        lambda row, _: "Unspecified" if row.platform is None else row.platform.name,
    ),
    PreviewColumn("Status", lambda row, _: _label(row.tracked_status)),
)

SET_STATUS = BulkAction(
    name="playergame.set_status",
    label="Set status…",
    title=ActTitle(
        one="Set this game's status", many="Set the status of {count} games"
    ),
    confirm_label="Save",
    subject="game",
    color="blue",
    inverse_aggregate="playergame",
    inverse_model=PlayerGame,
    fallback="games:list_games",
    scope=game_scope,
    resolve=status_resolution,
    run=set_status_one,
    inverse=set_status_back,
    preview=STATUS_PREVIEW,
    choice=STATUS_CHOICE,
)
