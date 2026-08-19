import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Final, NoReturn, cast
from uuid import UUID
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
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils.timezone import now as django_timezone_now
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status
from ninja.errors import HttpError
from ninja.security import django_auth

from common.criteria import FilterError, filter_from_json
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import execute_filter, regex_timeout_api
from games.filters import (
    MODE_PARSERS,
    filter_for_model,
    filter_query_context_for_library,
    filter_queryset_for_library,
    parse_session_filter,
)
from games.formatting import zone_label
from games.forms import game_option_data
from games.models import (
    Device,
    FilterPreset,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    PurchaseConversionState,
    Session,
)
from games.ownership import owned_or_404
from games.sorting import (
    MODE_SORTS,
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
    parse_per_page_override,
)
from timetracker.config import SettingSource
from timetracker.settings_commands import (
    SettingLockedError,
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

logger = logging.getLogger("games")

api = NinjaAPI(auth=django_auth)
playevent_router = Router()
game_router = Router()
device_router = Router()
platform_router = Router()
library_router = Router()

NOW_FACTORY = django_timezone_now
PAGE_SIZE = 10


class GameStatusUpdate(Schema):
    status: str


class PlayEventIn(Schema):
    game_id: UUID
    started: date | None = None
    ended: date | None = None
    note: str = ""
    days_to_finish: int | None = None


class AutoPlayEventIn(ModelSchema):
    class Meta:
        model = PlayEvent
        fields = ("game", "started", "ended", "note")


class UpdatePlayEventIn(Schema):
    started: date | None = None
    ended: date | None = None
    note: str = ""


class PlayEventOut(Schema):
    id: int
    game: str = Field(..., alias="game.name")
    started: date | None = None
    ended: date | None = None
    days_to_finish: int | None = None
    note: str = ""
    updated_at: datetime
    created_at: datetime


# One schema per search endpoint rather than one shared by all three: each
# entity's option value is whatever that entity's primary key is, and those
# stop agreeing as the identity cutover promotes them one group at a time.
class GameOption(Schema):  # mirrors SearchSelectOption
    value: UUID
    label: str
    data: dict


class PlatformOption(Schema):  # mirrors SearchSelectOption
    value: UUID
    label: str
    data: dict


class DeviceOption(Schema):  # mirrors SearchSelectOption
    value: int
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
        Game.objects.for_library(library)
        .select_related("platform")
        .order_by("sort_name")
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sort_name__icontains=q))
    return [
        {
            "value": g.id,
            "label": g.search_label,
            "data": game_option_data(g),
        }
        for g in qs[:limit]
    ]


@game_router.patch("/{game_id}/status", response={204: None})
def partial_update_game(request, game_id: UUID, payload: GameStatusUpdate):
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    game.status = payload.status
    game.save()
    messages.success(request, "Status updated")
    return Status(204, None)


@playevent_router.get("/", response=list[PlayEventOut])
def list_playevents(request):
    library = cast(User, request.user).library
    return PlayEvent.objects.for_library(library)


@playevent_router.post("/", response={201: PlayEventOut})
def create_playevent(request, payload: PlayEventIn):
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=payload.game_id)
    values = payload.dict(exclude={"game_id"})
    playevent = PlayEvent.objects.create(game=game, **values)
    messages.success(request, "Game played!")
    return playevent


@playevent_router.get("/{playevent_id}", response=PlayEventOut)
def get_playevent(request, playevent_id: int):
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    return playevent


@playevent_router.patch("/{playevent_id}", response=PlayEventOut)
def partial_update_playevent(request, playevent_id: int, payload: UpdatePlayEventIn):
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(playevent, attr, value)
    playevent.save()
    return playevent


@playevent_router.delete("/{playevent_id}", response={204: None})
def delete_playevent(request, playevent_id: int):
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    playevent.delete()
    return Status(204, None)


@device_router.get("/search", response=list[DeviceOption])
def search_devices(request, q: str = "", limit: int = 10):
    library = cast(User, request.user).library
    qs = Device.objects.for_library(library)
    if q:
        qs = qs.filter(name__icontains=q).order_by("name")
    else:
        qs = qs.annotate(last_used=Max("session__timestamp_start")).order_by(
            F("last_used").desc(nulls_last=True), "-created_at", "name"
        )
    return [{"value": d.id, "label": d.name, "data": {}} for d in qs[:limit]]


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


api.add_router("/playevent", playevent_router)
api.add_router("/games", game_router)
api.add_router("/devices", device_router)
api.add_router("/platforms", platform_router)
api.add_router("/timezones", timezone_router)

session_router = Router()


class PlatformOut(Schema):
    name: str
    icon: str


class GameOut(Schema):
    id: UUID
    name: str
    platform: PlatformOut | None = None


class DeviceOut(Schema):
    id: int
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
    id: int
    game: GameOut | None = None
    device: DeviceOut | None = None
    timestamp_start: datetime
    timestamp_end: datetime | None = None
    timestamp_start_timezone: str | None = None
    timestamp_end_timezone: str | None = None
    timestamp_start_timezone_label: str | None = None
    timestamp_end_timezone_label: str | None = None
    duration_manual_seconds: int
    is_manual: bool
    note: str
    emulated: bool
    created_at: datetime
    modified_at: datetime

    @staticmethod
    def resolve_duration_manual_seconds(obj: Session) -> int:
        return int(obj.duration_manual.total_seconds()) if obj.duration_manual else 0

    @staticmethod
    def resolve_is_manual(obj: Session) -> bool:
        return obj.is_manual()

    @staticmethod
    def resolve_timestamp_start_timezone_label(obj: Session, context) -> str | None:
        return _endpoint_zone_label(
            obj.timestamp_start, obj.timestamp_start_timezone, context
        )

    @staticmethod
    def resolve_timestamp_end_timezone_label(obj: Session, context) -> str | None:
        return _endpoint_zone_label(
            obj.timestamp_end, obj.timestamp_end_timezone, context
        )


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
    sessions = Session.objects.for_library(library).select_related(
        "game", "game__platform", "device"
    )
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
def get_session(request, session_id: int):
    library = cast(User, request.user).library
    return owned_or_404(
        Session.objects.for_library(library).select_related(
            "game", "game__platform", "device"
        ),
        library,
        id=session_id,
    )


class SessionDeviceUpdate(Schema):
    # Required key, nullable value: null clears the device (renders as
    # "No device").
    device_id: int | None


@session_router.patch("/{session_id}/device", response={204: None})
def partial_update_session_device(
    request, session_id: int, payload: SessionDeviceUpdate
):
    library = cast(User, request.user).library
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)
    device = None
    if payload.device_id is not None:
        # A stale id (device deleted in another tab) must 404, not surface as
        # an IntegrityError 500 the client's retry toast can never resolve.
        device = owned_or_404(
            Device.objects.for_library(library), library, id=payload.device_id
        )
    # The payload carries the integer pk the selector's options do, while the
    # column holds the device's uuid: bind the instance, not the id.
    session.device = device
    session.save()
    messages.success(request, "Device updated")
    return Status(204, None)


class SessionUpdate(Schema):
    # All optional: a partial update only touches the fields the client sends.
    # The client supplies its own ISO-UTC "now" for finish/reset. GeneratedFields
    # (duration_calculated/duration_total) are intentionally absent and thus
    # unwriteable.
    timestamp_start: datetime | None = None
    timestamp_end: datetime | None = None
    # IANA zone each timestamp was committed in; present-null clears to NULL
    # ("assume the display zone").
    timestamp_start_timezone: str | None = None
    timestamp_end_timezone: str | None = None


@session_router.patch("/{session_id}", response={200: SessionOut})
def partial_update_session(request, session_id: int, payload: SessionUpdate):
    library = cast(User, request.user).library
    session = owned_or_404(
        Session.objects.for_library(library).select_related(
            "game", "game__platform", "device"
        ),
        library,
        id=session_id,
    )
    data = payload.dict(exclude_unset=True)  # omitted fields are left untouched
    for zone_field in ("timestamp_start_timezone", "timestamp_end_timezone"):
        if zone_field in data and data[zone_field] is not None:
            try:
                data[zone_field] = ZoneInfo(data[zone_field]).key
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise HttpError(
                    422, f"{zone_field} must be an IANA time zone name"
                ) from exc
    new_start = data.get("timestamp_start", session.timestamp_start)
    new_end = data.get("timestamp_end", session.timestamp_end)
    if new_start is not None and new_end is not None and new_end < new_start:
        raise HttpError(422, "timestamp_end must be on or after timestamp_start")
    for field, value in data.items():
        setattr(session, field, value)
    session.save()  # fires post_save Session signal -> Game.playtime recalc
    session.refresh_from_db()  # reload DB-computed GeneratedFields + modified_at
    messages.success(request, "Session updated.")
    return session


api.add_router("/session", session_router)

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

    value: int
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


@preset_router.delete("/{preset_id}", response={204: None})
def delete_preset(request, preset_id: int):
    """Delete one of the current library's presets.

    Scoped to request.user.library so it cannot touch another library's preset (404
    instead). DELETE-only by routing; CSRF is enforced by django_auth.
    """
    library = cast(User, request.user).library
    preset = owned_or_404(
        FilterPreset.objects.for_library(library), library, id=preset_id
    )
    preset.delete()
    return Status(204, None)


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

    ``value`` is ``str | int | None`` (device id is an int, unset is None) — a
    ``str``-only field would 500. ``locked`` marks an env/`.env`/`.ini`-pinned
    value; ``/user`` forces it ``False`` (see :func:`list_user_settings`).
    ``namespace`` identifies which mutation surface produced this entry — the
    personal, site-admin, or library preferences surface — independent of
    ``source`` (where the resolved value came from).
    """

    key: str
    value: str | int | None
    source: SettingSource
    locked: bool
    namespace: SettingNamespace


class SettingValueIn(Schema):
    # ``None`` means "clear this setting" (unset → falls through to lower layers).
    value: Any = None


class DefaultDeviceIn(Schema):
    value: int | str | None = None


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


@settings_router.patch("/user/{key}", response=SettingOut)
def update_user_setting(request, key: str, payload: SettingValueIn):
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
        mutation = change_user_setting(request.user, key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    messages.success(request, f"{definition.label} saved")
    return _setting_out(
        key, mutation.effective, locked=False, namespace=SettingNamespace.USER
    )


@library_router.patch("/default-device", response=SettingOut)
def update_library_default_device(request, payload: DefaultDeviceIn):
    """Set the current library's default Device, or clear it with null.

    The live-settings client substitutes its field key into a URL template, while
    this endpoint serves only ``default-device``. Add a key-routed endpoint before
    adding another library preference.
    """
    library = request.user.library
    device = None
    if payload.value is not None:
        try:
            device_id = int(payload.value)
        except ValueError:
            raise HttpError(400, "Device must be an integer or null.") from None
        device = Device.objects.for_library(library).filter(pk=device_id).first()
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


@settings_router.patch("/site/{key}", response=SettingOut)
def update_site_setting(request, key: str, payload: SettingValueIn):
    """Set (or clear, with ``value: null``) a site setting's DB value.
    Superuser-only."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    try:
        mutation = change_site_setting(key, payload.value)
    except SettingLockedError as error:
        raise HttpError(
            409,
            f"{error.key} is controlled by {error.source.value}.",
        )
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    definition = get_definition(key)
    messages.success(request, f"{definition.label} saved")
    return _setting_out(key, mutation.effective, namespace=SettingNamespace.SITE)


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
