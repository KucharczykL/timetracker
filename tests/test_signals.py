import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.management import call_command
from django.test import TestCase

from games.models import Game, UserLibrary

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class SignalsTest(TestCase):
    @pytest.mark.untracked_games
    def test_destroying_an_untracked_game_does_not_raise(self):
        library = get_user_model().objects.create_user(username="signals").library
        g = Game(library=library, name="Signal Test Game")
        g.save()
        self.assertTrue(Game.objects.filter(pk=g.pk).exists())

        g.delete()

        self.assertFalse(Game.objects.filter(pk=g.pk).exists())


class RawFixtureLoadTest(TestCase):
    """A fixture load provisions no library."""

    def setUp(self):
        self.fixture_dir = self.enterContext(tempfile.TemporaryDirectory())

        self.library = (
            get_user_model().objects.create_user(username="raw-fixture").library
        )

    def _write_fixture(self, objects) -> str:
        path = Path(self.fixture_dir) / "fixture.json"
        path.write_text(serializers.serialize("json", objects))
        return str(path)

    def test_user_fixture_does_not_provision_a_library(self):
        user = get_user_model().objects.create_user(username="fixture-user")
        user_id = user.pk
        fixture = self._write_fixture([user])

        user.delete()
        call_command("loaddata", fixture, verbosity=0)

        restored_user = get_user_model().objects.get(pk=user_id)
        self.assertFalse(UserLibrary.objects.filter(user=restored_user).exists())
