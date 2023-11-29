import graphene

from games.graphql.mutations import GameMutation
from games.graphql.queries import (
    DeviceQuery,
    EditionQuery,
    GameQuery,
    PlatformQuery,
    PurchaseQuery,
    SessionQuery,
)


class Query(
    GameQuery,
    EditionQuery,
    DeviceQuery,
    PlatformQuery,
    PurchaseQuery,
    SessionQuery,
    graphene.ObjectType,
):
    pass


class Mutation(GameMutation, graphene.ObjectType):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)
