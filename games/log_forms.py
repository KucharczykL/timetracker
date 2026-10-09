"""Form for one Log a game press."""

import datetime
from functools import partial
from typing import Any, ClassVar, Final, cast

from django import forms
from django.db.models import Q

from common.components import PostCreate
from common.date_time_presentation import DateTimePresentation
from common.opener_facts import OpenerFacts, OpenerFactsMixin
from games.catalog_release import platform_refusal
from games.commands.endpoint import ActStatement, certainly_reversed
from games.entry_forms import Submission, SubmissionKind
from games.forms import (
    DEVICE_CREATE_URL,
    DEVICE_SEARCH_URL,
    DURATION_PARTS,
    NEW_GAME,
    NEW_PLATFORM,
    PLATFORM_CREATE_URL,
    PLATFORM_SEARCH_URL,
    DatePickerWidget,
    HoursMinutesField,
    PrimitiveWidgetsMixin,
    RadioListWidget,
    SearchSelectWidget,
    SingleGameChoiceField,
    TemporalFormField,
    _game_options,
    apply_primitive_widget_classes,
    device_field,
    device_options,
    platform_options,
)
from games.models import (
    Device,
    Game,
    Platform,
    PlayerGameStatus,
    Playthrough,
    UserLibrary,
)
from games.reads.log_game import HeldFacts, copy_release_for, held_facts
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.reads.playthrough_runs import library_runs
from games.reads.releases import UNSPECIFIED_PLATFORM
from games.writes.endpoint import KEEP, Keep, Restated
from games.writes.log_game import HistoricalHours, LogStatement, SessionTiming
from timetracker.temporal import TemporalValue

GAME_SEARCH_URL: Final = "/api/games/search"

#: Sentence each refusal states, for the page.
DATES_REVERSED = "This run finished before it started. Check the days."
DAY_REQUIRED = "Give the day you played."
ZERO_DURATION = "Give a duration above zero."
REMOVED_GAME = "This game is removed from your library. Restore it instead."
ANOTHER_GAMES_RUN = "That playthrough is another game's."

PLAYTIME_KINDS: Final = (("session", "Session"), ("historical", "Historical playtime"))
#: Status an untracked game shows.
UNTRACKED_STATUS: Final = PlayerGameStatus.UNPLAYED
STATUS_CHOICES: Final = tuple(
    (status.value, status.label) for status in PlayerGameStatus
)


def _canonical(value: TemporalValue | None) -> str:
    return "" if value is None or value.canonical is None else value.canonical


def normalised_note(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


class LogGameForm(OpenerFactsMixin, PrimitiveWidgetsMixin, Submission):
    """One Log a game press, as posted.

    Each `*_seen` field posts what the page showed. A field equal to its
    seen value states nothing, so an unchanged word keeps the status an
    act implies.
    """

    opener_fields = ("game",)
    kind: ClassVar[SubmissionKind] = "log"

    status_seen = forms.ChoiceField(
        required=False,
        choices=(("", ""), *STATUS_CHOICES),
        widget=forms.HiddenInput,
    )
    platform_seen = forms.CharField(required=False, widget=forms.HiddenInput)
    started_seen = forms.CharField(required=False, widget=forms.HiddenInput)
    completed_seen = forms.CharField(required=False, widget=forms.HiddenInput)
    run = forms.ModelChoiceField(
        queryset=Playthrough.objects.none(), required=False, widget=forms.HiddenInput
    )
    #: Count of playtimes written; keys each.
    attempt = forms.IntegerField(
        required=False, min_value=0, initial=0, widget=forms.HiddenInput
    )
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
    note_seen = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        facts: OpenerFacts | None = None,
        held: HeldFacts | None = None,
        prefill: Game | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        self.fields["game"] = SingleGameChoiceField(
            # Removed games stay; refusals name them.
            queryset=Game.objects.filter(
                Q(library__isnull=True) | Q(library=library)
            ).in_display_order(),
            label="Game",
            widget=SearchSelectWidget(
                search_url=GAME_SEARCH_URL,
                options_resolver=partial(_game_options, library=library),
                autofocus=True,
                dialog_create=NEW_GAME,
            ),
        )
        self.state_opener_facts(facts)
        if prefill is not None and "game" not in self.facts:
            self.initial["game"] = prefill.pk
        self.fields["status"] = forms.ChoiceField(
            choices=STATUS_CHOICES,
            initial=UNTRACKED_STATUS.value,
            label="Status",
        )
        # TODO(#1604): restrict it to the game's platforms.
        self.fields["platform"] = forms.ModelChoiceField(
            queryset=Platform.objects.visible_to(library),
            required=False,
            label="Platform",
            widget=SearchSelectWidget(
                search_url=PLATFORM_SEARCH_URL,
                options_resolver=partial(platform_options, library=library),
                create=PostCreate(PLATFORM_CREATE_URL),
                dialog_create=NEW_PLATFORM,
                none_label=UNSPECIFIED_PLATFORM,
                revert_on_leave=True,
            ),
        )
        self.fields["started"] = TemporalFormField(
            presentation=presentation, label="Started on"
        )
        self.fields["completed"] = TemporalFormField(
            presentation=presentation, label="Finished on"
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
        runs = cast(forms.ModelChoiceField, self.fields["run"])
        runs.queryset = library_runs(library)
        device_field(self, library=library, held=None)
        if held is not None:
            self._seed(held)
        default_device = library.preferences.default_device
        if default_device is not None:
            self.initial.setdefault("device", default_device.pk)
        apply_primitive_widget_classes(
            {name: self.fields[name] for name in ("status", "day", "playtime_kind")}
        )
        self.order_fields(
            [
                "game",
                "status",
                "platform",
                "started",
                "completed",
                "playtime_kind",
                "day",
                "duration",
                "device",
                "mastered",
                "note",
            ]
        )

    def _seed(self, held: HeldFacts) -> None:
        """Held state and the seen values."""
        shown = UNTRACKED_STATUS if held.status is None else held.status
        self.initial["status"] = shown.value
        self.initial["status_seen"] = shown.value
        platform = held.platform
        self.initial["platform"] = None if platform is None else platform.pk
        self.initial["platform_seen"] = "" if platform is None else str(platform.pk)
        run = held.run
        if run is not None:
            started = stated_start(run)
            completed = stated_completion(run)
            started_when = None if started is None else started.when
            completed_when = None if completed is None else completed.when
            self.initial["run"] = run.pk
            self.initial["started"] = started_when
            self.initial["completed"] = completed_when
            self.initial["started_seen"] = _canonical(started_when)
            self.initial["completed_seen"] = _canonical(completed_when)
            self.initial["note"] = run.note
            self.initial["note_seen"] = run.note
        self.initial["mastered"] = held.mastered
        self.initial["mastered_seen"] = held.mastered

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean_note_seen(self) -> str:
        return normalised_note(self.cleaned_data["note_seen"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        game: Game | None = cleaned.get("game")
        if game is not None:
            self._refuse_a_removed_game(game)
            self._refuse_a_platform(game, cleaned.get("platform"))
            self._refuse_a_run(game, cleaned.get("run"))
        # Empty field clears the endpoint.
        if certainly_reversed(
            earlier=cleaned.get("started"), later=cleaned.get("completed")
        ):
            self.add_error("completed", DATES_REVERSED)
        self._refuse_a_playtime(cleaned)
        return cleaned

    def _refuse_a_removed_game(self, game: Game) -> None:
        if held_facts(self.library, game).removed:
            self.add_error("game", REMOVED_GAME)

    def _refuse_a_platform(self, game: Game, platform: Platform | None) -> None:
        """Changed platform, no copy: needs a Release."""
        if "platform" in self.errors or platform is None:
            return
        if str(platform.pk) == self.cleaned_data.get("platform_seen"):
            return
        if copy_release_for(self.library, game, platform) is not None:
            return
        sentence = platform_refusal(game, platform)
        if sentence is not None:
            self.add_error("platform", sentence)

    def _refuse_a_run(self, game: Game, run: Playthrough | None) -> None:
        if run is not None and run.player_game.game_id != game.pk:
            self.add_error("run", ANOTHER_GAMES_RUN)

    def _duration_typed(self) -> bool:
        """Whether any duration box holds a value.

        A stated playtime is one whose boxes hold a number, zero included;
        an empty pair states no playtime.
        """
        return any(
            str(self.data.get(self.add_prefix(f"duration_{part.suffix}"), "")).strip()
            for part in DURATION_PARTS
        )

    def _refuse_a_playtime(self, cleaned: dict[str, Any]) -> None:
        if not self._duration_typed():
            return
        if "duration" not in self.errors and not cleaned.get("duration"):
            self.add_error("duration", ZERO_DURATION)
        if (
            cleaned.get("playtime_kind") != "historical"
            and "day" not in self.errors
            and cleaned.get("day") is None
        ):
            self.add_error("day", DAY_REQUIRED)

    def statement(self) -> LogStatement:
        """Valid form's statement; unchanged fields none."""
        cleaned = self.cleaned_data
        platform: Platform | None = cleaned.get("platform")
        run: Playthrough | None = cleaned.get("run")
        status_seen = cleaned.get("status_seen") or ""
        chosen = PlayerGameStatus(cleaned["status"])
        return LogStatement(
            game=cleaned["game"],
            platform_id=None if platform is None else platform.pk,
            platform_changed=(
                ("" if platform is None else str(platform.pk))
                != cleaned.get("platform_seen", "")
            ),
            run_id=None if run is None else run.pk,
            started=self._act("started", cleaned),
            completed=self._act("completed", cleaned),
            note=self._note(cleaned),
            playtime=self._playtime() if self._duration_typed() else None,
            attempt=cleaned.get("attempt") or 0,
            mastered=self._mastered(cleaned),
            status=KEEP if chosen.value == status_seen else chosen,
            seen_status=PlayerGameStatus(status_seen) if status_seen else None,
        )

    def _act(self, name: str, cleaned: dict[str, Any]) -> Restated[ActStatement]:
        """Changed day; None if cleared."""
        when: TemporalValue | None = cleaned.get(name)
        seen = cleaned.get(f"{name}_seen") or ""
        if when is None:
            return None if seen else KEEP
        if _canonical(when) == seen:
            return KEEP
        return ActStatement(when, "")

    def _note(self, cleaned: dict[str, Any]) -> str | Keep:
        note = cleaned.get("note", "")
        if note == cleaned.get("note_seen", ""):
            return KEEP
        return note

    def _playtime(self) -> SessionTiming | HistoricalHours:
        cleaned = self.cleaned_data
        device = cleaned.get("device")
        device_id = None if device is None else device.pk
        if cleaned["playtime_kind"] == "historical":
            return HistoricalHours(duration=cleaned["duration"], device_id=device_id)
        return SessionTiming(
            day=cleaned["day"], duration=cleaned["duration"], device_id=device_id
        )

    def _mastered(self, cleaned: dict[str, Any]) -> bool | Keep:
        mastered = bool(cleaned.get("mastered"))
        if mastered == bool(cleaned.get("mastered_seen")):
            return KEEP
        return mastered
