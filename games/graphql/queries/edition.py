import graphene

from games.graphql.types import Edition
from games.models import Game as EditionModel


class Query(graphene.ObjectType):
    editions = graphene.List(Edition)

    def resolve_editions(self, info, **kwargs):
        return EditionModel.objects.all()
