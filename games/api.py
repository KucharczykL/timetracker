from datetime import date, datetime
from typing import List

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as django_timezone_now
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status
from ninja.security import django_auth

from games.models import Device, Game, Platform, PlayEvent, Session

api = NinjaAPI(auth=django_auth)
playevent_router = Router()
game_router = Router()
device_router = Router()
platform_router = Router()

NOW_FACTORY = django_timezone_now


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
            "data": {"platform": g.platform_id or ""},
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


api.add_router("/session", session_router)
