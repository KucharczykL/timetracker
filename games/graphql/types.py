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
