"""The forms that state a copy."""

import datetime
import hashlib
import uuid
from functools import partial
from typing import Any, Literal, cast

from django import forms

from common.components import FormFieldGroup, PostCreate, SearchSelectOption
from common.components.search_select import ParamSources
from common.date_time_presentation import DateTimePresentation
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import EntryStatement
from games.end_ways import END_WAY_LABELS, EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.events.idempotency import IdempotencyKey, key_answered
from games.forms import (
    PrimitiveWidgetsMixin,
    RadioListWidget,
    SearchSelectWidget,
    SingleGameChoiceField,
    TemporalFormField,
    _game_options,
)
from games.models import (
    ENTRY_WAYS,
    EntryAccess,
    EntryFormat,
    Game,
    LibraryEntry,
    Release,
    UserLibrary,
)
from games.reads.endpoints import stated
from games.reads.releases import game_releases, release_label
from games.writes.endpoint import KEEP, Keep
from timetracker.temporal import TemporalValue

RELEASE_SEARCH_URL = "/api/releases/search"
RELEASE_CREATE_URL = "/api/releases/"
GAME_SEARCH_URL = "/api/games/search"

CHANGED_SINCE_OPENED = (
    "This copy changed since you opened this page. Reload it and save again."
)
RELEASE_OF_ANOTHER_GAME = "Pick a release of the game you chose."

WAY_CHOICES = [(way.value, END_WAY_LABELS[way]) for way in ENTRY_WAYS]

#: What it is, how had, a note.
_COPY_GROUPS = (
    FormFieldGroup("What", ("game", "release", "format"), look="hidden"),
    FormFieldGroup("How you have it", ("access", "acquired"), look="hidden"),
    FormFieldGroup("Note", ("note",), look="hidden"),
)


def copy_groups(form: forms.Form) -> list[FormFieldGroup]:
    """Each group, less absent fields."""
    return [
        group._replace(
            fields=tuple(name for name in group.fields if name in form.fields)
        )
        for group in _COPY_GROUPS
    ]


def release_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    """Resolve Release ids to picker options."""
    releases = (
        Release.objects.visible_to(library)
        .filter(pk__in=values)
        .select_related("edition", "platform")
    )
    return [
        {"value": str(release.pk), "label": release_label(release), "data": {}}
        for release in releases
    ]


def _entry_release_options(
    values, *, entry: LibraryEntry, library: UserLibrary
) -> list[SearchSelectOption]:
    """The row's own Release; others read."""
    if {str(value) for value in values} == {str(entry.release_id)}:
        return [
            {
                "value": str(entry.release_id),
                "label": release_label(entry.release),
                "data": {},
            }
        ]
    return release_options(values, library=library)


def end_seen(entry: LibraryEntry) -> str:
    """The rendered end, correction included."""
    marker = entry.access_end_recorded_at
    if marker is None:
        return ""
    stated_end = "\x1f".join(
        (
            marker.isoformat(),
            entry.access_end_way,
            str(entry.access_ended),
            entry.access_end_note,
        )
    )
    return hashlib.sha256(stated_end.encode()).hexdigest()


def _day(today: datetime.date) -> TemporalValue:
    return TemporalValue.from_day(today)


def _release_field(
    library: UserLibrary, params: ParamSources, *, create: bool
) -> forms.ModelChoiceField:
    return forms.ModelChoiceField(
        queryset=Release.objects.visible_to(library),
        label="Version",
        widget=SearchSelectWidget(
            search_url=RELEASE_SEARCH_URL,
            options_resolver=partial(release_options, library=library),
            create=(
                PostCreate(RELEASE_CREATE_URL, verb="Create release")
                if create
                else None
            ),
            params=params,
            commit_sole_option=True,
            placeholder="Search platforms…",
        ),
    )


def normalised_note(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


class _SeenEnd(forms.Form):
    """Refuses an end moved since rendering."""

    #: The end this page showed.
    access_end_seen = forms.CharField(required=False, widget=forms.HiddenInput)

    entry: LibraryEntry

    def _refuse_a_moved_end(self, cleaned: dict[str, Any]) -> None:
        if (cleaned.get("access_end_seen") or "") != end_seen(self.entry):
            self.add_error(None, CHANGED_SINCE_OPENED)


type SubmissionNoun = Literal["copy", "purchase"]
type SubmissionAct = Literal["add", "end", "resume", "refund"]


def page_key(
    noun: SubmissionNoun, act: SubmissionAct, token: uuid.UUID
) -> IdempotencyKey:
    return f"{noun}-{act}-{token}"


def one_click_key(
    noun: SubmissionNoun, act: SubmissionAct, token: uuid.UUID
) -> IdempotencyKey:
    return f"{noun}-{act}-now-{token}"


class _Submission(forms.Form):
    #: One key per page; a resubmit replays.
    submission = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid7)

    noun: SubmissionNoun = "copy"
    act: SubmissionAct

    def submission_key(self) -> IdempotencyKey:
        return page_key(self.noun, self.act, self.cleaned_data["submission"])

    def _replays(self, library: UserLibrary) -> bool:
        """This press already ran; dispatch replays."""
        submission = self.cleaned_data.get("submission")
        return submission is not None and key_answered(
            library, page_key(self.noun, self.act, submission)
        )


class EntryAddForm(PrimitiveWidgetsMixin, _Submission, forms.Form):
    """One copy; the Game fixed or picked."""

    act: SubmissionAct = "add"

    access = forms.ChoiceField(
        choices=EntryAccess.choices, initial=EntryAccess.OWNED, label="Got it as"
    )
    format = forms.ChoiceField(
        choices=EntryFormat.choices,
        initial=EntryFormat.DIGITAL,
        widget=RadioListWidget,
    )
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        game: Game | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        self.game = game
        params: ParamSources
        if game is None:
            self.fields["game"] = SingleGameChoiceField(
                queryset=Game.objects.visible_to(library).in_display_order(),
                label="Game",
                widget=SearchSelectWidget(
                    search_url=GAME_SEARCH_URL,
                    options_resolver=partial(_game_options, library=library),
                    autofocus=True,
                ),
            )
            params = {"game_id": {"field": self.add_prefix("game")}}
            create = True
        else:
            params = {"game_id": {"value": str(game.pk)}}
            create = game.library_id == library.pk
            #: The default Release reads first.
            default = game_releases(library, game).first()
            if default is not None and "release" not in self.initial:
                self.initial["release"] = default.pk
        self.fields["release"] = _release_field(library, params, create=create)
        self.fields["acquired"] = TemporalFormField(
            presentation=presentation, label="Got it on", initial=_day(today)
        )
        self.order_fields(["game", "release", "format", "access", "acquired", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        release = cast(Release | None, cleaned.get("release"))
        game = self.game or cleaned.get("game")
        if (
            release is not None
            and game is not None
            and release.edition.game_id != game.pk
        ):
            self.add_error("release", RELEASE_OF_ANOTHER_GAME)
        return cleaned

    def draft(self) -> EntryStatement:
        """What the creation states."""
        cleaned = self.cleaned_data
        return EntryStatement(
            release_id=cleaned["release"].pk,
            access=cleaned["access"],
            format=cleaned["format"],
            note=cleaned["note"],
            acquired=ActStatement(cleaned["acquired"], ""),
        )


class EntryEditForm(PrimitiveWidgetsMixin, forms.Form):
    """A copy's facts and its acquisition restated."""

    access = forms.TypedChoiceField(
        choices=EntryAccess.choices, coerce=EntryAccess, label="Got it as"
    )
    format = forms.TypedChoiceField(
        choices=EntryFormat.choices, coerce=EntryFormat, widget=RadioListWidget
    )
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        entry: LibraryEntry,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        initial: dict[str, Any] = {
            "release": entry.release_id,
            "access": entry.access,
            "format": entry.format,
            "note": entry.note,
            "acquired": entry.acquired,
        }
        kwargs["initial"] = initial | dict(kwargs.get("initial") or {})
        super().__init__(*args, **kwargs)
        self.entry = entry
        game = entry.player_game.game
        self.fields["release"] = _release_field(
            library,
            {"game_id": {"value": str(game.pk)}},
            create=game.library_id == library.pk,
        )
        self.fields["release"].widget.options_resolver = partial(
            _entry_release_options, entry=entry, library=library
        )
        self.fields["acquired"] = TemporalFormField(
            presentation=presentation, label="Got it on"
        )
        self.order_fields(["release", "format", "access", "acquired", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        release = cast(Release | None, cleaned.get("release"))
        if (
            release is not None
            and release.edition.game_id != self.entry.player_game.game_id
        ):
            self.add_error("release", RELEASE_OF_ANOTHER_GAME)
        return cleaned

    def acquired(self) -> ActStatement | Keep:
        """The acquisition, where the day moved."""
        when = self.cleaned_data["acquired"]
        if when == self.entry.acquired:
            return KEEP
        return ActStatement(when, self.entry.acquisition_note)


class EntryEndForm(PrimitiveWidgetsMixin, _Submission, _SeenEnd, forms.Form):
    """Access to a held copy ended."""

    act: SubmissionAct = "end"

    way = forms.ChoiceField(choices=WAY_CHOICES, label="What happened")
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        entry: LibraryEntry,
        presentation: DateTimePresentation,
        today: datetime.date,
        **kwargs,
    ):
        kwargs["initial"] = {"access_end_seen": end_seen(entry)} | dict(
            kwargs.get("initial") or {}
        )
        super().__init__(*args, **kwargs)
        self.entry = entry
        self.fields["ended"] = TemporalFormField(
            presentation=presentation, label="When", initial=_day(today)
        )
        self.order_fields(["way", "ended", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None and not self._replays(self.entry.library):
            self._refuse_a_moved_end(cleaned)
        return cleaned

    def statement(self) -> WayActStatement:
        cleaned = self.cleaned_data
        return WayActStatement(
            cleaned["ended"], EndWay(cleaned["way"]), cleaned["note"]
        )


class EntryResumeForm(PrimitiveWidgetsMixin, _Submission, _SeenEnd, forms.Form):
    """Access to an ended copy resumed."""

    act: SubmissionAct = "resume"

    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        entry: LibraryEntry,
        presentation: DateTimePresentation,
        today: datetime.date,
        **kwargs,
    ):
        kwargs["initial"] = {"access_end_seen": end_seen(entry)} | dict(
            kwargs.get("initial") or {}
        )
        super().__init__(*args, **kwargs)
        self.entry = entry
        self.fields["resumed"] = TemporalFormField(
            presentation=presentation, label="When", initial=_day(today)
        )
        self.order_fields(["resumed", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None and not self._replays(self.entry.library):
            self._refuse_a_moved_end(cleaned)
        return cleaned

    def statement(self) -> ActStatement:
        cleaned = self.cleaned_data
        return ActStatement(cleaned["resumed"], cleaned["note"])


class EntryEndEditForm(PrimitiveWidgetsMixin, _SeenEnd, forms.Form):
    """A standing end restated."""

    way = forms.ChoiceField(choices=WAY_CHOICES, label="What happened")
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        entry: LibraryEntry,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        ended = stated(entry, ENTRY_ACCESS_END)
        if ended is None:
            raise ValueError("Only an ended copy's end is edited.")
        kwargs["initial"] = {
            "way": ended.way,
            "ended": ended.when,
            "note": ended.note,
            "access_end_seen": end_seen(entry),
        } | dict(kwargs.get("initial") or {})
        super().__init__(*args, **kwargs)
        self.entry = entry
        self.fields["ended"] = TemporalFormField(
            presentation=presentation, label="When"
        )
        self.order_fields(["way", "ended", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None:
            self._refuse_a_moved_end(cleaned)
        return cleaned

    def access_end(self) -> WayActStatement:
        """The restated end."""
        cleaned = self.cleaned_data
        return WayActStatement(
            cleaned["ended"], EndWay(cleaned["way"]), cleaned["note"]
        )
