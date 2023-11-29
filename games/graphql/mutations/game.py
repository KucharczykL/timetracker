import graphene

from games.graphql.types import Game
from games.models import Game as GameModel


class UpdateGameMutation(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)
        name = graphene.String()
        year_released = graphene.Int()
        wikidata = graphene.String()

    game = graphene.Field(Game)

    def mutate(self, info, id, name=None, year_released=None, wikidata=None):
        game_instance = GameModel.objects.get(pk=id)
        if name is not None:
            game_instance.name = name
        if year_released is not None:
            game_instance.year_released = year_released
        if wikidata is not None:
            game_instance.wikidata = wikidata
        game_instance.save()
        return UpdateGameMutation(game=game_instance)


class Mutation(graphene.ObjectType):
    update_game = UpdateGameMutation.Field()
