import json
import logging
from datetime import date, datetime
from typing import Any, List

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as django_timezone_now
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status
from ninja.errors import HttpError
from ninja.security import django_auth

from common.criteria import FilterError, filter_from_json
from games.filters import (
    MODE_PARSERS,
    filter_for_model,
    parse_session_filter,
)
from games.forms import game_option_data
from games.models import Device, FilterPreset, Game, Platform, PlayEvent, Session
from timetracker.config import ResolvedSetting, SettingSource
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    SettingKey,
    SettingScope,
    UnregisteredSettingError,
    get_definition,
)
from timetracker.settings_resolver import (
    clear_site_setting,
    resolve_for_user_with_origin,
    resolve_with_origin,
    set_site_setting,
    set_user_preference,
)
from timetracker.theme import write_theme_cookies
from games.sorting import (
    MODE_SORTS,
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
    parse_per_page_override,
)

logger = logging.getLogger("games")

api = NinjaAPI(auth=django_auth)
playevent_router = Router()
game_router = Router()
device_router = Router()
platform_router = Router()

NOW_FACTORY = django_timezone_now
PAGE_SIZE = 10


class GameStatusUpdate(Schema):
    status: str


class PlayEventIn(Schema):
    game_id: int
    started: date | None = None
    ended: date | None = None
    note: str = ""
    days_to_finish: int | None = None


class AutoPlayEventIn(ModelSchema):
    class Meta:
        model = PlayEvent
        fields = ["game", "started", "ended", "note"]


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


class GameOption(Schema):  # mirrors SearchSelectOption
    value: int
    label: str
    data: dict


class StringOption(Schema):  # SearchSelectOption with a string value (e.g. group names)
    value: str
    label: str
    data: dict


@game_router.get("/search", response=list[GameOption])
def search_games(request, q: str = "", limit: int = 10):
    qs = Game.objects.select_related("platform").order_by("sort_name")
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
def partial_update_game(request, game_id: int, payload: GameStatusUpdate):
    game = get_object_or_404(Game, id=game_id)
    setattr(game, "status", payload.status)
    game.save()
    messages.success(request, "Status updated")
    return Status(204, None)


@playevent_router.get("/", response=List[PlayEventOut])
def list_playevents(request):
    return PlayEvent.objects.all()


@playevent_router.post("/", response={201: PlayEventOut})
def create_playevent(request, payload: PlayEventIn):
    playevent = PlayEvent.objects.create(**payload.dict())
    messages.success(request, "Game played!")
    return playevent


@playevent_router.get("/{playevent_id}", response=PlayEventOut)
def get_playevent(request, playevent_id: int):
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    return playevent


@playevent_router.patch("/{playevent_id}", response=PlayEventOut)
def partial_update_playevent(request, playevent_id: int, payload: UpdatePlayEventIn):
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(playevent, attr, value)
    playevent.save()
    return playevent


@playevent_router.delete("/{playevent_id}", response={204: None})
def delete_playevent(request, playevent_id: int):
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    playevent.delete()
    return Status(204, None)


@device_router.get("/search", response=list[GameOption])
def search_devices(request, q: str = "", limit: int = 10):
    qs = Device.objects.order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)
    return [{"value": d.id, "label": d.name, "data": {}} for d in qs[:limit]]


@platform_router.get("/search", response=list[GameOption])
def search_platforms(request, q: str = "", limit: int = 10):
    qs = Platform.objects.order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)
    return [{"value": p.id, "label": p.name, "data": {}} for p in qs[:limit]]


@platform_router.get("/groups", response=list[StringOption])
def search_platform_groups(request, q: str = "", limit: int = 10):
    qs = Platform.objects.exclude(group="")
    if q:
        qs = qs.filter(group__icontains=q)
    groups = qs.values_list("group", flat=True).distinct().order_by("group")
    return [{"value": group, "label": group, "data": {}} for group in groups[:limit]]


api.add_router("/playevent", playevent_router)
api.add_router("/games", game_router)
api.add_router("/devices", device_router)
api.add_router("/platforms", platform_router)

session_router = Router()


class PlatformOut(Schema):
    name: str
    icon: str


class GameOut(Schema):
    id: int
    name: str
    platform: PlatformOut | None = None


class DeviceOut(Schema):
    id: int
    name: str
    type: str


class SessionOut(Schema):
    id: int
    game: GameOut | None = None
    device: DeviceOut | None = None
    timestamp_start: datetime
    timestamp_end: datetime | None = None
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


class SessionListOut(Schema):
    items: list[SessionOut]
    count: int
    page: int
    page_size: int
    num_pages: int


@session_router.get("/", response=SessionListOut)
def list_sessions_api(request, filter: str = "", sort: str = "", page: int = 1):
    sessions = Session.objects.select_related("game", "game__platform", "device")
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
            sessions = sessions.filter(session_filter.to_q())
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
    return get_object_or_404(
        Session.objects.select_related("game", "game__platform", "device"),
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
    session = get_object_or_404(Session, id=session_id)
    if payload.device_id is not None:
        # A stale id (device deleted in another tab) must 404, not surface as
        # an IntegrityError 500 the client's retry toast can never resolve.
        get_object_or_404(Device, id=payload.device_id)
    session.device_id = payload.device_id
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


@session_router.patch("/{session_id}", response={200: SessionOut})
def partial_update_session(request, session_id: int, payload: SessionUpdate):
    # Single-user app: unscoped by user, like every other endpoint here.
    session = get_object_or_404(
        Session.objects.select_related("game", "game__platform", "device"),
        id=session_id,
    )
    data = payload.dict(exclude_unset=True)  # omitted fields are left untouched
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
def filter_count(request, model: str, filter: str = ""):
    """Live result count for the nested filter builder (#195).

    Generic across every filterable model: the ``model`` key selects the
    ``OperatorFilter`` subclass (``filter_for_model``) and the Django model
    (``apps.get_model``). GET is CSRF-safe (read-only); auth is inherited from
    ``NinjaAPI(auth=django_auth)``.
    """
    from django.apps import apps

    try:
        filter_cls = filter_for_model(model)
    except LookupError as exc:
        # Unknown Django model — a bad/hand-edited ``model`` key: a user 400.
        # A ``KeyError`` from filter_for_model means the model *exists* but has no
        # ``{Model}Filter`` class (a wiring bug for a model the client can reach);
        # let it propagate to a 500 so it surfaces, per the filter_from_json
        # contract of not masking genuine wiring bugs.
        raise HttpError(400, f"Unknown model: {model!r}") from exc
    queryset = apps.get_model("games", model).objects.all()
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
            queryset = queryset.filter(parsed.to_q())
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
    """The current user's presets for one mode, shaped for the combobox picker.

    ``limit=0`` means unbounded — the filter bar's overwrite-collision check
    fetches every name, so a >limit preset collection can't silently miss a
    collision and destroy a preset behind the warning's back (issue #212).
    """
    _reject_unknown_preset_mode(request, mode)
    presets = FilterPreset.objects.filter(mode=mode, user=request.user).order_by("name")
    if q:
        presets = presets.filter(name__icontains=q)
    if limit > 0:
        presets = presets[:limit]
    return [
        {
            "value": preset.id,
            "label": preset.name,
            "data": {
                "filter": json.dumps(preset.object_filter or {}),
                "sort": (preset.find_filter or {}).get("sort", ""),
                "per_page": _stored_per_page(preset.find_filter),
            },
        }
        for preset in presets
    ]


@preset_router.post("/", response={200: None, 201: None})
def save_preset(request, payload: PresetIn):
    """Create or overwrite a preset; 201 on create, 200 on in-place update.

    Upserts on the (user, mode, name) identity (unique at the DB level): re-saving
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
    _, created = FilterPreset.objects.update_or_create(
        user=request.user,
        name=name,
        mode=payload.mode,
        defaults={"object_filter": object_filter, "find_filter": find_filter},
    )
    return Status(201 if created else 200, None)


@preset_router.delete("/{preset_id}", response={204: None})
def delete_preset(request, preset_id: int):
    """Delete one of the current user's presets.

    Scoped to request.user so it cannot touch another user's preset (404
    instead). DELETE-only by routing; CSRF is enforced by django_auth.
    """
    preset = get_object_or_404(FilterPreset, id=preset_id, user=request.user)
    preset.delete()
    return Status(204, None)


api.add_router("/presets", preset_router)

settings_router = Router()


class SettingOut(Schema):
    """One resolved setting for the settings panel.

    ``value`` is ``str | int | None`` (device id is an int, unset is None) — a
    ``str``-only field would 500. ``locked`` marks an env/`.env`/`.ini`-pinned
    value; ``/user`` forces it ``False`` (see :func:`list_user_settings`).
    """

    key: str
    value: str | int | None
    source: str
    locked: bool


class SettingValueIn(Schema):
    # ``None`` means "clear this setting" (unset → falls through to lower layers).
    value: Any = None


def _settings_of_scope(*scopes: SettingScope) -> list[SettingKey]:
    return [
        key
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.scope in scopes
    ]


def _setting_out(key: SettingKey, resolved, *, locked: bool | None = None) -> dict:
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "locked": resolved.locked if locked is None else locked,
    }


def _raise_400(error: Exception):
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
        _setting_out(key, resolve_for_user_with_origin(request.user, key), locked=False)
        for key in _settings_of_scope(SettingScope.USER)
    ]


@settings_router.patch("/user/{key}", response=SettingOut)
def update_user_setting(
    request, key: str, payload: SettingValueIn, response: HttpResponse
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
        saved_value = set_user_preference(request.user, key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    messages.success(request, f"{definition.label} saved")
    # Build the immediate response without consulting the per-user snapshot: its
    # signal invalidation intentionally runs on commit, which may not have happened
    # yet when this endpoint participates in an outer transaction.
    resolved = (
        resolve_with_origin(key)
        if saved_value is None
        else ResolvedSetting(saved_value, SettingSource.USER, False)
    )
    if key == "THEME":
        write_theme_cookies(
            response,
            str(resolved.value),
            needs_migration=saved_value is None,
        )
    return _setting_out(key, resolved, locked=False)


@settings_router.get("/site", response=list[SettingOut])
def list_site_settings(request):
    """Site settings (and the site defaults under user prefs), resolved with
    origin. Superuser-only."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    return [
        _setting_out(key, resolve_with_origin(key))
        for key in _settings_of_scope(SettingScope.SITE, SettingScope.USER)
    ]


@settings_router.patch("/site/{key}", response={204: None})
def update_site_setting(request, key: str, payload: SettingValueIn):
    """Set (or clear, with ``value: null``) a site setting's DB value.
    Superuser-only."""
    if not request.user.is_superuser:
        raise HttpError(403, "Superuser required.")
    try:
        definition = get_definition(key)
    except UnregisteredSettingError:
        raise HttpError(400, f"Unknown setting {key!r}.")
    if definition.scope is SettingScope.INFRA:
        raise HttpError(400, f"{key} is infra-scoped and cannot be stored.")
    try:
        if payload.value is None:
            clear_site_setting(key)
        else:
            set_site_setting(key, payload.value)
    except (ValidationError, ValueError, TypeError) as error:
        _raise_400(error)
    messages.success(request, f"{definition.label} saved")
    return Status(204, None)


api.add_router("/settings", settings_router)

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
