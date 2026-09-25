"""Device or emulated, set on many sessions."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple, TypedDict

from django.contrib.auth.models import User
from django.http import QueryDict

from common.components.primitives import (
    Checkbox,
    Div,
    Fieldset,
    Label,
    Legend,
    Radio,
)
from common.components.search_select import DEFAULT_PREFETCH, SearchSelect
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
    RowOutcome,
)
from games.bulk_sessions import (
    device_cell,
    session_of,
    session_resolution,
    session_scope,
)
from games.commands.playersession import StatedDevice
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playersession import (
    PLAYERSESSION_CREATED,
    PLAYERSESSION_DEVICE_CHANGED,
    PLAYERSESSION_EMULATED_CHANGED,
)
from games.events.vocabulary import EventType
from games.forms import DEVICE_CREATE_URL, DEVICE_SEARCH_URL
from games.models import Device, LibraryEvent, PlayerSession, UserLibrary
from games.reads.events import aggregate_events
from games.writes.answers import answered
from games.writes.playersession import describe_session


class EditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    device: str | None
    emulated: bool


#: What a statement's JSON may name.
_KEYS = frozenset(EditJson.__annotations__)

#: What settling refuses.
NOTHING_STATED = "Choose a device, or whether the sessions were emulated."
DEVICE_AND_NONE = "Choose a device or No device, not both."
DEVICE_UNREADABLE = "That device could not be read. Choose one again."
DEVICE_GONE = (
    "That device is no longer available. Choose another one, or restore it first."
)
STATEMENT_UNREADABLE = "What to change could not be read. Choose it again."

#: What an Undo refuses.
NOT_EDITED_BY_THIS_BATCH = (
    "That session was not changed by this batch, so it was left as it is."
)

#: Heading style for both groups.
_HEADING = "text-type-body text-body"

#: A radio value of the emulated group.
type EmulatedAnswer = str  # "", "yes", "no"

LEAVE: EmulatedAnswer = ""
EMULATED: EmulatedAnswer = "yes"
NOT_EMULATED: EmulatedAnswer = "no"
_EMULATED_ANSWERS: Mapping[EmulatedAnswer, bool | None] = MappingProxyType(
    {LEAVE: None, EMULATED: True, NOT_EMULATED: False}
)


@dataclass(frozen=True, slots=True)
class EditStatement:
    """What one batch states; None leaves alone."""

    device: StatedDevice | None
    emulated: bool | None

    def __post_init__(self) -> None:
        if self.device is None and self.emulated is None:
            raise ValueError("An edit states a device, emulated, or both.")

    def encode(self) -> ChoiceValue:
        stated: EditJson = {}
        if self.device is not None:
            device_id = self.device.device_id
            stated["device"] = None if device_id is None else str(device_id)
        if self.emulated is not None:
            stated["emulated"] = self.emulated
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> EditStatement:
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
        device: StatedDevice | None = None
        if "device" in stated:
            key = stated["device"]
            if key is not None and not isinstance(key, str):
                raise _unreadable(f"{raw!r} states a device that is no key")
            device = StatedDevice(None if key is None else _device_key(key))
        emulated = stated.get("emulated")
        #: Present means stated: null is no bool.
        if "emulated" in stated and not isinstance(emulated, bool):
            raise _unreadable(f"{raw!r} states an emulated that is no bool")
        if device is None and emulated is None:
            raise _unreadable(f"{raw!r} states nothing")
        return cls(device, emulated)


def _unreadable(message: str) -> CommandRejected:
    return CommandRejected(message, sentence=STATEMENT_UNREADABLE)


def _device_key(stated: str) -> uuid.UUID:
    try:
        return uuid.UUID(stated)
    except ValueError as unreadable:
        raise CommandRejected(
            f"{stated!r} is no uuid: {unreadable}", sentence=DEVICE_UNREADABLE
        ) from unreadable


# ── The question ─────────────────────────────────────────────────────────────


class EditFields(NamedTuple):
    """The control's names, suffixed onto the runner's."""

    device: FieldName
    no_device: FieldName
    emulated: FieldName


def edit_fields(field_name: FieldName) -> EditFields:
    return EditFields(
        device=f"{field_name}-device",
        no_device=f"{field_name}-no-device",
        emulated=f"{field_name}-emulated",
    )


def offer_edit(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """Controls suffix `field_name`; none uses it bare."""
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    fields = edit_fields(field_name)
    return Control(
        Div(class_="flex flex-col gap-4")[
            Div(class_="flex flex-col gap-2")[
                Label(for_=fields.device, class_=_HEADING)["Device"],
                SearchSelect(
                    name=fields.device,
                    search_url=DEVICE_SEARCH_URL,
                    create_url=DEVICE_CREATE_URL,
                    prefetch=DEFAULT_PREFETCH,
                    placeholder="Leave as it is",
                    id=fields.device,
                ),
                Checkbox(name=fields.no_device, label="No device"),
            ],
            Fieldset(class_="flex flex-col gap-2")[
                Legend(class_=f"{_HEADING} mb-2")["Emulated"],
                Radio(
                    name=fields.emulated,
                    value=LEAVE,
                    label="Leave as it is",
                    checked=True,
                ),
                Radio(name=fields.emulated, value=EMULATED, label="Emulated"),
                Radio(name=fields.emulated, value=NOT_EMULATED, label="Not emulated"),
            ],
        ]
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the control's; checked."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    statement = (
        EditStatement.decode(carried) if carried else _composed(post, CHOICE_FIELD)
    )
    device = statement.device
    if device is not None and device.device_id is not None:
        held = Device.objects.for_library(library).filter(pk=device.device_id)
        if not held.exists():
            raise CommandRejected(
                f"device {device.device_id} is no live device of library {library.pk}",
                sentence=DEVICE_GONE,
            )
    return statement.encode()


def _composed(post: QueryDict, field_name: FieldName) -> EditStatement:
    fields = edit_fields(field_name)
    picked = post.get(fields.device, "")
    none = bool(post.get(fields.no_device))
    if picked and none:
        raise CommandRejected(
            "a device was picked and No device checked", sentence=DEVICE_AND_NONE
        )
    device: StatedDevice | None = None
    if picked:
        device = StatedDevice(_device_key(picked))
    elif none:
        device = StatedDevice(None)
    answer = post.get(fields.emulated, LEAVE)
    if answer not in _EMULATED_ANSWERS:
        raise _unreadable(f"{answer!r} is no emulated answer")
    emulated = _EMULATED_ANSWERS[answer]
    if device is None and emulated is None:
        raise CommandRejected("the edit states nothing", sentence=NOTHING_STATED)
    return EditStatement(device, emulated)


EDIT_CHOICE: BulkChoice[PlayerSession] = BulkChoice(
    offer=offer_edit, settle=settle_edit
)


# ── Forward ──────────────────────────────────────────────────────────────────


def _source() -> dict[str, object]:
    return {"bulk": {"action": EDIT.name}}


def edit_one(
    actor: User,
    session: PlayerSession,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered("session"):
        if choice is None:
            raise RowUnreadable(
                f"{EDIT.name} ran with no statement for PlayerSession "
                f"{session.pk} of library {actor.library.pk}. The act "
                "declares a choice, so the runner settles one before a row."
            )
        try:
            statement = EditStatement.decode(choice)
        except CommandRejected as drift:
            #: Settled this request: ours, not theirs.
            raise RowUnreadable(
                f"{EDIT.name} settled {choice!r} and cannot read it back: {drift}"
            ) from drift
    return RowOutcome.of(
        describe_session(
            actor,
            session,
            device=statement.device,
            emulated=statement.emulated,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    )


# ── Backward ─────────────────────────────────────────────────────────────────


def _earlier(
    events: Sequence[LibraryEvent], batch_id: uuid.UUID, changed: EventType
) -> LibraryEvent | None:
    """The fact's event before the batch's; none unchanged."""
    ours = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id and event.event_type == changed
        ),
        None,
    )
    if ours is None:
        return None
    family = (PLAYERSESSION_CREATED.event_type, changed)
    earlier = [
        event
        for event in events
        if event.sequence < ours.sequence and event.event_type in family
    ]
    if not earlier:
        raise RowUnreadable(
            f"session {ours.aggregate_id} of library {ours.library_id} states "
            f"{changed} at sequence {ours.sequence} and no creation before it"
        )
    return earlier[-1]


def _device_of(event: LibraryEvent) -> StatedDevice:
    """The device a created or device_changed payload states."""
    #: Both payloads name it `device`.
    if "device" not in event.payload:
        raise RowUnreadable(f"event {event.pk} states no device")
    device = event.payload["device"]
    if device is None:
        return StatedDevice(None)
    if not isinstance(device, dict) or "id" not in device:
        raise RowUnreadable(f"event {event.pk} states device {device!r}")
    return StatedDevice(uuid.UUID(device["id"]))


def _emulated_of(event: LibraryEvent) -> bool:
    """The flag a created or emulated_changed payload states."""
    emulated = event.payload.get("emulated")
    if not isinstance(emulated, bool):
        raise RowUnreadable(f"event {event.pk} states emulated {emulated!r}")
    return emulated


def values_before(
    library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID
) -> EditStatement:
    """The changed facts' values before the batch."""
    events = list(aggregate_events(library, session_id))
    device = _earlier(events, batch_id, PLAYERSESSION_DEVICE_CHANGED.event_type)
    emulated = _earlier(events, batch_id, PLAYERSESSION_EMULATED_CHANGED.event_type)
    if device is None and emulated is None:
        raise CommandRejected(
            f"batch {batch_id} changed no fact of session {session_id}",
            sentence=NOT_EDITED_BY_THIS_BATCH,
        )
    return EditStatement(
        None if device is None else _device_of(device),
        None if emulated is None else _emulated_of(emulated),
    )


def edit_back(
    actor: User,
    session_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Earlier values restated; later edits overwritten."""
    with answered("session"):
        before = values_before(actor.library, session_id, undoes)
    return RowOutcome.of(
        describe_session(
            actor,
            session_of(actor, session_id),
            device=before.device,
            emulated=before.emulated,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    )


# ── The confirmation ─────────────────────────────────────────────────────────


EDIT_PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Game", lambda row, _: row.playthrough.player_game.game.name),
    PreviewColumn("Day", lambda row, _: str(row.effective_day)),
    PreviewColumn(
        "Duration",
        lambda row, presentations: presentations.durations.format(
            row.effective_duration
        ),
        align="right",
    ),
    PreviewColumn("Device", device_cell),
    PreviewColumn("Emulated", lambda row, _: "Yes" if row.emulated else "No"),
)

EDIT = BulkAction(
    name="session.edit",
    label="Edit…",
    title=ActTitle(one="Edit this session", many="Edit these sessions"),
    confirm_label="Save",
    subject="session",
    color="blue",
    inverse_aggregate="playersession",
    inverse_model=PlayerSession,
    fallback="games:list_sessions",
    scope=session_scope,
    resolve=session_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=EDIT_PREVIEW,
    choice=EDIT_CHOICE,
)
