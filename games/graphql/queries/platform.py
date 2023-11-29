import graphene

from games.graphql.types import Platform
from games.models import Platform as PlatformModel


class Query(graphene.ObjectType):
    platforms = graphene.List(Platform)

    def resolve_platforms(self, info, **kwargs):
        return PlatformModel.objects.all()
