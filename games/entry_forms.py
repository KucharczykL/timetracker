"""The forms a copy is recorded, restated, ended and resumed with."""

import datetime
import uuid
from functools import partial
from typing import Any, cast

from django import forms

from common.components import PostCreate, SearchSelectOption
from common.components.search_select import ParamSources
from common.date_time_presentation import DateTimePresentation
from games.commands.endpoint import ActStatement, WayActStatement
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
from games.reads.releases import release_label
from games.writes.libraryentry import KEEP, EntryDraft, Keep
from timetracker.temporal import TemporalValue

RELEASE_SEARCH_URL = "/api/releases/search"
RELEASE_CREATE_URL = "/api/releases/"
GAME_SEARCH_URL = "/api/games/search"

CHANGED_SINCE_OPENED = (
    "This copy changed since you opened this page. Reload it and save again."
)
RELEASE_OF_ANOTHER_GAME = "Pick a release of the game you chose."

WAY_CHOICES = [(way.value, END_WAY_LABELS[way]) for way in ENTRY_WAYS]

#: Held states no end, and voids a standing one.
END_STATE_CHOICES = [("held", "Held"), ("ended", "Ended")]


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
    """The copy's own Release from the row; others read."""
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
    """The rendered end's marker, or empty while held."""
    marker = entry.access_end_recorded_at
    return "" if marker is None else marker.isoformat()


def _day(today: datetime.date) -> TemporalValue:
    return TemporalValue.from_day(today)


def _release_field(
    library: UserLibrary, params: ParamSources, *, create: bool
) -> forms.ModelChoiceField:
    return forms.ModelChoiceField(
        queryset=Release.objects.visible_to(library),
        label="Release",
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


def _note(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


class _SeenEnd(forms.Form):
    """Refuses a copy whose end moved since the page rendered."""

    #: The end this page showed.
    access_end_seen = forms.CharField(required=False, widget=forms.HiddenInput)

    entry: LibraryEntry

    def _refuse_a_moved_end(self, cleaned: dict[str, Any]) -> None:
        if (cleaned.get("access_end_seen") or "") != end_seen(self.entry):
            self.add_error(None, CHANGED_SINCE_OPENED)


class _Submission(forms.Form):
    #: One key per page; a resubmit replays.
    submission = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid7)

    act: str

    def submission_key(self) -> IdempotencyKey:
        """The act's key."""
        return f"copy-{self.act}-{self.cleaned_data['submission']}"

    def _replays(self, library: UserLibrary) -> bool:
        """This page's press already ran; the dispatch replays it."""
        submission = self.cleaned_data.get("submission")
        return submission is not None and key_answered(
            library, f"copy-{self.act}-{submission}"
        )


class EntryAddForm(PrimitiveWidgetsMixin, _Submission, forms.Form):
    """One copy recorded; the Game fixed or picked."""

    act = "add"

    access = forms.ChoiceField(choices=EntryAccess.choices, initial=EntryAccess.OWNED)
    format = forms.ChoiceField(choices=EntryFormat.choices, initial=EntryFormat.UNKNOWN)
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
                queryset=Game.objects.visible_to(library),
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
        self.fields["release"] = _release_field(library, params, create=create)
        self.fields["acquired"] = TemporalFormField(
            presentation=presentation, label="Acquired", initial=_day(today)
        )
        self.order_fields(["game", "release", "access", "format", "acquired", "note"])

    def clean_note(self) -> str:
        return _note(self.cleaned_data["note"])

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

    def draft(self) -> EntryDraft:
        """What the creation states."""
        cleaned = self.cleaned_data
        return EntryDraft(
            release_id=cleaned["release"].pk,
            access=cleaned["access"],
            format=cleaned["format"],
            note=cleaned["note"],
            acquired=ActStatement(cleaned["acquired"], ""),
        )


class EntryEditForm(PrimitiveWidgetsMixin, _SeenEnd, forms.Form):
    """A copy's facts, its acquisition and its end restated."""

    access = forms.ChoiceField(choices=EntryAccess.choices)
    format = forms.ChoiceField(choices=EntryFormat.choices)
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )
    end_state = forms.ChoiceField(
        choices=END_STATE_CHOICES, widget=RadioListWidget, label="Copy is"
    )
    way = forms.ChoiceField(choices=WAY_CHOICES, required=False, label="How it left")
    end_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="End note"
    )

    def __init__(
        self,
        *args,
        entry: LibraryEntry,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        **kwargs,
    ):
        ended = stated(entry, ENTRY_ACCESS_END)
        initial: dict[str, Any] = {
            "release": entry.release_id,
            "access": entry.access,
            "format": entry.format,
            "note": entry.note,
            "acquired": entry.acquired,
            "end_state": "held" if ended is None else "ended",
            "way": "" if ended is None else ended.way,
            "ended": _day(today) if ended is None else ended.when,
            "end_note": "" if ended is None else ended.note,
            "access_end_seen": end_seen(entry),
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
            presentation=presentation, label="Acquired"
        )
        self.fields["ended"] = TemporalFormField(
            presentation=presentation, label="Ended"
        )
        self.order_fields(
            [
                "release",
                "access",
                "format",
                "acquired",
                "note",
                "end_state",
                "way",
                "ended",
                "end_note",
            ]
        )

    def clean_note(self) -> str:
        return _note(self.cleaned_data["note"])

    def clean_end_note(self) -> str:
        return _note(self.cleaned_data["end_note"])

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
        if cleaned.get("end_state") == "ended" and not cleaned.get("way"):
            self.add_error("way", "Choose how the copy left.")
        self._refuse_a_moved_end(cleaned)
        return cleaned

    def acquired(self) -> ActStatement | Keep:
        """The acquisition, where the day moved."""
        when = self.cleaned_data["acquired"]
        if when == self.entry.acquired:
            return KEEP
        return ActStatement(when, self.entry.acquisition_note)

    def access_end(self) -> WayActStatement | None | Keep:
        """Held keeps a held copy and voids an ended one."""
        cleaned = self.cleaned_data
        if cleaned["end_state"] == "held":
            return KEEP if stated(self.entry, ENTRY_ACCESS_END) is None else None
        return WayActStatement(
            cleaned["ended"], EndWay(cleaned["way"]), cleaned["end_note"]
        )


class EntryEndForm(PrimitiveWidgetsMixin, _Submission, _SeenEnd, forms.Form):
    """Access to a held copy ended."""

    act = "end"

    way = forms.ChoiceField(choices=WAY_CHOICES, label="How it left")
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
            presentation=presentation, label="Ended", initial=_day(today)
        )
        self.order_fields(["way", "ended", "note"])

    def clean_note(self) -> str:
        return _note(self.cleaned_data["note"])

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

    act = "resume"

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
            presentation=presentation, label="Resumed", initial=_day(today)
        )
        self.order_fields(["resumed", "note"])

    def clean_note(self) -> str:
        return _note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None and not self._replays(self.entry.library):
            self._refuse_a_moved_end(cleaned)
        return cleaned

    def statement(self) -> ActStatement:
        cleaned = self.cleaned_data
        return ActStatement(cleaned["resumed"], cleaned["note"])
