"""Game facts, set on many games."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict

from common.components.primitives import FormFieldGroup, FormFields
from games.bulk_actions import BulkAction
from games.bulk_edit import (
    flag_field,
    form_refusal,
    held_flag,
    keeping,
    log_overwrite,
    restated,
    settled,
    stated_object,
    statement_unreadable,
)
from games.bulk_games import GAME_GONE, game_scope
from games.bulk_parts import (
    ActTitle,
    AsksNothing,
    BulkChoice,
    ChoiceValue,
    Control,
    EventRows,
    FieldName,
    Offered,
    PreviewColumn,
    Resolution,
    RowOutcome,
)
from games.bulk_sessions import lost
from games.events.append import SourceMetadata
from games.events.dispatch import CommandRejected, RowNotHeld
from games.events.idempotency import IdempotencyKey
from games.forms import (
    ChoiceSearchSelectWidget,
    PrimitiveWidgetsMixin,
    TriStateCheckboxWidget,
)
from games.models import (
    VISIBILITY_FIELDS,
    Game,
    PlayerGame,
    PlayerGameStatus,
    UserLibrary,
)
from games.reads.playergame_facts import batch_fact_changes
from games.writes.answers import answered
from games.writes.playergame import record_facts


class GameEditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    status: str
    mastered: bool
    excluded_from_unfinished: bool
    excluded_from_dropped: bool


#: What a statement's JSON may name.
_KEYS = frozenset(GameEditJson.__annotations__)

#: What settling refuses.
NOTHING_STATED = (
    "Choose a status, whether the games are mastered, or what they are left out of."
)
#: What an Undo refuses.
NOT_EDITED_BY_THIS_BATCH = (
    "That game was not changed by this batch, so it was left as it is."
)
GAME_REMOVED = "That game is removed. Restore it first."


@dataclass(frozen=True, slots=True, kw_only=True)
class GameEditStatement:
    """What one batch states; None leaves alone."""

    status: PlayerGameStatus | None = None
    mastered: bool | None = None
    excluded_from_unfinished: bool | None = None
    excluded_from_dropped: bool | None = None

    def __post_init__(self) -> None:
        if (
            self.status is None
            and self.mastered is None
            and self.excluded_from_unfinished is None
            and self.excluded_from_dropped is None
        ):
            raise ValueError("An edit states a status, mastered or a flag.")

    def encode(self) -> ChoiceValue:
        stated: GameEditJson = {}
        if self.status is not None:
            stated["status"] = self.status.value
        if self.mastered is not None:
            stated["mastered"] = self.mastered
        if self.excluded_from_unfinished is not None:
            stated["excluded_from_unfinished"] = self.excluded_from_unfinished
        if self.excluded_from_dropped is not None:
            stated["excluded_from_dropped"] = self.excluded_from_dropped
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> GameEditStatement:
        """An earlier settle's answer, or a refusal."""
        stated = stated_object(raw, _KEYS)
        status = stated.get("status")
        if "status" in stated and status not in PlayerGameStatus.values:
            raise statement_unreadable(f"{raw!r} states a status that is no word")
        mastered = _stated_flag(stated, "mastered", raw)
        unfinished = _stated_flag(stated, "excluded_from_unfinished", raw)
        dropped = _stated_flag(stated, "excluded_from_dropped", raw)
        try:
            return cls(
                status=None if status is None else PlayerGameStatus(status),
                mastered=mastered,
                excluded_from_unfinished=unfinished,
                excluded_from_dropped=dropped,
            )
        except ValueError as empty:
            raise statement_unreadable(f"{raw!r} states nothing") from empty


def _stated_flag(stated: dict[str, object], key: str, raw: ChoiceValue) -> bool | None:
    flag = stated.get(key)
    #: Present means stated: null is no bool.
    if key in stated and not isinstance(flag, bool):
        raise statement_unreadable(f"{raw!r} states a {key} that is no bool")
    return flag if isinstance(flag, bool) else None


def game_edit_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Game]:
    """Keys to tracked games, annotated with their facts."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        Game.objects.tracked_by(library)
        .filter(pk__in=wanted)
        .select_related("platform")
        .in_display_order()
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, GAME_GONE)))


# ── The question ─────────────────────────────────────────────────────────────


def _status_shown(status: str) -> str:
    return PlayerGameStatus(status).label


def _excluded_shown(excluded: bool) -> str:
    return "Excluded" if excluded else "Included"


_FACT_FIELDS = ("status", "mastered")

#: Groups name every visible field.
BULK_GAME_EDIT_GROUPS = (
    FormFieldGroup("Facts", _FACT_FIELDS, look="hidden"),
    FormFieldGroup(
        "Visibility",
        VISIBILITY_FIELDS,
        description="Leave these games out of:",
        id="bulk-visibility",
        look="panel",
    ),
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
    mastered = flag_field("Mastered")
    excluded_from_unfinished = flag_field("Unfinished lists")
    excluded_from_dropped = flag_field("Dropped figures")

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        prefix: FieldName,
        rows: Sequence[Game] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        if rows:
            cast(
                ChoiceSearchSelectWidget, self.fields["status"].widget
            ).placeholder = keeping(rows, lambda row: row.tracked_status, _status_shown)
            for name, value in (
                ("mastered", lambda row: row.tracked_mastered),
                (
                    "excluded_from_unfinished",
                    lambda row: row.tracked_excluded_from_unfinished,
                ),
                (
                    "excluded_from_dropped",
                    lambda row: row.tracked_excluded_from_dropped,
                ),
            ):
                cast(TriStateCheckboxWidget, self.fields[name].widget).held = held_flag(
                    rows, value
                )

    def clean(self) -> dict[str, Any]:
        super().clean()
        cleaned = self.cleaned_data
        if all(cleaned.get(name) is None for name in _FACT_FIELDS + VISIBILITY_FIELDS):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> GameEditStatement:
        """The valid form, as one statement."""
        cleaned = self.cleaned_data
        return GameEditStatement(
            status=cleaned["status"],
            mastered=cleaned["mastered"],
            excluded_from_unfinished=cleaned["excluded_from_unfinished"],
            excluded_from_dropped=cleaned["excluded_from_dropped"],
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[Game], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation states there are no rows.
        return AsksNothing()
    return Control(
        FormFields(
            BulkGameEditForm(prefix=field_name, rows=rows),
            groups=BULK_GAME_EDIT_GROUPS,
        )
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return GameEditStatement.decode(carried).encode()
    form = BulkGameEditForm(post, prefix=CHOICE_FIELD)
    if not form.is_valid():
        raise form_refusal(form, labelled=True)
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
    """One dispatch: a row never commits half."""
    return RowOutcome.of(
        record_facts(
            actor,
            game,
            status=statement.status,
            mastered=statement.mastered,
            excluded_from_unfinished=statement.excluded_from_unfinished,
            excluded_from_dropped=statement.excluded_from_dropped,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


def edit_one(
    actor: User,
    game: Game,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered("game"):
        statement = settled(
            choice,
            GameEditStatement.decode,
            act_name=EDIT.name,
            row_description=f"Game {game.pk} of library {actor.library.pk}",
        )
    return _state(
        actor,
        game,
        statement,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


# ── Backward ─────────────────────────────────────────────────────────────────


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
        changes = batch_fact_changes(actor.library, player_game_id, undoes)
        if not changes.changed_any:
            raise CommandRejected(
                f"batch {undoes} changed no fact of PlayerGame {player_game_id}",
                sentence=NOT_EDITED_BY_THIS_BATCH,
            )
        held_status = PlayerGameStatus(tracked.status)
        try:
            restatement = GameEditStatement(
                status=restated(changes.status, held_status),
                mastered=restated(changes.mastered, tracked.mastered),
                excluded_from_unfinished=restated(
                    changes.excluded_from_unfinished, tracked.excluded_from_unfinished
                ),
                excluded_from_dropped=restated(
                    changes.excluded_from_dropped, tracked.excluded_from_dropped
                ),
            )
        except ValueError:
            #: Every changed fact is back already.
            return RowOutcome.UNCHANGED
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"PlayerGame {player_game_id} is removed", sentence=GAME_REMOVED
            )
    described = f"game {tracked.game_id} of library {tracked.library_id}"
    for change, held, fact in (
        (changes.status, held_status, "status"),
        (changes.mastered, tracked.mastered, "mastered"),
        (
            changes.excluded_from_unfinished,
            tracked.excluded_from_unfinished,
            "excluded_from_unfinished",
        ),
        (
            changes.excluded_from_dropped,
            tracked.excluded_from_dropped,
            "excluded_from_dropped",
        ),
    ):
        log_overwrite(
            change, held, act_name=EDIT.name, fact=fact, row_description=described
        )
    return _state(
        actor,
        tracked.game,
        restatement,
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
    PreviewColumn(
        "Dropped figures",
        lambda row, _: _excluded_shown(row.tracked_excluded_from_dropped),
    ),
)

EDIT = BulkAction(
    name="playergame.edit",
    label="Edit…",
    title=ActTitle(one="Edit this game", many="Edit {count} games"),
    confirm_label="Save",
    subject="game",
    color="blue",
    undo_rows=EventRows(PlayerGame),
    fallback="games:list_games",
    scope=game_scope,
    resolve=game_edit_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=EDIT_PREVIEW,
    choice=EDIT_CHOICE,
)
