import graphene
from graphene_django import DjangoObjectType

from games.models import Device as DeviceModel
from games.models import Edition as EditionModel
from games.models import Game as GameModel
from games.models import Platform as PlatformModel
from games.models import Purchase as PurchaseModel
from games.models import Session as SessionModel


class Game(DjangoObjectType):
    class Meta:
        model = GameModel
        fields = "__all__"


class Edition(DjangoObjectType):
    class Meta:
        model = EditionModel
        fields = "__all__"


class Purchase(DjangoObjectType):
    class Meta:
        model = PurchaseModel
        fields = "__all__"


class Session(DjangoObjectType):
    class Meta:
        model = SessionModel
        fields = "__all__"


class Platform(DjangoObjectType):
    class Meta:
        model = PlatformModel
        fields = "__all__"


class Device(DjangoObjectType):
    class Meta:
        model = DeviceModel
        fields = "__all__"


class Query(graphene.ObjectType):
    games = graphene.List(Game)
    game_by_name = graphene.Field(Game, name=graphene.String(required=True))
    purchases = graphene.List(Purchase)
    editions = graphene.List(Edition)
    sessions = graphene.List(Session)
    platforms = graphene.List(Platform)
    devices = graphene.List(Device)

    def resolve_games(self, info, **kwargs):
        return GameModel.objects.all()

    def resolve_game_by_name(self, info, name):
        try:
            return GameModel.objects.get(name=name)
        except GameModel.DoesNotExist:
            return None

    def resolve_editions(self, info, **kwargs):
        return EditionModel.objects.all()

    def resolve_purchases(self, info, **kwargs):
        return PurchaseModel.objects.all()

    def resolve_sessions(self, info, **kwargs):
        return SessionModel.objects.all()

    def resolve_platforms(self, info, **kwargs):
        return PlatformModel.objects.all()

    def resolve_devices(self, info, **kwargs):
        return DeviceModel.objects.all()


schema = graphene.Schema(query=Query)
