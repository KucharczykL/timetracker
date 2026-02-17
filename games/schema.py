import graphene

from games.graphql.mutations import GameMutation
from games.graphql.queries import (
    DeviceQuery,
    GameQuery,
    PlatformQuery,
    PurchaseQuery,
    SessionQuery,
)


class Query(
    GameQuery,
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
