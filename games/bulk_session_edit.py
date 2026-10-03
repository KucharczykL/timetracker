"""Facts set on many sessions."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict

from common.components import PostCreate
from common.components.core import Fragment
from common.components.primitives import FORM_LABEL_CLASS, Div, FormFields, P
from common.utils import truncate
from games.bulk_actions import BulkAction
from games.bulk_edit import (
    Keeping,
    form_refusal,
    keeping,
    settled,
    stated_object,
    statement_unreadable,
)
from games.bulk_move import (
    TARGET_GONE,
    move_back_row,
    move_row,
    moved_by,
    refuse_another_game,
    target_run,
)
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
    RowOutcome,
)
from games.bulk_sessions import (
    device_cell,
    labelled_session_resolution,
    release_cell,
    run_label,
    run_label_cell,
    session_of,
    session_scope,
)
from games.commands.playersession import StatedDevice, StatedRelease, check_note
from games.commands.scope import NO_COPY_OF_RELEASE, checked_release
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playersession import (
    PLAYERSESSION_CREATED,
    PLAYERSESSION_DEVICE_CHANGED,
    PLAYERSESSION_EMULATED_CHANGED,
    PLAYERSESSION_NOTE_CHANGED,
    PLAYERSESSION_RELEASE_CHANGED,
)
from games.events.vocabulary import EventType
from games.forms import (
    DEVICE_CREATE_URL,
    DEVICE_SEARCH_URL,
    HELD_RELEASE_SEARCH_URL,
    KEEP,
    PLAYTHROUGH_CREATE_URL,
    PLAYTHROUGH_SEARCH_URL,
    ChoiceSearchSelectWidget,
    Keep,
    PrimitiveWidgetsMixin,
    SearchSelectWidget,
    UnsetFieldsForm,
    UnsetWidget,
    device_options,
    held_release_options,
    run_options,
)
from games.models import (
    Device,
    LibraryEvent,
    PlayerSession,
    Playthrough,
    Release,
    UserLibrary,
)
from games.reads.events import aggregate_events
from games.reads.playthrough_runs import library_runs
from games.reads.releases import held_releases, release_label
from games.writes.answers import answered
from games.writes.playersession import describe_session


class EditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    device: str | None
    emulated: bool
    note: str
    playthrough: str
    release: str | None


#: What a statement's JSON may name.
_KEYS = frozenset(EditJson.__annotations__)

#: What settling refuses.
NOTHING_STATED = (
    "Choose a playthrough, a release, a device, whether the sessions were "
    "emulated, or a note."
)
DEVICE_UNREADABLE = "That device could not be read. Choose one again."
RELEASE_UNREADABLE = "That release could not be read. Choose one again."
PLAYTHROUGH_UNREADABLE = "That playthrough could not be read. Choose one again."
SEVERAL_GAMES = (
    "These sessions are at {count} games. Narrow the list by game to change "
    "the playthrough or the release."
)
DEVICE_GONE = (
    "That device is no longer available. Choose another one, or restore it first."
)

#: What an Undo refuses.
NOT_EDITED_BY_THIS_BATCH = (
    "That session was not changed by this batch, so it was left as it is."
)

#: The fields' labels.
PLAYTHROUGH_LABEL = "Playthrough"
RELEASE_LABEL = "Release"


#: How long a kept note reads.
_KEPT_NOTE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class EditStatement:
    """What one batch states; None leaves alone."""

    device: StatedDevice | None
    emulated: bool | None
    note: str | None = None
    playthrough: uuid.UUID | None = None
    #: Own dispatch; a gone copy refuses alone.
    release: StatedRelease | None = None

    def __post_init__(self) -> None:
        if self.playthrough is None and self.release is None and not self.describes:
            raise ValueError(
                "An edit states a run, a release, a device, emulated or a note."
            )

    @property
    def describes(self) -> bool:
        """Whether `DescribeSession` has work."""
        return not (self.device is None and self.emulated is None and self.note is None)

    def encode(self) -> ChoiceValue:
        stated: EditJson = {}
        if self.device is not None:
            device_id = self.device.device_id
            stated["device"] = None if device_id is None else str(device_id)
        if self.emulated is not None:
            stated["emulated"] = self.emulated
        if self.note is not None:
            stated["note"] = self.note
        if self.playthrough is not None:
            stated["playthrough"] = str(self.playthrough)
        if self.release is not None:
            release_id = self.release.release_id
            stated["release"] = None if release_id is None else str(release_id)
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> EditStatement:
        """An earlier settle's answer, or a refusal."""
        stated = stated_object(raw, _KEYS)
        device: StatedDevice | None = None
        if "device" in stated:
            key = stated["device"]
            if key is not None and not isinstance(key, str):
                raise statement_unreadable(f"{raw!r} states a device that is no key")
            device = StatedDevice(
                None if key is None else _stated_key(key, sentence=DEVICE_UNREADABLE)
            )
        emulated = stated.get("emulated")
        #: Present means stated: null is no bool.
        if "emulated" in stated and not isinstance(emulated, bool):
            raise statement_unreadable(f"{raw!r} states an emulated that is no bool")
        note = stated.get("note")
        if "note" in stated and not isinstance(note, str):
            raise statement_unreadable(f"{raw!r} states a note that is no text")
        if note is not None:
            check_note(note)
        playthrough: uuid.UUID | None = None
        if "playthrough" in stated:
            run = stated["playthrough"]
            if not isinstance(run, str):
                raise statement_unreadable(
                    f"{raw!r} states a playthrough that is no key"
                )
            playthrough = _stated_key(run, sentence=PLAYTHROUGH_UNREADABLE)
        release: StatedRelease | None = None
        if "release" in stated:
            key = stated["release"]
            if key is not None and not isinstance(key, str):
                raise statement_unreadable(f"{raw!r} states a release that is no key")
            release = StatedRelease(
                None if key is None else _stated_key(key, sentence=RELEASE_UNREADABLE)
            )
        stated_facts = (device, emulated, note, playthrough, release)
        if all(fact is None for fact in stated_facts):
            raise statement_unreadable(f"{raw!r} states nothing")
        return cls(device, emulated, note, playthrough, release)


def _stated_key(stated: str, *, sentence: str) -> uuid.UUID:
    try:
        return uuid.UUID(stated)
    except ValueError as unreadable:
        raise CommandRejected(
            f"{stated!r} is no uuid: {unreadable}", sentence=sentence
        ) from unreadable


# ── The question ─────────────────────────────────────────────────────────────


def _keeping_run(rows: Sequence[PlayerSession]) -> Keeping:
    """By key: two games' runs share labels."""
    if len({row.playthrough_id for row in rows}) != 1:
        return "Keep: mixed"
    return f"Keep: {run_label(rows[0])}"


def _device_name(row: PlayerSession) -> str:
    return "no device" if row.device is None else row.device.name


def _release_name(row: PlayerSession) -> str:
    return "not stated" if row.release is None else release_label(row.release)


def _note_shown(note: str) -> str:
    return truncate(note, _KEPT_NOTE_LENGTH) if note else "no note"


#: Emulated's two answers; empty keeps.
_EMULATED_CHOICES = (("True", "Emulated"), ("False", "Not emulated"))


def _emulated_shown(emulated: bool) -> str:
    return "emulated" if emulated else "not emulated"


class BulkEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    """An empty field keeps; ⊘ states none."""

    playthrough = forms.ModelChoiceField(
        queryset=Playthrough.objects.none(),
        required=False,
        error_messages={"invalid_choice": TARGET_GONE},
        widget=SearchSelectWidget(
            search_url=PLAYTHROUGH_SEARCH_URL,
            options_resolver=run_options,
            create=PostCreate(PLAYTHROUGH_CREATE_URL),
        ),
    )
    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        error_messages={"invalid_choice": DEVICE_GONE},
        widget=UnsetWidget(
            SearchSelectWidget(
                search_url=DEVICE_SEARCH_URL,
                options_resolver=device_options,
                create=PostCreate(DEVICE_CREATE_URL),
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
    release = forms.ModelChoiceField(
        queryset=Release.objects.none(),
        required=False,
        label=RELEASE_LABEL,
        error_messages={"invalid_choice": NO_COPY_OF_RELEASE},
        widget=UnsetWidget(
            #: ⊘ states none; no none row here.
            SearchSelectWidget(
                search_url=HELD_RELEASE_SEARCH_URL,
                options_resolver=held_release_options,
            ),
            none_label="No release",
        ),
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
        run = cast(forms.ModelChoiceField, self.fields["playthrough"])
        run.queryset = library_runs(library)
        runs = cast(SearchSelectWidget, run.widget)
        runs.options_resolver = partial(run_options, library=library)
        release = cast(forms.ModelChoiceField, self.fields["release"])
        release.queryset = held_releases(library)
        releases = cast(SearchSelectWidget, cast(UnsetWidget, release.widget).widget)
        releases.options_resolver = partial(held_release_options, library=library)
        games = {row.playthrough.player_game.game_id for row in rows}
        if len(games) == 1:
            game_id = games.pop()
            #: One mapping feeds search and create.
            runs.params = {"game_id": {"value": str(game_id)}}
            releases.params = runs.params
            release.queryset = release.queryset.filter(edition__game_id=game_id)
        device = cast(forms.ModelChoiceField, self.fields["device"])
        device.queryset = Device.objects.for_library(library)
        picker = cast(SearchSelectWidget, cast(UnsetWidget, device.widget).widget)
        picker.options_resolver = partial(device_options, library=library)
        if rows:
            runs.placeholder = _keeping_run(rows)
            picker.placeholder = keeping(rows, _device_name, str)
            releases.placeholder = keeping(rows, _release_name, str)
            cast(
                ChoiceSearchSelectWidget, self.fields["emulated"].widget
            ).placeholder = keeping(rows, lambda row: row.emulated, _emulated_shown)
            note = cast(UnsetWidget, self.fields["note"].widget).widget
            note.attrs["placeholder"] = keeping(rows, lambda row: row.note, _note_shown)

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
            cleaned.get("playthrough") is None
            and cleaned.get("release") is KEEP
            and cleaned.get("device") is KEEP
            and cleaned.get("emulated") is None
            and cleaned.get("note") is KEEP
        ):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> EditStatement:
        """The valid form, as one statement."""
        device: Device | None | Keep = self.cleaned_data["device"]
        note: str | Keep = self.cleaned_data["note"]
        run: Playthrough | None = self.cleaned_data["playthrough"]
        release: Release | None | Keep = self.cleaned_data["release"]
        return EditStatement(
            None
            if device is KEEP
            else StatedDevice(None if device is None else device.pk),
            self.cleaned_data["emulated"],
            None if note is KEEP else note,
            None if run is None else run.pk,
            None
            if release is KEEP
            else StatedRelease(None if release is None else release.pk),
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    form = BulkEditForm(library=library, prefix=field_name, rows=rows)
    games = {row.playthrough.player_game_id for row in rows}
    if len(games) == 1:
        return Control(FormFields(form))
    #: Shown only: the settle form keeps both.
    del form.fields["playthrough"]
    del form.fields["release"]
    return Control(
        Fragment(
            Div(data_field_row="playthrough")[
                P(class_=FORM_LABEL_CLASS)[f"{PLAYTHROUGH_LABEL} and release"],
                P(class_="text-type-body text-body")[
                    SEVERAL_GAMES.format(count=len(games))
                ],
            ],
            FormFields(form),
        )
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's; checked."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    statement = EditStatement.decode(carried) if carried else _composed(library, post)
    if statement.playthrough is not None:
        target_run(library, statement.playthrough)
    device = statement.device
    if device is not None and device.device_id is not None:
        held = Device.objects.for_library(library).filter(pk=device.device_id)
        if not held.exists():
            raise CommandRejected(
                f"device {device.device_id} is no live device of library {library.pk}",
                sentence=DEVICE_GONE,
            )
    release = statement.release
    if release is not None and release.release_id is not None:
        copied = held_releases(library).filter(pk=release.release_id)
        if not copied.exists():
            raise CommandRejected(
                f"release {release.release_id} has no live copy in library "
                f"{library.pk}",
                sentence=NO_COPY_OF_RELEASE,
            )
    return statement.encode()


def _composed(library: UserLibrary, post: QueryDict) -> EditStatement:
    from games.views.bulk import CHOICE_FIELD

    form = BulkEditForm(post, library=library, prefix=CHOICE_FIELD)
    if not form.is_valid():
        raise form_refusal(form, labelled=False)
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
        statement = settled(
            choice,
            EditStatement.decode,
            act_name=EDIT.name,
            row_description=(
                f"PlayerSession {session.pk} of library {actor.library.pk}"
            ),
        )
        target = None
        if statement.playthrough is not None:
            target = target_run(actor.library, statement.playthrough)
            #: Before any write: nothing half-done.
            refuse_another_game(session, target)
        if statement.release is not None:
            checked_release(
                actor.library,
                statement.release.release_id,
                game_id=session.playthrough.player_game.game_id,
                held_id=session.release_id,
            )
    outcomes: list[RowOutcome] = []
    if target is not None:
        outcomes.append(
            move_row(
                actor,
                session,
                target,
                act=EDIT.name,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
    if statement.describes:
        outcomes.append(
            RowOutcome.of(
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
        )
    if statement.release is not None:
        outcomes.append(
            _state_release(
                actor,
                session.pk,
                statement.release,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
    return RowOutcome.either(outcomes)


def _state_release(
    actor: User,
    session_id: uuid.UUID,
    release: StatedRelease,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The Release alone, under its own key."""
    with answered("session"):
        return RowOutcome.of(
            describe_session(
                actor,
                session_of(actor, session_id),
                release=release,
                idempotency_key=f"{idempotency_key}-release",
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
    return StatedDevice(_referenced_key(event, device))


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


def _release_of(event: LibraryEvent) -> StatedRelease:
    """The Release a payload states."""
    if "release" not in event.payload:
        raise RowUnreadable(f"event {event.pk} states no release")
    release = event.payload["release"]
    if release is None:
        return StatedRelease(None)
    return StatedRelease(_referenced_key(event, release))


def _referenced_key(event: LibraryEvent, reference: object) -> uuid.UUID:
    """A recorded reference's key, or a defect."""
    if not isinstance(reference, dict) or "id" not in reference:
        raise RowUnreadable(f"event {event.pk} states reference {reference!r}")
    try:
        return uuid.UUID(reference["id"])
    except ValueError as unreadable:
        raise RowUnreadable(
            f"event {event.pk} states reference id {reference['id']!r}"
        ) from unreadable


def values_before(
    library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID
) -> EditStatement | None:
    """Described facts before the batch, or None."""
    events = list(aggregate_events(library, session_id))
    device = _earlier(events, batch_id, PLAYERSESSION_DEVICE_CHANGED.event_type)
    emulated = _earlier(events, batch_id, PLAYERSESSION_EMULATED_CHANGED.event_type)
    note = _earlier(events, batch_id, PLAYERSESSION_NOTE_CHANGED.event_type)
    release = _earlier(events, batch_id, PLAYERSESSION_RELEASE_CHANGED.event_type)
    if device is None and emulated is None and note is None and release is None:
        return None
    return EditStatement(
        None if device is None else _device_of(device),
        None if emulated is None else _emulated_of(emulated),
        None if note is None else _note_of(note),
        release=None if release is None else _release_of(release),
    )


def edit_back(
    actor: User,
    session_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Facts restated first, then the run."""
    with answered("session"):
        before = values_before(actor.library, session_id, undoes)
        moved = moved_by(actor.library, session_id, undoes)
        if before is None and not moved:
            raise CommandRejected(
                f"batch {undoes} changed no fact of session {session_id}",
                sentence=NOT_EDITED_BY_THIS_BATCH,
            )
        if before is not None and before.release is not None:
            #: Before any write; a gone copy refuses.
            session = session_of(actor, session_id)
            checked_release(
                actor.library,
                before.release.release_id,
                game_id=session.playthrough.player_game.game_id,
                held_id=session.release_id,
            )
    outcomes: list[RowOutcome] = []
    if before is not None and before.describes:
        outcomes.append(
            RowOutcome.of(
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
        )
    if before is not None and before.release is not None:
        outcomes.append(
            _state_release(
                actor,
                session_id,
                before.release,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
    if moved:
        outcomes.append(
            move_back_row(
                actor,
                session_id,
                act=EDIT.name,
                undoes=undoes,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
    return RowOutcome.either(outcomes)


# ── The confirmation ─────────────────────────────────────────────────────────


EDIT_PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Game", lambda row, _: row.playthrough.player_game.game.name),
    PreviewColumn(PLAYTHROUGH_LABEL, run_label_cell),
    PreviewColumn(RELEASE_LABEL, release_cell),
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
    undo_rows=EventRows(PlayerSession),
    fallback="games:list_sessions",
    scope=session_scope,
    resolve=labelled_session_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=EDIT_PREVIEW,
    choice=EDIT_CHOICE,
)
