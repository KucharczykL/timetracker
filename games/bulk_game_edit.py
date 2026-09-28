"""Status, mastered or the unfinished flag, set on many games."""

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

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
from games.bulk_games import GAME_GONE, game_scope
from games.bulk_sessions import lost
from games.events.append import SourceMetadata
from games.events.dispatch import CommandRejected, RowNotHeld, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.forms import ChoiceSearchSelectWidget, PrimitiveWidgetsMixin
from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary
from games.reads.playergame_facts import FactChange, facts_before
from games.writes.answers import answered
from games.writes.playergame import record_facts, set_excluded_from_unfinished

logger = logging.getLogger("games")


class GameEditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    status: str
    mastered: bool
    excluded_from_unfinished: bool


#: What a statement's JSON may name.
_KEYS = frozenset(GameEditJson.__annotations__)

#: What settling refuses.
NOTHING_STATED = (
    "Choose a status, whether the games are mastered, or whether unfinished "
    "lists leave them out."
)
STATEMENT_UNREADABLE = "What to change could not be read. Choose it again."

#: What an Undo refuses.
NOT_EDITED_BY_THIS_BATCH = (
    "That game was not changed by this batch, so it was left as it is."
)
GAME_REMOVED = "That game is removed. Restore it first."

#: A placeholder: what "leave as it is" keeps.
type Keeping = str  # "Keep: Played"


@dataclass(frozen=True, slots=True)
class GameEditStatement:
    """What one batch states; None leaves alone."""

    status: PlayerGameStatus | None
    mastered: bool | None
    excluded_from_unfinished: bool | None

    def __post_init__(self) -> None:
        if (
            self.status is None
            and self.mastered is None
            and self.excluded_from_unfinished is None
        ):
            raise ValueError("An edit states a status, mastered or the flag.")

    def encode(self) -> ChoiceValue:
        stated: GameEditJson = {}
        if self.status is not None:
            stated["status"] = self.status.value
        if self.mastered is not None:
            stated["mastered"] = self.mastered
        if self.excluded_from_unfinished is not None:
            stated["excluded_from_unfinished"] = self.excluded_from_unfinished
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> GameEditStatement:
        """An earlier settle's answer, or a refusal."""
        try:
            stated = json.loads(raw)
        except ValueError as unreadable:
            raise _unreadable(f"{raw!r} is no JSON: {unreadable}") from unreadable
        if not isinstance(stated, dict):
            raise _unreadable(f"{raw!r} is no object")
        unknown = set(stated) - _KEYS
        if unknown:
            raise _unreadable(f"{raw!r} names {sorted(unknown)}")
        status = stated.get("status")
        if "status" in stated and status not in PlayerGameStatus.values:
            raise _unreadable(f"{raw!r} states a status that is no word")
        flags: dict[str, bool | None] = {}
        for key in ("mastered", "excluded_from_unfinished"):
            flag = stated.get(key)
            #: Present means stated: null is no bool.
            if key in stated and not isinstance(flag, bool):
                raise _unreadable(f"{raw!r} states a {key} that is no bool")
            flags[key] = flag
        if status is None and all(flag is None for flag in flags.values()):
            raise _unreadable(f"{raw!r} states nothing")
        return cls(
            None if status is None else PlayerGameStatus(status),
            flags["mastered"],
            flags["excluded_from_unfinished"],
        )


def _unreadable(message: str) -> CommandRejected:
    return CommandRejected(message, sentence=STATEMENT_UNREADABLE)


def game_edit_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Game]:
    """Keys to tracked games, annotated with their facts."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        Game.objects.tracked_by(library)
        .filter(pk__in=wanted)
        .select_related("platform")
        .order_by("sort_name", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, GAME_GONE)))


# ── The question ─────────────────────────────────────────────────────────────


def _status_shown(status: str) -> str:
    return PlayerGameStatus(status).label


def _mastered_shown(mastered: bool) -> str:
    return "Mastered" if mastered else "Not mastered"


def _excluded_shown(excluded: bool) -> str:
    return "Excluded" if excluded else "Included"


def _keeping[T](
    rows: Sequence[Game], value: Callable[[Game], T], shown: Callable[[T], str]
) -> Keeping:
    """What the rows hold; differing, "mixed"."""
    held = {value(row) for row in rows}
    if len(held) != 1:
        return "Keep: mixed"
    return f"Keep: {shown(held.pop())}"


_MASTERED_CHOICES = (("True", "Mastered"), ("False", "Not mastered"))
_EXCLUDED_CHOICES = (
    ("True", "Excluded from unfinished lists"),
    ("False", "Included in unfinished lists"),
)


def _flag(choices: tuple[tuple[str, str], ...], label: str) -> forms.TypedChoiceField:
    return forms.TypedChoiceField(
        label=label,
        choices=choices,
        coerce=lambda value: value == "True",
        empty_value=None,
        required=False,
        widget=ChoiceSearchSelectWidget(),
    )


class BulkGameEditForm(PrimitiveWidgetsMixin, forms.Form):
    """An empty field keeps."""

    status = forms.TypedChoiceField(
        choices=PlayerGameStatus.choices,
        coerce=PlayerGameStatus,
        empty_value=None,
        required=False,
        widget=ChoiceSearchSelectWidget(),
    )
    mastered = _flag(_MASTERED_CHOICES, "Mastered")
    excluded_from_unfinished = _flag(_EXCLUDED_CHOICES, "Unfinished lists")

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        prefix: FieldName,
        rows: Sequence[Game] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        if rows:
            for name, value, shown in (
                ("status", lambda row: row.tracked_status, _status_shown),
                ("mastered", lambda row: row.tracked_mastered, _mastered_shown),
                (
                    "excluded_from_unfinished",
                    lambda row: row.tracked_excluded_from_unfinished,
                    _excluded_shown,
                ),
            ):
                cast(
                    ChoiceSearchSelectWidget, self.fields[name].widget
                ).placeholder = _keeping(rows, value, shown)

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        if all(
            cleaned.get(name) is None
            for name in ("status", "mastered", "excluded_from_unfinished")
        ):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> GameEditStatement:
        """The valid form, as one statement."""
        return GameEditStatement(
            self.cleaned_data["status"],
            self.cleaned_data["mastered"],
            self.cleaned_data["excluded_from_unfinished"],
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[Game], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    return Control(FormFields(BulkGameEditForm(prefix=field_name, rows=rows)))


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return GameEditStatement.decode(carried).encode()
    form = BulkGameEditForm(post, prefix=CHOICE_FIELD)
    if not form.is_valid():
        sentences = [
            str(message) for messages in form.errors.values() for message in messages
        ]
        raise CommandRejected(
            f"the edit form refuses: {sentences}", sentence=sentences[0]
        )
    return form.statement().encode()


EDIT_CHOICE: BulkChoice[Game] = BulkChoice(offer=offer_edit, settle=settle_edit)


# ── Forward ──────────────────────────────────────────────────────────────────


def _source() -> SourceMetadata:
    return {"bulk": {"action": EDIT.name}}


def _state(
    actor: User,
    game: Game,
    statement: GameEditStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Up to two dispatches; moved when either wrote."""
    outcomes: list[RowOutcome] = []
    if statement.status is not None or statement.mastered is not None:
        outcomes.append(
            RowOutcome.of(
                record_facts(
                    actor,
                    game,
                    status=statement.status,
                    mastered=statement.mastered,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    source_metadata=_source(),
                )
            )
        )
    if statement.excluded_from_unfinished is not None:
        outcomes.append(
            RowOutcome.of(
                set_excluded_from_unfinished(
                    actor,
                    game,
                    statement.excluded_from_unfinished,
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}-excluded",
                    source_metadata=_source(),
                )
            )
        )
    return RowOutcome.MOVED if RowOutcome.MOVED in outcomes else RowOutcome.UNCHANGED


def edit_one(
    actor: User,
    game: Game,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered("game"):
        if choice is None:
            raise RowUnreadable(
                f"{EDIT.name} ran with no statement for Game {game.pk} of "
                f"library {actor.library.pk}. The act declares a choice, so "
                "the runner settles one before a row."
            )
        try:
            statement = GameEditStatement.decode(choice)
        except CommandRejected as drift:
            #: Settled this request, so a defect.
            raise RowUnreadable(
                f"{EDIT.name} settled {choice!r} and cannot read it back: {drift}"
            ) from drift
    return _state(
        actor,
        game,
        statement,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


# ── Backward ─────────────────────────────────────────────────────────────────


def _restated(
    change: FactChange | None, held: object, fact: str, tracked: PlayerGame
) -> Any:
    """The earlier value, where the row differs."""
    if change is None or held == change.before:
        return None
    if held != change.stated:
        logger.info(
            "[bulk]: %s Undo states %s %s over %s on game %s of library %s",
            EDIT.name,
            fact,
            change.before,
            held,
            tracked.game_id,
            tracked.library_id,
        )
    return change.before


def edit_back(
    actor: User,
    player_game_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Each changed fact back to its earlier value."""
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
                "state a fact on."
            )
        before = facts_before(actor.library, player_game_id, undoes)
        if not before.changed_any:
            raise CommandRejected(
                f"batch {undoes} changed no fact of PlayerGame {player_game_id}",
                sentence=NOT_EDITED_BY_THIS_BATCH,
            )
        status = _restated(before.status, tracked.status, "status", tracked)
        mastered = _restated(before.mastered, tracked.mastered, "mastered", tracked)
        excluded = _restated(
            before.excluded_from_unfinished,
            tracked.excluded_from_unfinished,
            "excluded_from_unfinished",
            tracked,
        )
        if status is None and mastered is None and excluded is None:
            return RowOutcome.UNCHANGED
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"PlayerGame {player_game_id} is removed", sentence=GAME_REMOVED
            )
    return _state(
        actor,
        tracked.game,
        GameEditStatement(
            None if status is None else PlayerGameStatus(status), mastered, excluded
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


# ── The confirmation ─────────────────────────────────────────────────────────


EDIT_PREVIEW: tuple[PreviewColumn[Game], ...] = (
    PreviewColumn("Game", lambda row, _: row.name),
    PreviewColumn(
        "Platform",
        lambda row, _: "Unspecified" if row.platform is None else row.platform.name,
    ),
    PreviewColumn("Status", lambda row, _: _status_shown(row.tracked_status)),
    PreviewColumn("Mastered", lambda row, _: "Yes" if row.tracked_mastered else "No"),
    PreviewColumn(
        "Unfinished lists",
        lambda row, _: _excluded_shown(row.tracked_excluded_from_unfinished),
    ),
)

EDIT = BulkAction(
    name="playergame.edit",
    label="Edit…",
    title=ActTitle(one="Edit this game", many="Edit {count} games"),
    confirm_label="Save",
    subject="game",
    color="blue",
    inverse_aggregate="playergame",
    inverse_model=PlayerGame,
    fallback="games:list_games",
    scope=game_scope,
    resolve=game_edit_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=EDIT_PREVIEW,
    choice=EDIT_CHOICE,
)
