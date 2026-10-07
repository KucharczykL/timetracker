"""Platform, access, format or note on many copies."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict
from django.template.defaultfilters import truncatechars

from common.components.primitives import FormFields
from games.bulk_actions import BulkAction
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
from games.bulk_parts import (
    ActTitle,
    AsksNothing,
    BulkChoice,
    ChoiceValue,
    Control,
    EventRows,
    FieldName,
    Offered,
    RowOutcome,
)
from games.catalog_form import PLATFORM_GONE
from games.entry_forms import normalised_note
from games.events.append import SourceMetadata
from games.events.dispatch import CommandRejected
from games.events.idempotency import IdempotencyKey
from games.forms import (
    KEEP,
    PLATFORM_SEARCH_URL,
    ChoiceSearchSelectWidget,
    Keep,
    PrimitiveWidgetsMixin,
    SearchSelectWidget,
    UnsetFieldsForm,
    UnsetWidget,
    platform_options,
)
from games.ids import PlatformId
from games.models import (
    EntryAccess,
    EntryFormat,
    LibraryEntry,
    Platform,
    UserLibrary,
)
from games.reads.entry_facts import entry_fact_changes
from games.reads.releases import (
    UNSPECIFIED_PLATFORM,
    NoRelease,
    OnPlatform,
    SeveralReleases,
    platform_words,
    release_on_platform,
)
from games.writes.answers import answered
from games.writes.libraryentry import SUBJECT, describe_entry


class EntryEditJson(TypedDict, total=False):
    """The wire statement; absent is unstated."""

    access: str
    format: str
    note: str
    #: Null is Unspecified.
    platform: str | None


_KEYS = frozenset(EntryEditJson.__annotations__)

NOTHING_STATED = "Choose a platform, an access, a format or a note."
NOT_EDITED_BY_THIS_BATCH = (
    "That copy was not changed by this batch, so it was left as it is."
)
ENTRY_REMOVED = "That copy is removed. Restore it first."
PLATFORM_REMOVED = "That platform is removed."
NO_RELEASE_ON_PLATFORM = "A copy's game has no release on that platform."
SEVERAL_RELEASES_ON_PLATFORM = (
    "A copy's game has several releases on that platform. "
    "Choose one on the copy's own edit form."
)

#: How long a kept note reads.
_KEPT_NOTE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class StatedPlatform:
    """A platform, or None: Unspecified."""

    platform_id: PlatformId | None


@dataclass(frozen=True, slots=True)
class EntryEditStatement:
    """What one batch states; None leaves alone."""

    access: EntryAccess | None
    format: EntryFormat | None
    note: str | None
    platform: StatedPlatform | None = None

    def __post_init__(self) -> None:
        if (
            self.access is None
            and self.format is None
            and self.note is None
            and self.platform is None
        ):
            raise ValueError("An edit states a platform, access, format or note.")

    def encode(self) -> ChoiceValue:
        stated: EntryEditJson = {}
        if self.platform is not None:
            platform_id = self.platform.platform_id
            stated["platform"] = None if platform_id is None else str(platform_id)
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
        platform = (
            _stated_platform(raw, stated["platform"]) if "platform" in stated else None
        )
        try:
            return cls(
                None if access is None else EntryAccess(access),
                None if format is None else EntryFormat(format),
                note,
                platform,
            )
        except ValueError as empty:
            raise statement_unreadable(f"{raw!r} states nothing") from empty


def _stated_platform(raw: ChoiceValue, value: object) -> StatedPlatform:
    if value is None:
        return StatedPlatform(None)
    if not isinstance(value, str):
        raise statement_unreadable(f"{raw!r} states a platform that is no key")
    try:
        return StatedPlatform(uuid.UUID(value))
    except ValueError as unreadable:
        raise statement_unreadable(
            f"{raw!r} states a platform that is no key"
        ) from unreadable


@dataclass(frozen=True, slots=True)
class EntryFacts:
    """What one dispatch states; None leaves alone."""

    access: EntryAccess | None
    format: EntryFormat | None
    note: str | None
    release_id: uuid.UUID | None


# ── The question ─────────────────────────────────────────────────────────────


def _note_shown(note: str) -> str:
    return truncatechars(note, _KEPT_NOTE_LENGTH) if note else "no note"


class BulkEntryEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    """Empty keeps; ⊘ states Unspecified or no note."""

    platform = forms.ModelChoiceField(
        queryset=Platform.objects.none(),
        required=False,
        error_messages={"invalid_choice": PLATFORM_GONE},
        widget=UnsetWidget(
            SearchSelectWidget(
                search_url=PLATFORM_SEARCH_URL, options_resolver=platform_options
            ),
            none_label=UNSPECIFIED_PLATFORM,
        ),
    )
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
        library: UserLibrary,
        prefix: FieldName,
        rows: Sequence[LibraryEntry] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        platform = cast(forms.ModelChoiceField, self.fields["platform"])
        platform.queryset = Platform.objects.visible_to(library)
        platforms = cast(SearchSelectWidget, cast(UnsetWidget, platform.widget).widget)
        platforms.options_resolver = partial(platform_options, library=library)
        if rows:
            #: Keyed on the platform, not its name.
            names = {
                row.release.platform_id: platform_words(row.release) for row in rows
            }
            platforms.placeholder = keeping(
                rows, lambda row: row.release.platform_id, names.__getitem__
            )
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
            cleaned.get("platform") is KEEP
            and cleaned.get("access") is None
            and cleaned.get("format") is None
            and cleaned.get("note") is KEEP
        ):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> EntryEditStatement:
        """The valid form, as one statement."""
        note: str | Keep = self.cleaned_data["note"]
        platform: Platform | None | Keep = self.cleaned_data["platform"]
        return EntryEditStatement(
            self.cleaned_data["access"],
            self.cleaned_data["format"],
            None if note is KEEP else normalised_note(note),
            None
            if platform is KEEP
            else StatedPlatform(None if platform is None else platform.pk),
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[LibraryEntry], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation states there are no rows.
        return AsksNothing()
    return Control(
        FormFields(BulkEntryEditForm(library=library, prefix=field_name, rows=rows))
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return EntryEditStatement.decode(carried).encode()
    form = BulkEntryEditForm(post, library=library, prefix=CHOICE_FIELD)
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
    facts: EntryFacts,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One dispatch: a row never commits half."""
    return RowOutcome.of(
        describe_entry(
            actor,
            entry,
            access=facts.access,
            format=facts.format,
            note=facts.note,
            release_id=facts.release_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


def _release_id(
    library: UserLibrary, entry: LibraryEntry, stated: StatedPlatform
) -> uuid.UUID:
    """The copy's Release on that platform, or a refusal.

    A copy already there states its own Release, so a re-run
    under the row's key fingerprints as the first run did.
    """
    described = (
        f"LibraryEntry {entry.pk} of library {library.pk}, "
        f"game {entry.player_game.game_id}, platform {stated.platform_id}"
    )
    if (
        stated.platform_id is not None
        and Platform.objects.filter(
            pk=stated.platform_id, removed_at__isnull=False
        ).exists()
    ):
        raise CommandRejected(f"{described}: removed", sentence=PLATFORM_REMOVED)
    match release_on_platform(library, entry, stated.platform_id):
        case OnPlatform(release):
            return release.pk
        case NoRelease():
            raise CommandRejected(
                f"{described}: no Release", sentence=NO_RELEASE_ON_PLATFORM
            )
        case SeveralReleases():
            raise CommandRejected(
                f"{described}: several Releases",
                sentence=SEVERAL_RELEASES_ON_PLATFORM,
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
        release_id = (
            None
            if statement.platform is None
            else _release_id(actor.library, entry, statement.platform)
        )
    return _state(
        actor,
        entry,
        EntryFacts(statement.access, statement.format, statement.note, release_id),
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
    """Each changed fact back as before."""
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
        restatement = EntryFacts(
            restated(changes.access, held_access),
            restated(changes.format, held_format),
            restated(changes.note, entry.note),
            restated(changes.release, entry.release_id),
        )
        if restatement == EntryFacts(None, None, None, None):
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
        (changes.release, entry.release_id, "release"),
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
