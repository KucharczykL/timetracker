import graphene

from games.graphql.types import Game
from games.models import Game as GameModel


class Query(graphene.ObjectType):
    games = graphene.List(Game)
    game_by_name = graphene.Field(Game, name=graphene.String(required=True))

    def resolve_games(self, info, **kwargs):
        return GameModel.objects.all()

    def resolve_game_by_name(self, info, name):
        try:
            return GameModel.objects.get(name=name)
        except GameModel.DoesNotExist:
            return None
