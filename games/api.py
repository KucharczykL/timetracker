import json
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Final, NoReturn, assert_never, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    DateTimeField,
    F,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.http import HttpResponse
from django.urls import reverse
from django.utils.timezone import now as django_timezone_now
from ninja import Field, Header, NinjaAPI, Query, Router, Schema, Status
from ninja.errors import HttpError
from ninja.security import django_auth
from pydantic import (
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from common.criteria import FilterError, filter_from_json
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import execute_filter, regex_timeout_api
from games.api_creation import RowRefused, created_by_form
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    StatedDevice,
    TimedTiming,
    TimingStatement,
)
from games.commands.playthrough import ActStatement
from games.events.dispatch import IDEMPOTENCY_KEY_MAX_LENGTH, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.filters import (
    MODE_PARSERS,
    filter_for_model,
    filter_query_context_for_library,
    filter_queryset_for_library,
    parse_historical_playtime_filter,
    parse_session_filter,
)
from games.formatting import zone_label
from games.forms import DeviceForm, PlatformForm, game_option_data
from games.models import (
    Device,
    FilterPreset,
    Game,
    HistoricalPlaytime,
    Platform,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    Purchase,
    PurchaseConversionState,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.calendar import calendar_day_zone, calendar_sentence
from games.reads.historical_playtime_page import listed_records
from games.reads.player_sessions import readable_sessions
from games.reads.playthrough_endpoints import days_to_finish
from games.reads.playthrough_numbering import display_name, with_display_number
from games.reads.playthrough_runs import library_runs
from games.removal import remove
from games.sorting import (
    HISTORICAL_PLAYTIME_DEFAULT_SORT,
    HISTORICAL_PLAYTIME_SORTS,
    MODE_SORTS,
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
    parse_per_page_override,
)
from games.writes.answers import CommandFailed, answered
from games.writes.playergame import new_correlation_id, record_facts
from games.writes.playersession import (
    SessionDraft,
    correct_session,
    describe_session,
    move_session,
    record_session,
)
from games.writes.playthrough import (
    RunDraft,
    record_named_run,
    record_run,
    remove_run,
    restate_run,
)
from timetracker.config import SettingSource
from timetracker.settings_commands import (
    SettingLockedError,
    SettingMutation,
    SettingNamespace,
    change_library_default_device,
    change_site_setting,
    change_user_setting,
)
from timetracker.settings_registry import (
    DISPLAY_TIME_ZONE_CHOICES,
    SETTINGS_REGISTRY,
    SettingKey,
    SettingScope,
    UnregisteredSettingError,
    get_definition,
)
from timetracker.settings_resolver import (
    resolve_for_user_with_origin,
    resolve_with_origin,
)
from timetracker.temporal import TemporalValue
from timetracker.uuidv7 import UUIDv7

logger = logging.getLogger("games")

api = NinjaAPI(auth=django_auth)


@api.exception_handler(CommandFailed)
def _command_failed(request, failure: CommandFailed):
    #: The message rides the middleware's header.
    #: The status code reverts the optimistic label.
    messages.error(request, failure.message)
    return api.create_response(
        request, {"detail": failure.message}, status=failure.status_code
    )


def _stated_temporal(value: object) -> object:
    """Build the value a canonical string names.

    TemporalValueParseError is a ValueError, so pydantic
    answers 422.
    """
    if value is None or isinstance(value, TemporalValue):
        return value
    if isinstance(value, str):
        return TemporalValue(value)
    raise ValueError("A date is stated as a string.")


#: A canonical temporal value: 2026-03, 202X, 2026-03-04~.
#:
#: The schema is stated by hand, because pydantic reads the
#: dataclass otherwise and asks a request for its fields.
type StatedTemporal = Annotated[
    TemporalValue | None,
    BeforeValidator(_stated_temporal),
    PlainSerializer(lambda value: None if value is None else value.serialize()),
    WithJsonSchema(
        {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "examples": ["2026-03-04", "2026-03", "202X", "2024-01/..", "2026-03-04~"],
        }
    ),
]

playthrough_router = Router()
game_router = Router()
device_router = Router()
platform_router = Router()
library_router = Router()

NOW_FACTORY = django_timezone_now
PAGE_SIZE = 10


class GameStatusUpdate(Schema):
    #: The enum, so Ninja refuses unknown members.
    status: PlayerGameStatus


class PlaythroughIn(Schema):
    #: An unknown key is a mistake, not silence.
    model_config = ConfigDict(extra="forbid")

    game_id: UUIDv7
    started: StatedTemporal = None
    completed: StatedTemporal = None
    note: str = ""
    name: str = ""

    @model_validator(mode="after")
    def one_statement(self) -> PlaythroughIn:
        """A name states a run; an act states one too.

        The two write paths this body chooses between state
        different facts, and the name is read first. A body
        stating both would record the name alone, so it is
        refused rather than half read.
        """
        if self.name and (self.started or self.completed or self.note):
            raise ValueError(
                "A named run states no act. Send the name alone, or send "
                "the acts and the note without a name."
            )
        return self


class CreatedRow(Schema):
    """The row a create route made, as a picker reads it.

    One answer for every create route, because one element
    reads them all.
    """

    id: str
    label: str


class UpdatePlaythroughIn(Schema):
    #: An unknown key is a mistake, not silence.
    model_config = ConfigDict(extra="forbid")

    started: StatedTemporal = None
    completed: StatedTemporal = None
    note: str = ""


class PlaythroughOut(Schema):
    """One run, as the projection states it."""

    id: UUIDv7
    game: str = Field(..., alias="player_game.game.name")
    game_id: UUIDv7 = Field(..., alias="player_game.game.id")
    name: str
    #: What a screen calls the run: its name, else "Playthrough N".
    display_name: str
    note: str
    started: str | None
    started_lower: date | None
    started_upper: date | None
    start_recorded_at: datetime | None
    start_note: str
    completed: str | None
    completed_lower: date | None
    completed_upper: date | None
    completion_recorded_at: datetime | None
    completion_note: str
    days_to_finish: int | None
    created_at: datetime

    @staticmethod
    def resolve_display_name(run: Playthrough) -> str:
        return display_name(run)

    @staticmethod
    def resolve_started(run: Playthrough) -> str | None:
        return None if run.started is None else run.started.serialize()

    @staticmethod
    def resolve_completed(run: Playthrough) -> str | None:
        return None if run.completed is None else run.completed.serialize()

    @staticmethod
    def resolve_days_to_finish(run: Playthrough) -> int | None:
        return days_to_finish(run)


# One schema per search endpoint rather than one shared by all three: each
# entity's option value is whatever that entity's primary key is, and those
# stop agreeing as the identity cutover promotes them one group at a time.
class GameOption(Schema):  # mirrors SearchSelectOption
    value: UUIDv7
    label: str
    data: dict


class PlatformOption(Schema):  # mirrors SearchSelectOption
    value: UUIDv7
    label: str
    data: dict


class PlaythroughOption(Schema):  # mirrors SearchSelectOption
    value: UUIDv7
    label: str
    data: dict


class DeviceOption(Schema):  # mirrors SearchSelectOption
    value: UUIDv7
    label: str
    data: dict


class StringOption(Schema):  # SearchSelectOption with a string value (e.g. group names)
    value: str
    label: str
    data: dict


@game_router.get("/search", response=list[GameOption])
def search_games(request, q: str = "", limit: int = 10):
    library = cast(User, request.user).library
    qs = (
        Game.objects.visible_to(library)
        .select_related("platform")
        .order_by("sort_name")
    )
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(library=library, sort_name__icontains=q)
        )
    return [
        {
            "value": g.id,
            "label": g.search_label,
            "data": game_option_data(g),
        }
        for g in qs[:limit]
    ]


@game_router.patch("/{game_id}/status", response={204: None})
def partial_update_game(request, game_id: UUIDv7, payload: GameStatusUpdate):
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
    record_facts(
        cast("User", request.user),
        game,
        status=payload.status,
        correlation_id=new_correlation_id(),
    )
    messages.success(request, "Status updated")
    return Status(204, None)


def _readable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """What the two GET routes answer about, each row numbered."""
    return with_display_number(library_runs(library)).select_related(
        "player_game__game"
    )


def _writable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """What PATCH and DELETE find.

    The read scope, less the run's own mark: RemovePlaythrough
    answers Unchanged for a run already removed, and a scope
    that hides it answers 404 instead. Every other narrowing
    is kept, so no route writes a run no route reads.
    """
    return Playthrough.objects.select_related("player_game__game").filter(
        library=library,
        player_game__library=library,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    )


@playthrough_router.get("/", response=list[PlaythroughOut])
def list_playthroughs(
    request,
    game: UUIDv7 | None = None,
    limit: int = Query(100, ge=0),
    offset: int = Query(0, ge=0),
):
    """The library's live ordinary runs, newest first.

    `game` narrows to one game's runs. `limit=0` is unbounded,
    as on presets. The order ends on the key, so an offset
    reads a stable page.
    """
    library = cast(User, request.user).library
    runs = _readable_runs(library)
    if game is not None:
        runs = runs.filter(player_game__game_id=game)
    runs = runs.order_by("-created_at", "id")[offset:]
    return runs if limit == 0 else runs[:limit]


@playthrough_router.post("/", response={201: CreatedRow})
def create_playthrough(request, payload: PlaythroughIn):
    """State one run at a game; answer the row it reached.

    Two write paths meet here, and the body says which. A
    name alone is the picker's create row, which states no
    act and adopts the placeholder a tracked game holds. A
    body that states an act is the add-run form, which
    keeps `record_run`'s own rule.
    """
    actor = cast(User, request.user)
    library = actor.library
    game = owned_or_404(Game.objects.for_library(library), library, id=payload.game_id)
    correlation_id = new_correlation_id()
    if payload.name:
        recorded = record_named_run(
            actor, game, payload.name, correlation_id=correlation_id
        )
    else:
        recorded = record_run(
            actor,
            game,
            RunDraft(
                #: Recording states both acts, dated or not.
                started=ActStatement(payload.started),
                completed=ActStatement(payload.completed),
                note=payload.note,
            ),
            correlation_id=correlation_id,
        )
    #: Read back before a word is said: a queued message rides the
    #: answer whatever its status, so a success stated ahead of a
    #: defect is a green toast over an empty field.
    with answered("playthrough"):
        row = _created_run(library, game, recorded.playthrough_id)
    if recorded.recorded:
        messages.success(request, "Playthrough recorded")
    else:
        #: The name was already at this game, so the answer is that
        #: run. Saying it was recorded would state a second one.
        messages.info(request, f"{row.label} is already at this game")
    if recorded.tracked_the_game:
        #: Tracking is an act of its own, so it is said.
        messages.info(request, f"{game} is now tracked in your library.")
    return Status(201, row)


def _created_run(
    library: UserLibrary, game: Game, playthrough_id: uuid.UUID
) -> CreatedRow:
    """The row a creation reached, as a picker reads it.

    Read whole and picked in Python: a queryset narrowed to
    one key counts the number over one row.
    """
    numbered = _readable_runs(library).filter(player_game__game_id=game.pk)
    for run in numbered:
        if run.pk == playthrough_id:
            return CreatedRow(id=str(run.pk), label=display_name(run))
    #: The row is this library's own, stated one act ago: absent here
    #: the row is wrong, not the statement, which is the defect the
    #: boundary records.
    raise RowUnreadable(
        f"Run {playthrough_id} at game {game.pk} was recorded in library "
        f"{library.pk} and no read of that game's runs answers it."
    )


@playthrough_router.get("/search", response=list[PlaythroughOption])
def search_playthroughs(request, game_id: UUIDv7, q: str = "", limit: int = 10):
    """One game's live ordinary runs, as picker options.

    Declared ahead of the route that reads a key, which
    would otherwise take `search` for one and answer 422.

    The list route answers `PlaythroughOut`, which states a
    `display_name` and no `value`, and reads no query. A
    picker cannot read it, and widening it would make one
    route answer two readers.

    The game is stated, unlike on the list: a picker offers
    the runs of the game a form names, never every run. It is
    `game_id`, as the creation body names it, because the picker
    reads one mapping for its query and its POST alike.
    """
    library = cast(User, request.user).library
    #: Narrowed on the partition the number counts over, so
    #: the rows keep the numbers the game's page shows. The
    #: query narrows further, and only ever to named rows: a
    #: blank name holds no text for `icontains` to find.
    runs = _readable_runs(library).filter(player_game__game_id=game_id)
    if q:
        runs = runs.filter(name__icontains=q)
    runs = runs.order_by("-created_at", "id")[:limit]
    return [{"value": run.id, "label": display_name(run), "data": {}} for run in runs]


@playthrough_router.get("/{playthrough_id}", response=PlaythroughOut)
def get_playthrough(request, playthrough_id: UUIDv7):
    library = cast(User, request.user).library
    return owned_or_404(_readable_runs(library), library, id=playthrough_id)


@playthrough_router.patch("/{playthrough_id}", response={204: None})
def partial_update_playthrough(
    request, playthrough_id: UUIDv7, payload: UpdatePlaythroughIn
):
    library = cast(User, request.user).library
    run = owned_or_404(_writable_runs(library), library, id=playthrough_id)
    #: The stated keys, not a serialized dict.
    #:
    #: An endpoint the request leaves out is stated as
    #: nothing, so a note-only PATCH records no act. dict()
    #: would hand back canonical strings and every key, and
    #: the commands take values.
    stated = payload.model_fields_set
    restate_run(
        cast("User", request.user),
        run,
        RunDraft(
            started=ActStatement(payload.started) if "started" in stated else None,
            completed=ActStatement(payload.completed)
            if "completed" in stated
            else None,
            note=payload.note if "note" in stated else run.note,
        ),
        correlation_id=new_correlation_id(),
    )
    return Status(204, None)


#: DELETE is the transport's word, not ours.
@playthrough_router.delete("/{playthrough_id}", response={204: None})
def remove_playthrough(request, playthrough_id: UUIDv7):
    library = cast(User, request.user).library
    run = owned_or_404(_writable_runs(library), library, id=playthrough_id)
    remove_run(cast("User", request.user), run, correlation_id=new_correlation_id())
    return Status(204, None)


@device_router.get("/search", response=list[DeviceOption])
def search_devices(request, q: str = "", limit: int = 10):
    library = cast(User, request.user).library
    qs = Device.objects.for_library(library)
    if q:
        qs = qs.filter(name__icontains=q).order_by("name")
    else:
        #: The live rows, on the base manager: a removed one moves nothing.
        qs = qs.annotate(
            last_used=Max(
                "player_sessions__sort_instant",
                filter=Q(player_sessions__removed_at__isnull=True),
            )
        ).order_by(F("last_used").desc(nulls_last=True), "-created_at", "name")
    return [{"value": d.id, "label": d.name, "data": {}} for d in qs[:limit]]


class RowIn(Schema):
    """The one fact a create row states."""

    #: An unknown key is a mistake, not silence.
    model_config = ConfigDict(extra="forbid")

    name: str


@api.exception_handler(RowRefused)
def _row_refused(request, refusal: RowRefused):
    #: The sentence rides the middleware's header, which is
    #: what shows the toast. Nothing else queues one here.
    messages.error(request, refusal.sentence)
    return api.create_response(request, {"detail": refusal.sentence}, status=422)


@device_router.post("/", response={201: CreatedRow})
def create_device(request, payload: RowIn):
    """One device, named and nothing else.

    `type` is stated here because the form requires it and
    the row's default names it. A person corrects it on the
    device page.

    A device the library already holds is answered rather
    than made a second time. The column states no rule of
    its own, and the create row is judged on the loaded
    window: a library holding more devices than the window
    shows would type a name it already holds.
    """
    library = cast(User, request.user).library
    held = (
        Device.objects.for_library(library)
        .filter(name__iexact=payload.name.strip())
        .first()
    )
    if held is not None:
        messages.info(request, f"{held.name} is already in your library")
        return Status(201, CreatedRow(id=str(held.pk), label=held.name))
    device = created_by_form(
        DeviceForm, library=library, name=payload.name, type=Device.UNKNOWN
    )
    messages.success(request, f"{device.name} added")
    return Status(201, CreatedRow(id=str(device.pk), label=device.name))


@platform_router.post("/", response={201: CreatedRow})
def create_platform(request, payload: RowIn):
    """One platform, private to the library that made it.

    A shared platform is a fixture, not a thing a picker
    makes. Two rules refuse a duplicate and they are not
    one: `Platform.clean` refuses a private row shadowing a
    shared one, and the private unique constraint refuses
    the library's own.
    """
    library = cast(User, request.user).library
    platform = created_by_form(PlatformForm, library=library, name=payload.name)
    messages.success(request, f"{platform.name} added")
    return Status(201, CreatedRow(id=str(platform.pk), label=platform.name))


@platform_router.get("/search", response=list[PlatformOption])
def search_platforms(request, q: str = "", limit: int = 10):
    library = cast(User, request.user).library
    qs = Platform.objects.visible_to(library)
    if q:
        qs = qs.filter(name__icontains=q).order_by("name")
    else:
        epoch = Value(datetime(1970, 1, 1, tzinfo=UTC))
        qs = (
            qs.annotate(
                last_game_use=Subquery(
                    Game.objects.for_library(library)
                    .filter(platform=OuterRef("pk"))
                    .order_by("-updated_at")
                    .values("updated_at")[:1],
                    output_field=DateTimeField(),
                ),
                last_purchase_use=Subquery(
                    Purchase.objects.for_library(library)
                    .filter(platform=OuterRef("pk"))
                    .order_by("-updated_at")
                    .values("updated_at")[:1],
                    output_field=DateTimeField(),
                ),
            )
            .annotate(
                last_used=Case(
                    When(
                        last_game_use__isnull=True,
                        last_purchase_use__isnull=True,
                        then=Value(None, output_field=DateTimeField()),
                    ),
                    default=Greatest(
                        Coalesce("last_game_use", epoch),
                        Coalesce("last_purchase_use", epoch),
                    ),
                    output_field=DateTimeField(),
                )
            )
            .order_by(F("last_used").desc(nulls_last=True), "-created_at", "name")
        )
    return [{"value": p.id, "label": p.name, "data": {}} for p in qs[:limit]]


@platform_router.get("/groups", response=list[StringOption])
def search_platform_groups(request, q: str = "", limit: int = 10):
    library = cast(User, request.user).library
    qs = Platform.objects.visible_to(library).exclude(group="")
    if q:
        qs = qs.filter(group__icontains=q)
    groups = qs.values_list("group", flat=True).distinct().order_by("group")
    return [{"value": group, "label": group, "data": {}} for group in groups[:limit]]


timezone_router = Router()

# The pinned clear-to-NULL row: "" posts as the form's empty choice, which
# cleans to None ("assume the account display zone"). Browse-all only — a
# filtered query is asking for zones, not for the clear action.
_ACCOUNT_ZONE_OPTION: Final[dict[str, object]] = {
    "value": "",
    "label": "Use account display zone",
    "data": {},
}


@timezone_router.get("/search", response=list[StringOption])
def search_timezones(request, q: str = "", limit: int = 10):
    """IANA zone options for the session time-zone picker, shaped like
    /api/platforms/groups (the existing list[StringOption] feed) so the
    SearchSelect client needs nothing new. DISPLAY_TIME_ZONE_CHOICES is already
    the sorted tzdata list."""
    zone_names = [zone_name for zone_name, _label in DISPLAY_TIME_ZONE_CHOICES]
    if q:
        query = q.lower()
        matches = [name for name in zone_names if query in name.lower()]
        return [{"value": name, "label": name, "data": {}} for name in matches[:limit]]
    return [
        _ACCOUNT_ZONE_OPTION,
        *(
            {"value": name, "label": name, "data": {}}
            for name in zone_names[: max(limit - 1, 0)]
        ),
    ]


api.add_router("/playthrough", playthrough_router)
api.add_router("/games", game_router)
api.add_router("/devices", device_router)
api.add_router("/platforms", platform_router)
api.add_router("/timezones", timezone_router)

session_router = Router()


class PlatformOut(Schema):
    name: str
    icon: str


class GameOut(Schema):
    id: UUIDv7
    name: str
    platform: PlatformOut | None = None


class DeviceOut(Schema):
    id: UUIDv7
    name: str
    type: str


def _endpoint_zone_label(
    value: datetime | None,
    zone_name: str | None,
    context: Mapping[str, Any] | None,
) -> str | None:
    """The label the client appends verbatim, or ``None`` when there is nothing
    to label: no stored zone, an unusable one (dropped from tzdata — must not
    500 a list page), or one that equals this request's account display zone.

    Computed here rather than in the browser because ``tzname()`` says "JST"
    where Intl's ``timeZoneName: "short"`` says "GMT+9"; server-rendered and
    client-rebuilt rows share one table and must read identically.
    """
    request = context.get("request") if context else None
    if request is None or value is None or not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError, ValueError:
        return None
    if zone.key == date_time_presentation_for_request(request).timezone.key:
        return None
    return zone_label(value, zone)


class SessionOut(Schema):
    """The projection row, the game reached through its run."""

    id: UUIDv7
    playthrough_id: UUIDv7
    game: GameOut | None = Field(None, alias="playthrough.player_game.game")
    device: DeviceOut | None = None
    timing_mode: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    started_at_zone: str | None = None
    ended_at_zone: str | None = None
    started_at_zone_label: str | None = None
    ended_at_zone_label: str | None = None
    #: The written day of a Duration-only row; null otherwise.
    stated_day: date | None = None
    #: The hand-stated duration: whole for Duration-only, an override for
    #: Corrected; null on a Timed row.
    stated_duration_seconds: int | None = None
    #: The day in the library's calendar, and the counted duration.
    day: date = Field(..., alias="effective_day")
    duration_seconds: int
    note: str
    emulated: bool
    created_at: datetime

    @staticmethod
    def resolve_stated_duration_seconds(obj: PlayerSession) -> int | None:
        if obj.stated_duration is None:
            return None
        return int(obj.stated_duration.total_seconds())

    @staticmethod
    def resolve_duration_seconds(obj: PlayerSession) -> int:
        return int(obj.effective_duration.total_seconds())

    @staticmethod
    def resolve_started_at_zone_label(obj: PlayerSession, context) -> str | None:
        return _endpoint_zone_label(obj.started_at, obj.started_at_zone, context)

    @staticmethod
    def resolve_ended_at_zone_label(obj: PlayerSession, context) -> str | None:
        return _endpoint_zone_label(obj.ended_at, obj.ended_at_zone, context)


class SessionListOut(Schema):
    items: list[SessionOut]
    count: int
    page: int
    page_size: int
    num_pages: int


@session_router.get("/", response=SessionListOut)
@regex_timeout_api
def list_sessions_api(request, filter: str = "", sort: str = "", page: int = 1):
    library = cast(User, request.user).library
    sessions: QuerySet[PlayerSession] = readable_sessions(library)
    if filter:
        try:
            session_filter = parse_session_filter(filter)
        except FilterError as exc:
            logger.warning(
                "rejected invalid filter (entity=session, user=%s, path=%s): %s",
                request.user,
                request.path,
                exc,
            )
            raise HttpError(400, f"Invalid filter: {exc}") from exc
        if session_filter is not None:
            sessions = execute_filter(
                session_filter,
                sessions,
                filter_query_context_for_library(library),
            )
    # `sort` is read from request.GET by parse_find_filter; declared above so it
    # appears in the OpenAPI schema. Unknown sort keys are rejected (not silently
    # dropped) for parity with the filter rejection above — silently-wrong ordering
    # is worse than an explicit error for an API consumer.
    sort_result = apply_sort(
        sessions, parse_find_filter(request), SESSION_SORTS, SESSION_DEFAULT_SORT
    )
    if sort_result.unknown:
        # repr() the raw keys: parse_sort_terms only strips outer whitespace, so an
        # embedded newline would otherwise forge log lines (CWE-117).
        logger.warning(
            "rejected unknown sort field(s) (entity=session, user=%s, path=%s): %s",
            request.user,
            request.path,
            ", ".join(repr(key) for key in sort_result.unknown),
        )
        raise HttpError(400, f"Invalid sort: {', '.join(sort_result.unknown)}")
    paginator = Paginator(sort_result.queryset, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    return {
        "items": list(page_obj.object_list),
        "count": paginator.count,
        "page": page_obj.number,
        "page_size": PAGE_SIZE,
        "num_pages": paginator.num_pages,
    }


@session_router.get("/{session_id}", response=SessionOut)
def get_session(request, session_id: UUIDv7):
    library = cast(User, request.user).library
    return owned_or_404(readable_sessions(library), library, id=session_id)


class SessionDeviceUpdate(Schema):
    # Required key, nullable value: null clears the device (renders as
    # "No device").
    device_id: UUIDv7 | None


def _answered_or_http(failure: CommandFailed) -> NoReturn:
    """A refused command, as the API says it."""
    raise HttpError(failure.status_code, failure.message)


@session_router.patch("/{session_id}/device", response={204: None})
def partial_update_session_device(
    request, session_id: UUIDv7, payload: SessionDeviceUpdate
):
    library = cast(User, request.user).library
    session = owned_or_404(readable_sessions(library), library, id=session_id)
    try:
        describe_session(
            cast(User, request.user),
            session,
            device=StatedDevice(payload.device_id),
            correlation_id=new_correlation_id(),
        )
    except CommandFailed as failure:
        _answered_or_http(failure)
    messages.success(request, "Device updated")
    return Status(204, None)


class TimedIn(Schema):
    """A start, an optional end, each with an optional zone."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    started_at_zone: str | None = None
    ended_at: datetime | None = None
    ended_at_zone: str | None = None


#: What `timedelta` can hold, read off it.
MAX_DURATION_SECONDS: Final[int] = int(timedelta.max.total_seconds())

#: The seconds one timing statement carries.
#:
#: Bounded because `timedelta(seconds=...)` runs before the dispatch,
#: where an `OverflowError` reaches no answer. The bound is the
#: type's own range and not zero: the sign is the command's rule,
#: and it has a sentence for it.
type DurationSeconds = Annotated[
    int, Field(ge=-MAX_DURATION_SECONDS, le=MAX_DURATION_SECONDS)
]


class DurationOnlyIn(Schema):
    """A written day and how long it lasted."""

    model_config = ConfigDict(extra="forbid")

    day: date
    duration_seconds: DurationSeconds


class CorrectedIn(Schema):
    """Both instants and a duration that replaces the elapsed time."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    ended_at: datetime
    duration_seconds: DurationSeconds
    started_at_zone: str | None = None
    ended_at_zone: str | None = None


#: Told apart by shape: each refuses the others' keys.
type TimingIn = CorrectedIn | TimedIn | DurationOnlyIn


class SessionUpdate(Schema):
    """Each named key is one act; an omitted key states nothing.

    `timing` is a correction of the whole statement; `note`, `device_id`
    and `emulated` a description; `playthrough_id` a move. A key the
    body does not know is refused, so the old `timestamp_end` cannot
    pass unread.
    """

    model_config = ConfigDict(extra="forbid")

    timing: TimingIn | None = None
    note: str | None = None
    #: Present-null clears the device.
    device_id: UUIDv7 | None = None
    emulated: bool | None = None
    playthrough_id: UUIDv7 | None = None


def _timing_statement(timing: TimingIn, day_zone: str) -> TimingStatement:
    match timing:
        case CorrectedIn():
            return CorrectedTiming(
                started_at=timing.started_at,
                ended_at=timing.ended_at,
                duration=timedelta(seconds=timing.duration_seconds),
                day_zone=day_zone,
                started_at_zone=timing.started_at_zone,
                ended_at_zone=timing.ended_at_zone,
            )
        case TimedIn():
            return TimedTiming(
                started_at=timing.started_at,
                day_zone=day_zone,
                started_at_zone=timing.started_at_zone,
                ended_at=timing.ended_at,
                ended_at_zone=timing.ended_at_zone,
            )
        case DurationOnlyIn():
            return DurationOnlyTiming(
                day=timing.day, duration=timedelta(seconds=timing.duration_seconds)
            )
        case _:
            assert_never(timing)


class SessionIn(Schema):
    """One session, stated whole: the run and one timing."""

    #: An unknown key is a mistake, not silence.
    model_config = ConfigDict(extra="forbid")

    playthrough_id: UUIDv7
    timing: TimingIn
    device_id: UUIDv7 | None = None
    note: str = ""
    emulated: bool = False


def _stated_idempotency_key(header: str | None) -> IdempotencyKey | None:
    """The key the caller states, or none.

    Measured here because neither length reaches an answer:
    `validate_idempotency_key` raises a plain `ValueError` that no
    answer maps. The strip comes first, and the stripped key is the
    one claimed: a key of spaces alone passes both that check and
    the not-empty constraint on either key column, and a trailing
    space is not a second key.
    """
    if header is None:
        return None
    key = header.strip()
    if not key or len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise HttpError(
            422,
            "An Idempotency-Key is one to "
            f"{IDEMPOTENCY_KEY_MAX_LENGTH} characters, spaces aside.",
        )
    return key


@session_router.post("/", response={201: SessionOut})
def create_session(
    request,
    payload: SessionIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    actor = cast(User, request.user)
    library = actor.library
    stated_key = _stated_idempotency_key(idempotency_key)
    #: Both resolve inside `build`, behind the key.
    try:
        session_id = record_session(
            actor,
            SessionDraft(
                playthrough_id=payload.playthrough_id,
                timing=_timing_statement(
                    payload.timing, calendar_day_zone(library).key
                ),
                device_id=payload.device_id,
                note=payload.note,
                emulated=payload.emulated,
            ),
            correlation_id=new_correlation_id(),
            idempotency_key=stated_key,
        )
    except CommandFailed as failure:
        _answered_or_http(failure)
    #: Read before the message: a repeat under the key of a session
    #: since removed answers no row, and a toast queued ahead of
    #: that read would say the opposite of the status.
    recorded = owned_or_404(readable_sessions(library), library, pk=session_id)
    messages.success(request, "Session recorded.")
    return Status(201, recorded)


@session_router.patch("/{session_id}", response={200: SessionOut})
def partial_update_session(request, session_id: UUIDv7, payload: SessionUpdate):
    library = cast(User, request.user).library
    actor = cast(User, request.user)
    session = owned_or_404(readable_sessions(library), library, id=session_id)
    stated = payload.dict(exclude_unset=True)
    correlation_id = new_correlation_id()
    try:
        if payload.timing is not None:
            correct_session(
                actor,
                session,
                _timing_statement(payload.timing, calendar_day_zone(library).key),
                correlation_id=correlation_id,
            )
        described = {key for key in ("note", "device_id", "emulated") if key in stated}
        if described:
            describe_session(
                actor,
                session,
                note=payload.note,
                device=StatedDevice(payload.device_id)
                if "device_id" in stated
                else None,
                emulated=payload.emulated,
                correlation_id=correlation_id,
            )
        if payload.playthrough_id is not None:
            move_session(
                actor, session, payload.playthrough_id, correlation_id=correlation_id
            )
    except CommandFailed as failure:
        _answered_or_http(failure)
    #: Read before the message: this scope reads a catalog
    #: mark no command reads, so a move can lose the row.
    updated = owned_or_404(readable_sessions(library), library, pk=session.pk)
    messages.success(request, "Session updated.")
    return updated


api.add_router("/session", session_router)

historical_playtime_router = Router()


class HistoricalPlaytimeOut(Schema):
    """The projection row, its runs by key."""

    id: UUIDv7
    player_game_id: UUIDv7
    game: GameOut = Field(..., alias="player_game.game")
    playthrough_ids: list[UUIDv7]
    duration_seconds: int
    #: Canonical temporal text; null is unknown.
    when: StatedTemporal = None
    when_lower: date | None = None
    when_upper: date | None = None
    provenance: str
    device: DeviceOut | None = None
    emulated: bool
    note: str
    created_at: datetime

    @staticmethod
    def resolve_duration_seconds(obj: HistoricalPlaytime) -> int:
        return int(obj.duration.total_seconds())

    @staticmethod
    def resolve_playthrough_ids(obj: HistoricalPlaytime) -> list[uuid.UUID]:
        return sorted(run.playthrough_id for run in obj.runs.all())


class HistoricalPlaytimeListOut(Schema):
    items: list[HistoricalPlaytimeOut]
    count: int
    page: int
    page_size: int
    num_pages: int


@historical_playtime_router.get("/", response=HistoricalPlaytimeListOut)
@regex_timeout_api
def list_historical_playtime_api(
    request, filter: str = "", sort: str = "", page: int = 1
):
    library = cast(User, request.user).library
    records: QuerySet[HistoricalPlaytime] = listed_records(library)
    if filter:
        try:
            record_filter = parse_historical_playtime_filter(filter)
        except FilterError as exc:
            logger.warning(
                "rejected invalid filter (entity=historical playtime, user=%s, "
                "path=%s): %s",
                request.user,
                request.path,
                exc,
            )
            raise HttpError(400, f"Invalid filter: {exc}") from exc
        if record_filter is not None:
            records = execute_filter(
                record_filter,
                records,
                filter_query_context_for_library(library),
            )
    sort_result = apply_sort(
        records,
        parse_find_filter(request),
        HISTORICAL_PLAYTIME_SORTS,
        HISTORICAL_PLAYTIME_DEFAULT_SORT,
    )
    if sort_result.unknown:
        logger.warning(
            "rejected unknown sort field(s) (entity=historical playtime, user=%s, "
            "path=%s): %s",
            request.user,
            request.path,
            ", ".join(repr(key) for key in sort_result.unknown),
        )
        raise HttpError(400, f"Invalid sort: {', '.join(sort_result.unknown)}")
    paginator = Paginator(sort_result.queryset, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    return {
        "items": list(page_obj.object_list),
        "count": paginator.count,
        "page": page_obj.number,
        "page_size": PAGE_SIZE,
        "num_pages": paginator.num_pages,
    }


@historical_playtime_router.get("/{record_id}", response=HistoricalPlaytimeOut)
def get_historical_playtime(request, record_id: UUIDv7):
    library = cast(User, request.user).library
    return owned_or_404(listed_records(library), library, id=record_id)


api.add_router("/historical-playtime", historical_playtime_router)

filter_router = Router()


class FilterCountOut(Schema):
    count: int


@filter_router.get("/count", response=FilterCountOut)
@regex_timeout_api
def filter_count(request, model: str, filter: str = ""):
    """Live result count for the nested filter builder (#195).

    Generic across every filterable model: the ``model`` key selects the
    ``OperatorFilter`` subclass (``filter_for_model``) and the Django model
    ownership base. GET is CSRF-safe (read-only); auth is inherited from
    ``NinjaAPI(auth=django_auth)``.
    """
    try:
        filter_cls = filter_for_model(model)
    except LookupError as exc:
        # Unknown Django model — a bad/hand-edited ``model`` key: a user 400.
        # A ``KeyError`` from filter_for_model means the model *exists* but has no
        # ``{Model}Filter`` class (a wiring bug for a model the client can reach);
        # let it propagate to a 500 so it surfaces, per the filter_from_json
        # contract of not masking genuine wiring bugs.
        raise HttpError(400, f"Unknown model: {model!r}") from exc
    library = cast(User, request.user).library
    queryset = filter_queryset_for_library(model, library)
    if filter:
        # "" -> None (count all); "{}" -> an all-None filter whose to_q() is an
        # empty Q() (also counts all). A present-but-invalid filter -> 400.
        try:
            parsed = filter_from_json(filter_cls, filter)
        except FilterError as exc:
            logger.warning(
                "rejected invalid filter (entity=%s, user=%s): %s",
                model,
                request.user,
                exc,
            )
            raise HttpError(400, f"Invalid filter: {exc}") from exc
        if parsed is not None:
            queryset = execute_filter(
                parsed,
                queryset,
                filter_query_context_for_library(library),
            )
    return {"count": queryset.count()}


api.add_router("/filter", filter_router)

preset_router = Router()


class PresetOption(Schema):
    """Preset picker option; empty string values mean inherit."""

    value: UUIDv7
    label: str
    data: dict[str, str]


class PresetIn(Schema):
    # ``filter: dict | None`` makes Ninja reject scalar/array payloads with a 422
    # before the handler runs — the schema subsumes the old hand-rolled
    # "filter is not an object" guard (issue #206). ``None`` means "no filter".
    name: str
    mode: str
    filter: dict | None = None
    # Sort is persisted only for modes that support it.
    sort: str | None = None
    # Missing or invalid means inherit; any valid value is pinned.
    per_page: str | None = None


def _preset_per_page(raw: str | None) -> int | None:
    return parse_per_page_override(raw)


def _stored_per_page(find_filter: dict | None) -> str:
    """Serialize a valid override; otherwise inherit."""
    per_page = (find_filter or {}).get("per_page")
    if isinstance(per_page, bool) or not isinstance(per_page, int) or per_page < 0:
        return ""
    return str(per_page)


def _reject_unknown_preset_mode(request, mode: str) -> None:
    """400 for a mode outside MODE_PARSERS (parity-tested against MODE_CHOICES)."""
    if mode not in MODE_PARSERS:
        logger.warning(
            "rejected preset request (user=%s, path=%s): unknown mode %r",
            request.user,
            request.path,
            mode,
        )
        raise HttpError(400, f"Unknown preset mode '{mode}'.")


@preset_router.get("/", response=list[PresetOption])
def list_presets(request, mode: str = "games", q: str = "", limit: int = 100):
    """The current library's presets for one mode, shaped for the combobox picker.

    ``limit=0`` means unbounded — the filter bar's overwrite-collision check
    fetches every name, so a >limit preset collection can't silently miss a
    collision and destroy a preset behind the warning's back (issue #212).
    """
    _reject_unknown_preset_mode(request, mode)
    library = cast(User, request.user).library
    presets = (
        FilterPreset.objects.for_library(library).filter(mode=mode).order_by("name")
    )
    if q:
        presets = presets.filter(name__icontains=q)
    if limit > 0:
        presets = presets[:limit]
    return [
        {
            "value": preset.id,
            "label": preset.name,
            "data": {
                "filter": json.dumps(preset.object_filter or {}, sort_keys=True),
                "sort": (preset.find_filter or {}).get("sort", ""),
                "per_page": _stored_per_page(preset.find_filter),
            },
        }
        for preset in presets
    ]


@preset_router.post("/", response={200: None, 201: None})
def save_preset(request, payload: PresetIn):
    """Create or overwrite a preset; 201 on create, 200 on in-place update.

    Upserts on the (library, mode, name) identity (unique at the DB level): re-saving
    a name overwrites the stored filter rather than creating a duplicate row; the
    filter bar warns inline before the user confirms an overwrite (issue #212).
    The client derives its "saved"/"updated" toast from the status code.
    """
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Preset name is required.")
    _reject_unknown_preset_mode(request, payload.mode)

    object_filter = payload.filter or {}
    try:
        # Semantic validation: the JSON body is already well-formed (Ninja parsed
        # it), but the filter tree itself can be invalid (unknown field, BETWEEN
        # without value2, …) — MODE_PARSERS raises FilterError on those.
        MODE_PARSERS[payload.mode](json.dumps(object_filter))
    except FilterError as exc:
        logger.warning(
            "rejected preset save (mode=%s, user=%s, path=%s): %s",
            payload.mode,
            request.user,
            request.path,
            exc,
        )
        raise HttpError(400, f"Invalid filter: {exc}") from exc

    # Page size is universal; sort is mode-gated. Page is never persisted.
    find_filter: dict[str, object] = {}
    if payload.sort and payload.mode in MODE_SORTS:
        find_filter["sort"] = payload.sort
    per_page = _preset_per_page(payload.per_page)
    if per_page is not None:
        find_filter["per_page"] = per_page
    library = cast(User, request.user).library
    _, created = FilterPreset.objects.update_or_create(
        library=library,
        name=name,
        mode=payload.mode,
        defaults={"object_filter": object_filter, "find_filter": find_filter},
    )
    return Status(201 if created else 200, None)


class RemovedPresetOut(Schema):
    #: Where Undo posts.
    restore_url: str


#: DELETE is the transport's word, not ours.
@preset_router.delete("/{preset_id}", response={200: RemovedPresetOut})
def remove_preset(request, preset_id: UUIDv7):
    """Take one of the library's presets out; say where Undo posts.

    Scoped to request.user.library so it cannot touch another library's preset (404
    instead). DELETE-only by routing; CSRF is enforced by django_auth.
    """
    library = cast(User, request.user).library
    preset = owned_or_404(
        FilterPreset.objects.for_library(library), library, id=preset_id
    )
    remove(preset)
    return Status(
        200,
        RemovedPresetOut(restore_url=reverse("games:restore_preset", args=[preset.id])),
    )


api.add_router("/presets", preset_router)

settings_router = Router()
conversion_router = Router()


class ConversionStatusOut(Schema):
    library_id: str
    requested_version: int
    requested_currency: str
    published_version: int
    published_currency: str
    status: str
    retry_at: datetime | None
    last_error: str


@conversion_router.get("/status", response=ConversionStatusOut)
def conversion_status(request):
    state = PurchaseConversionState.objects.get(library=request.user.library)
    return {
        "library_id": str(state.library_id),
        "requested_version": state.requested_version,
        "requested_currency": state.requested_currency,
        "published_version": state.published_version,
        "published_currency": state.published_currency,
        "status": state.status,
        "retry_at": state.retry_at,
        "last_error": state.last_error,
    }


api.add_router("/conversion", conversion_router)


class SettingOut(Schema):
    """One resolved setting for the settings panel.

    ``value`` covers the primitive values used by the general settings surfaces.
    Identity-bearing settings use dedicated strict schemas. ``locked`` marks an
    env/`.env`/`.ini`-pinned value; ``/user`` forces it ``False`` (see
    :func:`list_user_settings`).
    ``namespace`` identifies which mutation surface produced this entry — the
    personal, site-admin, or library preferences surface — independent of
    ``source`` (where the resolved value came from).
    """

    key: str
    value: str | int | None
    source: SettingSource
    locked: bool
    namespace: SettingNamespace


class CalendarDeltaOut(Schema):
    """What a display-zone change moved, over the live sessions."""

    day_zone: str
    sessions: int
    day_moved: int
    month_moved: int
    year_moved: int


class SettingChangeOut(SettingOut):
    """A change's answer: the resolved setting, and the calendar it moved."""

    calendar: CalendarDeltaOut | None = None


class SettingValueIn(Schema):
    # ``None`` means "clear this setting" (unset → falls through to lower layers).
    value: Any = None


class DefaultDeviceIn(Schema):
    value: UUIDv7 | None = None


class DefaultDeviceOut(Schema):
    key: str
    value: UUIDv7 | None
    source: SettingSource
    locked: bool
    namespace: SettingNamespace


def _settings_of_scope(*scopes: SettingScope) -> list[SettingKey]:
    return [
        key
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.scope in scopes
    ]


def _setting_out(
    key: SettingKey,
    resolved,
    *,
    locked: bool | None = None,
    namespace: SettingNamespace,
) -> dict:
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "locked": resolved.locked if locked is None else locked,
        "namespace": namespace,
    }


def _raise_400(error: Exception) -> NoReturn:
    """400 with a clean message. ``str()`` of a Django ``ValidationError`` is its
    message-*list* repr, so unwrap via ``.messages``."""
    if isinstance(error, ValidationError):
        raise HttpError(400, " ".join(error.messages))
    raise HttpError(400, str(error))


@settings_router.get("/user", response=list[SettingOut])
def list_user_settings(request):
    """The requesting user's personal prefs, resolved with origin.

    No id parameter — scoped to ``request.user``, so cross-user reads are
    impossible. ``locked`` is forced ``False``: a user can always override a pref
    (env-locking per-user prefs is deferred), so the panel never shows one as
    read-only, whatever layer the effective value comes from.
    """
    return [
        _setting_out(
            key,
            resolve_for_user_with_origin(request.user, key),
            locked=False,
            namespace=SettingNamespace.USER,
        )
        for key in _settings_of_scope(SettingScope.USER)
    ]


def _setting_change_out(
    key: SettingKey,
    mutation: SettingMutation,
    *,
    locked: bool | None = None,
    namespace: SettingNamespace,
) -> dict:
    return {
        **_setting_out(key, mutation.effective, locked=locked, namespace=namespace),
        "calendar": (
            None if mutation.calendar is None else mutation.calendar._asdict()
        ),
    }


def _report_saved(
    request, response: HttpResponse, key: SettingKey, mutation: SettingMutation
) -> None:
    """One toast: the calendar's sentence when its zone moved, else "saved".

    A setting that reloads the page after a save reads the toast on
    the page it lands on, so the header rides no response the browser
    discards.
    """
    if get_definition(key).reload_after_save:
        response["HX-Refresh"] = "true"
    if mutation.calendar is not None:
        messages.success(request, calendar_sentence(mutation.calendar))
        return
    messages.success(request, f"{get_definition(key).label} saved")


@settings_router.patch("/user/{key}", response=SettingChangeOut)
def update_user_setting(
    request, response: HttpResponse, key: str, payload: SettingValueIn
):
    """Set (or clear, with ``value: null``) one of the user's prefs.

    Return the freshly resolved value and origin so live controls can update their
    source metadata without reloading the page.
    """
    try:
        definition = get_definition(key)
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    if definition.scope is not SettingScope.USER:
        raise HttpError(400, f"{key} is not a user-scoped setting.")
    try:
        with answered("time zone"):
            mutation = change_user_setting(request.user, key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    _report_saved(request, response, key, mutation)
    return _setting_change_out(
        key, mutation, locked=False, namespace=SettingNamespace.USER
    )


@library_router.patch("/default-device", response=DefaultDeviceOut)
def update_library_default_device(request, payload: DefaultDeviceIn):
    """Set the current library's default Device, or clear it with null.

    The live-settings client substitutes its field key into a URL template, while
    this endpoint serves only ``default-device``. Add a key-routed endpoint before
    adding another library preference.
    """
    library = request.user.library
    device = None
    if payload.value is not None:
        device = Device.objects.for_library(library).filter(pk=payload.value).first()
        if device is None:
            raise HttpError(404, "Device not found.")
    change_library_default_device(library, device)
    messages.success(request, "Default device saved")
    return {
        "key": "default-device",
        "value": device.pk if device is not None else None,
        "source": SettingSource.LIBRARY,
        "locked": False,
        "namespace": SettingNamespace.LIBRARY,
    }


@settings_router.get("/site", response=list[SettingOut])
def list_site_settings(request):
    """Site settings (and the site defaults under user prefs), resolved with
    origin. Superuser-only."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    return [
        _setting_out(key, resolve_with_origin(key), namespace=SettingNamespace.SITE)
        for key in _settings_of_scope(SettingScope.SITE, SettingScope.USER)
    ]


@settings_router.patch("/site/{key}", response=SettingChangeOut)
def update_site_setting(
    request, response: HttpResponse, key: str, payload: SettingValueIn
):
    """Set (or clear, with ``value: null``) a site setting's DB value.
    Superuser-only."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    try:
        with answered("time zone"):
            mutation = change_site_setting(key, payload.value, actor=request.user)
    except SettingLockedError as error:
        raise HttpError(
            409,
            f"{error.key} is controlled by {error.source.value}.",
        )
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    _report_saved(request, response, key, mutation)
    return _setting_change_out(key, mutation, namespace=SettingNamespace.SITE)


api.add_router("/settings", settings_router)
api.add_router("/library", library_router)

client_error_logger = logging.getLogger("client_errors")

client_error_router = Router()


class ClientErrorIn(Schema):
    error_id: str = Field(..., max_length=16)
    context: str = Field(..., max_length=200)
    detail: str = Field(..., max_length=500)
    url: str = Field(..., max_length=200)


def _one_line(value: str) -> str:
    """Collapse CR/LF so a client field cannot forge extra log entries."""
    return value.replace("\r", " ").replace("\n", " ")


@client_error_router.post("/", response={204: None})
def report_client_error(request, payload: ClientErrorIn):
    """Log a browser-side error so production observability can see it (#232).

    Auth + CSRF are inherited from ``NinjaAPI(auth=django_auth)``. Fields are
    length-capped by the schema (over-length -> 422) and CRLF-stripped so the
    single log line cannot be forged.
    """
    client_error_logger.error(
        "client error [%s] user=%s context=%s url=%s detail=%s",
        _one_line(payload.error_id),
        request.user,
        _one_line(payload.context),
        _one_line(payload.url),
        _one_line(payload.detail),
    )
    return Status(204, None)


api.add_router("/client-error", client_error_router)
