import graphene

from games.graphql.types import Session
from games.models import Session as SessionModel


class Query(graphene.ObjectType):
    sessions = graphene.List(Session)

    def resolve_sessions(self, info, **kwargs):
        return SessionModel.objects.all()
