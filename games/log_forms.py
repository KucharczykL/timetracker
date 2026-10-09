"""The form Log a game states one play from."""

import datetime
from collections.abc import Mapping
from functools import partial
from typing import Any, ClassVar, Final, cast

from django import forms

from common.components import PostCreate
from common.date_time_presentation import DateTimePresentation
from common.opener_facts import OpenerFacts, OpenerFactsMixin
from games.commands.endpoint import ActStatement, certainly_reversed
from games.entry_forms import CopyFields, Submission, SubmissionKind
from games.forms import (
    DEVICE_CREATE_URL,
    DEVICE_SEARCH_URL,
    NEW_GAME,
    CheckboxListWidget,
    DatePickerWidget,
    HoursMinutesField,
    PlaythroughSelectWidget,
    PrimitiveWidgetsMixin,
    RadioListWidget,
    SearchSelectWidget,
    SingleGameChoiceField,
    TemporalFormField,
    _game_options,
    apply_primitive_widget_classes,
    device_field,
    device_options,
    run_options,
)
from games.models import (
    Device,
    Game,
    PlayerGameStatus,
    Playthrough,
    UserLibrary,
)
from games.price_fields import ignore_fields
from games.reads.log_game import HeldFacts
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.reads.playthrough_runs import (
    library_runs,
    live_ordinary_runs,
    tracked_game,
)
from games.writes.log_game import (
    RUN_SECTIONS,
    SECTIONS,
    HistoricalHours,
    LogSection,
    LogStatement,
    SessionTiming,
)
from timetracker.temporal import TemporalValue

GAME_SEARCH_URL: Final = "/api/games/search"

#: Literal, so Tailwind finds them. A tick shows its line, hides its summary.
TICKED_SHOWN: Final[Mapping[LogSection, str]] = {
    "copy": "hidden group-has-[[value=copy]:checked]/log:flex",
    "dates": "hidden group-has-[[value=dates]:checked]/log:flex",
    "playtime": "hidden group-has-[[value=playtime]:checked]/log:flex",
    "more": "hidden group-has-[[value=more]:checked]/log:flex",
}
SUMMARY_HIDDEN: Final[Mapping[LogSection, str]] = {
    "copy": "group-has-[[value=copy]:checked]/log:hidden",
    "dates": "group-has-[[value=dates]:checked]/log:hidden",
    "playtime": "group-has-[[value=playtime]:checked]/log:hidden",
    "more": "group-has-[[value=more]:checked]/log:hidden",
}
#: The run picker shows while any section that names a run is ticked.
RUN_ROW_SHOWN: Final = "hidden group-has-[:is([value=dates],[value=playtime],[value=more]):checked]/log:flex"

SECTION_LABELS: Final[Mapping[LogSection, str]] = {
    "copy": "Copy and price",
    "dates": "Dates",
    "playtime": "Playtime",
    "more": "Mastered and note",
}
#: The copy tick, where the game already holds a copy.
ANOTHER_COPY_LABEL: Final = "Another copy"

COPY_FIELDS: Final = (
    "release",
    "access",
    "format",
    "acquired",
    "price",
    "amount",
    "currency",
)
PLAYTIME_FIELDS: Final = ("playtime_kind", "day", "duration", "device")

PLAYTIME_KINDS: Final = (("session", "Session"), ("historical", "Historical playtime"))

DATES_REVERSED = "This run finished before it started. Check the days."
PICK_A_RUN = "This game holds several playthroughs. Pick the one this is for."
ANOTHER_GAMES_RUN = "That playthrough is another game's."
DAY_REQUIRED = "Give the day you played."
ZERO_DURATION = "Give a duration above zero."


def _canonical(value: TemporalValue | None) -> str:
    return "" if value is None or value.canonical is None else value.canonical


class LogGameForm(OpenerFactsMixin, PrimitiveWidgetsMixin, Submission, CopyFields):
    """One press of Log a game: a copy, dates, a playtime, a status.

    Every section is optional. A section's fields are checked only
    when its tick is set; an unticked section's errors are dropped,
    since its hidden fields post anyway.
    """

    opener_fields = ("game",)
    kind: ClassVar[SubmissionKind] = "log"

    sections = forms.MultipleChoiceField(
        required=False, widget=CheckboxListWidget, label="Add"
    )
    #: Sections an earlier press of this page wrote; they are not offered again.
    saved = forms.MultipleChoiceField(
        required=False,
        widget=forms.MultipleHiddenInput,
        choices=[(section, section) for section in SECTIONS],
    )
    playthrough = forms.ModelChoiceField(
        queryset=Playthrough.objects.none(),
        required=False,
        widget=PlaythroughSelectWidget(game_field="game"),
        label="Playthrough",
    )
    started_seen = forms.CharField(required=False, widget=forms.HiddenInput)
    completed_seen = forms.CharField(required=False, widget=forms.HiddenInput)
    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        widget=SearchSelectWidget(
            search_url=DEVICE_SEARCH_URL,
            options_resolver=device_options,
            create=PostCreate(DEVICE_CREATE_URL),
            none_label="No device",
        ),
    )
    mastered = forms.BooleanField(required=False, label="Mastered")
    mastered_seen = forms.BooleanField(required=False, widget=forms.HiddenInput)
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        facts: OpenerFacts | None = None,
        held: HeldFacts | None = None,
        **kwargs,
    ):
        super().__init__(*args, user=library.user, **kwargs)
        self.library = library
        self.fields["game"] = SingleGameChoiceField(
            queryset=Game.objects.visible_to(library).in_display_order(),
            label="Game",
            widget=SearchSelectWidget(
                search_url=GAME_SEARCH_URL,
                options_resolver=partial(_game_options, library=library),
                autofocus=True,
                dialog_create=NEW_GAME,
            ),
        )
        self.state_opener_facts(facts)
        game = self.stated("game", Game)
        self.install_copy_fields(
            library=library,
            presentation=presentation,
            today=today,
            game_field="game",
            game=game,
        )
        self.fields["started"] = TemporalFormField(
            presentation=presentation, label="Started"
        )
        self.fields["completed"] = TemporalFormField(
            presentation=presentation, label="Finished"
        )
        self.fields["day"] = forms.DateField(
            required=False,
            initial=today,
            widget=DatePickerWidget(presentation=presentation, label="Day"),
        )
        self.fields["playtime_kind"] = forms.ChoiceField(
            choices=PLAYTIME_KINDS,
            initial="session",
            widget=RadioListWidget,
            label="Kind",
        )
        self.fields["duration"] = HoursMinutesField(label="Duration")
        self.fields["status"] = forms.ChoiceField(
            required=False,
            label="Status",
            choices=[
                ("", _status_none_label(held)),
                *((status.value, status.label) for status in PlayerGameStatus),
            ],
        )
        self._offer_sections(held)
        runs = cast(forms.ModelChoiceField, self.fields["playthrough"])
        runs.queryset = library_runs(library)
        runs.widget.options_resolver = partial(run_options, library=library)
        device_field(self, library=library, held=None)
        if held is not None:
            self._seed(held)
        default_device = library.preferences.default_device
        if default_device is not None:
            self.initial.setdefault("device", default_device.pk)
        #: Widgets were stamped at build; `required` reaches them too.
        for name in ("release", "access", "format", "price", "acquired", "day"):
            _unrequire(self.fields[name])
        apply_primitive_widget_classes(
            {name: self.fields[name] for name in ("status", "day", "playtime_kind")}
        )
        self.order_fields(
            [
                "game",
                "status",
                "sections",
                "saved",
                "release",
                "format",
                "access",
                "acquired",
                "price",
                "amount",
                "currency",
                "playthrough",
                "started",
                "completed",
                "started_seen",
                "completed_seen",
                "playtime_kind",
                "day",
                "duration",
                "device",
                "mastered",
                "mastered_seen",
                "note",
            ]
        )

    def saved_sections(self) -> frozenset[LogSection]:
        if not self.is_bound:
            return frozenset()
        posted = self.fields["saved"].widget.value_from_datadict(
            self.data, self.files, self.add_prefix("saved")
        )
        return frozenset(
            cast(LogSection, value) for value in (posted or []) if value in SECTIONS
        )

    def _offer_sections(self, held: HeldFacts | None) -> None:
        """Each section a press has not yet written, its copy label read."""
        labels = dict(SECTION_LABELS)
        if held is not None and held.platform is not None:
            labels["copy"] = ANOTHER_COPY_LABEL
        saved = self.saved_sections()
        cast(forms.MultipleChoiceField, self.fields["sections"]).choices = [
            (section, labels[section]) for section in SECTIONS if section not in saved
        ]

    def _seed(self, held: HeldFacts) -> None:
        """What a fixed game holds, as the form's first state."""
        run = held.run
        if run is not None:
            started = stated_start(run)
            completed = stated_completion(run)
            started_when = None if started is None else started.when
            completed_when = None if completed is None else completed.when
            self.initial["playthrough"] = run.pk
            self.initial["started"] = started_when
            self.initial["completed"] = completed_when
            self.initial["started_seen"] = _canonical(started_when)
            self.initial["completed_seen"] = _canonical(completed_when)
            self.initial["note"] = run.note
        self.initial["mastered"] = held.mastered
        self.initial["mastered_seen"] = held.mastered

    def clean_note(self) -> str:
        return self.cleaned_data["note"].replace("\r\n", "\n").strip()

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        ticked = self._ticked()
        self._drop_unticked(ticked)
        if "copy" in ticked:
            self._refuse_an_empty_copy(cleaned)
            self.refuse_release_of_other_game(cleaned.get("game"))
        if "dates" in ticked and certainly_reversed(
            earlier=cleaned.get("started"), later=cleaned.get("completed")
        ):
            self.add_error("completed", DATES_REVERSED)
        if "playtime" in ticked:
            self._refuse_a_playtime(cleaned)
        if ticked & RUN_SECTIONS:
            self._refuse_a_run(cleaned)
        return cleaned

    def _ticked(self) -> frozenset[LogSection]:
        return frozenset(
            cast(LogSection, value)
            for value in (self.cleaned_data.get("sections") or ())
        )

    def _drop_unticked(self, ticked: frozenset[LogSection]) -> None:
        if "copy" not in ticked:
            ignore_fields(self, *COPY_FIELDS)
        if "dates" not in ticked:
            ignore_fields(self, "started", "completed")
        if "playtime" not in ticked:
            ignore_fields(self, *PLAYTIME_FIELDS)
        if not ticked & RUN_SECTIONS:
            ignore_fields(self, "playthrough")

    def _refuse_an_empty_copy(self, cleaned: dict[str, Any]) -> None:
        for name in ("release", "access", "format"):
            if not cleaned.get(name) and name not in self.errors:
                self.add_error(name, forms.Field.default_error_messages["required"])
        if not cleaned.get("price") and "price" not in self.errors:
            self.add_error("price", forms.Field.default_error_messages["required"])

    def _refuse_a_playtime(self, cleaned: dict[str, Any]) -> None:
        if cleaned.get("playtime_kind") == "historical":
            ignore_fields(self, "day")
        elif "day" not in self.errors and cleaned.get("day") is None:
            self.add_error("day", DAY_REQUIRED)
        if "duration" not in self.errors and not cleaned.get("duration"):
            self.add_error("duration", ZERO_DURATION)

    def _refuse_a_run(self, cleaned: dict[str, Any]) -> None:
        game: Game | None = cleaned.get("game")
        run: Playthrough | None = cleaned.get("playthrough")
        if game is None:
            return
        if run is not None:
            if run.player_game.game_id != game.pk:
                self.add_error("playthrough", ANOTHER_GAMES_RUN)
            return
        tracked = tracked_game(self.library, game)
        if (
            tracked is not None
            and "playthrough" not in self.errors
            and live_ordinary_runs(self.library, tracked).count() > 1
        ):
            self.add_error("playthrough", PICK_A_RUN)

    def statement(self) -> LogStatement:
        """What the valid form states; each part only where ticked."""
        cleaned = self.cleaned_data
        ticked = self._ticked()
        run: Playthrough | None = cleaned.get("playthrough")
        copy_ticked = "copy" in ticked
        return LogStatement(
            game=cleaned["game"],
            sections=ticked,
            copy=self.copy_statement("") if copy_ticked else None,
            purchase=self.copy_purchase_draft("") if copy_ticked else None,
            run_id=None if run is None else run.pk,
            started=self._act("started", "started_seen") if "dates" in ticked else None,
            completed=(
                self._act("completed", "completed_seen") if "dates" in ticked else None
            ),
            note=cleaned["note"] if "more" in ticked else None,
            playtime=self._playtime() if "playtime" in ticked else None,
            mastered=self._mastered() if "more" in ticked else None,
            status=(
                PlayerGameStatus(cleaned["status"]) if cleaned.get("status") else None
            ),
        )

    def _act(self, name: str, seen_name: str) -> ActStatement | None:
        """The day, where it differs from the one the page showed."""
        when: TemporalValue | None = self.cleaned_data.get(name)
        if when is None or _canonical(when) == self.cleaned_data.get(seen_name, ""):
            return None
        return ActStatement(when, "")

    def _playtime(self) -> SessionTiming | HistoricalHours:
        cleaned = self.cleaned_data
        device = cleaned.get("device")
        device_id = None if device is None else device.pk
        if cleaned["playtime_kind"] == "historical":
            return HistoricalHours(duration=cleaned["duration"], device_id=device_id)
        return SessionTiming(
            day=cleaned["day"], duration=cleaned["duration"], device_id=device_id
        )

    def _mastered(self) -> bool | None:
        cleaned = self.cleaned_data
        mastered = bool(cleaned["mastered"])
        if mastered == bool(cleaned.get("mastered_seen")):
            return None
        return mastered


def _status_none_label(held: HeldFacts | None) -> str:
    """The status row reads what the game already holds."""
    if held is None or held.status is None:
        return "Leave as is"
    return f"Leave as is: {held.status.label}"


def _unrequire(field: forms.Field) -> None:
    """A copy's fields are checked only where the copy is ticked."""
    field.required = False
    field.widget.is_required = False
