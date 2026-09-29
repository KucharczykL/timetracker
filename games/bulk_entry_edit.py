"""Access, format or note, set on many copies."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict
from django.template.defaultfilters import truncatechars

from common.components.primitives import FormFields
from games.bulk_actions import (
    ActTitle,
    AsksNothing,
    BulkAction,
    BulkChoice,
    ChoiceValue,
    Control,
    EventRows,
    FieldName,
    Offered,
    RowOutcome,
)
from games.bulk_edit import (
    form_refusal,
    keeping,
    log_overwrite,
    restated,
    settled,
    stated_object,
    statement_unreadable,
)
from games.bulk_entries import (
    ENTRY_PREVIEW,
    entry_resolution,
    entry_scope,
    removed_entry,
)
from games.events.append import SourceMetadata
from games.events.dispatch import CommandRejected
from games.events.idempotency import IdempotencyKey
from games.forms import (
    KEEP,
    ChoiceSearchSelectWidget,
    Keep,
    PrimitiveWidgetsMixin,
    UnsetFieldsForm,
    UnsetWidget,
)
from games.models import EntryAccess, EntryFormat, LibraryEntry, UserLibrary
from games.reads.entry_facts import entry_fact_changes
from games.writes.answers import answered
from games.writes.libraryentry import SUBJECT, describe_entry


class EntryEditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    access: str
    format: str
    note: str


_KEYS = frozenset(EntryEditJson.__annotations__)

NOTHING_STATED = "Choose an access, a format or a note."
NOT_EDITED_BY_THIS_BATCH = (
    "That copy was not changed by this batch, so it was left as it is."
)
ENTRY_REMOVED = "That copy is removed. Restore it first."

#: How long a kept note reads.
_KEPT_NOTE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class EntryEditStatement:
    """What one batch states; None leaves alone."""

    access: EntryAccess | None
    format: EntryFormat | None
    note: str | None

    def __post_init__(self) -> None:
        if self.access is None and self.format is None and self.note is None:
            raise ValueError("An edit states an access, a format or a note.")

    def encode(self) -> ChoiceValue:
        stated: EntryEditJson = {}
        if self.access is not None:
            stated["access"] = self.access.value
        if self.format is not None:
            stated["format"] = self.format.value
        if self.note is not None:
            stated["note"] = self.note
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> EntryEditStatement:
        """An earlier settle's answer, or a refusal."""
        stated = stated_object(raw, _KEYS)
        access = stated.get("access")
        if "access" in stated and access not in EntryAccess.values:
            raise statement_unreadable(f"{raw!r} states an access that is no word")
        format = stated.get("format")
        if "format" in stated and format not in EntryFormat.values:
            raise statement_unreadable(f"{raw!r} states a format that is no word")
        note = stated.get("note")
        if "note" in stated and not isinstance(note, str):
            raise statement_unreadable(f"{raw!r} states a note that is no text")
        try:
            return cls(
                None if access is None else EntryAccess(access),
                None if format is None else EntryFormat(format),
                note,
            )
        except ValueError as empty:
            raise statement_unreadable(f"{raw!r} states nothing") from empty


# ── The question ─────────────────────────────────────────────────────────────


def _note_shown(note: str) -> str:
    return truncatechars(note, _KEPT_NOTE_LENGTH) if note else "no note"


class BulkEntryEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    """An empty field keeps; ⊘ states no note."""

    access = forms.TypedChoiceField(
        choices=EntryAccess.choices,
        coerce=EntryAccess,
        empty_value=None,
        required=False,
        widget=ChoiceSearchSelectWidget(),
    )
    format = forms.TypedChoiceField(
        choices=EntryFormat.choices,
        coerce=EntryFormat,
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
        prefix: FieldName,
        rows: Sequence[LibraryEntry] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        if rows:
            cast(
                ChoiceSearchSelectWidget, self.fields["access"].widget
            ).placeholder = keeping(
                rows, lambda row: row.access, lambda word: EntryAccess(word).label
            )
            cast(
                ChoiceSearchSelectWidget, self.fields["format"].widget
            ).placeholder = keeping(
                rows, lambda row: row.format, lambda word: EntryFormat(word).label
            )
            note = cast(UnsetWidget, self.fields["note"].widget).widget
            note.attrs["placeholder"] = keeping(rows, lambda row: row.note, _note_shown)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if (
            cleaned.get("access") is None
            and cleaned.get("format") is None
            and cleaned.get("note") is KEEP
        ):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> EntryEditStatement:
        """The valid form, as one statement."""
        note: str | Keep = self.cleaned_data["note"]
        return EntryEditStatement(
            self.cleaned_data["access"],
            self.cleaned_data["format"],
            None if note is KEEP else note,
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[LibraryEntry], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation states there are no rows.
        return AsksNothing()
    return Control(FormFields(BulkEntryEditForm(prefix=field_name, rows=rows)))


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return EntryEditStatement.decode(carried).encode()
    form = BulkEntryEditForm(post, prefix=CHOICE_FIELD)
    if not form.is_valid():
        raise form_refusal(form, labelled=True)
    return form.statement().encode()


EDIT_CHOICE: BulkChoice[LibraryEntry] = BulkChoice(offer=offer_edit, settle=settle_edit)


# ── Forward ──────────────────────────────────────────────────────────────────


def _source() -> SourceMetadata:
    return {"bulk": {"action": ENTRY_EDIT.name}}


def _state(
    actor: User,
    entry: LibraryEntry,
    statement: EntryEditStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One dispatch: a row never commits half."""
    return RowOutcome.of(
        describe_entry(
            actor,
            entry,
            access=None if statement.access is None else statement.access.value,
            format=None if statement.format is None else statement.format.value,
            note=statement.note,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


def edit_one(
    actor: User,
    entry: LibraryEntry,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered(SUBJECT):
        statement = settled(
            choice,
            EntryEditStatement.decode,
            act_name=ENTRY_EDIT.name,
            row_description=f"LibraryEntry {entry.pk} of library {actor.library.pk}",
        )
    return _state(
        actor,
        entry,
        statement,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


# ── Backward ─────────────────────────────────────────────────────────────────


def edit_back(
    actor: User,
    entry_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Each changed fact back to its earlier value."""
    entry = removed_entry(actor, entry_id)
    with answered(SUBJECT):
        changes = entry_fact_changes(actor.library, entry_id, undoes)
        if not changes.changed_any:
            raise CommandRejected(
                f"batch {undoes} changed no fact of LibraryEntry {entry_id}",
                sentence=NOT_EDITED_BY_THIS_BATCH,
            )
        held_access = EntryAccess(entry.access)
        held_format = EntryFormat(entry.format)
        try:
            restatement = EntryEditStatement(
                restated(changes.access, held_access),
                restated(changes.format, held_format),
                restated(changes.note, entry.note),
            )
        except ValueError:
            #: Every changed fact is back already.
            return RowOutcome.UNCHANGED
        if entry.removed_at is not None:
            raise CommandRejected(
                f"LibraryEntry {entry_id} is removed", sentence=ENTRY_REMOVED
            )
    described = f"LibraryEntry {entry.pk} of library {entry.library_id}"
    for change, held, fact in (
        (changes.access, held_access, "access"),
        (changes.format, held_format, "format"),
        (changes.note, entry.note, "note"),
    ):
        log_overwrite(
            change, held, act_name=ENTRY_EDIT.name, fact=fact, row_description=described
        )
    return _state(
        actor,
        entry,
        restatement,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


ENTRY_EDIT = BulkAction(
    name="entry.edit",
    label="Edit…",
    title=ActTitle(one="Edit this copy", many="Edit {count} copies"),
    confirm_label="Save",
    subject=SUBJECT,
    color="blue",
    undo_rows=EventRows(LibraryEntry),
    fallback="games:list_library",
    scope=entry_scope,
    resolve=entry_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=ENTRY_PREVIEW,
    choice=EDIT_CHOICE,
)
