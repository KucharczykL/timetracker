"""Device, emulated or note, set on many sessions."""

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict

from common.components.primitives import FormFields
from common.utils import truncate
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
from games.commands.playersession import StatedDevice, check_note
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playersession import (
    PLAYERSESSION_CREATED,
    PLAYERSESSION_DEVICE_CHANGED,
    PLAYERSESSION_EMULATED_CHANGED,
    PLAYERSESSION_NOTE_CHANGED,
)
from games.events.vocabulary import EventType
from games.forms import (
    DEVICE_CREATE_URL,
    DEVICE_SEARCH_URL,
    KEEP,
    ChoiceSearchSelectWidget,
    Keep,
    PrimitiveWidgetsMixin,
    SearchSelectWidget,
    UnsetFieldsForm,
    UnsetWidget,
    device_options,
)
from games.models import Device, LibraryEvent, PlayerSession, UserLibrary
from games.reads.events import aggregate_events
from games.writes.answers import answered
from games.writes.playersession import describe_session


class EditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    device: str | None
    emulated: bool
    note: str


#: What a statement's JSON may name.
_KEYS = frozenset(EditJson.__annotations__)

#: What settling refuses.
NOTHING_STATED = "Choose a device, whether the sessions were emulated, or a note."
DEVICE_UNREADABLE = "That device could not be read. Choose one again."
DEVICE_GONE = (
    "That device is no longer available. Choose another one, or restore it first."
)
STATEMENT_UNREADABLE = "What to change could not be read. Choose it again."

#: What an Undo refuses.
NOT_EDITED_BY_THIS_BATCH = (
    "That session was not changed by this batch, so it was left as it is."
)

#: A placeholder: what "leave as it is" keeps.
type Keeping = str  # "Keep: Steam Deck"

#: How long a kept note reads.
_KEPT_NOTE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class EditStatement:
    """What one batch states; None leaves alone."""

    device: StatedDevice | None
    emulated: bool | None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.device is None and self.emulated is None and self.note is None:
            raise ValueError("An edit states a device, emulated, a note, or more.")

    def encode(self) -> ChoiceValue:
        stated: EditJson = {}
        if self.device is not None:
            device_id = self.device.device_id
            stated["device"] = None if device_id is None else str(device_id)
        if self.emulated is not None:
            stated["emulated"] = self.emulated
        if self.note is not None:
            stated["note"] = self.note
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
        note = stated.get("note")
        if "note" in stated and not isinstance(note, str):
            raise _unreadable(f"{raw!r} states a note that is no text")
        if note is not None:
            check_note(note)
        if device is None and emulated is None and note is None:
            raise _unreadable(f"{raw!r} states nothing")
        return cls(device, emulated, note)


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


def _keeping[T](
    rows: Sequence[PlayerSession],
    value: Callable[[PlayerSession], T],
    shown: Callable[[T], str],
) -> Keeping:
    """What the rows hold; differing, "mixed"."""
    held = {value(row) for row in rows}
    if len(held) != 1:
        return "Keep: mixed"
    return f"Keep: {shown(held.pop())}"


def _device_name(row: PlayerSession) -> str:
    return "no device" if row.device is None else row.device.name


def _note_shown(note: str) -> str:
    return truncate(note, _KEPT_NOTE_LENGTH) if note else "no note"


#: Emulated's two answers; empty keeps.
_EMULATED_CHOICES = (("True", "Emulated"), ("False", "Not emulated"))


def _emulated_shown(emulated: bool) -> str:
    return "emulated" if emulated else "not emulated"


class BulkEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    """An empty field keeps; ⊘ states none."""

    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        error_messages={"invalid_choice": DEVICE_GONE},
        widget=UnsetWidget(
            SearchSelectWidget(
                search_url=DEVICE_SEARCH_URL,
                options_resolver=device_options,
                create_url=DEVICE_CREATE_URL,
            ),
            none_label="No device",
        ),
    )
    emulated = forms.TypedChoiceField(
        choices=_EMULATED_CHOICES,
        coerce=lambda value: value == "True",
        empty_value=None,
        required=False,
        widget=ChoiceSearchSelectWidget(),
    )
    note = forms.CharField(
        required=False,
        widget=UnsetWidget(forms.Textarea(attrs={"rows": 2}), none_label="No note"),
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        library: UserLibrary,
        prefix: FieldName,
        rows: Sequence[PlayerSession] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        device = cast(forms.ModelChoiceField, self.fields["device"])
        device.queryset = Device.objects.for_library(library)
        picker = cast(SearchSelectWidget, cast(UnsetWidget, device.widget).widget)
        picker.options_resolver = partial(device_options, library=library)
        if rows:
            picker.placeholder = _keeping(rows, _device_name, str)
            cast(
                ChoiceSearchSelectWidget, self.fields["emulated"].widget
            ).placeholder = _keeping(rows, lambda row: row.emulated, _emulated_shown)
            note = cast(UnsetWidget, self.fields["note"].widget).widget
            note.attrs["placeholder"] = _keeping(
                rows, lambda row: row.note, _note_shown
            )

    def clean_note(self) -> str:
        note = self.cleaned_data["note"]
        if note:
            try:
                check_note(note)
            except CommandRejected as refused:
                raise forms.ValidationError(refused.sentence or "") from refused
        return note

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if (
            cleaned.get("device") is KEEP
            and cleaned.get("emulated") is None
            and cleaned.get("note") is KEEP
        ):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> EditStatement:
        """The valid form, as one statement."""
        device: Device | None | Keep = self.cleaned_data["device"]
        note: str | Keep = self.cleaned_data["note"]
        return EditStatement(
            None
            if device is KEEP
            else StatedDevice(None if device is None else device.pk),
            self.cleaned_data["emulated"],
            None if note is KEEP else note,
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    return Control(
        FormFields(BulkEditForm(library=library, prefix=field_name, rows=rows))
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's; checked."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    statement = EditStatement.decode(carried) if carried else _composed(library, post)
    device = statement.device
    if device is not None and device.device_id is not None:
        held = Device.objects.for_library(library).filter(pk=device.device_id)
        if not held.exists():
            raise CommandRejected(
                f"device {device.device_id} is no live device of library {library.pk}",
                sentence=DEVICE_GONE,
            )
    return statement.encode()


def _composed(library: UserLibrary, post: QueryDict) -> EditStatement:
    from games.views.bulk import CHOICE_FIELD

    form = BulkEditForm(post, library=library, prefix=CHOICE_FIELD)
    if not form.is_valid():
        sentences = [
            str(message) for messages in form.errors.values() for message in messages
        ]
        raise CommandRejected(
            f"the edit form refuses: {sentences}", sentence=sentences[0]
        )
    return form.statement()


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
            note=statement.note,
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


def _note_of(event: LibraryEvent) -> str:
    """The note a created or note_changed payload states."""
    note = event.payload.get("note")
    if not isinstance(note, str):
        raise RowUnreadable(f"event {event.pk} states note {note!r}")
    return note


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
    note = _earlier(events, batch_id, PLAYERSESSION_NOTE_CHANGED.event_type)
    if device is None and emulated is None and note is None:
        raise CommandRejected(
            f"batch {batch_id} changed no fact of session {session_id}",
            sentence=NOT_EDITED_BY_THIS_BATCH,
        )
    return EditStatement(
        None if device is None else _device_of(device),
        None if emulated is None else _emulated_of(emulated),
        None if note is None else _note_of(note),
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
            note=before.note,
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
    PreviewColumn("Note", lambda row, _: row.note),
)

EDIT = BulkAction(
    name="session.edit",
    label="Edit…",
    title=ActTitle(one="Edit this session", many="Edit {count} sessions"),
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
