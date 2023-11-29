import graphene

from games.graphql.types import Device
from games.models import Device as DeviceModel


class Query(graphene.ObjectType):
    devices = graphene.List(Device)

    def resolve_devices(self, info, **kwargs):
        return DeviceModel.objects.all()
