import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()

from django.test import TestCase
from graphene_django.utils.testing import GraphQLTestCase

from games import schema
from games.models import Game


class GameAPITestCase(GraphQLTestCase):
    GRAPHENE_SCHEMA = schema.schema

    def test_query_all_games(self):
        response = self.query(
            """
        query {
            games {
                id
                name
            }
        }
        """
        )

        self.assertResponseNoErrors(response)
        self.assertEqual(
            len(json.loads(response.content)["data"]["games"]),
            Game.objects.count(),
        )
