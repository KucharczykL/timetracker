import graphene

from games.graphql.types import Purchase
from games.models import Purchase as PurchaseModel


class Query(graphene.ObjectType):
    purchases = graphene.List(Purchase)

    def resolve_purchases(self, info, **kwargs):
        return PurchaseModel.objects.all()
