from datetime import date, datetime
from typing import List

from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as django_timezone_now
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status

from games.models import Game, PlayEvent, Session

api = NinjaAPI()
playevent_router = Router()
game_router = Router()

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


api.add_router("/playevent", playevent_router)
api.add_router("/games", game_router)

session_router = Router()


class SessionDeviceUpdate(Schema):
    device_id: int


@session_router.patch("/{session_id}/device", response={204: None})
def partial_update_session_device(request, session_id: int, payload: SessionDeviceUpdate):
    session = get_object_or_404(Session, id=session_id)
    session.device_id = payload.device_id
    session.save()
    messages.success(request, "Device updated")
    return Status(204, None)


api.add_router("/session", session_router)

