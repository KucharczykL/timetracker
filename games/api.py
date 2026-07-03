import logging
from datetime import date, datetime
from typing import List

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as django_timezone_now
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status
from ninja.errors import HttpError
from ninja.security import django_auth

from common.criteria import FilterError, filter_from_json
from games.filters import filter_for_model, parse_session_filter
from games.forms import game_option_data
from games.models import Device, Game, Platform, PlayEvent, Session
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
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
    device_id: int


@session_router.patch("/{session_id}/device", response={204: None})
def partial_update_session_device(
    request, session_id: int, payload: SessionDeviceUpdate
):
    session = get_object_or_404(Session, id=session_id)
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
